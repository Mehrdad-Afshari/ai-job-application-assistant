import io
import json
import os
from typing import List, Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader


class ScoreBreakdown(BaseModel):
    technical_skills: int = Field(ge=0, le=45)
    experience_projects: int = Field(ge=0, le=25)
    education_domain: int = Field(ge=0, le=15)
    other_requirements: int = Field(ge=0, le=15)


class Requirement(BaseModel):
    requirement: str
    priority: Literal["required", "preferred"]
    category: Literal["technical", "experience", "education", "other"]
    status: Literal["matched", "partial", "missing"]
    evidence: str


class ExtractionResult(BaseModel):
    detected_language: str
    requirements: List[Requirement]
    keywords: List[str]


class WritingResult(BaseModel):
    summary: str
    cv_suggestions: List[str]
    cover_letter: str
    interview_questions: List[str]


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


app = FastAPI(title="AI Job Application Assistant API", version="1.2.0", description="Hybrid deterministic + LLM CV/job matching.")
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


def extraction_prompt(cv_text: str, job_description: str) -> str:
    return f'''You are a strict evidence extractor. Compare the CV and job posting. Return ONLY JSON.

JSON structure:
{{"detected_language":"German","requirements":[{{"requirement":"Python","priority":"required","category":"technical","status":"matched","evidence":"Python listed in Skills"}}],"keywords":["Python"]}}

Rules:
- Extract only 6-10 most important requirements from the JOB POSTING.
- priority is required or preferred based on wording/context.
- category must be technical, experience, education, or other.
- status is matched ONLY when explicit CV evidence supports it; partial only for genuinely related evidence; otherwise missing.
- Never convert a job-posting statement into CV evidence.
- Evidence must cite a short fact actually present in the CV. If missing, write exactly "No evidence in CV".
- Do not treat generic software/AI experience as proof of a specific technology such as AWS, Microsoft Office, OKR, CI/CD, or a specific industry.
- Do not treat "AI" as proof of "AI agents" unless agents/tools/agentic systems are explicitly present in the CV.
- Preserve 6-12 useful ATS keywords from the job posting.
- Detect the main job-posting language.

CV:\n---\n{compact_text(cv_text, 9000)}\n---\nJOB POSTING:\n---\n{compact_text(job_description, 6000)}\n---'''


def dedupe_requirements(items: List[Requirement]) -> List[Requirement]:
    seen = set()
    result = []
    for item in items:
        key = " ".join(item.requirement.lower().split())
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result[:10]


def calculate_scores(requirements: List[Requirement]) -> ScoreBreakdown:
    maxima = {"technical": 45, "experience": 25, "education": 15, "other": 15}
    scores = {}
    for category, maximum in maxima.items():
        items = [r for r in requirements if r.category == category]
        if not items:
            scores[category] = maximum
            continue
        earned = 0.0
        possible = 0.0
        for item in items:
            weight = 2.0 if item.priority == "required" else 1.0
            possible += weight
            earned += weight * {"matched": 1.0, "partial": 0.5, "missing": 0.0}[item.status]
        scores[category] = round(maximum * earned / possible) if possible else maximum
    return ScoreBreakdown(
        technical_skills=scores["technical"],
        experience_projects=scores["experience"],
        education_domain=scores["education"],
        other_requirements=scores["other"],
    )


def writing_prompt(cv_text: str, job_description: str, extraction: ExtractionResult, score: int) -> str:
    evidence = "\n".join(f'- {r.requirement} | {r.priority} | {r.status} | {r.evidence}' for r in extraction.requirements)
    language = extraction.detected_language
    return f'''You are a career-writing assistant. Return ONLY JSON with this structure:
{{"summary":"...","cv_suggestions":["..."],"cover_letter":"...","interview_questions":["..."]}}

Write ALL natural-language output in {language}. Technology/product names may stay in their original form.
The deterministic match score is {score}/100. Do not change or reinterpret the score.
Use ONLY the supplied CV and verified requirement evidence. Never invent skills or experience.
- summary: 2 concise sentences explaining strongest matches and main gaps.
- cv_suggestions: exactly 3 specific truthful improvements tied to actual CV content; never tell the candidate to claim missing experience.
- cover_letter: 100-140 words, credible, tailored, and entirely in {language}.
- interview_questions: exactly 5 likely questions in {language}; for missing items ask about learning/approach, never assume experience.

VERIFIED REQUIREMENTS:\n{evidence}

CV:\n---\n{compact_text(cv_text, 6500)}\n---\nJOB POSTING:\n---\n{compact_text(job_description, 4000)}\n---'''


async def ollama_json(prompt: str, num_predict: int) -> dict:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(f"{base_url}/api/generate", json={
                "model": model, "prompt": prompt, "stream": False, "format": "json",
                "keep_alive": "10m", "options": {"temperature": 0.0, "num_predict": num_predict}
            })
            response.raise_for_status()
            text = response.json().get("response", "").strip()
            if not text:
                raise ValueError("Empty Ollama response")
            return json.loads(text)
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail="Cannot connect to Ollama.") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Ollama analysis timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"Ollama HTTP {exc.response.status_code}: {exc.response.text[:250]}") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Ollama returned invalid JSON.") from exc


async def analyze(cv_text: str, job_description: str) -> AnalysisResult:
    try:
        extraction = ExtractionResult.model_validate(await ollama_json(extraction_prompt(cv_text, job_description), 900))
        extraction.requirements = dedupe_requirements(extraction.requirements)
        breakdown = calculate_scores(extraction.requirements)
        score = sum(breakdown.model_dump().values())
        writing = WritingResult.model_validate(await ollama_json(writing_prompt(cv_text, job_description, extraction, score), 750))
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail=f"AI response validation failed: {exc.errors()[0]['msg']}") from exc

    matched = [r.requirement for r in extraction.requirements if r.status == "matched"]
    missing = [r.requirement for r in extraction.requirements if r.status == "missing"]
    return AnalysisResult(
        match_score=score, score_breakdown=breakdown, detected_language=extraction.detected_language,
        summary=writing.summary, requirements=extraction.requirements, matched_skills=matched,
        missing_skills=missing, keywords=list(dict.fromkeys(extraction.keywords))[:12],
        cv_suggestions=writing.cv_suggestions[:3], cover_letter=writing.cover_letter,
        interview_questions=writing.interview_questions[:5],
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-job-application-assistant", "version": "1.2.0", "pipeline": "hybrid-deterministic-llm"}


@app.post("/analyze", response_model=AnalysisResult)
async def analyze_endpoint(cv: UploadFile = File(...), job_description: str = Form(...)):
    if cv.content_type != "application/pdf" and not (cv.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF CV.")
    if len(job_description.strip()) < 80:
        raise HTTPException(status_code=400, detail="Please provide a more complete job description.")
    data = await cv.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CV file is too large. Maximum size is 5 MB.")
    return await analyze(extract_pdf_text(data), job_description)
