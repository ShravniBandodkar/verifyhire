'use client';
import { useEffect, useState } from 'react';
import { API_BASE, api, getToken } from '@/lib/api';
import { Check, DevKeys, HoldToReveal, Section, Shell, Stat, Status, SwipeCard, useToast } from '@/components/ui';

const TABS: [string, string][] = [['overview', 'Overview'], ['search', 'Talent search'], ['jobs', 'Jobs & matches'], ['team', 'Team'], ['dev', 'Developers']];
const EXAMPLE = 'Find PAN-verified full-stack engineers in Bengaluru with 4–6 years experience, verified B.Tech degree, current CTC under 22 LPA, and at least 2 verified manager references';

export default function EmployerPage() {
  const [tab, setTab] = useState('overview');
  const [co, setCo] = useState<any>(null);
  const [cand, setCand] = useState<string | null>(null);
  const toast = useToast();
  const load = () => api('/employer/company').then(setCo);
  useEffect(() => { load(); const t = setInterval(load, 6000); return () => clearInterval(t); }, []);
  const verified = co?.kyb_status === 'approved';
  return (
    <Shell title={co?.name || 'Employer'} tabs={TABS} tab={tab} setTab={setTab}>
      {co && !verified && (
        <div className="mb-6 rounded-xl border border-saffron bg-saffron-50 p-4 text-sm">
          <b>KYB status: {co.kyb_status}.</b> Candidate search and vault access unlock once the KYB Underwriting agent (or a human governor) approves your company.
          <div className="mt-1 text-ink-700">{co.kyb_report?.narrative}</div>
        </div>
      )}
      {co && tab === 'overview' && <Overview co={co} rerun={async () => { await api('/employer/company/kyb', { method: 'POST' }); load(); toast.show('KYB agent re-ran', 'ok'); }} />}
      {tab === 'search' && <Search open={setCand} disabled={!verified} />}
      {tab === 'jobs' && <Jobs open={setCand} toast={toast.show} disabled={!verified} />}
      {tab === 'team' && co && <Team co={co} toast={toast.show} />}
      {tab === 'dev' && <DevKeys />}
      {cand && <CandidateDrawer id={cand} close={() => setCand(null)} toast={toast.show} />}
      {toast.node}
    </Shell>
  );
}

function Overview({ co, rerun }: any) {
  const [a, setA] = useState<any>(null);
  useEffect(() => { api('/employer/analytics').then(setA).catch(() => {}); }, []);
  return (
    <div className="space-y-6">
      {a && (
        <div className="grid gap-4 md:grid-cols-5">
          <Stat label="Open jobs" value={a.open_jobs} /><Stat label="AI matches" value={a.ai_matches} />
          <Stat label="Shortlisted" value={a.shortlisted} /><Stat label="Interviews" value={a.interviews} />
          <Stat label="Avg trust of matches" value={a.avg_trust_of_matches} hint={a.bgv_turnaround} />
        </div>
      )}
      <Section title="Corporate KYB report" action={<button className="btn-ghost" onClick={rerun}>Re-run KYB agent</button>}>
        <div className="flex flex-wrap items-center gap-3">
          <Status s={co.kyb_status} /><span className="mono">risk {co.risk_score}/100</span>
          <span className="text-sm text-ink-500">PAN {co.pan_masked} · CIN {co.cin || '—'} · GSTIN {co.gstin || '—'} · {co.domain}</span>
        </div>
        <p className="mt-3 text-sm">{co.kyb_report?.narrative}</p>
        <div className="mt-4 grid gap-1.5 md:grid-cols-2">
          {(co.kyb_report?.checks || []).map((c: any) => (
            <div key={c.check} className="flex items-start gap-2 rounded-lg bg-paper-200/50 px-3 py-2 text-sm">
              <span className={c.ok ? 'text-seal' : 'text-alarm'}>{c.ok ? '✓' : '✗'}</span>
              <div className="flex-1"><div>{c.check}</div><div className="mono text-ink-500">{c.detail}</div></div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function ResultCard({ r, open }: any) {
  return (
    <div className="rounded-xl border border-paper-300 bg-white p-4">
      <div className="flex items-start gap-3">
        <div className="flex-1">
          <button className="font-display text-lg hover:underline" onClick={() => open(r.candidate_id)}>{r.name}</button>
          <div className="text-sm text-ink-500">{r.headline} · {r.city} · {r.years_experience} yrs</div>
        </div>
        <div className="text-right"><div className="font-display text-2xl">{Math.round(r.score)}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">match</div></div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">{(r.badges || []).map((b: string) => <span key={b} className="chip bg-seal-50 text-seal">✓ {b}</span>)}<span className="chip bg-paper-200">trust {r.trust_score}</span>{r.exact === false && <span className="chip bg-saffron-50 text-saffron">near match</span>}</div>
      <ul className="mt-2 space-y-0.5 text-xs text-ink-700">{(r.reasons || []).map((x: string) => <li key={x}>• {x}</li>)}</ul>
      {r.components && (
        <div className="mt-3 grid grid-cols-5 gap-1">
          {Object.entries(r.components).map(([k, v]: any) => (
            <div key={k} title={k}><div className="h-1.5 rounded bg-paper-200"><div className="h-1.5 rounded bg-ink-900" style={{ width: `${Math.min(100, v * 100)}%` }} /></div><div className="mt-0.5 truncate text-[9px] uppercase text-ink-500">{k.replace('_', ' ')}</div></div>
          ))}
        </div>
      )}
    </div>
  );
}

function Search({ open, disabled }: any) {
  const [q, setQ] = useState(EXAMPLE); const [res, setRes] = useState<any>(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  async function run() { setBusy(true); setErr(''); try { setRes(await api('/employer/search', { body: { query: q } })); } catch (e: any) { setErr(e.message); } setBusy(false); }
  return (
    <div className="space-y-6">
      <Section title="Ask in plain language">
        <form onSubmit={(e) => { e.preventDefault(); run(); }} className="space-y-3">
          <textarea className="input text-base" rows={3} value={q} onChange={(e) => setQ(e.target.value)} />
          <div className="flex flex-wrap gap-2">
            <button className="btn-primary" disabled={busy || disabled}>{busy ? 'Searching…' : 'Search verified talent'}</button>
            {['React TypeScript engineers in Bengaluru', 'AI engineer with LangChain and RAG, 2+ years', 'DevOps kubernetes terraform Pune under 30 LPA', 'Aadhaar-verified Java backend developers, trust score above 80'].map((s) => (
              <button type="button" key={s} className="chip bg-paper-200 hover:bg-paper-300" onClick={() => setQ(s)}>{s}</button>
            ))}
          </div>
          {err && <p className="text-sm text-alarm">{err}</p>}
        </form>
        {res && (
          <div className="mt-4 rounded-lg bg-paper-200/60 p-3 text-sm">
            <div className="label">Agent-parsed filters</div>
            <div className="flex flex-wrap gap-1">{Object.entries(res.filters).filter(([, v]: any) => v !== null && v !== undefined && !(Array.isArray(v) && !v.length)).map(([k, v]: any) => <span key={k} className="chip bg-white mono">{k}: {Array.isArray(v) ? v.join(', ') : String(v)}</span>)}</div>
            <div className="mono mt-2 text-ink-500">{res.results.length} of {res.total_candidates} profiles · {res.latency_ms.total} ms · {res.vector_backend}{res.llm_parsed ? ' · LLM-assisted parse' : ''}</div>
          </div>
        )}
      </Section>
      {res && <div className="grid gap-3 md:grid-cols-2">{res.results.map((r: any) => <ResultCard key={r.candidate_id} r={r} open={open} />)}</div>}
    </div>
  );
}

function Jobs({ open, toast, disabled }: any) {
  const [jobs, setJobs] = useState<any[]>([]); const [sel, setSel] = useState<string | null>(null);
  const [prompt, setPrompt] = useState('We need a senior React + Node engineer in Bengaluru, 4–8 years, budget up to 35 LPA, PAN verified');
  const [draft, setDraft] = useState<any>(null); const [busy, setBusy] = useState(false);
  const load = () => api<any[]>('/employer/jobs').then((j) => { setJobs(j); if (!sel && j[0]) setSel(j[0].id); });
  useEffect(() => { load(); }, []);
  return (
    <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
      <div className="space-y-4">
        <Section title="Prompt-to-JD">
          <textarea className="input" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <button className="btn-primary mt-2 w-full" disabled={busy || disabled} onClick={async () => { setBusy(true); setDraft(await api('/employer/jobs/draft', { body: { prompt } })); setBusy(false); }}>Structure with AI</button>
          {draft && (
            <div className="mt-3 space-y-2 text-sm">
              <input className="input font-medium" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
              <textarea className="input" rows={3} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
              <div className="flex flex-wrap gap-1">{draft.skills.map((s: string) => <span key={s} className="chip bg-paper-200">{s}</span>)}</div>
              <div className="mono text-ink-500">{draft.location} · {draft.min_exp}-{draft.max_exp} yrs · ₹{draft.ctc_min_lpa ?? '?'}–{draft.ctc_max_lpa ?? '?'}L · trust ≥ {draft.min_trust}{draft.require_pan ? ' · PAN' : ''}</div>
              <button className="btn-seal w-full" disabled={busy} onClick={async () => {
                setBusy(true);
                try { const { _llm, ...body } = draft; const j = await api<any>('/employer/jobs', { body }); toast('Job posted — Matchmaker agent found candidates', 'ok'); setDraft(null); setSel(j.id); load(); } catch (e: any) { toast(e.message, 'error'); }
                setBusy(false);
              }}>Post job & match</button>
            </div>
          )}
        </Section>
        <Section title="Requisitions">
          <div className="space-y-1">
            {jobs.map((j) => (
              <button key={j.id} onClick={() => setSel(j.id)} className={'w-full rounded-lg p-2 text-left text-sm ' + (sel === j.id ? 'bg-ink-900 text-paper-100' : 'hover:bg-paper-200')}>
                <div className="font-medium">{j.title}</div>
                <div className={sel === j.id ? 'text-paper-300 text-xs' : 'text-ink-500 text-xs'}>{j.location} · {j.pipeline.suggested} new · {j.pipeline.shortlisted} shortlisted · {j.pipeline.interview} interviews</div>
              </button>
            ))}
          </div>
        </Section>
      </div>
      {sel && <MatchFeed jobId={sel} open={open} toast={toast} onChange={load} />}
    </div>
  );
}

function MatchFeed({ jobId, open, toast, onChange }: any) {
  const [ms, setMs] = useState<any[]>([]); const [view, setView] = useState<'deck' | 'list'>('deck');
  const load = () => api<any[]>(`/employer/jobs/${jobId}/matches`).then(setMs);
  useEffect(() => { load(); }, [jobId]);
  async function swipe(m: any, action: string) {
    const r = await api<any>(`/employer/matches/${m.match_id}/swipe`, { body: { action } });
    toast(action === 'up' ? `Interview auto-scheduled: ${r.interview_at}` : action === 'right' ? 'Shortlisted' : 'Passed', 'ok');
    load(); onChange();
  }
  const deck = ms.filter((m) => m.status === 'suggested');
  const top = deck[0];
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h2 className="font-display text-xl">AI-matched candidates</h2>
        <div className="ml-auto flex gap-1 rounded-lg bg-paper-200 p-1">
          <button className={view === 'deck' ? 'tab-active' : 'tab'} onClick={() => setView('deck')}>Swipe deck</button>
          <button className={view === 'list' ? 'tab-active' : 'tab'} onClick={() => setView('list')}>Pipeline</button>
        </div>
        <button className="btn-ghost" onClick={async () => { await api(`/employer/jobs/${jobId}/rematch`, { method: 'POST' }); load(); }}>Re-match</button>
      </div>
      {view === 'deck' ? (
        <div className="mx-auto max-w-lg">
          {top ? (
            <>
              <SwipeCard key={top.match_id} onSwipe={(d) => swipe(top, d)}>
                <div className="cursor-grab"><ResultCard r={{ ...top, candidate_id: top.candidate_id }} open={open} /></div>
              </SwipeCard>
              <div className="mt-4 grid grid-cols-3 gap-2">
                <button className="btn-ghost" onClick={() => swipe(top, 'left')}>← Pass</button>
                <button className="btn-primary" onClick={() => swipe(top, 'up')}>↑ Interview</button>
                <button className="btn-seal" onClick={() => swipe(top, 'right')}>Shortlist →</button>
              </div>
              <details className="mt-4 card p-3 text-sm"><summary className="cursor-pointer font-medium">Agent-drafted outreach</summary><p className="mt-2 whitespace-pre-wrap text-ink-700">{top.outreach_draft}</p></details>
              <p className="mt-2 text-center text-xs text-ink-500">{deck.length} in deck · drag the card right / left / up on touch or with a mouse</p>
            </>
          ) : <p className="text-center text-sm text-ink-500">Deck empty — see the Pipeline view.</p>}
        </div>
      ) : (
        <div className="card divide-y divide-paper-300">
          {ms.map((m) => (
            <div key={m.match_id} className="flex flex-wrap items-center gap-3 p-3 text-sm">
              <button className="font-medium hover:underline" onClick={() => open(m.candidate_id)}>{m.name}</button>
              <span className="text-ink-500">{m.headline}</span><span className="mono">{Math.round(m.score)}</span><Status s={m.status} />
              {m.interview_at && <span className="text-xs">📅 {m.interview_at}</span>}
              <div className="ml-auto flex gap-1">
                <button className="btn-ghost" onClick={() => swipe(m, 'right')}>Shortlist</button>
                <button className="btn-ghost" onClick={() => swipe(m, 'up')}>Interview</button>
                <button className="btn-ghost" onClick={() => swipe(m, 'left')}>Archive</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CandidateDrawer({ id, close, toast }: any) {
  const [c, setC] = useState<any>(null); const [err, setErr] = useState(''); const [viewer, setViewer] = useState<string | null>(null);
  const load = () => api(`/employer/candidates/${id}`).then(setC).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [id]);
  const reveal = (field: string) => async () => (await api<any>(`/employer/candidates/${id}/reveal`, { body: { field } })).value;
  async function viewDoc(docId: string) {
    const r = await fetch(`${API_BASE}/api/v1/employer/documents/${docId}/view`, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!r.ok) { toast((await r.json()).detail, 'error'); return; }
    setViewer(URL.createObjectURL(await r.blob()));
  }
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink-950/30" onClick={close}>
      <div className="h-full w-full max-w-2xl overflow-auto bg-paper-100 p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <button className="btn-ghost float-right" onClick={close}>Close</button>
        {err && <p className="text-alarm">{err}</p>}
        {c && (
          <div className="space-y-5">
            <div>
              <h2 className="font-display text-3xl">{c.name}</h2>
              <div className="text-ink-500">{c.headline} · {c.city} · {c.years_experience} yrs · Trust {c.trust_score}/100</div>
              <div className="mt-2 flex flex-wrap gap-1">{Object.entries(c.verification).map(([k, v]: any) => <Check key={k} ok={v} label={k} />)}</div>
              <p className="mt-3 text-sm">{c.summary}</p>
            </div>
            <Section title="Contact & identity (masked)">
              <div className="grid grid-cols-[8rem_1fr] items-center gap-2 text-sm">
                <span className="text-ink-500">Email</span><HoldToReveal masked={c.masked.email} reveal={reveal('email')} disabled={!c.grant} />
                <span className="text-ink-500">Phone</span><HoldToReveal masked={c.masked.phone} reveal={reveal('phone')} disabled={!c.grant} />
                <span className="text-ink-500">PAN</span><HoldToReveal masked={c.masked.pan || '—'} reveal={reveal('pan')} disabled={!c.grant?.reveal_identity_numbers} />
                <span className="text-ink-500">Current CTC</span><HoldToReveal masked={c.masked.current_ctc || '—'} reveal={reveal('current_ctc')} disabled={!c.grant} />
                <span className="text-ink-500">Aadhaar</span><span className="mono">{c.masked.aadhaar || 'not verified'} <span className="text-ink-300">(never revealed)</span></span>
              </div>
              <p className="mt-2 text-xs text-ink-500">Press and hold to unmask for 10 s. Every reveal is written to the candidate’s audit log.</p>
            </Section>
            <Section title="Vault documents" action={c.grant ? <span className="text-xs text-seal">consent active until {new Date(c.grant.expires_at + 'Z').toLocaleString()}</span> : null}>
              {!c.grant && (
                <div className="mb-3 rounded-lg bg-paper-200 p-3 text-sm">
                  {c.pending_request ? 'Access request pending candidate approval.' : (
                    <button className="btn-primary" onClick={async () => { await api(`/employer/candidates/${id}/access-request`, { body: { doc_types: ['resume', 'degree', 'experience_letter', 'payslip', 'pan'], reason: 'Evaluating for an open role', reveal_identity_numbers: true } }); toast('Request sent to candidate', 'ok'); load(); }}>
                      Request document access
                    </button>
                  )}
                </div>
              )}
              <div className="divide-y divide-paper-300">
                {c.documents.map((d: any) => (
                  <div key={d.id} className="flex items-center gap-3 py-2 text-sm">
                    <span className="chip bg-ink-900 text-paper-100">{d.doc_type.replace('_', ' ')}</span><Status s={d.status} />{d.badge && <span className="chip bg-seal-50 text-seal">signed</span>}
                    <button className="btn-ghost ml-auto" disabled={!d.accessible} onClick={() => viewDoc(d.id)}>{d.accessible ? 'View (watermarked)' : 'Locked'}</button>
                  </div>
                ))}
              </div>
            </Section>
            <Section title="Experience & references">
              {c.experience.map((e: any, i: number) => <div key={i} className="flex gap-2 text-sm"><Check ok={e.verified} label="" /> {e.title} · {e.company} <span className="text-ink-500">{e.start} – {e.end}</span></div>)}
              <div className="mt-3 space-y-1">{c.references.map((r: any, i: number) => <div key={i} className="flex gap-2 text-sm"><Status s={r.status} /> {r.name} · {r.relationship} at {r.company}{r.rating ? ` · ${r.rating}/5` : ''}</div>)}</div>
            </Section>
          </div>
        )}
        {viewer && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-ink-950/80 p-6" onClick={() => setViewer(null)} onContextMenu={(e) => e.preventDefault()}>
            <iframe src={viewer} className="h-full w-full max-w-4xl rounded-lg bg-white" title="Watermarked document" />
          </div>
        )}
      </div>
    </div>
  );
}

function Team({ co, toast }: any) {
  const [list, setList] = useState<any[]>([]); const [f, setF] = useState<any>({});
  const load = () => api<any[]>('/employer/recruiters').then(setList);
  useEffect(() => { load(); }, []);
  return (
    <Section title="Recruiter sub-accounts (RBAC)">
      <form className="grid gap-2 md:grid-cols-4" onSubmit={async (e) => { e.preventDefault(); try { await api('/employer/recruiters', { body: f }); toast('Recruiter added', 'ok'); load(); } catch (e: any) { toast(e.message, 'error'); } }}>
        <input className="input" placeholder="Full name" onChange={(e) => setF({ ...f, full_name: e.target.value })} />
        <input className="input" placeholder={`name@${co.domain}`} onChange={(e) => setF({ ...f, email: e.target.value })} />
        <input className="input" type="password" placeholder="Temp password" onChange={(e) => setF({ ...f, password: e.target.value })} />
        <button className="btn-primary">Add recruiter</button>
      </form>
      <div className="mt-4 divide-y divide-paper-300">{list.map((u) => <div key={u.id} className="flex gap-3 py-2 text-sm"><span className="font-medium">{u.full_name}</span><span className="mono">{u.email}</span><span className="chip bg-paper-200">{u.role.replace('_', ' ')}</span></div>)}</div>
      <p className="mt-3 text-xs text-ink-500">Recruiters must use the verified corporate domain @{co.domain}; they inherit the company’s KYB status.</p>
    </Section>
  );
}
