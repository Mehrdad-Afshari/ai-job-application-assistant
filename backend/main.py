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
    technical_skills: int = Field(ge=0, le=45)
    experience_projects: int = Field(ge=0, le=25)
    education_domain: int = Field(ge=0, le=15)
    other_requirements: int = Field(ge=0, le=15)


class Requirement(BaseModel):
    requirement: str
    priority: Literal["required", "preferred"] = "preferred"
    category: Literal["technical", "experience", "education", "other"] = "other"
    status: Literal["matched", "partial", "missing"] = "missing"
    evidence: str = "No evidence in CV"


class AnalysisResult(BaseModel):
    match_score: int
    score_breakdown: ScoreBreakdown
    detected_language: str
    summary: str
    requirements: List[Requirement]
    matched_skills: List[str]
    missing_skills: List[str]
    keywords: List[str]
    analysis_seconds: float


class WritingResult(BaseModel):
    cv_suggestions: List[str] = Field(default_factory=list)
    cover_letter: str = ""
    interview_questions: List[str] = Field(default_factory=list)


app = FastAPI(title="AI Job Application Assistant API", version="1.3.0", description="Fast evidence-guarded local AI job matching.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def extract_pdf_text(data: bytes) -> str:
    try:
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages).strip()
    except Exception as exc:
        raise HTTPException(400, "Could not read the PDF file.") from exc
    if not text:
        raise HTTPException(400, "No readable text was found in the PDF.")
    return text


def compact(text: str, limit: int) -> str:
    return "\n".join(x.strip() for x in text.splitlines() if x.strip())[:limit]


def language_of(job: str) -> str:
    low = f" {job.lower()} "
    german = sum(low.count(x) for x in [" und ", " der ", " die ", " das ", " mit ", " erfahrung", "kenntnisse", "aufgaben", "wir "])
    return "German" if german >= 4 else "English"


def norm(value: str) -> str:
    value = value.lower().replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9äöüß+#./-]+", " ", value).strip()


def tokens(value: str) -> set[str]:
    stop = {"and","or","the","with","for","from","und","oder","der","die","das","mit","von","für","in","im","zu","eine","einer","sowie","kenntnisse","erfahrung","erfahrungen","sehr","gute"}
    return {x for x in re.findall(r"[a-z0-9äöüß+#.]+", norm(value)) if len(x) > 2 and x not in stop}


def evidence_guard(req: Requirement, cv: str) -> Requirement:
    cv_norm = norm(cv)
    ev = (req.evidence or "").strip()
    if not ev or ev.lower() == "no evidence in cv":
        req.status, req.evidence = "missing", "No evidence in CV"
        return req
    ev_norm = norm(ev)
    # Evidence must actually occur in, or strongly overlap with, CV text.
    ev_tokens = tokens(ev_norm)
    cv_tokens = tokens(cv_norm)
    overlap = len(ev_tokens & cv_tokens) / max(1, len(ev_tokens))
    if ev_norm not in cv_norm and overlap < 0.72:
        req.status, req.evidence = "missing", "No evidence in CV"
        return req
    req_tokens = tokens(req.requirement)
    relevance = len(req_tokens & cv_tokens) / max(1, len(req_tokens))
    if req.status == "matched" and relevance < 0.18:
        req.status = "partial" if relevance > 0 else "missing"
        if req.status == "missing": req.evidence = "No evidence in CV"
    return req


def normalize_extraction(raw: dict, cv: str) -> tuple[list[Requirement], list[str]]:
    rows = raw.get("requirements") or []
    if isinstance(rows, dict): rows = list(rows.values())
    result, seen = [], set()
    for item in rows:
        if not isinstance(item, dict): continue
        name = str(item.get("requirement") or item.get("name") or "").strip()
        key = norm(name)
        if not name or key in seen: continue
        seen.add(key)
        priority = str(item.get("priority", "preferred")).lower()
        category = str(item.get("category", "other")).lower()
        status = str(item.get("status", "missing")).lower()
        r = Requirement(
            requirement=name,
            priority=priority if priority in {"required","preferred"} else "preferred",
            category=category if category in {"technical","experience","education","other"} else "other",
            status=status if status in {"matched","partial","missing"} else "missing",
            evidence=str(item.get("evidence") or "No evidence in CV")[:220],
        )
        result.append(evidence_guard(r, cv))
    keywords = raw.get("keywords") or []
    if isinstance(keywords, str): keywords = [keywords]
    return result[:10], list(dict.fromkeys(str(x) for x in keywords if x))[:12]


def score(requirements: list[Requirement]) -> ScoreBreakdown:
    maxima = {"technical":45,"experience":25,"education":15,"other":15}
    values = {}
    all_possible = {c: sum(2 if r.priority == "required" else 1 for r in requirements if r.category == c) for c in maxima}
    total_weight = sum(all_possible.values()) or 1
    for category, maximum in maxima.items():
        items = [r for r in requirements if r.category == category]
        if not items:
            # No extracted evidence means neutral/unknown, not a free perfect score.
            values[category] = 0
            continue
        possible = sum(2 if r.priority == "required" else 1 for r in items)
        earned = sum((2 if r.priority == "required" else 1) * {"matched":1.0,"partial":0.5,"missing":0.0}[r.status] for r in items)
        values[category] = round(maximum * earned / possible)
    return ScoreBreakdown(technical_skills=values["technical"], experience_projects=values["experience"], education_domain=values["education"], other_requirements=values["other"])


def summary_for(language: str, matched: list[str], missing: list[str], score_value: int) -> str:
    if language == "German":
        strength = ", ".join(matched[:3]) if matched else "keine eindeutig belegten Kernanforderungen"
        gaps = ", ".join(missing[:3]) if missing else "keine wesentlichen belegten Lücken"
        return f"Der evidenzbasierte Match-Score beträgt {score_value}/100. Stärken: {strength}. Offene bzw. nicht belegte Anforderungen: {gaps}."
    strength = ", ".join(matched[:3]) if matched else "no clearly evidenced core requirements"
    gaps = ", ".join(missing[:3]) if missing else "no major evidenced gaps"
    return f"The evidence-based match score is {score_value}/100. Strengths: {strength}. Missing or unverified requirements: {gaps}."


def extraction_prompt(cv: str, job: str) -> str:
    return f'''Return ONLY compact JSON: {{"requirements":[{{"requirement":"...","priority":"required|preferred","category":"technical|experience|education|other","status":"matched|partial|missing","evidence":"EXACT short quote from CV or No evidence in CV"}}],"keywords":["..."]}}.
Extract 6-9 important requirements from JOB. Evidence MUST be a short verbatim substring copied from CV. If you cannot copy supporting words from CV, status MUST be missing and evidence MUST be exactly "No evidence in CV". Never infer AWS, Office, OKR, agents, testing, cloud, industry, or other specific skills from generic software/AI experience. Use partial only when the copied CV evidence is directly related but weaker than the requirement. Keep evidence under 18 words. No explanations outside JSON.
CV:\n---\n{compact(cv, 7000)}\n---\nJOB:\n---\n{compact(job, 4500)}\n---'''


async def ollama(prompt: str, num_predict: int) -> dict:
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    try:
        async with httpx.AsyncClient(timeout=150.0) as client:
            r = await client.post(f"{base}/api/generate", json={"model":model,"prompt":prompt,"stream":False,"format":"json","keep_alive":"15m","options":{"temperature":0,"num_predict":num_predict,"num_ctx":4096}})
            r.raise_for_status()
            return json.loads(r.json().get("response", "{}"))
    except httpx.ConnectError as exc: raise HTTPException(503, "Cannot connect to Ollama.") from exc
    except httpx.TimeoutException as exc: raise HTTPException(504, "Ollama analysis timed out.") from exc
    except Exception as exc: raise HTTPException(502, f"Local AI analysis failed: {type(exc).__name__}") from exc


@app.get("/health")
async def health():
    return {"status":"ok","service":"ai-job-application-assistant","version":"1.3.0","pipeline":"fast-evidence-guarded"}


@app.post("/analyze", response_model=AnalysisResult)
async def analyze_endpoint(cv: UploadFile = File(...), job_description: str = Form(...)):
    started = time.perf_counter()
    if cv.content_type != "application/pdf" and not (cv.filename or "").lower().endswith(".pdf"): raise HTTPException(400, "Please upload a PDF CV.")
    if len(job_description.strip()) < 80: raise HTTPException(400, "Please provide a more complete job description.")
    data = await cv.read()
    if len(data) > 5*1024*1024: raise HTTPException(413, "CV file is too large. Maximum size is 5 MB.")
    cv_text = extract_pdf_text(data)
    raw = await ollama(extraction_prompt(cv_text, job_description), 650)
    requirements, keywords = normalize_extraction(raw, cv_text)
    if len(requirements) < 3: raise HTTPException(502, "The local model did not extract enough usable requirements. Please try again.")
    breakdown = score(requirements)
    total = sum(breakdown.model_dump().values())
    matched = [r.requirement for r in requirements if r.status == "matched"]
    missing = [r.requirement for r in requirements if r.status == "missing"]
    lang = language_of(job_description)
    return AnalysisResult(match_score=total, score_breakdown=breakdown, detected_language=lang, summary=summary_for(lang, matched, missing, total), requirements=requirements, matched_skills=matched, missing_skills=missing, keywords=keywords, analysis_seconds=round(time.perf_counter()-started,1))


@app.post("/generate", response_model=WritingResult)
async def generate_endpoint(cv: UploadFile = File(...), job_description: str = Form(...), analysis_json: str = Form(...)):
    data = await cv.read(); cv_text = extract_pdf_text(data)
    try: analysis = json.loads(analysis_json)
    except json.JSONDecodeError as exc: raise HTTPException(400, "Invalid analysis data.") from exc
    lang = analysis.get("detected_language", language_of(job_description))
    reqs = analysis.get("requirements", [])
    evidence = "\n".join(f'- {x.get("requirement")}: {x.get("status")} | {x.get("evidence")}' for x in reqs[:10])
    prompt = f'''Return ONLY JSON with keys cv_suggestions, cover_letter, interview_questions. Write entirely in {lang}. Use only CV facts and this verified analysis. Exactly 3 truthful CV suggestions, a 90-130 word cover letter, exactly 5 interview questions. Never tell the candidate to add experience they do not have; for gaps suggest learning or honest positioning.\nVERIFIED ANALYSIS:\n{evidence}\nCV:\n{compact(cv_text,5000)}\nJOB:\n{compact(job_description,3000)}'''
    raw = await ollama(prompt, 600)
    suggestions = raw.get("cv_suggestions") or raw.get("suggestions") or []
    questions = raw.get("interview_questions") or raw.get("questions") or []
    return WritingResult(cv_suggestions=suggestions[:3] if isinstance(suggestions,list) else [], cover_letter=str(raw.get("cover_letter") or ""), interview_questions=questions[:5] if isinstance(questions,list) else [])
