'use client';

import { FormEvent, useState } from 'react';

type Result = {
  match_score: number;
  summary: string;
  matched_skills: string[];
  missing_skills: string[];
  keywords: string[];
  cv_suggestions: string[];
  cover_letter: string;
  interview_questions: string[];
};

function Chips({ items, tone = 'good' }: { items: string[]; tone?: 'good' | 'warn' | 'neutral' }) {
  return <div className="chips">{items.map((item) => <span className={`chip ${tone}`} key={item}>{item}</span>)}</div>;
}

export default function Home() {
  const [cv, setCv] = useState<File | null>(null);
  const [job, setJob] = useState('');
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!cv) return setError('Please select your CV as a PDF.');
    setLoading(true); setError(''); setResult(null);
    const data = new FormData();
    data.append('cv', cv);
    data.append('job_description', job);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/analyze`, { method: 'POST', body: data });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || 'Analysis failed.');
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed.');
    } finally { setLoading(false); }
  }

  return (
    <main>
      <section className="hero">
        <div className="badge">LOCAL-FIRST AI • PRIVACY FRIENDLY</div>
        <h1>AI Job Application <span>Assistant</span></h1>
        <p>Compare your CV with a job description and get an evidence-based match score, skill gaps and tailored application guidance.</p>
      </section>

      <form className="inputGrid" onSubmit={submit}>
        <label className="card upload">
          <strong>1. Upload your CV</strong>
          <span>PDF • max 5 MB</span>
          <input type="file" accept="application/pdf,.pdf" onChange={(e) => setCv(e.target.files?.[0] || null)} />
          <div className="fileBox">{cv ? `✓ ${cv.name}` : 'Choose PDF CV'}</div>
        </label>
        <label className="card">
          <strong>2. Paste the job description</strong>
          <textarea required minLength={80} value={job} onChange={(e) => setJob(e.target.value)} placeholder="Paste the complete job posting here…" />
        </label>
        <button disabled={loading} type="submit">{loading ? 'Analyzing with AI…' : 'Analyze Application →'}</button>
      </form>

      {error && <div className="error">{error}</div>}

      {result && <section className="results">
        <div className="scoreCard">
          <div className="score">{result.match_score}<small>/100</small></div>
          <div><h2>Application Match</h2><p>{result.summary}</p></div>
        </div>
        <div className="twoCol">
          <article className="card"><h3>✓ Matched Skills</h3><Chips items={result.matched_skills} /></article>
          <article className="card"><h3>△ Missing / Weak Skills</h3><Chips items={result.missing_skills} tone="warn" /></article>
        </div>
        <article className="card"><h3>ATS Keywords</h3><Chips items={result.keywords} tone="neutral" /></article>
        <article className="card"><h3>CV Improvement Suggestions</h3><ol>{result.cv_suggestions.map((x) => <li key={x}>{x}</li>)}</ol></article>
        <article className="card"><h3>Tailored Cover Letter</h3><pre>{result.cover_letter}</pre></article>
        <article className="card"><h3>Likely Interview Questions</h3><ol>{result.interview_questions.map((x) => <li key={x}>{x}</li>)}</ol></article>
      </section>}

      <footer>Built by Mehrdad Afshari • Next.js + FastAPI + Ollama</footer>
    </main>
  );
}
