'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, fmtDate, getUser, logout, User } from '@/lib/api';

/* ---------------- Shell ---------------- */
export function Shell({ title, tabs, tab, setTab, children }: {
  title: string; tabs: [string, string][]; tab: string; setTab: (t: string) => void; children: React.ReactNode;
}) {
  const [user, setUser] = useState<User | null>(null);
  const [chat, setChat] = useState(false);
  useEffect(() => { const u = getUser(); if (!u) window.location.href = '/'; setUser(u); }, []);
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-paper-300 bg-paper/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-3">
          <a href="/" className="flex items-center gap-2">
            <Seal /><span className="font-display text-xl font-semibold tracking-tight">VerifyHire</span>
          </a>
          <span className="hidden max-w-[14rem] truncate text-sm text-ink-500 2xl:inline">/ {title}</span>
          <nav className="ml-2 hidden gap-1 lg:flex">
            {tabs.map(([k, l]) => <button key={k} onClick={() => setTab(k)} className={(tab === k ? 'tab-active' : 'tab') + ' whitespace-nowrap'}>{l}</button>)}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Bell />
            <button className="btn-ghost whitespace-nowrap" onClick={() => setChat(true)}>Ask agent</button>
            <div className="hidden whitespace-nowrap text-right text-xs leading-tight xl:block">
              <div className="font-medium">{user?.full_name}</div><div className="text-ink-500">{user?.role.replace('_', ' ')}</div>
            </div>
            <button className="btn-ghost whitespace-nowrap" onClick={logout}>Log out</button>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-4 pb-2 lg:hidden">
          {tabs.map(([k, l]) => <button key={k} onClick={() => setTab(k)} className={(tab === k ? 'tab-active' : 'tab') + ' whitespace-nowrap'}>{l}</button>)}
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
      {chat && <SupportChat onClose={() => setChat(false)} />}
    </div>
  );
}

export function Seal({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden>
      <circle cx="16" cy="16" r="15" fill="#0b1220" />
      <circle cx="16" cy="16" r="11.5" fill="none" stroke="#0f7a55" strokeWidth="1.5" strokeDasharray="2 2" />
      <path d="M10.5 16.5l3.6 3.6 7.4-8" fill="none" stroke="#f6f4ef" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ---------------- Notifications (also → desktop tray) ---------------- */
function Bell() {
  const [items, setItems] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const seen = useRef<Set<string>>(new Set());
  const load = useCallback(async () => {
    try {
      const n = await api<any[]>('/notifications');
      if (seen.current.size) {
        n.filter((x) => !x.read && !seen.current.has(x.id)).forEach((x) => window.vhDesktop?.notify(x.title, x.body));
      }
      n.forEach((x) => seen.current.add(x.id));
      setItems(n);
    } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, [load]);
  const unread = items.filter((x) => !x.read).length;
  return (
    <div className="relative">
      <button className="btn-ghost relative" onClick={async () => { setOpen(!open); if (!open && unread) { await api('/notifications/read', { method: 'POST' }); load(); } }}>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 8a6 6 0 1112 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.94 1.94 0 003.4 0" /></svg>
        {unread > 0 && <span className="absolute -right-1 -top-1 rounded-full bg-alarm px-1.5 text-[10px] font-bold text-white">{unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 max-h-96 w-80 overflow-auto card p-2">
          {items.length === 0 && <p className="p-3 text-sm text-ink-500">No notifications yet.</p>}
          {items.map((n) => (
            <div key={n.id} className="rounded-lg p-2 hover:bg-paper-200">
              <div className="text-sm font-medium">{n.title}</div>
              {n.body && <div className="text-xs text-ink-500">{n.body}</div>}
              <div className="mt-0.5 text-[10px] text-ink-300">{fmtDate(n.ts)}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- Support chat (Agent 6) ---------------- */
function SupportChat({ onClose }: { onClose: () => void }) {
  const [msgs, setMsgs] = useState<any[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { api<any[]>('/support/history').then(setMsgs).catch(() => {}); }, []);
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth' }); }, [msgs]);
  const role = getUser()?.role;
  const suggestions = role === 'candidate'
    ? ['What is missing from my trust score?', 'Who has access to my documents?', 'Revoke access for Nimbus', 'Change my city to Pune']
    : ['What is my KYB status?', 'Summarise my job pipeline', 'How do API keys work?'];
  async function send(m: string) {
    if (!m.trim()) return;
    setMsgs((x) => [...x, { role: 'user', content: m }]); setText(''); setBusy(true);
    try {
      const r = await api<any>('/support/chat', { body: { message: m } });
      setMsgs((x) => [...x, { role: 'agent', content: r.reply, tool_calls: [{ tool: r.tool }] }]);
    } catch (e: any) { setMsgs((x) => [...x, { role: 'agent', content: 'Error: ' + e.message }]); }
    setBusy(false);
  }
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink-950/30" onClick={onClose}>
      <div className="flex h-full w-full max-w-md flex-col bg-paper-100 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-paper-300 p-4">
          <div><div className="font-display text-lg">Support & Dispute Agent</div><div className="text-xs text-ink-500">Autonomous · acts via audited tool calls</div></div>
          <button className="btn-ghost" onClick={onClose}>Close</button>
        </div>
        <div className="flex-1 space-y-3 overflow-auto p-4">
          {msgs.length === 0 && <p className="text-sm text-ink-500">Ask me anything — I can explain your status, change consent, re-run KYC or correct your profile.</p>}
          {msgs.map((m, i) => (
            <div key={i} className={m.role === 'user' ? 'ml-10 rounded-xl bg-ink-900 p-3 text-sm text-paper-100' : 'mr-6 rounded-xl border border-paper-300 bg-white p-3 text-sm'}>
              <div className="whitespace-pre-wrap">{m.content}</div>
              {m.role === 'agent' && m.tool_calls?.[0]?.tool && <div className="mono mt-2 text-ink-500">tool → {m.tool_calls[0].tool}</div>}
            </div>
          ))}
          {busy && <div className="text-xs text-ink-500">Agent is working…</div>}
          <div ref={end} />
        </div>
        <div className="border-t border-paper-300 p-3">
          <div className="mb-2 flex flex-wrap gap-1">{suggestions.map((s) => <button key={s} className="chip bg-paper-200 hover:bg-paper-300" onClick={() => send(s)}>{s}</button>)}</div>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); send(text); }}>
            <input className="input" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a message…" />
            <button className="btn-primary" disabled={busy}>Send</button>
          </form>
        </div>
      </div>
    </div>
  );
}

/* ---------------- Trust meter ---------------- */
export function TrustMeter({ score, size = 168 }: { score: number; size?: number }) {
  const r = 70, c = 2 * Math.PI * r;
  const color = score >= 80 ? '#0f7a55' : score >= 50 ? '#e0861a' : '#c2362b';
  return (
    <svg width={size} height={size} viewBox="0 0 180 180" role="img" aria-label={`Trust score ${score}`}>
      <circle cx="90" cy="90" r={r} fill="none" stroke="#ece8de" strokeWidth="14" />
      <circle cx="90" cy="90" r={r} fill="none" stroke={color} strokeWidth="14" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} transform="rotate(-90 90 90)" style={{ transition: 'stroke-dashoffset .8s ease' }} />
      <text x="90" y="88" textAnchor="middle" fontSize="40" fontWeight="700" fill="#111a2e" fontFamily="Georgia, serif">{score}</text>
      <text x="90" y="112" textAnchor="middle" fontSize="12" fill="#5b6787" letterSpacing="2">TRUST SCORE</text>
    </svg>
  );
}

export function Status({ s }: { s: string }) {
  const map: Record<string, string> = {
    verified: 'bg-seal-50 text-seal', approved: 'bg-seal-50 text-seal', granted: 'bg-seal-50 text-seal', shortlisted: 'bg-seal-50 text-seal',
    flagged: 'bg-saffron-50 text-saffron', pending: 'bg-saffron-50 text-saffron', sent: 'bg-saffron-50 text-saffron', processing: 'bg-saffron-50 text-saffron',
    interview: 'bg-ink-900 text-paper-100', suggested: 'bg-paper-200 text-ink-700',
    rejected: 'bg-alarm-50 text-alarm', denied: 'bg-alarm-50 text-alarm', revoked: 'bg-alarm-50 text-alarm', declined: 'bg-alarm-50 text-alarm',
    expired: 'bg-paper-200 text-ink-500', archived: 'bg-paper-200 text-ink-500',
  };
  return <span className={'chip ' + (map[s] || 'bg-paper-200 text-ink-700')}>{s}</span>;
}

export function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={'chip ' + (ok ? 'bg-seal-50 text-seal' : 'bg-paper-200 text-ink-500')}>
      {ok ? '✓' : '○'} {label}
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="card p-4">
      <div className="label">{label}</div>
      <div className="font-display text-3xl">{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-500">{hint}</div>}
    </div>
  );
}

/* ---------------- Slide-to-consent gesture ---------------- */
export function SlideToConsent({ onConfirm, label = 'Slide to grant access' }: { onConfirm: () => void; label?: string }) {
  const track = useRef<HTMLDivElement>(null);
  const [x, setX] = useState(0);
  const [drag, setDrag] = useState(false);
  const [done, setDone] = useState(false);
  const max = () => (track.current ? track.current.clientWidth - 52 : 200);
  function move(clientX: number) {
    if (!drag || !track.current) return;
    const rect = track.current.getBoundingClientRect();
    setX(Math.max(0, Math.min(max(), clientX - rect.left - 26)));
  }
  function end() {
    setDrag(false);
    if (x >= max() * 0.9) { setX(max()); setDone(true); if (navigator.vibrate) navigator.vibrate(30); onConfirm(); }
    else setX(0);
  }
  return (
    <div ref={track} className="relative h-12 w-full select-none overflow-hidden rounded-full bg-ink-900 touch-none"
      onPointerMove={(e) => move(e.clientX)} onPointerUp={end} onPointerLeave={() => drag && end()}>
      <div className="absolute inset-y-0 left-0 rounded-full bg-seal/80" style={{ width: x + 52 }} />
      <div className="absolute inset-0 flex items-center justify-center text-sm font-medium text-paper-100/80">{done ? 'Granted ✓' : label + ' →'}</div>
      <div role="slider" aria-label={label} aria-valuenow={Math.round((x / max()) * 100)} tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') { setDone(true); onConfirm(); } }}
        onPointerDown={(e) => { (e.target as HTMLElement).setPointerCapture(e.pointerId); setDrag(true); }}
        className="absolute top-1 flex h-10 w-10 cursor-grab items-center justify-center rounded-full bg-paper-100 text-ink-900 shadow"
        style={{ left: x + 4, transition: drag ? 'none' : 'left .25s' }}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M9 18l6-6-6-6" /></svg>
      </div>
    </div>
  );
}

/* ---------------- Hold-to-reveal masked PII ---------------- */
export function HoldToReveal({ masked, reveal, disabled }: { masked: string; reveal: () => Promise<string>; disabled?: boolean }) {
  const [val, setVal] = useState<string | null>(null);
  const [holding, setHolding] = useState(false);
  const [err, setErr] = useState('');
  const timer = useRef<any>(null);
  async function start() {
    if (disabled) { setErr('Needs candidate consent'); setTimeout(() => setErr(''), 1800); return; }
    setHolding(true);
    timer.current = setTimeout(async () => {
      try { setVal(await reveal()); } catch (e: any) { setErr(e.message); setTimeout(() => setErr(''), 2500); }
    }, 450);
  }
  function stop() { setHolding(false); clearTimeout(timer.current); setVal(null); }
  return (
    <button type="button" onPointerDown={start} onPointerUp={stop} onPointerLeave={stop}
      className={'group relative inline-flex min-w-[9rem] items-center gap-2 rounded-md border border-paper-300 bg-white px-2 py-1 text-left text-sm ' + (holding ? 'ring-2 ring-saffron' : '')}
      title="Press and hold to reveal (audited)">
      <span className={'mono ' + (val ? '' : 'blurred')}>{val ?? masked}</span>
      <span className="ml-auto text-[10px] uppercase tracking-wider text-ink-300 group-hover:text-ink-500">{err || (val ? 'logged' : 'hold')}</span>
    </button>
  );
}

/* ---------------- Drag-and-drop multi-doc ingest ---------------- */
export function DropZone({ onFiles, busy }: { onFiles: (f: File[]) => void; busy?: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  return (
    <div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); const f = Array.from(e.dataTransfer.files); if (f.length) onFiles(f); }}
      onClick={() => input.current?.click()}
      className={'flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 text-center transition ' + (over ? 'border-seal bg-seal-50' : 'border-paper-300 bg-paper-100 hover:bg-paper-200')}>
      <input ref={input} type="file" multiple hidden accept=".pdf,.docx,.jpg,.jpeg,.png,.zip,.txt"
        onChange={(e) => { const f = Array.from(e.target.files || []); if (f.length) onFiles(f); e.target.value = ''; }} />
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#5b6787" strokeWidth="1.6"><path d="M12 16V4m0 0l-4 4m4-4l4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" /></svg>
      <div className="mt-2 font-medium">{busy ? 'Agents are classifying, extracting and verifying…' : 'Drop documents, a folder’s files, or a ZIP here'}</div>
      <div className="text-xs text-ink-500">Aadhaar · PAN · resume · degree · experience letter · payslip — the agents figure out which is which</div>
    </div>
  );
}

/* ---------------- Swipe card ---------------- */
export function SwipeCard({ children, onSwipe }: { children: React.ReactNode; onSwipe: (dir: 'left' | 'right' | 'up') => void }) {
  const [d, setD] = useState({ x: 0, y: 0 });
  const start = useRef<{ x: number; y: number } | null>(null);
  const hint = d.x > 60 ? 'SHORTLIST' : d.x < -60 ? 'PASS' : d.y < -60 ? 'INTERVIEW' : '';
  return (
    <div className="relative touch-none select-none"
      onPointerDown={(e) => { start.current = { x: e.clientX, y: e.clientY }; (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId); }}
      onPointerMove={(e) => { if (start.current) setD({ x: e.clientX - start.current.x, y: e.clientY - start.current.y }); }}
      onPointerUp={() => {
        const { x, y } = d; start.current = null; setD({ x: 0, y: 0 });
        if (x > 110) onSwipe('right'); else if (x < -110) onSwipe('left'); else if (y < -110) onSwipe('up');
      }}
      style={{ transform: `translate(${d.x}px, ${d.y}px) rotate(${d.x / 18}deg)`, transition: start.current ? 'none' : 'transform .25s' }}>
      {hint && <div className={'absolute left-4 top-4 z-10 rounded-md border-2 px-2 py-1 text-sm font-bold ' + (hint === 'PASS' ? 'border-alarm text-alarm' : hint === 'SHORTLIST' ? 'border-seal text-seal' : 'border-ink-900 text-ink-900')}>{hint}</div>}
      {children}
    </div>
  );
}

export function useToast() {
  const [msg, setMsg] = useState<{ t: string; kind: string } | null>(null);
  const show = useCallback((t: string, kind = 'info') => { setMsg({ t, kind }); setTimeout(() => setMsg(null), 3500); }, []);
  const node = msg ? (
    <div className={'fixed bottom-5 left-1/2 z-[60] -translate-x-1/2 rounded-lg px-4 py-2 text-sm text-white shadow-lg ' + (msg.kind === 'error' ? 'bg-alarm' : msg.kind === 'ok' ? 'bg-seal' : 'bg-ink-900')}>{msg.t}</div>
  ) : null;
  return { show, node };
}

export function Section({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="card p-5">
      <div className="mb-4 flex items-center justify-between gap-3"><h2 className="font-display text-xl">{title}</h2>{action}</div>
      {children}
    </section>
  );
}

export function DevKeys() {
  const [keys, setKeys] = useState<any[]>([]);
  const [fresh, setFresh] = useState('');
  const [name, setName] = useState('my-integration');
  const load = () => api<any[]>('/developer/keys').then(setKeys).catch(() => {});
  useEffect(() => { load(); }, []);
  const base = typeof window !== 'undefined' ? window.location.origin : '';
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Section title="API keys">
        <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); const k = await api<any>('/developer/keys', { body: { name } }); setFresh(k.key); load(); }}>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          <button className="btn-primary">Create key</button>
        </form>
        {fresh && <div className="mt-3 rounded-lg bg-seal-50 p-3 text-sm"><div className="font-medium text-seal">Copy now — shown once</div><div className="mono break-all">{fresh}</div></div>}
        <div className="mt-4 divide-y divide-paper-300">
          {keys.map((k) => (
            <div key={k.id} className="flex items-center gap-3 py-2 text-sm">
              <span className="mono">{k.prefix}…</span><span>{k.name}</span>{k.revoked && <Status s="revoked" />}
              {!k.revoked && <button className="btn-ghost ml-auto" onClick={async () => { await api(`/developer/keys/${k.id}`, { method: 'DELETE' }); load(); }}>Revoke</button>}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Build on VerifyHire" action={<a className="btn-ghost" href={`${base}/docs`} target="_blank">Open API docs</a>}>
        <p className="mb-3 text-sm text-ink-500">Every screen in this app uses the same public REST API. Authenticate with a key in the <span className="mono">X-API-Key</span> header.</p>
        <pre className="mono overflow-auto rounded-lg bg-ink-950 p-3 text-paper-200">{`curl -H "X-API-Key: vh_…" \\
  -H "Content-Type: application/json" \\
  -d '{"query":"PAN-verified React engineers in Pune, 3-6 years"}' \\
  ${base}/api/v1/employer/search`}</pre>
        <p className="mt-3 text-xs text-ink-500">OpenAPI spec: <span className="mono">{base}/openapi.json</span> — generate SDKs in any language.</p>
      </Section>
    </div>
  );
}
