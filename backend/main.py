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


app = FastAPI(
    title="AI Job Application Assistant API",
    version="1.1.0",
    description="Evidence-based CV and job matching using a local Ollama model.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    compact = "\n".join(lines)
    return compact[:limit]


def build_prompt(cv_text: str, job_description: str) -> str:
    cv = compact_text(cv_text, 12000)
    job = compact_text(job_description, 8000)
    return f"""
Act as an evidence-based technical recruiter and ATS analyst. Compare the CV with the job posting.

STRICT RULES
1. Use only facts explicitly supported by the CV. Never infer or invent skills or experience.
2. Identify important job requirements and classify each as required or preferred from the wording/context of the posting.
3. For each requirement mark matched, partial, or missing and provide a very short CV evidence note. For missing requirements use "No evidence in CV".
4. The four score components must add up exactly to match_score:
   technical_skills max 45; experience_projects max 25; education_domain max 15; other_requirements max 15.
5. Penalize missing REQUIRED requirements more than preferred requirements. Domain/industry experience must not receive a large penalty unless the posting actually requires it.
6. matched_skills may contain only skills supported by the CV AND relevant to this job.
7. missing_skills should focus on meaningful required/preferred gaps, not generic extras.
8. Detect the main language of the JOB POSTING. Write summary, CV suggestions, cover letter and interview questions entirely in that language. Do not mix languages except for established technology/product names.
9. ATS keywords should preserve useful terminology from the job posting.
10. Give 3-5 concrete CV suggestions. Refer to a real CV section/project/experience when possible and explain what to emphasize or clarify. Never advise the candidate to falsely add a skill.
11. Write a concise, credible cover letter (roughly 130-190 words) grounded in the CV. Do not claim missing experience.
12. Write 5 likely interview questions. If a requirement is missing, phrase it as a gap/learning question rather than falsely assuming experience.
13. Keep the whole response concise to reduce latency.

CV
---
{cv}
---
JOB POSTING
---
{job}
---
""".strip()


async def analyze_with_ollama(prompt: str) -> AnalysisResult:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    schema = AnalysisResult.model_json_schema()
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0.0, "num_predict": 1800},
                },
            )
            response.raise_for_status()
            raw_text = response.json().get("response", "").strip()
            if not raw_text:
                raise ValueError("Ollama returned an empty response")
            result = AnalysisResult.model_validate(json.loads(raw_text))
            total = sum(result.score_breakdown.model_dump().values())
            result.match_score = max(0, min(100, total))
            return result
    except httpx.ConnectError as exc:
        raise HTTPException(status_code=503, detail="Cannot connect to Ollama. Start Ollama and verify the configured model.") from exc
    except (KeyError, json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=502, detail=f"Invalid structured AI response ({type(exc).__name__}). Please try again.") from exc
    except httpx.HTTPStatusError as exc:
        detail = "Ollama request failed."
        if exc.response.status_code == 400:
            detail += " Update Ollama if your version does not support JSON-schema output."
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Ollama request failed.") from exc


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-job-application-assistant", "version": "1.1.0"}


@app.post("/analyze", response_model=AnalysisResult)
async def analyze(cv: UploadFile = File(...), job_description: str = Form(...)):
    if cv.content_type != "application/pdf" and not (cv.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload a PDF CV.")
    if len(job_description.strip()) < 80:
        raise HTTPException(status_code=400, detail="Please provide a more complete job description.")
    data = await cv.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CV file is too large. Maximum size is 5 MB.")
    cv_text = extract_pdf_text(data)
    return await analyze_with_ollama(build_prompt(cv_text, job_description))
