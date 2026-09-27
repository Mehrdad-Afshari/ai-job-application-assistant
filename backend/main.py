import io
import json
import os
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


class ExtractionResult(BaseModel):
    detected_language: str = "English"
    requirements: List[Requirement] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)


class WritingResult(BaseModel):
    summary: str = "Analysis completed from the verified requirement evidence."
    cv_suggestions: List[str] = Field(default_factory=list)
    cover_letter: str = ""
    interview_questions: List[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    match_score: int = Field(ge=0, le=100)
    score_breakdown: ScoreBreakdown
    detected_language: str
    summary: str
    requirements: List[Requirement]
    matched_skills: List[str]
    missing_skills: List[str]
    keywords: List[str]
    cv_suggestions: List[str]
    cover_letter: str
    interview_questions: List[str]


app = FastAPI(title="AI Job Application Assistant API", version="1.2.1", description="Hybrid deterministic + LLM CV/job matching.")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def extract_pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not read the PDF file.") from exc
    if not text:
        raise HTTPException(status_code=400, detail="No readable text was found in the PDF.")
    return text


def compact_text(text: str, limit: int) -> str:
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())[:limit]


def normalize_choice(value, allowed, default):
    candidate = str(value or "").strip().lower()
    aliases = {"mandatory": "required", "must": "required", "nice-to-have": "preferred", "nice to have": "preferred", "match": "matched", "yes": "matched", "no": "missing", "not matched": "missing"}
    candidate = aliases.get(candidate, candidate)
    return candidate if candidate in allowed else default


def normalize_extraction(raw: dict) -> ExtractionResult:
    language = raw.get("detected_language") or raw.get("language") or "English"
    raw_requirements = raw.get("requirements") or raw.get("job_requirements") or []
    requirements = []
    if isinstance(raw_requirements, dict):
        raw_requirements = list(raw_requirements.values())
    for item in raw_requirements:
        if isinstance(item, str):
            requirements.append(Requirement(requirement=item))
            continue
        if not isinstance(item, dict):
            continue
        name = item.get("requirement") or item.get("name") or item.get("skill") or item.get("title")
        if not name:
            continue
        requirements.append(Requirement(
            requirement=str(name),
            priority=normalize_choice(item.get("priority"), {"required", "preferred"}, "preferred"),
            category=normalize_choice(item.get("category"), {"technical", "experience", "education", "other"}, "other"),
            status=normalize_choice(item.get("status"), {"matched", "partial", "missing"}, "missing"),
            evidence=str(item.get("evidence") or "No evidence in CV"),
        ))
    keywords = raw.get("keywords") or raw.get("ats_keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    return ExtractionResult(detected_language=str(language), requirements=requirements, keywords=[str(x) for x in keywords if x])


def normalize_writing(raw: dict, language: str) -> WritingResult:
    suggestions = raw.get("cv_suggestions") or raw.get("suggestions") or []
    questions = raw.get("interview_questions") or raw.get("questions") or []
    if isinstance(suggestions, str): suggestions = [suggestions]
    if isinstance(questions, str): questions = [questions]
    fallback = "Analyse auf Basis der verifizierten Anforderungen abgeschlossen." if "german" in language.lower() or "deutsch" in language.lower() else "Analysis completed from the verified requirements."
    return WritingResult(
        summary=str(raw.get("summary") or raw.get("assessment") or fallback),
        cv_suggestions=[str(x) for x in suggestions if x],
        cover_letter=str(raw.get("cover_letter") or raw.get("coverLetter") or ""),
        interview_questions=[str(x) for x in questions if x],
    )


def extraction_prompt(cv_text: str, job_description: str) -> str:
    return f'''Strictly compare CV evidence to the job posting. Return ONLY JSON with keys: detected_language, requirements, keywords.
Each requirements item MUST contain: requirement, priority, category, status, evidence.
Allowed priority: required, preferred. Allowed category: technical, experience, education, other. Allowed status: matched, partial, missing.
Extract 6-10 important requirements. A specific technology is matched only if explicitly supported by the CV. Never use the job posting itself as CV evidence. Missing evidence must be "No evidence in CV". Keep evidence short. Detect the job language.
CV:\n---\n{compact_text(cv_text, 8500)}\n---\nJOB:\n---\n{compact_text(job_description, 5500)}\n---'''


def dedupe_requirements(items: List[Requirement]) -> List[Requirement]:
    seen, result = set(), []
    for item in items:
        key = " ".join(item.requirement.lower().split())
        if key and key not in seen:
            seen.add(key); result.append(item)
    return result[:10]


def calculate_scores(requirements: List[Requirement]) -> ScoreBreakdown:
    maxima = {"technical": 45, "experience": 25, "education": 15, "other": 15}
    scores = {}
    for category, maximum in maxima.items():
        items = [r for r in requirements if r.category == category]
        if not items:
            scores[category] = maximum
            continue
        possible = sum(2.0 if r.priority == "required" else 1.0 for r in items)
        earned = sum((2.0 if r.priority == "required" else 1.0) * {"matched": 1.0, "partial": .5, "missing": 0.0}[r.status] for r in items)
        scores[category] = round(maximum * earned / possible)
    return ScoreBreakdown(technical_skills=scores["technical"], experience_projects=scores["experience"], education_domain=scores["education"], other_requirements=scores["other"])


def writing_prompt(cv_text: str, job_description: str, extraction: ExtractionResult, score: int) -> str:
    evidence = "\n".join(f'- {r.requirement} | {r.priority} | {r.status} | {r.evidence}' for r in extraction.requirements)
    return f'''Return ONLY JSON with keys summary, cv_suggestions, cover_letter, interview_questions. Write all natural language in {extraction.detected_language}. Match score is fixed at {score}/100. Use only CV facts and verified evidence. Summary: 2 sentences. CV suggestions: exactly 3 truthful specific items. Cover letter: 90-130 words. Interview questions: exactly 5. Never claim missing experience.
EVIDENCE:\n{evidence}\nCV:\n{compact_text(cv_text, 5500)}\nJOB:\n{compact_text(job_description, 3200)}'''


async def ollama_json(prompt: str, num_predict: int) -> dict:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(f"{base_url}/api/generate", json={"model": model, "prompt": prompt, "stream": False, "format": "json", "keep_alive": "10m", "options": {"temperature": 0.0, "num_predict": num_predict}})
            response.raise_for_status()
            text = response.json().get("response", "").strip()
            if not text: raise ValueError("Empty Ollama response")
            value = json.loads(text)
            return value if isinstance(value, dict) else {}
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail="Cannot connect to Ollama.") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Ollama analysis timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Ollama HTTP {exc.response.status_code}: {exc.response.text[:250]}") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Ollama returned invalid JSON.") from exc


async def run_analysis(cv_text: str, job_description: str) -> AnalysisResult:
    extraction = normalize_extraction(await ollama_json(extraction_prompt(cv_text, job_description), 850))
    extraction.requirements = dedupe_requirements(extraction.requirements)
    if not extraction.requirements:
        raise HTTPException(status_code=502, detail="The local model did not extract usable job requirements. Please try again.")
    breakdown = calculate_scores(extraction.requirements)
    score = sum(breakdown.model_dump().values())
    writing = normalize_writing(await ollama_json(writing_prompt(cv_text, job_description, extraction, score), 650), extraction.detected_language)
    matched = [r.requirement for r in extraction.requirements if r.status == "matched"]
    missing = [r.requirement for r in extraction.requirements if r.status == "missing"]
    return AnalysisResult(match_score=score, score_breakdown=breakdown, detected_language=extraction.detected_language, summary=writing.summary, requirements=extraction.requirements, matched_skills=matched, missing_skills=missing, keywords=list(dict.fromkeys(extraction.keywords))[:12], cv_suggestions=writing.cv_suggestions[:3], cover_letter=writing.cover_letter, interview_questions=writing.interview_questions[:5])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-job-application-assistant", "version": "1.2.1", "pipeline": "hybrid-deterministic-llm"}


@app.post("/analyze", response_model=AnalysisResult)
async def analyze_endpoint(cv: UploadFile = File(...), job_description: str = Form(...)):
    if cv.content_type != "application/pdf" and not (cv.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF CV.")
    if len(job_description.strip()) < 80:
        raise HTTPException(status_code=400, detail="Please provide a more complete job description.")
    data = await cv.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CV file is too large. Maximum size is 5 MB.")
    return await run_analysis(extract_pdf_text(data), job_description)
