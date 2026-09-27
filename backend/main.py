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

app=FastAPI(title='AI Job Application Assistant API',version='1.4.0',description='Deterministic semantic skill matching with local AI extraction.')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:3000'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

SKILLS={
 'python':['python'],'fastapi':['fastapi'],'javascript':['javascript','js'],'typescript':['typescript'],'react':['react','next.js','nextjs'],'node':['node.js','nodejs'],
 'csharp':['c#','.net','dotnet'],'java':['java'],'sql':['sql','sql server','postgresql','mysql'],'git':['git','github'],'docker':['docker'],'kubernetes':['kubernetes','k8s'],
 'aws':['aws','amazon web services'],'azure':['azure'],'gcp':['gcp','google cloud'],'cloud':['cloud computing','cloud technologies','cloud-technologien'],
 'llm':['llm','large language model','language models','llama','ollama'],'rag':['rag','retrieval augmented generation','retrieval-augmented generation'],
 'agents':['ai agent','ai-agent','ai agents','ki-agent','ki agent','agentic','agent skills','mcp'],'ml':['machine learning','ml'],'genai':['generative ai','genai','generative künstliche intelligenz'],
 'testing':['unit test','unit tests','testing','pytest','jest','tests'],'code_review':['code review','code reviews'],'cicd':['ci/cd','continuous integration','continuous deployment'],
 'agile':['agile','scrum','kanban'],'okr':['okr'],'office':['microsoft office','ms office','excel','powerpoint','word'],'api':['rest api','restful','api development','schnittstellen'],
 'fullstack':['full-stack','full stack','frontend and backend','frontend & backend'],'security':['it security','cybersecurity','security'],'requirements':['requirements engineering','requirement analysis','anforderungsanalyse'],
 'masters':['m.sc','msc','master of science','master’s','master\'s'],'bachelors':['b.sc','bsc','bachelor'],'computer_science':['computer science','informatik']
}

def extract_pdf_text(data:bytes)->str:
    try:text='\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(data)).pages).strip()
    except Exception as exc:raise HTTPException(400,'Could not read the PDF file.') from exc
    if not text:raise HTTPException(400,'No readable text was found in the PDF.')
    return text
def compact(t:str,n:int)->str:return '\n'.join(x.strip() for x in t.splitlines() if x.strip())[:n]
def norm(t:str)->str:return re.sub(r'\s+',' ',t.lower().replace('–','-').replace('—','-')).strip()
def language_of(job:str)->str:
    low=f' {job.lower()} ';return 'German' if sum(low.count(x) for x in [' und ',' der ',' die ',' das ',' mit ',' erfahrung','kenntnisse','aufgaben','wir '])>=4 else 'English'
def present(text:str,term:str)->bool:
    t=norm(text);q=norm(term)
    if len(q)<=3:return bool(re.search(r'(?<![a-z0-9])'+re.escape(q)+r'(?![a-z0-9])',t))
    return q in t
def skill_set(text:str)->set[str]:
    return {skill for skill,aliases in SKILLS.items() if any(present(text,a) for a in aliases)}
def evidence_for(skill:str,cv:str)->str:
    for alias in SKILLS.get(skill,[]):
        if present(cv,alias):return alias
    return 'No evidence in CV'
def requirement_skills(req:str)->set[str]:return skill_set(req)
def classify(req:str,cv:str)->tuple[str,str]:
    needed=requirement_skills(req);have=skill_set(cv)
    if not needed:return 'missing','No explicit skill evidence in CV'
    hits=needed&have
    if not hits:return 'missing','No evidence in CV'
    evidence=', '.join(evidence_for(x,cv) for x in sorted(hits))
    if hits==needed:return 'matched',evidence
    return 'partial',evidence

def parse_json(text:str)->dict:
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',(text or '').strip(),flags=re.I|re.S).strip()
    try:v=json.loads(text);return v if isinstance(v,dict) else {}
    except Exception:return {}

async def ollama(prompt:str,num_predict:int,timeout:float=90)->dict:
    base=os.getenv('OLLAMA_BASE_URL','http://localhost:11434').rstrip('/');model=os.getenv('OLLAMA_MODEL','llama3.2')
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r=await c.post(f'{base}/api/generate',json={'model':model,'prompt':prompt,'stream':False,'format':'json','keep_alive':'15m','options':{'temperature':0,'num_predict':num_predict,'num_ctx':3072}});r.raise_for_status();return parse_json(r.json().get('response',''))
    except httpx.ConnectError as exc:raise HTTPException(503,'Cannot connect to Ollama.') from exc
    except httpx.TimeoutException:return {}
    except Exception:return {}

def fallback_extract(job:str)->list[dict]:
    cues=['erfahrung','kenntnisse','software','ki','ai','llm','cloud','aws','agil','okr','office','studium','abschluss','degree','python','java','typescript','tests','full-stack','full stack','schnittstellen','security','sicherheit']
    out=[];seen=set()
    for line in job.splitlines():
        line=line.strip(' •-*\t');low=line.lower()
        if not 15<=len(line)<=220 or not any(x in low for x in cues):continue
        key=norm(line)
        if key in seen:continue
        seen.add(key);out.append({'requirement':line,'priority':'preferred' if any(x in low for x in ['wünsch','von vorteil','idealerweise','preferred','nice to have']) else 'required'})
        if len(out)>=8:break
    return out

def category(req:str)->str:
    s=requirement_skills(req);low=req.lower()
    if s&{'masters','bachelors','computer_science'} or any(x in low for x in ['studium','abschluss','degree']):return 'education'
    if any(x in low for x in ['jahre erfahrung','years of experience','berufserfahrung']):return 'experience'
    if s:return 'technical'
    return 'other'

def extract_prompt(job:str)->str:
    return f'''Extract only the 6-8 most important candidate requirements from this job posting. Return ONLY compact JSON: {{"requirements":[{{"requirement":"short requirement text","priority":"required"}}],"keywords":["keyword"]}}. priority is required or preferred. Do NOT compare with a CV. Do NOT add evidence, status, explanations or categories. Keep each requirement concise.\nJOB:\n{compact(job,3800)}'''

def build_requirements(raw:dict,job:str,cv:str)->tuple[list[Requirement],list[str]]:
    rows=raw.get('requirements') if isinstance(raw,dict) else None
    if not isinstance(rows,list) or len(rows)<3:rows=fallback_extract(job)
    result=[];seen=set()
    for x in rows[:9]:
        if isinstance(x,str):name=x;p='preferred'
        elif isinstance(x,dict):name=str(x.get('requirement') or x.get('name') or '').strip();p=str(x.get('priority','preferred')).lower()
        else:continue
        key=norm(name)
        if not name or key in seen:continue
        seen.add(key);status,evidence=classify(name,cv);result.append(Requirement(requirement=name,priority=p if p in {'required','preferred'} else 'preferred',category=category(name),status=status,evidence=evidence))
    kws=raw.get('keywords',[]) if isinstance(raw,dict) else []
    if not isinstance(kws,list):kws=[]
    if not kws:
        kws=[a for skill in sorted(skill_set(job)) for a in SKILLS[skill][:1]][:12]
    return result,list(dict.fromkeys(str(x) for x in kws if x))[:12]

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

@app.get('/health')
async def health():return {'status':'ok','service':'ai-job-application-assistant','version':'1.4.0','pipeline':'deterministic-semantic-match'}
@app.post('/analyze',response_model=AnalysisResult)
async def analyze_endpoint(cv:UploadFile=File(...),job_description:str=Form(...)):
    started=time.perf_counter()
    if cv.content_type!='application/pdf' and not (cv.filename or '').lower().endswith('.pdf'):raise HTTPException(400,'Please upload a PDF CV.')
    if len(job_description.strip())<80:raise HTTPException(400,'Please provide a more complete job description.')
    data=await cv.read()
    if len(data)>5*1024*1024:raise HTTPException(413,'CV file is too large. Maximum size is 5 MB.')
    cvt=extract_pdf_text(data);raw=await ollama(extract_prompt(job_description),350,75);reqs,kws=build_requirements(raw,job_description,cvt)
    if len(reqs)<3:raise HTTPException(502,'Could not identify enough job requirements from this posting.')
    bd=score(reqs);total=sum(bd.model_dump().values());matched=[r.requirement for r in reqs if r.status=='matched'];missing=[r.requirement for r in reqs if r.status=='missing'];lang=language_of(job_description)
    return AnalysisResult(match_score=total,score_breakdown=bd,detected_language=lang,summary=summary(lang,matched,missing,total),requirements=reqs,matched_skills=matched,missing_skills=missing,keywords=kws,analysis_seconds=round(time.perf_counter()-started,1))
@app.post('/generate',response_model=WritingResult)
async def generate_endpoint(cv:UploadFile=File(...),job_description:str=Form(...),analysis_json:str=Form(...)):
    cvt=extract_pdf_text(await cv.read())
    try:a=json.loads(analysis_json)
    except json.JSONDecodeError as exc:raise HTTPException(400,'Invalid analysis data.') from exc
    lang=a.get('detected_language',language_of(job_description));ev='\n'.join(f"- {x.get('requirement')}: {x.get('status')} | {x.get('evidence')}" for x in a.get('requirements',[])[:9]);p=f'''Return ONLY JSON with cv_suggestions, cover_letter, interview_questions. Write entirely in {lang}. Exactly 3 truthful suggestions, a concise 90-130 word cover letter, exactly 5 interview questions. Use ONLY the verified statuses/evidence and CV facts. Never convert a missing requirement into claimed experience.\nVERIFIED:\n{ev}\nCV:\n{compact(cvt,4200)}\nJOB:\n{compact(job_description,2300)}''';raw=await ollama(p,500,120);s=raw.get('cv_suggestions') or [];q=raw.get('interview_questions') or [];return WritingResult(cv_suggestions=s[:3] if isinstance(s,list) else [],cover_letter=str(raw.get('cover_letter') or ''),interview_questions=q[:5] if isinstance(q,list) else [])
