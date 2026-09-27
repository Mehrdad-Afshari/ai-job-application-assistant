import io
import json
import os
from typing import List

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
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
    version="1.0.0",
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
Compare the candidate CV with the job description. Be evidence-based: never claim a skill is present unless the CV supports it.
Return ONLY valid JSON. Do not use markdown fences.

Required JSON shape:
{{
  "match_score": 0,
  "summary": "2-4 sentence assessment",
  "matched_skills": ["skill"],
  "missing_skills": ["skill"],
  "keywords": ["important ATS keyword"],
  "cv_suggestions": ["specific improvement"],
  "cover_letter": "short tailored professional cover letter",
  "interview_questions": ["question"]
}}

Scoring guidance:
- Required technical skills: 45%
- Relevant experience/projects: 25%
- Education/domain fit: 15%
- Tools, soft skills and other requirements: 15%

CV:
---
{cv_text[:18000]}
---

JOB DESCRIPTION:
---
{job_description[:12000]}
---
""".strip()


async def analyze_with_ollama(prompt: str) -> AnalysisResult:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.2")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            )
            response.raise_for_status()
            payload = response.json()
            result = json.loads(payload["response"])
            return AnalysisResult.model_validate(result)
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to Ollama. Start Ollama and make sure the configured model is installed.",
        ) from exc
    except (KeyError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="The AI model returned an invalid structured response.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Ollama request failed.") from exc


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ai-job-application-assistant"}


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
