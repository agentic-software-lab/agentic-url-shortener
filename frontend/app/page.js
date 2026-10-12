'use client';

import { useState } from 'react';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
const ORCHESTRATOR = process.env.NEXT_PUBLIC_ORCHESTRATOR_URL || 'http://127.0.0.1:8001';

export default function Home() {
  const [url, setUrl] = useState('https://example.com');
  const [record, setRecord] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function shorten(e) {
    e.preventDefault();
    setLoading(true); setError(''); setAnalytics(null);
    try {
      const res = await fetch(`${API}/urls`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      setRecord(await res.json());
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }

  async function loadAnalytics() {
    if (!record) return;
    setError('');
    try {
      const res = await fetch(`${API}/urls/${record.short_code}/analytics`);
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      setAnalytics(await res.json());
    } catch (err) { setError(err.message); }
  }

  return (
    <main>
      <section className="hero">
        <p className="eyebrow">CONTROLLED AUTONOMY • AGENTIC SDLC</p>
        <h1>Agentic Software Engineering System</h1>
        <p>Explore a controlled-autonomy SDLC workflow for requirement analysis, planning, implementation, validation, and release readiness, using a URL shortener as the reference application.</p>
      </section>

      <section className="card">
        <h2>1. Reference Application — URL Shortener</h2>
        <form onSubmit={shorten}>
          <label>Long URL</label>
          <div className="row">
            <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/long/path" required />
            <button disabled={loading}>{loading ? 'Creating…' : 'Shorten URL'}</button>
          </div>
        </form>
        {error && <p className="error">{error}</p>}
        {record && (
          <div className="result">
            <span className="status">ACTIVE</span>
            <p><b>Short code:</b> {record.short_code}</p>
            <p><b>Original:</b> {record.original_url}</p>
            <a href={`${API}/r/${record.short_code}`} target="_blank" rel="noreferrer">Open short URL ↗</a>
            <button className="secondary" onClick={loadAnalytics}>Refresh analytics</button>
            {analytics && <p><b>Clicks:</b> {analytics.clicks}</p>}
          </div>
        )}
      </section>

      <section className="card">
        <h2>2. Agentic SDLC Workflow</h2>
        <p className="note">Workflow overview for greenfield and clarified requirements. Run a workflow in the orchestrator to inspect its actual task graph and status.</p>
        <ol className="workflow-stages">
          <li><strong>Interpret requirements</strong><p>Normalize scope and acceptance criteria. Ambiguous requests pause for clarification choices and human clarification approval.</p></li>
          <li><strong>Plan tasks and dependencies</strong><p>The deterministic planner selects tasks from confirmed scope; analytics is included only when requested.</p></li>
          <li><strong>Review in parallel</strong>
            <div className="workflow-branches" aria-label="Parallel design reviews">
              <div><b>Architecture</b><p>Record design decisions.</p></div>
              <div><b>Security</b><p>Review constraints and request downstream guard work when needed.</p></div>
            </div>
            <p>Both reviews must succeed before implementation becomes eligible.</p>
          </li>
          <li className="workflow-approval"><strong>Human implementation approval</strong><p>Approve planned work before generating the candidate.</p></li>
          <li><strong>Generate the candidate</strong><p>Produce source, tests, a reviewable diff, and an integrity manifest.</p></li>
          <li><strong>Validate and document in parallel branches</strong>
            <div className="workflow-branches" aria-label="Parallel validation and documentation branches">
              <div><b>Testing / Validation</b><p>Wait for optional analytics and redirect-guard tasks, then check integrity, policy, and candidate tests.</p></div>
              <div><b>Documentation</b><p>Write setup instructions and scope alongside the validation branch.</p></div>
            </div>
            <p>Release waits for successful testing and documentation.</p>
          </li>
          <li className="workflow-approval"><strong>Human release approval</strong><p>Review evidence. Release rechecks candidate integrity before marking review readiness.</p></li>
          <li><strong>Reviewable engineering outcome</strong><p>Inspect artifacts, validation, decisions, audit records, and limitations in the summary.</p></li>
        </ol>
        <div className="workflow-detail">
          <h3>Incremental replanning</h3>
          <p>Agent findings can request new or revised downstream tasks. After wave synchronization, the engine validates the revised graph, preserves completed work, and records the reason and changes. Invalid plans safe-stop execution.</p>
          <h3>Brownfield path</h3>
          <p>Impact analysis, human implementation approval, a bounded expiration change, regression validation, human release approval, and final integrity verification.</p>
          <p className="note">Replacing a requirement starts a new candidate with fresh approvals. Retries are bounded; registered fallback and rollback callbacks support recovery, and failed dependencies block downstream work.</p>
        </div>
        <a className="workflow-link" href={`${ORCHESTRATOR}/docs`} target="_blank" rel="noreferrer">Open orchestrator: create, clarify, approve, and review workflows ↗</a>

      </section>
    </main>
  );
}
