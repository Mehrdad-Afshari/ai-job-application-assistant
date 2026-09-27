# AI Job Application Assistant

A local-first AI application that compares a CV with a job description and produces evidence-based application insights.

## v1.2 Highlights

- PDF CV parsing
- Evidence-based job requirement extraction
- Required vs. preferred requirement classification
- Matched / partial / missing evidence states
- **Deterministic Python scoring** instead of letting the LLM invent a score
- Technical, experience, education and other score breakdowns
- ATS keyword extraction
- Language-aware CV suggestions, cover letter and interview questions
- Local-first processing with Ollama
- Responsive Next.js dashboard

## Tech Stack

- **Frontend:** Next.js, TypeScript, Tailwind CSS
- **Backend:** FastAPI, Python, Pydantic, pypdf
- **AI:** Ollama (`llama3.2` by default)

## Hybrid Pipeline

```text
CV PDF + Job Description
          |
          v
     PDF/Text Preprocessing
          |
          v
  LLM Evidence Extraction
  requirements + evidence
          |
          v
 Deterministic Python Scoring
          |
          v
 LLM Application Writing
 summary + CV suggestions
 cover letter + interview Qs
          |
          v
     Next.js Dashboard
```

The LLM does not control the final match score. Python calculates it from the verified requirement statuses, with required requirements weighted more heavily than preferred ones. Matched and missing lists are generated from the same canonical requirement table to prevent contradictory results.

## Quick Start

### 1. Ollama

```bash
ollama pull llama3.2
```

### 2. Backend

Python 3.12 is recommended.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Health check: `http://localhost:8000/health`

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## Environment Variables

Frontend (`frontend/.env.local`):

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Backend (optional):

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

## API

`POST /analyze` accepts multipart form data:

- `cv`: PDF file (max 5 MB)
- `job_description`: full job-description text

## Privacy

The default configuration uses a locally running Ollama model, so CV and job-description content do not need to be sent to a third-party LLM API.

## Roadmap

- [x] MVP architecture
- [x] PDF parsing
- [x] Evidence-based requirement extraction
- [x] Deterministic scoring engine
- [x] Language-aware application writing
- [x] Responsive analysis dashboard
- [ ] DOCX support
- [ ] Export analysis as PDF
- [ ] Optional cloud LLM providers
- [ ] Job-analysis history

## Author

**Mehrdad Afshari** — AI & Software Developer
