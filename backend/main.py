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
    cv_suggestions:List[str]=Field(default_factory=list); cover_letter:str=''; interview_questions:List[str]=Field(default_factory=list); generation_seconds:float=0

app=FastAPI(title='AI Job Application Assistant API',version='1.5.2',description='Instant deterministic evidence-based CV/job matching with resilient local AI writing.')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:3000'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

SKILLS={'python':['python'],'fastapi':['fastapi'],'javascript':['javascript'],'typescript':['typescript'],'react':['react','next.js','nextjs'],'node':['node.js','nodejs'],'csharp':['c#','.net','dotnet'],'java':['java'],'sql':['sql','sql server','postgresql','mysql'],'git':['git','github'],'docker':['docker'],'kubernetes':['kubernetes','k8s'],'aws':['aws','amazon web services'],'azure':['azure'],'gcp':['gcp','google cloud'],'cloud':['cloud computing','cloud technologies','cloud-technologien'],'llm':['llm','large language model','language models','llama','ollama'],'rag':['rag','retrieval augmented generation','retrieval-augmented generation'],'agents':['ai agent','ai-agent','ai agents','ki-agent','ki agent','agentic','agent skills','mcp'],'ml':['machine learning','ki-/ml','ml-verfahren'],'genai':['generative ai','genai'],'testing':['unit test','unit tests','testing','pytest','jest','tests'],'code_review':['code review','code reviews'],'cicd':['ci/cd','continuous integration','continuous deployment'],'agile':['agile','agilen','scrum','kanban'],'okr':['okr'],'office':['microsoft-office','microsoft office','ms office','excel','powerpoint','word'],'api':['rest api','restful','api development','schnittstellen'],'fullstack':['full-stack','full stack','frontend and backend','frontend & backend'],'security':['it-sicherheit','it security','cybersecurity'],'requirements':['requirements engineering','requirement analysis','anforderungsanalyse','fachlichen anforderungen'],'masters':['m.sc','msc','master of science','master’s','master\'s'],'bachelors':['b.sc','bsc','bachelor'],'computer_science':['computer science','informatik'],'german':['deutschkenntnisse','german'],'communication':['kommunikationsfähigkeit','communication skills'],'teamwork':['teamgeist','teamwork','team player']}
BENEFIT_CUES=['monatsgehalt','gewinnbeteiligung','mobiles arbeiten','flexible arbeitszeiten','urlaubstage','benefits','unternehmenskultur','raum für mitgestaltung','betriebliche altersvorsorge','jobrad','kantine','vergütung','gehalt','arbeitszeiten']
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
            if 12<=len(p)<=320:pieces.append(p)
    return pieces
def atomize(line:str)->list[str]:
    low=line.lower()
    if 'microsoft-office' in low and ('aws' in low or 'cloud-technologien' in low):
        out=['Sehr gute Kenntnisse in Microsoft-Office-Anwendungen']
        if 'ki-/ml' in low or 'ml-verfahren' in low:out.append('Erfahrung mit KI-/ML-Verfahren')
        if 'aws' in low or 'cloud' in low:out.append('Erfahrung mit Cloud-Technologien (AWS)')
        if 'lernbereitschaft' in low:out.append('Ausgeprägte Lernbereitschaft für das Einarbeiten in neue Systeme')
        return out
    if 'agilen arbeitsmethoden' in low and 'okr' in low:return ['Erfahrungen mit agilen Arbeitsmethoden','Erfahrungen mit der OKR-Methodik']
    if 'code reviews' in low and ('tests' in low or 'it-sicherheit' in low):
        out=['Erfahrung mit Code Reviews','Erfahrung mit Softwaretests']
        if 'human-in-the-loop' in low:out.append('Human-in-the-Loop bei KI-generierten Ergebnissen')
        if 'it-sicherheit' in low:out.append('IT-Sicherheit und regulatorische Anforderungen')
        return out
    if 'studium' in low and 'berufserfahrung' in low and ('alternativ' in low or 'ausbildung' in low):return ['Abgeschlossenes Studium im Bereich Informatik oder vergleichbar']
    return [line]
def is_benefit(line:str)->bool:return any(x in line.lower() for x in BENEFIT_CUES)
def priority(line:str)->str:return 'preferred' if any(x in line.lower() for x in ['von vorteil','wünschenswert','idealerweise','nice to have','preferred','optional']) else 'required'
def category(line:str)->str:
    s=skill_set(line);low=line.lower()
    if s&{'masters','bachelors','computer_science'} or any(x in low for x in ['studium','abschluss','ausbildung','degree']):return 'education'
    if any(x in low for x in ['mehrjähriger berufserfahrung','jahre erfahrung','years of experience','berufserfahrung']):return 'experience'
    if s&{'communication','teamwork','german'} or any(x in low for x in ['arbeitsweise','lernbereitschaft','zuverlässig','verantwortungsbewusst']):return 'other'
    return 'technical' if s or any(x in low for x in ['entwickeln','implementieren','software','architektur','tests','prototypen','anforderungen','code reviews']) else 'other'
def classify(line:str,cv:str)->tuple[str,str]:
    needed=skill_set(line);have=skill_set(cv);hits=needed&have
    if needed:
        ev=', '.join(evidence_for(x,cv) for x in sorted(hits)) if hits else 'No evidence in CV';ratio=len(hits)/len(needed)
        return ('matched',ev) if ratio>=.8 else ('partial',ev) if ratio>=.34 else ('missing','No evidence in CV')
    low=line.lower();cvn=norm(cv)
    if 'berufserfahrung' in low or 'years of experience' in low:
        hits=[x for x in ['software developer','softwareentwickler','developer','entwickler','work experience','professional experience','berufserfahrung'] if x in cvn]
        return ('partial',', '.join(hits[:3])) if hits else ('missing','No explicit work-experience evidence in CV')
    words=[w for w in re.findall(r'[a-zäöüß]{5,}',low) if w not in {'einen','einer','einem','sowie','diese','dieser','hohen','ausgeprägte','bereich','erfahrung','kenntnisse'}];hits=[w for w in words if w in cvn]
    if len(hits)>=3:return 'partial',', '.join(hits[:4])
    return 'missing','No explicit evidence in CV'
def extract_requirements(job:str,cv:str)->list[Requirement]:
    candidates=[];seen=set()
    for original in split_job(job):
        if is_benefit(original):continue
        bp=priority(original)
        for line in atomize(original):
            low=line.lower();skills=skill_set(line)
            if not skills and not any(x in low for x in REQ_CUES):continue
            key=norm(line)
            if key in seen:continue
            seen.add(key);rank=(3 if skills else 0)+(2 if any(x in low for x in ['entwickeln','konzipieren','implementieren','softwarequalität','prototypen','anforderungen','erfahrung','kenntnisse','studium']) else 0)+(1 if bp=='required' else 0);candidates.append((rank,line,bp))
    candidates.sort(key=lambda x:x[0],reverse=True);out=[];edu_seen=False
    for _,line,p in candidates:
        cat=category(line)
        if cat=='education':
            if edu_seen:continue
            edu_seen=True
        status,evidence=classify(line,cv);out.append(Requirement(requirement=line,priority=p,category=cat,status=status,evidence=evidence))
        if len(out)>=12:break
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
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',(text or '').strip(),flags=re.I|re.S).strip()
    try:v=json.loads(text);return v if isinstance(v,dict) else {}
    except Exception:pass
    a=text.find('{');b=text.rfind('}')
    if a>=0 and b>a:
        try:v=json.loads(text[a:b+1]);return v if isinstance(v,dict) else {}
        except Exception:pass
    return {}
async def ollama(prompt:str,n:int)->dict:
    base=os.getenv('OLLAMA_BASE_URL','http://localhost:11434').rstrip('/');model=os.getenv('OLLAMA_MODEL','llama3.2')
    try:
        async with httpx.AsyncClient(timeout=150) as c:
            r=await c.post(f'{base}/api/generate',json={'model':model,'prompt':prompt,'stream':False,'format':'json','keep_alive':'15m','options':{'temperature':0,'num_predict':n,'num_ctx':4096}});r.raise_for_status();return parse_json(r.json().get('response',''))
    except httpx.ConnectError as exc:raise HTTPException(503,'Cannot connect to Ollama.') from exc
    except httpx.TimeoutException as exc:raise HTTPException(504,'Local AI generation timed out.') from exc
    except Exception as exc:raise HTTPException(502,f'Local AI generation failed: {type(exc).__name__}') from exc

@app.get('/health')
async def health():return {'status':'ok','service':'ai-job-application-assistant','version':'1.5.2','pipeline':'atomic-analysis-resilient-generation'}
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
    started=time.perf_counter();cvt=extract_pdf_text(await cv.read())
    try:a=json.loads(analysis_json)
    except json.JSONDecodeError as exc:raise HTTPException(400,'Invalid analysis data.') from exc
    lang=a.get('detected_language',language_of(job_description));ev='\n'.join(f"- {x.get('requirement')}: {x.get('status')} | {x.get('evidence')}" for x in a.get('requirements',[])[:12]);p=f'''Return ONLY one valid compact JSON object. No markdown. Required keys: cv_suggestions, cover_letter, interview_questions. cv_suggestions MUST be an array of exactly 3 strings. interview_questions MUST be an array of exactly 5 strings. cover_letter MUST be one string of 80-120 words. Write entirely in {lang}. Use only CV facts and VERIFIED ANALYSIS. Never claim experience marked missing.\nVERIFIED ANALYSIS:\n{ev}\nCV:\n{compact(cvt,3600)}\nJOB:\n{compact(job_description,1800)}''';raw=await ollama(p,700)
    s=raw.get('cv_suggestions');q=raw.get('interview_questions');letter=raw.get('cover_letter')
    if not isinstance(s,list) or not isinstance(q,list) or not isinstance(letter,str) or not letter.strip():raise HTTPException(502,'The local model returned incomplete application materials. Please try again.')
    return WritingResult(cv_suggestions=[str(x) for x in s[:3]],cover_letter=letter.strip(),interview_questions=[str(x) for x in q[:5]],generation_seconds=round(time.perf_counter()-started,1))
