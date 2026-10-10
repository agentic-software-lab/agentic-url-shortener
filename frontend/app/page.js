'use client';

import { useState } from 'react';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

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
        <div className="flow">
          <span>Requirement</span><b>→</b><span>Requirements Agent</span><b>→</b><span>Planner</span><b>→</b><span>Architecture + Security</span><b>→</b><span className="approval">Human Approval</span><b>→</b><span>Implementation</span><b>→</b><span>Test + Docs</span><b>→</b><span>Validation</span><b>→</b><span>Release</span>
        </div>
        <p className="note">Run the greenfield, brownfield, and ambiguous scenarios from the terminal to exercise dependency gates, approvals, retries and safe-stop behavior.</p>
      </section>
    </main>
  );
}
