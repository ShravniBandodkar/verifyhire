'use client';
import { useEffect, useState } from 'react';
import { api, getUser, homeFor, setSession } from '@/lib/api';
import { Seal } from '@/components/ui';

const DEMOS = [
  { label: 'Candidate', sub: 'Aisha Kapoor', email: 'aisha@demo.example', pw: 'Candidate@123' },
  { label: 'Employer', sub: 'Nimbus Cloudworks · KYB approved', email: 'hr@nimbuscloud.example', pw: 'Employer@123' },
  { label: 'Shell employer', sub: 'Quanta Retail · rejected by KYB agent', email: 'quanta.hiring@gmail.com', pw: 'Employer@123' },
  { label: 'Governor', sub: 'Human oversight console', email: 'governor@verifyhire.example', pw: 'Governor@123' },
];

const AGENTS = [
  ['KYC & Document Forensics', 'OCR, tamper detection, NSDL/UIDAI checks, signed badges'],
  ['Corporate KYB Underwriting', 'PAN · CIN · GSTIN · EPFO cross-checks, shell detection'],
  ['Reference & Tenure', 'Signed referee links, ring detection, tenure match'],
  ['Semantic Talent Matchmaker', 'Hybrid vector + SQL search, explainable scores'],
  ['Career & Resume Architect', 'Standardised profile, Trust Score, next steps'],
  ['Support & Dispute', 'Chat that acts: consent, KYC retries, corrections'],
  ['DevSecOps & FinOps', 'Anti-scraping, key rotation, self-healing index'],
];

export default function Home() {
  const [mode, setMode] = useState<'login' | 'candidate' | 'employer'>('login');
  const [f, setF] = useState<any>({});
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [stats, setStats] = useState<any>(null);
  useEffect(() => {
    const u = getUser(); if (u) window.location.href = homeFor(u.role);
    api('/public/stats').then(setStats).catch(() => {});
  }, []);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  async function submit(e?: React.FormEvent, override?: any) {
    e?.preventDefault(); setErr(''); setBusy(true);
    try {
      let r: any;
      const body = override || f;
      if (override || mode === 'login') r = await api('/auth/login', { body: { email: body.email, password: body.password } });
      else if (mode === 'candidate') r = await api('/auth/register/candidate', { body });
      else r = await api('/auth/register/employer', { body: { ...body, headcount: Number(body.headcount || 0), incorporation_year: body.incorporation_year ? Number(body.incorporation_year) : null, locations: (body.locations || '').split(',').map((s: string) => s.trim()).filter(Boolean) } });
      setSession(r.access_token, r.user);
      window.location.href = homeFor(r.user.role);
    } catch (e: any) { setErr(e.message); }
    setBusy(false);
  }

  return (
    <div className="min-h-screen">
      <div className="mx-auto grid max-w-7xl gap-10 px-5 py-10 lg:grid-cols-[1.2fr_1fr] lg:py-16">
        <div>
          <div className="flex items-center gap-3"><Seal size={40} /><span className="font-display text-3xl font-semibold">VerifyHire</span></div>
          <h1 className="mt-10 font-display text-4xl leading-tight md:text-5xl">The resume that’s already been checked.</h1>
          <p className="mt-4 max-w-xl text-lg text-ink-500">
            A consent-first vault of Aadhaar & PAN-verified candidates, KYB-verified employers, and seven AI agents that do the
            verification, matching and support work a back office used to do.
          </p>
          {stats && (
            <div className="mt-8 grid max-w-xl grid-cols-3 gap-3">
              <div className="card p-3"><div className="font-display text-2xl">{stats.candidates}</div><div className="text-xs text-ink-500">candidates in vault</div></div>
              <div className="card p-3"><div className="font-display text-2xl">{stats.agent_decisions}</div><div className="text-xs text-ink-500">agent decisions logged</div></div>
              <div className="card p-3"><div className="font-display text-2xl">{stats.autonomy_rate}%</div><div className="text-xs text-ink-500">handled without humans</div></div>
            </div>
          )}
          <div className="mt-10">
            <div className="label">The autonomous workforce</div>
            <ol className="mt-2 grid gap-2 sm:grid-cols-2">
              {AGENTS.map(([n, d], i) => (
                <li key={n} className="flex gap-3 rounded-lg border border-paper-300 bg-paper-100 p-3">
                  <span className="mono mt-0.5 text-ink-300">{String(i + 1).padStart(2, '0')}</span>
                  <div><div className="text-sm font-medium">{n}</div><div className="text-xs text-ink-500">{d}</div></div>
                </li>
              ))}
            </ol>
          </div>
        </div>

        <div className="lg:pt-16">
          <div className="card p-6">
            <div className="mb-5 flex gap-1 rounded-lg bg-paper-200 p-1">
              {(['login', 'candidate', 'employer'] as const).map((m) => (
                <button key={m} onClick={() => { setMode(m); setErr(''); }} className={'flex-1 rounded-md py-1.5 text-sm ' + (mode === m ? 'bg-paper-100 shadow-card font-medium' : 'text-ink-500')}>
                  {m === 'login' ? 'Log in' : m === 'candidate' ? 'Join as candidate' : 'Register employer'}
                </button>
              ))}
            </div>
            <form onSubmit={submit} className="space-y-3">
              {mode !== 'login' && <div><label className="label">Full name</label><input className="input" required onChange={set('full_name')} /></div>}
              <div><label className="label">{mode === 'employer' ? 'Corporate email' : 'Email'}</label><input className="input" type="email" required onChange={set('email')} /></div>
              <div><label className="label">Password</label><input className="input" type="password" required minLength={8} onChange={set('password')} /></div>
              {mode === 'candidate' && <div><label className="label">City</label><input className="input" onChange={set('city')} placeholder="Bengaluru" /></div>}
              {mode === 'employer' && (
                <div className="grid grid-cols-2 gap-3">
                  <div className="col-span-2"><label className="label">Registered company name</label><input className="input" required onChange={set('company_name')} /></div>
                  <div><label className="label">Company PAN</label><input className="input uppercase" required onChange={set('pan')} placeholder="AAACN4455F" /></div>
                  <div><label className="label">GSTIN</label><input className="input uppercase" onChange={set('gstin')} /></div>
                  <div className="col-span-2"><label className="label">CIN / LLPIN</label><input className="input uppercase" onChange={set('cin')} /></div>
                  <div><label className="label">Revenue bracket</label>
                    <select className="input" onChange={set('revenue_bracket')} defaultValue=""><option value="">—</option>{['< 1 Cr', '1-10 Cr', '10-100 Cr', '100-500 Cr', '500+ Cr'].map((x) => <option key={x}>{x}</option>)}</select></div>
                  <div><label className="label">Headcount</label><input className="input" type="number" onChange={set('headcount')} /></div>
                  <div><label className="label">Incorporated</label><input className="input" type="number" onChange={set('incorporation_year')} placeholder="2014" /></div>
                  <div><label className="label">Vertical</label><input className="input" onChange={set('vertical')} /></div>
                  <p className="col-span-2 text-xs text-ink-500">The KYB Underwriting agent checks PAN, GSTIN, MCA21 and EPFO the moment you submit.</p>
                </div>
              )}
              {err && <div className="rounded-lg bg-alarm-50 p-2 text-sm text-alarm">{err}</div>}
              <button className="btn-primary w-full" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Log in' : 'Create account'}</button>
            </form>
          </div>
          <div className="mt-6">
            <div className="label">One-click demo accounts</div>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {DEMOS.map((d) => (
                <button key={d.email} onClick={() => submit(undefined, { email: d.email, password: d.pw })} className="card p-3 text-left hover:border-ink-500">
                  <div className="text-sm font-medium">{d.label}</div><div className="text-xs text-ink-500">{d.sub}</div>
                </button>
              ))}
            </div>
            <p className="mt-4 text-xs text-ink-500">
              Sandbox mode: all identities are synthetic and government APIs are simulated. Sample documents: <a className="underline" href="/samples/aisha_kyc_bundle.zip">KYC bundle (ZIP)</a> ·{' '}
              <a className="underline" href="/samples/TAMPERED_pan_spliced.jpg">tampered PAN</a> · <a className="underline" href="/samples/TAMPERED_degree_photoshop.pdf">tampered degree</a> · <a className="underline" href="/docs">API docs</a>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
