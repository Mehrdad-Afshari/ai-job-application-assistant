'use client';

import { FormEvent, useState } from 'react';

type Requirement = { requirement: string; priority: 'required'|'preferred'; status: 'matched'|'partial'|'missing'; evidence: string };
type Result = { match_score:number; score_breakdown:{technical_skills:number;experience_projects:number;education_domain:number;other_requirements:number}; detected_language:string; summary:string; requirements:Requirement[]; matched_skills:string[]; missing_skills:string[]; keywords:string[]; analysis_seconds:number };
type Writing = { cv_suggestions:string[]; cover_letter:string; interview_questions:string[] };

function Chips({items,tone='good'}:{items:string[];tone?:'good'|'warn'|'neutral'}){return <div className="chips">{items.map((x,i)=><span className={`chip ${tone}`} key={`${tone}-${i}-${x}`}>{x}</span>)}</div>}

export default function Home(){
 const [cv,setCv]=useState<File|null>(null),[job,setJob]=useState(''),[result,setResult]=useState<Result|null>(null),[writing,setWriting]=useState<Writing|null>(null);
 const [loading,setLoading]=useState(false),[generating,setGenerating]=useState(false),[error,setError]=useState('');
 const api=process.env.NEXT_PUBLIC_API_URL||'http://localhost:8000';
 async function submit(e:FormEvent){e.preventDefault();if(!cv)return setError('Please select your CV as a PDF.');setLoading(true);setError('');setResult(null);setWriting(null);const d=new FormData();d.append('cv',cv);d.append('job_description',job);try{const r=await fetch(`${api}/analyze`,{method:'POST',body:d});const b=await r.json();if(!r.ok)throw new Error(b.detail||'Analysis failed.');setResult(b)}catch(e){setError(e instanceof Error?e.message:'Analysis failed.')}finally{setLoading(false)}}
 async function generate(){if(!cv||!result)return;setGenerating(true);setError('');const d=new FormData();d.append('cv',cv);d.append('job_description',job);d.append('analysis_json',JSON.stringify(result));try{const r=await fetch(`${api}/generate`,{method:'POST',body:d});const b=await r.json();if(!r.ok)throw new Error(b.detail||'Generation failed.');setWriting(b)}catch(e){setError(e instanceof Error?e.message:'Generation failed.')}finally{setGenerating(false)}}
 return <main>
  <section className="hero"><div className="badge">LOCAL-FIRST AI • PRIVACY FRIENDLY</div><h1>AI Job Application <span>Assistant</span></h1><p>Fast evidence-based CV matching first. Generate application materials only when you need them.</p></section>
  <form className="inputGrid" onSubmit={submit}><label className="card upload"><strong>1. Upload your CV</strong><span>PDF • max 5 MB</span><input type="file" accept="application/pdf,.pdf" onChange={e=>setCv(e.target.files?.[0]||null)}/><div className="fileBox">{cv?`✓ ${cv.name}`:'Choose PDF CV'}</div></label><label className="card"><strong>2. Paste the job description</strong><textarea required minLength={80} value={job} onChange={e=>setJob(e.target.value)} placeholder="Paste the complete job posting here…"/></label><button disabled={loading}>{loading?'Running fast evidence analysis…':'Analyze Match →'}</button></form>
  {error&&<div className="error">{error}</div>}
  {result&&<section className="results">
   <div className="scoreCard"><div className="score">{result.match_score}<small>/100</small></div><div><h2>Evidence-based Match</h2><p>{result.summary}</p><span className="language">{result.detected_language} • {result.analysis_seconds}s</span></div></div>
   <article className="card"><h3>Why this score?</h3><div className="breakdown"><div><b>{result.score_breakdown.technical_skills}/45</b><span>Technical skills</span></div><div><b>{result.score_breakdown.experience_projects}/25</b><span>Experience & projects</span></div><div><b>{result.score_breakdown.education_domain}/15</b><span>Education & domain</span></div><div><b>{result.score_breakdown.other_requirements}/15</b><span>Other requirements</span></div></div></article>
   <article className="card"><h3>Requirement Evidence</h3><div className="requirements">{result.requirements.map((r,i)=><div className={`requirement ${r.status}`} key={`r-${i}`}><div><b>{r.requirement}</b><span className="priority">{r.priority}</span></div><small>{r.status.toUpperCase()} • {r.evidence}</small></div>)}</div></article>
   <div className="twoCol"><article className="card"><h3>✓ Verified Matches</h3><Chips items={result.matched_skills}/></article><article className="card"><h3>△ Missing / Unverified</h3><Chips items={result.missing_skills} tone="warn"/></article></div>
   <article className="card"><h3>ATS Keywords</h3><Chips items={result.keywords} tone="neutral"/></article>
   <button onClick={generate} disabled={generating} type="button">{generating?'Generating application materials…':'Generate CV Suggestions, Cover Letter & Interview Questions →'}</button>
   {writing&&<><article className="card"><h3>CV Improvement Suggestions</h3><ol>{writing.cv_suggestions.map((x,i)=><li key={`s-${i}`}>{x}</li>)}</ol></article><article className="card"><h3>Tailored Cover Letter</h3><pre>{writing.cover_letter}</pre></article><article className="card"><h3>Likely Interview Questions</h3><ol>{writing.interview_questions.map((x,i)=><li key={`q-${i}`}>{x}</li>)}</ol></article></>}
  </section>}
  <footer>Built by Mehrdad Afshari • Next.js + FastAPI + Ollama</footer>
 </main>
}
