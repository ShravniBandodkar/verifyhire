'use client';
import { useEffect, useState } from 'react';
import { api, fmtDate } from '@/lib/api';
import { Section, Shell, Stat, Status, useToast } from '@/components/ui';

const TABS: [string, string][] = [['agents', 'Agent workforce'], ['queue', 'Escalations'], ['log', 'Decision log'], ['kyb', 'Companies'], ['ledger', 'Ledger'], ['ops', 'DevSecOps']];

export default function AdminPage() {
  const [tab, setTab] = useState('agents');
  const toast = useToast();
  return (
    <Shell title="Governor console" tabs={TABS} tab={tab} setTab={setTab}>
      {tab === 'agents' && <Agents />}
      {tab === 'queue' && <Runs needsHuman toast={toast.show} />}
      {tab === 'log' && <Runs toast={toast.show} />}
      {tab === 'kyb' && <Companies toast={toast.show} />}
      {tab === 'ledger' && <Ledger />}
      {tab === 'ops' && <Ops toast={toast.show} />}
      {toast.node}
    </Shell>
  );
}

function Agents() {
  const [a, setA] = useState<any[]>([]); const [s, setS] = useState<any>(null);
  useEffect(() => { api<any[]>('/admin/agents').then(setA); api('/public/stats').then(setS); }, []);
  return (
    <div className="space-y-6">
      {s && <div className="grid gap-4 md:grid-cols-4">
        <Stat label="Agent decisions" value={s.agent_decisions} /><Stat label="Autonomy rate" value={`${s.autonomy_rate}%`} hint="decisions not needing a human" />
        <Stat label="LLM provider" value={s.llm_provider} hint="rule engines run when none" /><Stat label="Vector index" value={s.vector_backend} />
      </div>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {a.map((x, i) => (
          <div key={x.key} className="card p-5">
            <div className="mono text-ink-300">AGENT {String(i + 1).padStart(2, '0')}</div>
            <div className="mt-1 font-display text-lg">{x.name}</div>
            <div className="text-xs text-ink-500">Replaces: {x.replaces}</div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center">
              <div><div className="font-display text-2xl">{x.runs}</div><div className="text-[10px] uppercase text-ink-500">runs</div></div>
              <div><div className="font-display text-2xl">{x.avg_ms}</div><div className="text-[10px] uppercase text-ink-500">avg ms</div></div>
              <div><div className={'font-display text-2xl ' + (x.escalations ? 'text-saffron' : '')}>{x.escalations}</div><div className="text-[10px] uppercase text-ink-500">escalated</div></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Runs({ needsHuman, toast }: any) {
  const [runs, setRuns] = useState<any[]>([]); const [open, setOpen] = useState<string | null>(null); const [agent, setAgent] = useState('');
  const load = () => api<any[]>(`/admin/runs?limit=200${needsHuman ? '&needs_human=true' : ''}${agent ? `&agent=${agent}` : ''}`).then(setRuns);
  useEffect(() => { load(); }, [agent, needsHuman]);
  async function override(r: any, status: string) {
    const [kind, id] = r.subject.split(':');
    await api(`/admin/${kind === 'company' ? 'companies' : 'documents'}/${id}/override`, { body: { status, note: 'governor review' } });
    toast(`Override → ${status}`, 'ok'); load();
  }
  return (
    <Section title={needsHuman ? 'Human governor queue' : 'Every agent decision'} action={!needsHuman && (
      <select className="input w-auto" value={agent} onChange={(e) => setAgent(e.target.value)}>
        <option value="">All agents</option>{['kyc_forensics', 'kyb_underwriting', 'reference_tenure', 'talent_matchmaker', 'resume_architect', 'support_dispute', 'devsecops_finops'].map((a) => <option key={a}>{a}</option>)}
      </select>)}>
      {runs.length === 0 && <p className="text-sm text-ink-500">{needsHuman ? 'Nothing needs a human right now — the agents handled everything.' : 'No runs.'}</p>}
      <div className="divide-y divide-paper-300">
        {runs.map((r) => (
          <div key={r.id} className="py-2.5 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="chip bg-ink-900 text-paper-100">{r.agent}</span><Status s={r.decision} />
              {r.llm_used && <span className="chip bg-paper-200">LLM</span>}
              <span className="mono text-ink-500">{r.subject}</span><span className="mono text-ink-300">{r.duration_ms} ms</span>
              <span className="ml-auto text-xs text-ink-500">{fmtDate(r.ts)}</span>
            </div>
            <div className="mt-1 text-ink-700">{r.summary}</div>
            <div className="mt-1 flex gap-2">
              <button className="text-xs underline" onClick={() => setOpen(open === r.id ? null : r.id)}>{open === r.id ? 'hide trace' : 'trace'}</button>
              {needsHuman && (r.subject.startsWith('company:') || r.subject.startsWith('document:')) && (
                <>
                  <button className="btn-seal py-1" onClick={() => override(r, r.subject.startsWith('company') ? 'approved' : 'verified')}>Approve</button>
                  <button className="btn-danger py-1" onClick={() => override(r, 'rejected')}>Reject</button>
                </>
              )}
              {needsHuman && <button className="btn-ghost py-1" onClick={async () => { await api(`/admin/runs/${r.id}/resolve`, { method: 'POST' }); load(); }}>Acknowledge</button>}
            </div>
            {open === r.id && <pre className="mono mt-2 overflow-auto rounded-lg bg-ink-950 p-3 text-paper-200">{JSON.stringify(r.steps, null, 2)}</pre>}
          </div>
        ))}
      </div>
    </Section>
  );
}

function Companies({ toast }: any) {
  const [cs, setCs] = useState<any[]>([]);
  const load = () => api<any[]>('/admin/companies').then(setCs);
  useEffect(() => { load(); }, []);
  return (
    <div className="space-y-4">
      {cs.map((c) => (
        <Section key={c.id} title={c.name} action={<div className="flex items-center gap-2"><Status s={c.kyb_status} /><span className="mono">risk {c.risk_score}</span></div>}>
          <p className="text-sm">{c.narrative}</p>
          <div className="mt-3 flex flex-wrap gap-1">{c.checks.filter((x: any) => !x.ok).map((x: any) => <span key={x.check} className="chip bg-alarm-50 text-alarm">✗ {x.check}</span>)}</div>
          <div className="mt-3 flex gap-2">
            <button className="btn-seal" onClick={async () => { await api(`/admin/companies/${c.id}/override`, { body: { status: 'approved' } }); toast('Approved', 'ok'); load(); }}>Approve</button>
            <button className="btn-danger" onClick={async () => { await api(`/admin/companies/${c.id}/override`, { body: { status: 'rejected' } }); toast('Rejected', 'ok'); load(); }}>Reject</button>
          </div>
        </Section>
      ))}
    </div>
  );
}

function Ledger() {
  const [ev, setEv] = useState<any[]>([]); const [v, setV] = useState<any>(null);
  useEffect(() => { api<any[]>('/admin/ledger?limit=200').then(setEv); }, []);
  return (
    <Section title="Immutable audit ledger" action={<button className="btn-primary" onClick={async () => setV(await api('/admin/ledger/verify'))}>Verify hash chain</button>}>
      {v && <div className={'mb-3 rounded-lg p-3 text-sm ' + (v.valid ? 'bg-seal-50 text-seal' : 'bg-alarm-50 text-alarm')}>{v.valid ? `Chain intact — ${v.checked} events verified. Head ${v.head.slice(0, 20)}…` : `Chain BROKEN at #${v.broken_at_seq}`}</div>}
      <div className="max-h-[40rem] overflow-auto">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-paper-100 text-xs uppercase text-ink-500"><tr><th className="py-2">#</th><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Hash ← prev</th></tr></thead>
          <tbody className="divide-y divide-paper-300">
            {ev.map((e) => (
              <tr key={e.seq}><td className="mono py-1.5">{e.seq}</td><td className="text-xs">{fmtDate(e.ts)}</td>
                <td className="mono">{e.actor_type === 'agent' ? e.actor : e.actor.slice(0, 8)}</td><td>{e.action}</td><td className="mono text-ink-500">{e.target}</td>
                <td className="mono text-ink-500">{e.hash.slice(0, 10)} ← {e.prev_hash.slice(0, 10)}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}

function Ops({ toast }: any) {
  const [p, setP] = useState<any>(null); const [blocks, setBlocks] = useState<any[]>([]);
  const run = async () => { setP(await api('/admin/devsecops/patrol', { method: 'POST' })); setBlocks(await api('/admin/security/blocks')); };
  useEffect(() => { run(); }, []);
  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <button className="btn-primary" onClick={run}>Run patrol now</button>
        <button className="btn-ghost" onClick={async () => { const r = await api<any>('/admin/devsecops/rotate-keys', { method: 'POST' }); toast(`Master key rotated to ${r.active_kek} · ${r.rewrapped} data keys re-wrapped`, 'ok'); run(); }}>Rotate vault master key</button>
      </div>
      {p && (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            <Stat label="p50 latency" value={`${p.telemetry.p50_ms} ms`} /><Stat label="p95 latency" value={`${p.telemetry.p95_ms} ms`} />
            <Stat label="Requests (5 min)" value={p.telemetry.requests_5m} hint={`error rate ${(p.telemetry.error_rate * 100).toFixed(2)}%`} />
            <Stat label="Scaling decision" value={p.scaling.replace('_', ' ')} />
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Section title="Health & self-healing">
              <div className="space-y-1 text-sm">
                <div>Vector index: <span className="mono">{p.vector_index.backend}</span> · {p.vector_index.size}/{p.vector_index.profiles} profiles indexed</div>
                <div>Audit chain: {p.ledger.valid ? <span className="text-seal">intact ({p.ledger.checked} events)</span> : <span className="text-alarm">broken</span>}</div>
                <div>Vault KEK versions: <span className="mono">{p.kek_versions.join(', ')}</span></div>
                <div>FinOps: {p.finops.infra} · LLM {p.finops.llm_provider} · est. ${p.finops.est_monthly_usd.toFixed(0)}/mo</div>
                <div className="pt-2 font-medium">Actions taken</div>
                {p.actions.length ? p.actions.map((a: string) => <div key={a}>• {a}</div>) : <div className="text-ink-500">No action needed.</div>}
              </div>
            </Section>
            <Section title="Slowest routes (5 min)">
              {p.telemetry.slow_routes.map((r: any) => <div key={r.route} className="flex justify-between text-sm"><span className="mono">{r.route}</span><span>{r.avg_ms} ms</span></div>)}
            </Section>
          </div>
          <Section title="Blocks issued by the security agent">
            {blocks.length === 0 && <p className="text-sm text-ink-500">No scraping or abuse detected.</p>}
            {blocks.map((b, i) => <div key={i} className="py-1 text-sm"><span className="mono">{b.key}</span> — {b.reason} <span className="text-xs text-ink-500">until {fmtDate(b.until)}</span></div>)}
          </Section>
        </>
      )}
    </div>
  );
}
