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
    status: Literal["matched", "partial", "missing"]
    evidence: str


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


app = FastAPI(title="AI Job Application Assistant API", version="1.1.1", description="Evidence-based CV and job matching using a local Ollama model.")
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


def build_prompt(cv_text: str, job_description: str) -> str:
    cv = compact_text(cv_text, 10000)
    job = compact_text(job_description, 6500)
    return f'''Act as an evidence-based technical recruiter and ATS analyst. Compare the CV with the job posting.
Return ONLY one valid JSON object, with no markdown and no text before or after it.

Use exactly this structure:
{{
 "match_score": 0,
 "score_breakdown": {{"technical_skills": 0, "experience_projects": 0, "education_domain": 0, "other_requirements": 0}},
 "detected_language": "German or English or other language",
 "summary": "...",
 "requirements": [{{"requirement":"...","priority":"required","status":"matched","evidence":"..."}}],
 "matched_skills": ["..."],
 "missing_skills": ["..."],
 "keywords": ["..."],
 "cv_suggestions": ["..."],
 "cover_letter": "...",
 "interview_questions": ["..."]
}}

Rules:
- Only facts explicitly supported by the CV may be called matched. Never invent experience or skills.
- Classify important requirements as required/preferred and matched/partial/missing. Missing evidence = "No evidence in CV".
- Score maxima: technical_skills 45, experience_projects 25, education_domain 15, other_requirements 15. Penalize missing required items more than preferred ones. Industry experience gets a large penalty only if actually required.
- Keep 6-10 most important requirements, 5-12 matched skills, 2-8 meaningful gaps, and 6-12 ATS keywords.
- Detect the job posting language. Write summary, CV suggestions, cover letter and interview questions fully in that language; technology names may remain unchanged.
- Give 3-5 specific, truthful CV suggestions tied to real CV sections/projects/experience.
- Cover letter: credible and concise, about 110-160 words, never claim missing experience.
- Exactly 5 interview questions. For missing skills ask how the candidate would learn/handle the gap instead of assuming experience.
- Keep evidence notes short.

CV:\n---\n{cv}\n---\nJOB POSTING:\n---\n{job}\n---'''


async def analyze_with_ollama(prompt: str) -> AnalysisResult:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    try:
        async with httpx.AsyncClient(timeout=240.0) as client:
            response = await client.post(f"{base_url}/api/generate", json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0, "num_predict": 1500}
            })
            response.raise_for_status()
            raw_text = response.json().get("response", "").strip()
            if not raw_text:
                raise ValueError("Ollama returned an empty response")
            result = AnalysisResult.model_validate(json.loads(raw_text))
            result.match_score = max(0, min(100, sum(result.score_breakdown.model_dump().values())))
            return result
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail="Cannot connect to Ollama. Start Ollama and verify the configured model.") from exc
    except (KeyError, json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"Invalid structured AI response ({type(exc).__name__}). Please try again.") from exc
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300].replace("\n", " ")
        raise HTTPException(status_code=502, detail=f"Ollama HTTP {exc.response.status_code}: {body or 'request failed'}") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Ollama analysis timed out. Please try again.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Ollama connection error: {type(exc).__name__}") from exc


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-job-application-assistant", "version": "1.1.1"}


@app.post("/analyze", response_model=AnalysisResult)
async def analyze(cv: UploadFile = File(...), job_description: str = Form(...)):
    if cv.content_type != "application/pdf" and not (cv.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF CV.")
    if len(job_description.strip()) < 80:
        raise HTTPException(status_code=400, detail="Please provide a more complete job description.")
    data = await cv.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CV file is too large. Maximum size is 5 MB.")
    return await analyze_with_ollama(build_prompt(extract_pdf_text(data), job_description))
