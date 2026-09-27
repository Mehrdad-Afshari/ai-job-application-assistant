# AI Job Application Assistant

A **local-first, evidence-based AI job application assistant** that compares a PDF CV with a job description, calculates a transparent match score, identifies verified and missing requirements, and generates guarded application material with a local LLM.

Built as a portfolio project to explore practical AI-assisted software engineering, hybrid deterministic/LLM pipelines, hallucination control, and privacy-friendly AI applications.

## Why this project?

Many CV/job matching tools ask an LLM to both interpret the documents and invent a final score. That makes the result difficult to explain and can create contradictions or unsupported claims.

This project deliberately separates responsibilities:

- **Deterministic analysis** handles requirement matching and scoring.
- **Evidence states** distinguish `MATCHED`, `PARTIAL`, and `MISSING` requirements.
- **Local AI generation** is used only where natural-language generation adds value.
- **Generation guardrails** prevent known missing requirements from being presented as verified candidate experience.

## Features

- PDF CV upload and text extraction
- Job-description requirement extraction
- Required vs. preferred requirement classification
- Evidence-based `MATCHED / PARTIAL / MISSING` states
- Deterministic 100-point scoring engine
- Score breakdown for technical skills, experience/projects, education/domain, and other requirements
- ATS keyword extraction
- Automatic German/English detection
- Evidence-aware CV improvement suggestions
- Tailored local-AI cover letter generation
- Five role-specific interview questions
- Guardrails against unsupported experience claims
- Generation quality and repetition checks
- Local processing with Ollama
- Responsive Next.js dashboard
- Analysis and generation latency reporting

## Architecture

```text
PDF CV + Job Description
          |
          v
   Text Preprocessing
          |
          v
 Requirement Extraction
          |
          v
 Evidence Classification
 MATCHED / PARTIAL / MISSING
          |
          v
 Deterministic Python Scoring
          |
          +----------------------+
          |                      |
          v                      v
 Analysis Dashboard      Guarded Local LLM
                              |
                              v
                    Tailored Cover Letter
                              +
                    Deterministic Suggestions
                    & Interview Questions
```

The local LLM **does not control the match score**. The backend calculates the score from canonical requirement states. This also keeps the verified/missing lists consistent with the score shown to the user.

## Generation Guardrails

The application-writing stage receives the existing analysis as structured evidence. Requirements marked `MISSING` are treated as gaps rather than candidate experience.

The backend additionally validates generated output and can reject a cover letter when it detects an unsupported experience claim or low-quality/repetitive generation. CV suggestions and interview questions are generated deterministically from the evidence table, reducing unnecessary LLM work and improving consistency.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 15, TypeScript, Tailwind CSS |
| Backend | FastAPI, Python, Pydantic |
| PDF processing | pypdf |
| Local AI | Ollama + Llama 3.2 |
| HTTP client | HTTPX |
| Source control | Git + GitHub |

## Current Version

**v1.6.1 — Fast Analysis + Polished Guarded Generation**

During development, local generation latency on the test environment was reduced from approximately **101 s to 49 s** while moving suggestions and interview-question generation out of the LLM path. Actual performance depends on the user's hardware and Ollama configuration.

## Quick Start

### Prerequisites

- Node.js 20+
- Python **3.12 recommended**
- Ollama

### 1. Install the local model

```bash
ollama pull llama3.2
```

### 2. Start the backend

```bash
cd backend
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Health check:

```text
http://localhost:8000/health
```

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Environment Variables

Frontend — `frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Backend — optional:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

## API

### `POST /analyze`

Multipart form data:

- `cv` — PDF CV, maximum 5 MB
- `job_description` — complete job-description text

Returns the evidence table, score breakdown, ATS keywords, language, and analysis latency.

### `POST /generate`

Uses the CV, job description, and structured analysis result to create guarded application-writing output.

Returns:

- three evidence-aware CV suggestions
- tailored cover letter
- five interview questions
- generation latency

## Privacy

By default, the project uses a locally running Ollama model. CV and job-description content therefore do not need to be sent to a third-party LLM API.

## Engineering Decisions

**Why deterministic scoring?**  
A numeric score should be reproducible and explainable instead of changing whenever an LLM produces a different response.

**Why use an LLM only for the cover letter?**  
Natural-language generation benefits from an LLM. Requirement scoring, suggestions, and question selection can be handled more reliably and quickly with deterministic application logic.

**Why local AI?**  
CVs contain personal information. Local inference provides a useful privacy-first default and makes the project runnable without paid AI API credentials.

## Limitations

- Requirement extraction currently uses a curated skill/keyword model rather than semantic embeddings.
- Local cover-letter quality and speed depend on the selected Ollama model and hardware.
- PDF text extraction expects a text-readable PDF; scanned/image-only CVs are not OCR processed.
- The current release focuses on German and English job postings.

## Roadmap

- [x] PDF CV parsing
- [x] Evidence-based requirement matching
- [x] Deterministic scoring engine
- [x] German/English support
- [x] Local LLM application writing
- [x] Hallucination guardrails
- [x] Generation quality checks
- [x] Responsive dashboard
- [ ] Automated backend tests
- [ ] DOCX CV support
- [ ] Export analysis as PDF
- [ ] Optional semantic/embedding-based requirement matching
- [ ] Optional cloud LLM providers
- [ ] Analysis history

## Author

**Mehrdad Afshari**  
M.Sc. Computer Science student at the University of Rostock · Software Developer · AI-focused application development

## License

This repository is currently provided as a portfolio and learning project. Add an explicit open-source license before reusing or distributing the code under open-source terms.
