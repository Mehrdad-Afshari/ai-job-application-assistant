import io
import json
import os
import re
import time
from typing import List, Literal
import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pypdf import PdfReader

class ScoreBreakdown(BaseModel):
    technical_skills:int=Field(ge=0,le=45); experience_projects:int=Field(ge=0,le=25); education_domain:int=Field(ge=0,le=15); other_requirements:int=Field(ge=0,le=15)
class Requirement(BaseModel):
    requirement:str; priority:Literal['required','preferred']='preferred'; category:Literal['technical','experience','education','other']='other'; status:Literal['matched','partial','missing']='missing'; evidence:str='No evidence in CV'
class AnalysisResult(BaseModel):
    match_score:int; score_breakdown:ScoreBreakdown; detected_language:str; summary:str; requirements:List[Requirement]; matched_skills:List[str]; missing_skills:List[str]; keywords:List[str]; analysis_seconds:float
class WritingResult(BaseModel):
    cv_suggestions:List[str]=Field(default_factory=list); cover_letter:str=''; interview_questions:List[str]=Field(default_factory=list)

app=FastAPI(title='AI Job Application Assistant API',version='1.5.0',description='Instant deterministic evidence-based CV/job matching with optional local AI writing.')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:3000'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

SKILLS={
'python':['python'],'fastapi':['fastapi'],'javascript':['javascript'],'typescript':['typescript'],'react':['react','next.js','nextjs'],'node':['node.js','nodejs'],'csharp':['c#','.net','dotnet'],'java':['java'],'sql':['sql','sql server','postgresql','mysql'],'git':['git','github'],'docker':['docker'],'kubernetes':['kubernetes','k8s'],'aws':['aws','amazon web services'],'azure':['azure'],'gcp':['gcp','google cloud'],'cloud':['cloud computing','cloud technologies','cloud-technologien'],'llm':['llm','large language model','language models','llama','ollama'],'rag':['rag','retrieval augmented generation','retrieval-augmented generation'],'agents':['ai agent','ai-agent','ai agents','ki-agent','ki agent','agentic','agent skills','mcp'],'ml':['machine learning','ki-/ml','ml-verfahren'],'genai':['generative ai','genai'],'testing':['unit test','unit tests','testing','pytest','jest','tests'],'code_review':['code review','code reviews'],'cicd':['ci/cd','continuous integration','continuous deployment'],'agile':['agile','agilen','scrum','kanban'],'okr':['okr'],'office':['microsoft-office','microsoft office','ms office','excel','powerpoint','word'],'api':['rest api','restful','api development','schnittstellen'],'fullstack':['full-stack','full stack','frontend and backend','frontend & backend'],'security':['it-sicherheit','it security','cybersecurity'],'requirements':['requirements engineering','requirement analysis','anforderungsanalyse','fachlichen anforderungen'],'masters':['m.sc','msc','master of science','master’s','master\'s'],'bachelors':['b.sc','bsc','bachelor'],'computer_science':['computer science','informatik'],'german':['deutschkenntnisse','german'],'communication':['kommunikationsfähigkeit','communication skills'],'teamwork':['teamgeist','teamwork','team player']}
BENEFIT_CUES=['monatsgehalt','gewinnbeteiligung','mobiles arbeiten','flexible arbeitszeiten','urlaubstage','benefits','unternehmenskultur','raum für mitgestaltung','betriebliche altersvorsorge','jobrad','kantine','vergütung','gehalt','woche','arbeitszeiten']
REQ_CUES=['erfahrung','kenntnisse','studium','abschluss','ausbildung','deutschkenntnisse','kommunikationsfähigkeit','teamgeist','lernbereitschaft','arbeitsweise','entwickeln','entwicklung','konzipieren','implementieren','integrieren','betreiben','softwarequalität','code reviews','tests','anforderungen','architekturentscheidungen','standards','sicherstellen','überführen','prototypen','experience','knowledge','degree','develop','implement','requirements','responsible']

def extract_pdf_text(data:bytes)->str:
    try:text='\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(data)).pages).strip()
    except Exception as exc:raise HTTPException(400,'Could not read the PDF file.') from exc
    if not text:raise HTTPException(400,'No readable text was found in the PDF.')
    return text
def norm(t:str)->str:return re.sub(r'\s+',' ',t.lower().replace('–','-').replace('—','-')).strip()
def compact(t:str,n:int)->str:return '\n'.join(x.strip() for x in t.splitlines() if x.strip())[:n]
def present(text:str,term:str)->bool:
    t=norm(text);q=norm(term)
    if len(q)<=3:return bool(re.search(r'(?<![a-z0-9])'+re.escape(q)+r'(?![a-z0-9])',t))
    return q in t
def skill_set(text:str)->set[str]:return {s for s,a in SKILLS.items() if any(present(text,x) for x in a)}
def evidence_for(skill:str,cv:str)->str:
    for a in SKILLS.get(skill,[]):
        if present(cv,a):return a
    return 'No evidence in CV'
def language_of(job:str)->str:
    low=f' {job.lower()} ';return 'German' if sum(low.count(x) for x in [' und ',' der ',' die ',' das ',' mit ',' erfahrung','kenntnisse','aufgaben','wir '])>=4 else 'English'
def split_job(job:str)->list[str]:
    pieces=[]
    for raw in job.splitlines():
        raw=raw.strip(' •-*\t')
        if not raw:continue
        for p in re.split(r'(?<=[.!?])\s+(?=[A-ZÄÖÜ])',raw):
            p=p.strip(' •-*\t')
            if 12<=len(p)<=280:pieces.append(p)
    return pieces
def is_benefit(line:str)->bool:return any(x in line.lower() for x in BENEFIT_CUES)
def priority(line:str)->str:return 'preferred' if any(x in line.lower() for x in ['von vorteil','wünschenswert','idealerweise','nice to have','preferred','optional']) else 'required'
def category(line:str)->str:
    s=skill_set(line);low=line.lower()
    if s&{'masters','bachelors','computer_science'} or any(x in low for x in ['studium','abschluss','ausbildung','degree']):return 'education'
    if any(x in low for x in ['mehrjähriger berufserfahrung','jahre erfahrung','years of experience','berufserfahrung']):return 'experience'
    if s&{'communication','teamwork','german'} or any(x in low for x in ['arbeitsweise','lernbereitschaft','zuverlässig','verantwortungsbewusst']):return 'other'
    return 'technical' if s or any(x in low for x in ['entwickeln','implementieren','software','architektur','tests','prototypen','anforderungen']) else 'other'
def classify(line:str,cv:str)->tuple[str,str]:
    needed=skill_set(line);have=skill_set(cv);hits=needed&have
    if needed:
        ev=', '.join(evidence_for(x,cv) for x in sorted(hits)) if hits else 'No evidence in CV'
        ratio=len(hits)/len(needed)
        return ('matched',ev) if ratio>=.8 else ('partial',ev) if ratio>=.34 else ('missing','No evidence in CV')
    # Soft requirements are only matched when their wording is explicitly evidenced; no guessing.
    words=[w for w in re.findall(r'[a-zäöüß]{5,}',line.lower()) if w not in {'einen','einer','einem','sowie','diese','dieser','hohen','ausgeprägte','bereich'}]
    cvn=norm(cv);hits=[w for w in words if w in cvn]
    if len(hits)>=3:return 'partial',', '.join(hits[:4])
    return 'missing','No explicit evidence in CV'
def extract_requirements(job:str,cv:str)->list[Requirement]:
    candidates=[];seen=set()
    for line in split_job(job):
        low=line.lower();skills=skill_set(line)
        if is_benefit(line):continue
        if not skills and not any(x in low for x in REQ_CUES):continue
        key=norm(line)
        if key in seen:continue
        seen.add(key)
        # Rank technical/responsibility lines above generic soft requirements.
        rank=(3 if skills else 0)+(2 if any(x in low for x in ['entwickeln','konzipieren','implementieren','softwarequalität','prototypen','anforderungen','erfahrung','kenntnisse']) else 0)+(1 if priority(line)=='required' else 0)
        candidates.append((rank,line))
    candidates.sort(key=lambda x:x[0],reverse=True)
    out=[]
    for _,line in candidates[:10]:
        status,evidence=classify(line,cv);out.append(Requirement(requirement=line,priority=priority(line),category=category(line),status=status,evidence=evidence))
    return out
def keywords(job:str)->list[str]:return [SKILLS[s][0] for s in sorted(skill_set(job))][:12]
def score(reqs:list[Requirement])->ScoreBreakdown:
    maxima={'technical':45,'experience':25,'education':15,'other':15};vals={}
    for cat,mx in maxima.items():
        items=[r for r in reqs if r.category==cat]
        if not items:vals[cat]=0;continue
        poss=sum(2 if r.priority=='required' else 1 for r in items);earned=sum((2 if r.priority=='required' else 1)*{'matched':1,'partial':.5,'missing':0}[r.status] for r in items);vals[cat]=round(mx*earned/poss)
    return ScoreBreakdown(technical_skills=vals['technical'],experience_projects=vals['experience'],education_domain=vals['education'],other_requirements=vals['other'])
def summary(lang:str,m:list[str],miss:list[str],s:int)->str:
    if lang=='German':return f"Der evidenzbasierte Match-Score beträgt {s}/100. Verifizierte Übereinstimmungen: {', '.join(m[:3]) if m else 'keine eindeutigen Volltreffer'}. Nicht belegte Anforderungen: {', '.join(miss[:3]) if miss else 'keine in den analysierten Kernanforderungen'}."
    return f"The evidence-based match score is {s}/100. Verified matches: {', '.join(m[:3]) if m else 'no clear full matches'}. Unverified requirements: {', '.join(miss[:3]) if miss else 'none among the analyzed core requirements'}."
def parse_json(text:str)->dict:
    try:v=json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',(text or '').strip(),flags=re.I|re.S));return v if isinstance(v,dict) else {}
    except Exception:return {}
async def ollama(prompt:str,n:int)->dict:
    base=os.getenv('OLLAMA_BASE_URL','http://localhost:11434').rstrip('/');model=os.getenv('OLLAMA_MODEL','llama3.2')
    try:
        async with httpx.AsyncClient(timeout=120) as c:
            r=await c.post(f'{base}/api/generate',json={'model':model,'prompt':prompt,'stream':False,'format':'json','keep_alive':'15m','options':{'temperature':0,'num_predict':n,'num_ctx':3072}});r.raise_for_status();return parse_json(r.json().get('response',''))
    except Exception:return {}

@app.get('/health')
async def health():return {'status':'ok','service':'ai-job-application-assistant','version':'1.5.0','pipeline':'instant-deterministic-analysis'}
@app.post('/analyze',response_model=AnalysisResult)
async def analyze_endpoint(cv:UploadFile=File(...),job_description:str=Form(...)):
    started=time.perf_counter()
    if cv.content_type!='application/pdf' and not (cv.filename or '').lower().endswith('.pdf'):raise HTTPException(400,'Please upload a PDF CV.')
    if len(job_description.strip())<80:raise HTTPException(400,'Please provide a more complete job description.')
    data=await cv.read()
    if len(data)>5*1024*1024:raise HTTPException(413,'CV file is too large. Maximum size is 5 MB.')
    cvt=extract_pdf_text(data);reqs=extract_requirements(job_description,cvt)
    if len(reqs)<3:raise HTTPException(422,'Could not identify enough candidate requirements. Paste the complete job posting with responsibilities and qualifications.')
    bd=score(reqs);total=sum(bd.model_dump().values());matched=[r.requirement for r in reqs if r.status=='matched'];missing=[r.requirement for r in reqs if r.status=='missing'];lang=language_of(job_description)
    return AnalysisResult(match_score=total,score_breakdown=bd,detected_language=lang,summary=summary(lang,matched,missing,total),requirements=reqs,matched_skills=matched,missing_skills=missing,keywords=keywords(job_description),analysis_seconds=round(time.perf_counter()-started,2))
@app.post('/generate',response_model=WritingResult)
async def generate_endpoint(cv:UploadFile=File(...),job_description:str=Form(...),analysis_json:str=Form(...)):
    cvt=extract_pdf_text(await cv.read())
    try:a=json.loads(analysis_json)
    except json.JSONDecodeError as exc:raise HTTPException(400,'Invalid analysis data.') from exc
    lang=a.get('detected_language',language_of(job_description));ev='\n'.join(f"- {x.get('requirement')}: {x.get('status')} | {x.get('evidence')}" for x in a.get('requirements',[])[:10]);p=f'''Return ONLY valid JSON with cv_suggestions, cover_letter, interview_questions. Write entirely in {lang}. Exactly 3 truthful CV suggestions, a 90-130 word cover letter, exactly 5 interview questions. Use ONLY verified evidence and CV facts. Never claim missing experience.\nVERIFIED ANALYSIS:\n{ev}\nCV:\n{compact(cvt,4200)}\nJOB:\n{compact(job_description,2400)}''';raw=await ollama(p,500);s=raw.get('cv_suggestions') or [];q=raw.get('interview_questions') or [];return WritingResult(cv_suggestions=s[:3] if isinstance(s,list) else [],cover_letter=str(raw.get('cover_letter') or ''),interview_questions=q[:5] if isinstance(q,list) else [])
