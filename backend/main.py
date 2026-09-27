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

app=FastAPI(title='AI Job Application Assistant API',version='1.3.2',description='Fast evidence-guarded local AI job matching.')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:3000'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

def extract_pdf_text(data:bytes)->str:
    try:text='\n'.join((p.extract_text() or '') for p in PdfReader(io.BytesIO(data)).pages).strip()
    except Exception as exc:raise HTTPException(400,'Could not read the PDF file.') from exc
    if not text:raise HTTPException(400,'No readable text was found in the PDF.')
    return text
def compact(text:str,limit:int)->str:return '\n'.join(x.strip() for x in text.splitlines() if x.strip())[:limit]
def language_of(job:str)->str:
    low=f' {job.lower()} ';return 'German' if sum(low.count(x) for x in [' und ',' der ',' die ',' das ',' mit ',' erfahrung','kenntnisse','aufgaben','wir '])>=4 else 'English'
def norm(v:str)->str:return re.sub(r'[^a-z0-9äöüß+#./-]+',' ',v.lower().replace('–','-').replace('—','-')).strip()
def toks(v:str)->set[str]:
    stop={'and','or','the','with','for','from','und','oder','der','die','das','mit','von','für','eine','einer','sowie','kenntnisse','erfahrung','erfahrungen','sehr','gute','develop','development','entwickeln','entwicklung'}
    return {x for x in re.findall(r'[a-z0-9äöüß+#.]+',norm(v)) if len(x)>2 and x not in stop}
def evidence_guard(r:Requirement,cv:str)->Requirement:
    ev=(r.evidence or '').strip();cvn=norm(cv)
    if not ev or ev.lower()=='no evidence in cv':r.status='missing';r.evidence='No evidence in CV';return r
    evn=norm(ev);overlap=len(toks(evn)&toks(cvn))/max(1,len(toks(evn)))
    if evn not in cvn and overlap<.7:r.status='missing';r.evidence='No evidence in CV'
    return r
def rows_from_raw(raw:dict)->list:
    rows=raw.get('requirements') or raw.get('job_requirements') or raw.get('items') or raw.get('matches') or []
    if isinstance(rows,dict):rows=[({'requirement':k,**v} if isinstance(v,dict) else {'requirement':k,'status':v}) for k,v in rows.items()]
    return rows if isinstance(rows,list) else []
def normalize_extraction(raw:dict,cv:str)->tuple[list[Requirement],list[str]]:
    result=[];seen=set()
    for item in rows_from_raw(raw):
        if isinstance(item,str):item={'requirement':item}
        if not isinstance(item,dict):continue
        name=str(item.get('requirement') or item.get('name') or item.get('skill') or item.get('title') or '').strip();key=norm(name)
        if not name or key in seen:continue
        seen.add(key);p=str(item.get('priority','preferred')).lower();c=str(item.get('category','other')).lower();s=str(item.get('status','missing')).lower();aliases={'mandatory':'required','must':'required','nice-to-have':'preferred','match':'matched','yes':'matched','no':'missing','not matched':'missing'};p=aliases.get(p,p);s=aliases.get(s,s)
        r=Requirement(requirement=name,priority=p if p in {'required','preferred'} else 'preferred',category=c if c in {'technical','experience','education','other'} else 'other',status=s if s in {'matched','partial','missing'} else 'missing',evidence=str(item.get('evidence') or item.get('cv_evidence') or 'No evidence in CV')[:220]);result.append(evidence_guard(r,cv))
    kws=raw.get('keywords') or raw.get('ats_keywords') or []
    if isinstance(kws,str):kws=[kws]
    return result[:10],list(dict.fromkeys(str(x) for x in kws if x))[:12]
def fallback_requirements(job:str,cv:str)->list[Requirement]:
    lines=[x.strip(' •-*\t') for x in job.splitlines() if 18<=len(x.strip())<=240];cues=['erfahrung','kenntnisse','entwicklung','entwickeln','software','ki','ai','llm','cloud','aws','agil','okr','microsoft','office','studium','abschluss','degree','experience','knowledge','develop','python','java','c#','typescript','tests','testing'];chosen=[];seen=set();cvt=toks(cv)
    for line in lines:
        low=line.lower()
        if not any(c in low for c in cues):continue
        key=norm(line)
        if key in seen:continue
        seen.add(key);rt=toks(line);overlap=len(rt&cvt)/max(1,len(rt));status='partial' if overlap>=.28 else 'missing';evidence='Related terminology found in CV' if status=='partial' else 'No evidence in CV';cat='education' if any(x in low for x in ['studium','abschluss','degree','master','bachelor']) else 'experience' if any(x in low for x in ['erfahrung','experience','praxis']) else 'technical' if any(x in low for x in ['software','ki','ai','llm','cloud','aws','python','java','c#','typescript','tests']) else 'other';priority='preferred' if any(x in low for x in ['wünsch','von vorteil','idealerweise','preferred','nice to have']) else 'required';chosen.append(Requirement(requirement=line[:180],priority=priority,category=cat,status=status,evidence=evidence))
        if len(chosen)>=8:break
    return chosen
def score(reqs:list[Requirement])->ScoreBreakdown:
    maxima={'technical':45,'experience':25,'education':15,'other':15};v={}
    for cat,mx in maxima.items():
        items=[r for r in reqs if r.category==cat]
        if not items:v[cat]=0;continue
        poss=sum(2 if r.priority=='required' else 1 for r in items);earned=sum((2 if r.priority=='required' else 1)*{'matched':1,'partial':.5,'missing':0}[r.status] for r in items);v[cat]=round(mx*earned/poss)
    return ScoreBreakdown(technical_skills=v['technical'],experience_projects=v['experience'],education_domain=v['education'],other_requirements=v['other'])
def summary(lang:str,m:list[str],miss:list[str],s:int)->str:
    if lang=='German':return f"Der evidenzbasierte Match-Score beträgt {s}/100. Belegte Stärken: {', '.join(m[:3]) if m else 'keine eindeutigen Volltreffer'}. Nicht belegte Anforderungen: {', '.join(miss[:3]) if miss else 'keine wesentlichen'}."
    return f"The evidence-based match score is {s}/100. Verified strengths: {', '.join(m[:3]) if m else 'no clear full matches'}. Unverified requirements: {', '.join(miss[:3]) if miss else 'none significant'}."
def prompt(cv:str,job:str)->str:return f'''Return ONLY valid compact JSON with top-level keys requirements and keywords. requirements is an array of 6-8 objects, each with requirement, priority, category, status, evidence. priority required|preferred; category technical|experience|education|other; status matched|partial|missing. Evidence MUST be a short exact substring copied from CV. If unavailable: status missing and evidence "No evidence in CV". Never infer AWS, Office, OKR, agents, cloud or testing from generic experience. No markdown.\nCV:\n{compact(cv,6000)}\nJOB:\n{compact(job,3800)}'''
def parse_model_json(text:str)->dict:
    text=(text or '').strip()
    if not text:return {}
    text=re.sub(r'^```(?:json)?\s*|\s*```$','',text,flags=re.I|re.S).strip()
    try:
        value=json.loads(text);return value if isinstance(value,dict) else {}
    except json.JSONDecodeError:pass
    start=text.find('{');end=text.rfind('}')
    if start>=0 and end>start:
        try:
            value=json.loads(text[start:end+1]);return value if isinstance(value,dict) else {}
        except json.JSONDecodeError:pass
    # A truncated/malformed local-model response is not fatal; caller uses deterministic fallback.
    return {}
async def ollama(p:str,n:int)->dict:
    base=os.getenv('OLLAMA_BASE_URL','http://localhost:11434').rstrip('/');model=os.getenv('OLLAMA_MODEL','llama3.2')
    try:
        async with httpx.AsyncClient(timeout=150) as client:
            r=await client.post(f'{base}/api/generate',json={'model':model,'prompt':p,'stream':False,'format':'json','keep_alive':'15m','options':{'temperature':0,'num_predict':n,'num_ctx':4096}});r.raise_for_status();return parse_model_json(r.json().get('response',''))
    except httpx.ConnectError as exc:raise HTTPException(503,'Cannot connect to Ollama.') from exc
    except httpx.TimeoutException as exc:raise HTTPException(504,'Ollama analysis timed out.') from exc
    except httpx.HTTPStatusError as exc:raise HTTPException(502,f'Ollama HTTP {exc.response.status_code}.') from exc
    except (ValueError,TypeError,KeyError):return {}

@app.get('/health')
async def health():return {'status':'ok','service':'ai-job-application-assistant','version':'1.3.2','pipeline':'fast-evidence-guarded-resilient'}
@app.post('/analyze',response_model=AnalysisResult)
async def analyze_endpoint(cv:UploadFile=File(...),job_description:str=Form(...)):
    started=time.perf_counter()
    if cv.content_type!='application/pdf' and not (cv.filename or '').lower().endswith('.pdf'):raise HTTPException(400,'Please upload a PDF CV.')
    if len(job_description.strip())<80:raise HTTPException(400,'Please provide a more complete job description.')
    data=await cv.read()
    if len(data)>5*1024*1024:raise HTTPException(413,'CV file is too large. Maximum size is 5 MB.')
    cvt=extract_pdf_text(data);raw=await ollama(prompt(cvt,job_description),700);reqs,kws=normalize_extraction(raw,cvt)
    if len(reqs)<3:reqs=fallback_requirements(job_description,cvt)
    if len(reqs)<3:raise HTTPException(502,'Could not identify enough job requirements from this posting.')
    bd=score(reqs);total=sum(bd.model_dump().values());matched=[r.requirement for r in reqs if r.status=='matched'];missing=[r.requirement for r in reqs if r.status=='missing'];lang=language_of(job_description)
    return AnalysisResult(match_score=total,score_breakdown=bd,detected_language=lang,summary=summary(lang,matched,missing,total),requirements=reqs,matched_skills=matched,missing_skills=missing,keywords=kws,analysis_seconds=round(time.perf_counter()-started,1))
@app.post('/generate',response_model=WritingResult)
async def generate_endpoint(cv:UploadFile=File(...),job_description:str=Form(...),analysis_json:str=Form(...)):
    cvt=extract_pdf_text(await cv.read())
    try:a=json.loads(analysis_json)
    except json.JSONDecodeError as exc:raise HTTPException(400,'Invalid analysis data.') from exc
    lang=a.get('detected_language',language_of(job_description));ev='\n'.join(f"- {x.get('requirement')}: {x.get('status')} | {x.get('evidence')}" for x in a.get('requirements',[])[:10]);p=f'''Return ONLY valid JSON with cv_suggestions, cover_letter, interview_questions. Write entirely in {lang}. Exactly 3 truthful suggestions, a 90-130 word cover letter, exactly 5 questions. Never invent missing experience. VERIFIED:\n{ev}\nCV:\n{compact(cvt,4500)}\nJOB:\n{compact(job_description,2500)}''';raw=await ollama(p,550);s=raw.get('cv_suggestions') or [];q=raw.get('interview_questions') or [];return WritingResult(cv_suggestions=s[:3] if isinstance(s,list) else [],cover_letter=str(raw.get('cover_letter') or ''),interview_questions=q[:5] if isinstance(q,list) else [])
