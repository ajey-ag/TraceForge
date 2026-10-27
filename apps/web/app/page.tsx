"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type Investigation = {
  id: string; fixture_id: string; source: string; repository: string; commit_sha: string;
  status: string; stage: string; outcome: string | null; explanation: string | null;
  created_at: string; policy: { provider?: string; execution_policy?: string };
  timeline?: { to_status: string; stage: string; reason: string; at: string }[];
  attempts?: { number: number; status: string; error: string | null }[];
};
type Report = {
  outcome: string; summary: string; provider: string | null;
  reproduction_status: string; patch_status: string; verification_status: string;
  model_calls: number; observed_model_cost_usd: number | null; estimated_model_cost_usd: number;
  parsed: { failure_category: string; failed_test_identifiers: string[]; failures: unknown[]; limitations: string[] };
  evidence: { id: string; type: string; sha256: string }[];
  diagnosis: unknown; reproduction: unknown; verification: unknown[]; routing: unknown[];
  patches: { id?: string; attempt: number; status: string; explanation?: string; reason?: string }[];
  limitations: string[];
};

async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? "GET" : "POST", cache: "no-store",
    headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail));
  return data;
}

function Json({ value }: { value: unknown }) {
  return <pre>{JSON.stringify(value, null, 2)}</pre>;
}

export default function Dashboard() {
  const [items, setItems] = useState<Investigation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<Investigation | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [artifact, setArtifact] = useState("");
  const [experiments, setExperiments] = useState<unknown[]>([]);
  const [policy, setPolicy] = useState("repair");
  const [provider, setProvider] = useState("fake");

  const refresh = useCallback(async () => {
    try {
      await api("/ready"); setReady(true);
      const history = await api<{ items: Investigation[] }>(`/investigations?limit=20&offset=${offset}${status ? `&status=${status}` : ""}`);
      setItems(history.items);
      if (selected) {
        const current = await api<Investigation>(`/investigations/${selected}`);
        setDetail(current);
        if (current.status === "COMPLETED") setReport(await api<Report>(`/investigations/${selected}/report`));
        else setReport(null);
      }
      setError("");
    } catch (e) { setReady(false); setError((e as Error).message); }
  }, [selected, status, offset]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), 2500);
    return () => clearInterval(timer);
  }, [refresh]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError("");
    const data = new FormData(event.currentTarget);
    try {
      const result = await api<Investigation>("/investigations", {
        fixture_id: "calculator-add", execution_policy: policy,
        provider: policy === "saved_evidence_only" ? "fake" : provider,
        strategy: data.get("strategy"),
        max_model_calls: policy === "saved_evidence_only" ? 0 : Number(data.get("calls")),
        max_spend_usd: policy === "saved_evidence_only" || provider === "fake" ? 0 : Number(data.get("spend")),
      });
      setSelected(result.id); setReport(null); setDetail(result); setArtifact("");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function github(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      const result = await api<{ id: string }>("/integrations/github/runs", {
        repository: data.get("repository"), run_id: Number(data.get("run")), attempt: Number(data.get("attempt")),
      });
      setSelected(result.id); setReport(null); setArtifact("");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function readArtifact(path: string) {
    try {
      const response = await fetch(`/api${path}`);
      const text = await response.text();
      if (!response.ok) throw new Error(text);
      setArtifact(text);
    } catch (e) { setError((e as Error).message); }
  }

  return <main>
    <header><div><p className="eyebrow">CI FAILURE INVESTIGATION</p><h1>TraceForge</h1>
      <p>Evidence → diagnosis → controlled reproduction → verified repair</p></div>
      <span className={`badge ${ready ? "good" : "warn"}`}>{ready ? "Backend ready" : "Backend unavailable"}</span>
    </header>
    <aside className="notice">Controlled demo: calculator fixture. Fake-provider results are explicitly labeled.
      GitHub imports are saved-log investigations; arbitrary repository execution is unavailable.</aside>
    {error && <div className="error" role="alert">{error}</div>}
    <section className="grid">
      <article><h2>New investigation</h2><form onSubmit={submit}>
        <label>Fixture<input value="calculator-add" readOnly /></label>
        <label>Execution policy<select value={policy} onChange={e => setPolicy(e.target.value)}>
          <option value="saved_evidence_only">Parse saved evidence only</option>
          <option value="diagnose">Evidence-backed diagnosis</option><option value="repair">Controlled repair + verification</option>
        </select></label>
        <label>Provider<select value={provider} onChange={e => setProvider(e.target.value)} disabled={policy === "saved_evidence_only"}>
          <option value="fake">Fake — deterministic demo, no paid calls</option><option value="openai">OpenAI — requires server credentials</option>
        </select></label>
        <label>Routing strategy<select name="strategy"><option value="rule_based">Rule-based escalation</option><option value="cheap">Cheaper model throughout</option><option value="strong">Stronger model throughout</option></select></label>
        <div className="grid"><label>Maximum model calls<input name="calls" type="number" min="1" max="10" defaultValue="3" /></label>
          <label>Maximum spend (USD)<input name="spend" type="number" min="0" max="10" step="0.01" defaultValue="0.10" disabled={provider === "fake"} /></label></div>
        <button disabled={busy}>Start investigation</button>
      </form></article>
      <article><h2>Import GitHub Actions failure</h2><p>Configure the repository allowlist and token on the backend first.</p>
        <form onSubmit={github}><label>Repository<input name="repository" placeholder="owner/repository" required pattern="[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+" /></label>
          <div className="grid"><label>Run ID<input name="run" type="number" min="1" required /></label>
            <label>Attempt<input name="attempt" type="number" min="1" max="100" defaultValue="1" /></label></div>
          <button disabled={busy}>Import failed run</button>
        </form><p>No external writes or pull requests are performed.</p>
      </article>
    </section>
    <section className="workspace">
      <article><h2>History</h2><label>Status filter<select value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}>
        <option value="">All statuses</option>{["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"].map(s => <option key={s}>{s}</option>)}
      </select></label>
        {!items.length && <p>No investigations on this page.</p>}
        <ul className="history">{items.map(item => <li key={item.id}><button className={selected === item.id ? "selected" : "secondary"} onClick={() => {
          setSelected(item.id); setDetail(item); setReport(null); setArtifact("");
        }}><strong>{item.fixture_id}</strong><span>{item.status} · {item.stage}</span>
          <small>{item.source} · {item.policy.provider || "no model"} · {new Date(item.created_at).toLocaleString()}</small></button></li>)}</ul>
        <div className="actions"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous</button>
          <button disabled={items.length < 20} onClick={() => setOffset(offset + 20)}>Next</button></div>
      </article>
      <article>{!detail ? <><h2>Investigation workspace</h2><p>Select a persisted investigation or start a new one.</p></> : <>
        <div className="actions"><h2>{detail.outcome || detail.status}</h2>
          {["QUEUED", "RUNNING"].includes(detail.status) && <button className="danger" onClick={async () => {
            try { await api(`/investigations/${detail.id}/cancel`, {}); await refresh(); } catch (e) { setError((e as Error).message); }
          }}>Cancel</button>}</div>
        <p className="mono">{detail.id}</p><p>{detail.repository}<br /><code>{detail.commit_sha}</code></p>
        <p>{detail.explanation}</p>
        <h3>Execution timeline</h3><ol>{detail.timeline?.map((event, index) => <li key={index}>
          <strong>{event.stage} · {event.to_status}</strong><p>{event.reason}</p>
        </li>)}</ol>
        {!!detail.attempts?.length && <details><summary>Worker attempts</summary><Json value={detail.attempts} /></details>}
        {!report && <p>Report unavailable while queued/running, or after cancellation/infrastructure failure. See timeline and attempts.</p>}
        {report && <>
          <div className="badges"><span className="badge">{detail.source}</span><span className={`badge ${report.provider === "fake" ? "warn" : ""}`}>{report.provider || "Deterministic parser"}</span>
            <span className={`badge ${report.outcome === "VERIFIED_REPAIR" ? "good" : ""}`}>{report.verification_status}</span></div>
          <p>{report.summary}</p><h3>Failure evidence</h3><p>{report.parsed.failure_category}</p>
          <Json value={report.parsed.failures} />
          <div className="actions">{report.evidence.map(e => <button className="secondary" key={e.id} title={e.sha256} onClick={() => readArtifact(`/investigations/${detail.id}/evidence/${e.id}`)}>{e.type}</button>)}</div>
          <h3>Diagnosis</h3>{report.diagnosis ? <Json value={report.diagnosis} /> : <p>No model diagnosis requested.</p>}
          <details><summary>Reproduction: {report.reproduction_status}</summary><Json value={report.reproduction} /></details>
          <h3>Patch review</h3>{!report.patches.length && <p>No patch proposed.</p>}
          {report.patches.map(p => <div className="patch" key={p.attempt}><strong>Attempt {p.attempt}: {p.status}</strong><p>{p.explanation || p.reason}</p>
            {p.id && <div className="actions"><button onClick={() => readArtifact(`/investigations/${detail.id}/patches/${p.id}`)}>Inspect diff</button>
              <a href={`/api/investigations/${detail.id}/patches/${p.id}`}>Download diff</a></div>}</div>)}
          <details><summary>Verification runs</summary><Json value={report.verification} /></details>
          <h3>Usage</h3><p>{report.model_calls} model calls · Estimated ${report.estimated_model_cost_usd.toFixed(6)} · Observed billing: {report.observed_model_cost_usd === null ? "unavailable" : `$${report.observed_model_cost_usd}`}</p>
          <details><summary>Routing decisions and budgets</summary><Json value={report.routing} /></details>
          <h3>Limitations</h3><ul>{[...report.parsed.limitations, ...report.limitations].map((note, i) => <li key={i}>{note}</li>)}</ul>
          <a href={`/api/investigations/${detail.id}/report`} target="_blank" rel="noreferrer">Open full JSON report</a>
        </>}
        {artifact && <section><h3>Artifact inspection</h3><pre>{artifact}</pre></section>}
      </>}</article>
    </section>
    <article><div className="actions"><h2>Experiments</h2><button onClick={async () => {
      try { setExperiments(await api<unknown[]>("/experiments")); } catch (e) { setError((e as Error).message); }
    }}>Load persisted experiments</button></div>
      {!experiments.length ? <p>No results loaded. Experiments are manually initiated; no research claims are inferred from the demo.</p> : <Json value={experiments} />}
    </article>
    <footer>TraceForge · local controlled demonstration · evidence and verification are separate outcomes</footer>
  </main>;
}
