# AI Job Application Assistant

An AI-powered web application that compares a CV with a job description and returns structured, actionable application insights.

## Features

- PDF CV upload and text extraction
- Job description analysis
- Overall job match score
- Matched and missing skills
- ATS/job keywords
- CV improvement suggestions
- Tailored cover-letter draft
- Likely interview questions
- Local-first AI with Ollama

## Tech Stack

- **Frontend:** Next.js, TypeScript, Tailwind CSS
- **Backend:** FastAPI, Python, Pydantic, pypdf
- **AI:** Ollama (`llama3.2` by default)

## Architecture

```text
CV PDF + Job Description
          |
          v
     Next.js UI
          |
          v
   FastAPI Backend
      /       \
 PDF Parser   Prompt Builder
                  |
                  v
                Ollama
                  |
                  v
         Structured JSON Result
```

## Quick Start

### 1. Ollama

Install Ollama and pull the default model:

```bash
ollama pull llama3.2
```

### 2. Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Backend health check: `http://localhost:8000/health`

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

- `cv`: PDF file
- `job_description`: job description text

The response is validated against a Pydantic schema before being returned to the frontend.

## Privacy

The default configuration uses a locally running Ollama model. CV content and job descriptions do not need to be sent to a third-party LLM API.

## Roadmap

- [x] MVP architecture
- [x] PDF parsing
- [x] Structured AI analysis
- [x] Responsive analysis dashboard
- [ ] DOCX support
- [ ] Export analysis as PDF
- [ ] Optional cloud LLM providers
- [ ] Job-analysis history

## Author

**Mehrdad Afshari** — AI & Software Developer
