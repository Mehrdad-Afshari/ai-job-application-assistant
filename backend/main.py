import io
import json
import os
from typing import List

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError
from pypdf import PdfReader


class AnalysisResult(BaseModel):
    match_score: int = Field(ge=0, le=100)
    summary: str
    matched_skills: List[str]
    missing_skills: List[str]
    keywords: List[str]
    cv_suggestions: List[str]
    cover_letter: str
    interview_questions: List[str]


app = FastAPI(
    title="AI Job Application Assistant API",
    version="1.0.1",
    description="Analyze a CV against a job description using a local Ollama model.",
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


def build_prompt(cv_text: str, job_description: str) -> str:
    return f"""
You are an expert technical recruiter and ATS analyst.
Compare the candidate CV with the job description.
Use only evidence found in the CV. Never invent experience, skills, education, employers, achievements, or certifications.
Return a concise professional analysis that follows the supplied JSON schema exactly.

Scoring guidance:
- Required technical skills: 45%
- Relevant experience/projects: 25%
- Education/domain fit: 15%
- Tools, soft skills and other requirements: 15%

Rules:
- match_score must be an integer from 0 to 100.
- Every list must contain plain strings only.
- missing_skills should contain requirements that matter for this specific job and are not supported by the CV.
- keywords should contain useful ATS terms from the job description.
- cv_suggestions must be specific and must not tell the candidate to claim experience they do not have.
- cover_letter must be short, truthful and tailored to the supplied job description.
- interview_questions should focus on likely questions for this candidate and role.

CV:
---
{cv_text[:18000]}
---

JOB DESCRIPTION:
---
{job_description[:12000]}
---
""".strip()


def normalize_result(raw: dict) -> dict:
    aliases = {
        "score": "match_score",
        "overall_match_score": "match_score",
        "matchScore": "match_score",
        "assessment": "summary",
        "matchedSkills": "matched_skills",
        "missingSkills": "missing_skills",
        "ats_keywords": "keywords",
        "atsKeywords": "keywords",
        "suggestions": "cv_suggestions",
        "cvSuggestions": "cv_suggestions",
        "coverLetter": "cover_letter",
        "interviewQuestions": "interview_questions",
    }
    for source, target in aliases.items():
        if target not in raw and source in raw:
            raw[target] = raw[source]

    if isinstance(raw.get("match_score"), str):
        cleaned = raw["match_score"].replace("%", "").strip()
        try:
            raw["match_score"] = round(float(cleaned))
        except ValueError:
            pass

    list_fields = ["matched_skills", "missing_skills", "keywords", "cv_suggestions", "interview_questions"]
    for field in list_fields:
        value = raw.get(field)
        if isinstance(value, str):
            raw[field] = [value]
        elif value is None:
            raw[field] = []

    return raw


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
                    "options": {"temperature": 0.1},
                },
            )
            response.raise_for_status()
            payload = response.json()
            raw_text = payload.get("response", "").strip()
            if not raw_text:
                raise ValueError("Ollama returned an empty response")
            result = normalize_result(json.loads(raw_text))
            return AnalysisResult.model_validate(result)
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to Ollama. Start Ollama and make sure the configured model is installed.",
        ) from exc
    except (KeyError, json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"The AI model returned an invalid structured response ({type(exc).__name__}). Please try again.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = "Ollama request failed."
        if exc.response.status_code == 400:
            detail += " Your Ollama version may not support JSON-schema structured output; update Ollama and try again."
        raise HTTPException(status_code=502, detail=detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Ollama request failed.") from exc


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-job-application-assistant", "version": "1.0.1"}


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
