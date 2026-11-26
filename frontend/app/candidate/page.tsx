'use client';
import { useEffect, useRef, useState } from 'react';
import { api, biometricConfirm, fmtDate } from '@/lib/api';
import { Check, DevKeys, DropZone, Section, Shell, SlideToConsent, Stat, Status, TrustMeter, useToast } from '@/components/ui';

const TABS: [string, string][] = [['overview', 'Overview'], ['vault', 'Vault'], ['verify', 'Verify'], ['consent', 'Consent & audit'], ['jobs', 'Job matches'], ['profile', 'Profile'], ['dev', 'Developers']];

export default function CandidatePage() {
  const [tab, setTab] = useState('overview');
  const [p, setP] = useState<any>(null);
  const toast = useToast();
  const load = () => api('/candidate/profile')
    .then((x) => { setP(x); window.vhDesktop?.cache.set('profile', JSON.stringify(x)); })
    .catch(async (e) => {
      const cached = await window.vhDesktop?.cache.get('profile');  // desktop: encrypted offline copy
      if (cached) { setP(JSON.parse(cached)); toast.show('Offline — showing encrypted local copy'); } else toast.show(e.message, 'error');
    });
  useEffect(() => { load(); }, []);
  return (
    <Shell title="Candidate vault" tabs={TABS} tab={tab} setTab={setTab}>
      {!p ? <p className="text-ink-500">Loading…</p> : (
        <>
          {tab === 'overview' && <Overview p={p} go={setTab} />}
          {tab === 'vault' && <Vault onChange={load} toast={toast.show} />}
          {tab === 'verify' && <Verify p={p} onChange={load} toast={toast.show} />}
          {tab === 'consent' && <Consent toast={toast.show} />}
          {tab === 'jobs' && <Jobs />}
          {tab === 'profile' && <Profile p={p} onSaved={(x: any) => { setP(x); toast.show('Saved — Architect agent re-scored your profile', 'ok'); }} />}
          {tab === 'dev' && <DevKeys />}
        </>
      )}
      {toast.node}
    </Shell>
  );
}

function Overview({ p, go }: any) {
  const [bench, setBench] = useState<any>(null);
  useEffect(() => { api('/candidate/ctc-benchmark').then(setBench).catch(() => {}); }, []);
  const sp = p.standardized_profile || {};
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <section className="card flex flex-col items-center p-6 lg:row-span-2">
        <TrustMeter score={p.trust_score} />
        <div className="mt-4 w-full space-y-2">
          {Object.entries(p.trust_breakdown || {}).map(([k, v]: any) => (
            <div key={k} className="flex items-center gap-2 text-sm">
              <span className={v.points === v.max ? 'text-seal' : 'text-ink-300'}>{v.points === v.max ? '●' : '○'}</span>
              <span className="flex-1">{v.label}</span><span className="mono text-ink-500">{v.points}/{v.max}</span>
            </div>
          ))}
        </div>
      </section>
      <Section title={`Hi ${p.full_name.split(' ')[0]} — here’s your verified profile`}>
        <div className="font-display text-lg">{sp.headline || p.headline}</div>
        <p className="mt-2 text-sm text-ink-700">{sp.executive_summary}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Check ok={p.aadhaar_verified} label={p.aadhaar_masked || 'Aadhaar'} /><Check ok={p.pan_verified} label={p.pan_masked || 'PAN'} />
          <Check ok={p.photo_verified} label="Selfie" /><Check ok={p.degree_verified} label="Degree" />
          <Check ok={p.experience_verified} label="Employment" /><Check ok={p.ctc_verified} label="CTC" />
        </div>
        <div className="mt-3 flex flex-wrap gap-1">{(p.skills || []).map((s: string) => <span key={s} className="chip bg-paper-200">{s}</span>)}</div>
      </Section>
      <Section title="What the Architect agent suggests next">
        {p.gaps.length === 0 ? <p className="text-sm text-seal">You’re fully verified. Employers see a 100% Trust Score.</p> : (
          <ul className="space-y-2">
            {p.gaps.map((g: any) => (
              <li key={g.key} className="flex items-start gap-3 rounded-lg bg-paper-200/60 p-3 text-sm">
                <span className="chip bg-saffron-50 text-saffron">+{g.points}</span>
                <div className="flex-1"><div className="font-medium">{g.label}</div><div className="text-ink-500">{g.action}</div></div>
                <button className="btn-ghost" onClick={() => go(['aadhaar', 'photo', 'references'].includes(g.key) ? 'verify' : 'vault')}>Do it</button>
              </li>
            ))}
          </ul>
        )}
      </Section>
      <div className="lg:col-span-2">
        <Section title="CTC benchmark">
          {!bench || !bench.peers ? <p className="text-sm text-ink-500">Add skills and experience to see how your CTC compares.</p> : (
            <div>
              <div className="relative mt-6 h-3 rounded-full bg-gradient-to-r from-paper-300 via-seal/40 to-seal">
                {[['p25', bench.p25], ['median', bench.median], ['p75', bench.p75], ['p90', bench.p90]].map(([l, v]: any, i: number) => {
                  const pos = ((v - bench.p25 * 0.8) / (bench.p90 * 1.1 - bench.p25 * 0.8)) * 100;
                  return <div key={l} className={'absolute -translate-x-1/2 whitespace-nowrap text-[10px] text-ink-500 ' + (i % 2 ? 'top-4' : '-top-5')} style={{ left: `${pos}%` }}>{l} ₹{v}L</div>;
                })}
                {bench.yours && <div className="absolute -top-1 h-5 w-1.5 -translate-x-1/2 rounded bg-ink-900" style={{ left: `${Math.min(100, Math.max(0, ((bench.yours - bench.p25 * 0.8) / (bench.p90 * 1.1 - bench.p25 * 0.8)) * 100))}%` }} />}
              </div>
              <p className="mt-8 text-sm">{bench.yours ? <>Your verified CTC <b>₹{bench.yours} LPA</b> sits at the <b>{bench.your_percentile}th percentile</b>. </> : 'Upload a payslip to place yourself on this curve. '}<span className="text-ink-500">{bench.basis}.</span></p>
            </div>
          )}
        </Section>
      </div>
    </div>
  );
}

function Vault({ onChange, toast }: any) {
  const [docs, setDocs] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const load = () => api<any[]>('/candidate/documents').then(setDocs);
  useEffect(() => {
    load();
    // Desktop: File → "Batch ingest" (folder / ZIP / multi-select) arrives over IPC
    window.vhDesktop?.onIngest?.((items) => upload(items.map((i) => new File([i.data], i.name))));
  }, []);
  async function upload(files: File[]) {
    setBusy(true);
    const fd = new FormData(); files.forEach((f) => fd.append('files', f));
    try {
      const r = await api<any>('/candidate/documents/bulk', { form: fd });
      const v = r.results.filter((x: any) => x.verdict === 'verified').length;
      toast(`${r.processed} processed · ${v} verified${r.errors.length ? ' · ' + r.errors.join('; ') : ''}`, v === r.processed ? 'ok' : 'info');
      load(); onChange();
    } catch (e: any) { toast(e.message, 'error'); }
    setBusy(false);
  }
  return (
    <div className="space-y-6">
      <DropZone onFiles={upload} busy={busy} />
      <p className="text-xs text-ink-500">No documents handy? Try the synthetic <a className="underline" href="/samples/aisha_kyc_bundle.zip">KYC bundle</a> or the <a className="underline" href="/samples/TAMPERED_pan_spliced.jpg">tampered PAN</a> to watch the forensics agent react.</p>
      <Section title="Encrypted vault">
        {docs.length === 0 && <p className="text-sm text-ink-500">Nothing here yet.</p>}
        <div className="divide-y divide-paper-300">
          {docs.map((d) => (
            <div key={d.id} className="py-3">
              <div className="flex flex-wrap items-center gap-3">
                <span className="chip bg-ink-900 text-paper-100">{d.doc_type.replace('_', ' ')}</span>
                <span className="text-sm font-medium">{d.filename}</span>
                <Status s={d.status} />
                {d.badge && <span className="chip bg-seal-50 text-seal" title={d.badge}>signed badge</span>}
                {typeof d.forensics?.risk === 'number' && <span className="mono text-ink-500">risk {d.forensics.risk}</span>}
                <div className="ml-auto flex gap-2">
                  <button className="btn-ghost" onClick={() => setOpen(open === d.id ? null : d.id)}>{open === d.id ? 'Hide' : 'Agent report'}</button>
                  {d.status !== 'verified' && <button className="btn-ghost" onClick={async () => { await api(`/candidate/documents/${d.id}/reverify`, { method: 'POST' }); load(); onChange(); }}>Re-verify</button>}
                  <button className="btn-ghost" onClick={async () => { if (confirm('Erase this document permanently?')) { await api(`/candidate/documents/${d.id}`, { method: 'DELETE' }); load(); onChange(); } }}>Erase</button>
                </div>
              </div>
              {open === d.id && (
                <div className="mt-3 grid gap-3 rounded-lg bg-paper-200/60 p-3 text-sm md:grid-cols-2">
                  <div><div className="label">Extracted fields</div>
                    {Object.entries(d.extracted || {}).map(([k, v]: any) => <div key={k} className="flex gap-2"><span className="w-32 text-ink-500">{k}</span><span className="mono">{Array.isArray(v) ? v.join(', ') : String(v)}</span></div>)}
                  </div>
                  <div><div className="label">Forensics & registry checks</div>
                    {(d.forensics?.reasons || []).length === 0 ? <div className="text-seal">No anomalies detected.</div> : d.forensics.reasons.map((r: string) => <div key={r} className="text-alarm">• {r}</div>)}
                    {d.forensics?.gov?.pan && <div className="mono mt-1">NSDL: {d.forensics.gov.pan.status}{d.forensics.gov.pan.name_match != null && ` · name match ${d.forensics.gov.pan.name_match}`}</div>}
                    {d.forensics?.gov?.nad && <div className="mono mt-1">NAD/DigiLocker: {d.forensics.gov.nad.found ? 'record found' : 'not found'}</div>}
                    {d.forensics?.ela && <div className="mono mt-1">ELA ratio {d.forensics.ela.ela_ratio}</div>}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function Verify({ p, onChange, toast }: any) {
  const [aad, setAad] = useState(''); const [otp, setOtp] = useState(''); const [sent, setSent] = useState('');
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Section title="Aadhaar OTP e-KYC">
        {p.aadhaar_verified ? <p className="text-sm text-seal">Verified · stored only as <span className="mono">{p.aadhaar_masked}</span> + irreversible token.</p> : (
          <form className="space-y-3" onSubmit={async (e) => {
            e.preventDefault();
            try {
              if (!sent) { const r = await api<any>('/candidate/kyc/aadhaar/otp', { body: { aadhaar_number: aad } }); setSent(r.hint); }
              else { await api('/candidate/kyc/aadhaar/verify', { body: { aadhaar_number: aad, otp } }); toast('Aadhaar verified', 'ok'); onChange(); }
            } catch (e: any) { toast(e.message, 'error'); }
          }}>
            <div><label className="label">Aadhaar number</label><input className="input mono" value={aad} onChange={(e) => setAad(e.target.value)} placeholder="5274 1896 3301" /></div>
            {sent && <div><label className="label">OTP</label><input className="input mono" value={otp} onChange={(e) => setOtp(e.target.value)} /><p className="mt-1 text-xs text-ink-500">{sent}</p></div>}
            <button className="btn-primary">{sent ? 'Verify OTP' : 'Send OTP'}</button>
            <p className="text-xs text-ink-500">Sandbox DigiLocker/UIDAI adapter. The demo Aadhaar is in <a className="underline" href="/samples/README.txt">README.txt</a>. Only the masked number is ever stored.</p>
          </form>
        )}
      </Section>
      <Liveness done={p.photo_verified} onDone={onChange} toast={toast} />
      <div className="lg:col-span-2"><References onChange={onChange} toast={toast} /></div>
    </div>
  );
}

function Liveness({ done, onDone, toast }: any) {
  const video = useRef<HTMLVideoElement>(null);
  const [on, setOn] = useState(false); const [busy, setBusy] = useState(false); const [res, setRes] = useState<any>(null);
  async function start() {
    try { const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' } }); if (video.current) { video.current.srcObject = s; await video.current.play(); } setOn(true); }
    catch { toast('Camera unavailable', 'error'); }
  }
  async function capture() {
    setBusy(true);
    const v = video.current!; const c = document.createElement('canvas'); c.width = v.videoWidth; c.height = v.videoHeight;
    const fd = new FormData();
    for (let i = 0; i < 3; i++) {
      c.getContext('2d')!.drawImage(v, 0, 0);
      const b: Blob = await new Promise((r) => c.toBlob((x) => r(x!), 'image/jpeg', 0.85));
      fd.append('frames', b, `f${i}.jpg`);
      await new Promise((r) => setTimeout(r, 650));
    }
    try { const r = await api<any>('/candidate/kyc/liveness', { form: fd }); setRes(r); if (r.live) { toast('Liveness passed', 'ok'); onDone(); } }
    catch (e: any) { toast(e.message, 'error'); }
    (v.srcObject as MediaStream)?.getTracks().forEach((t) => t.stop()); setOn(false); setBusy(false);
  }
  return (
    <Section title="Live selfie (active liveness)">
      {done ? <p className="text-sm text-seal">Liveness verified.</p> : (
        <div className="space-y-3">
          <div className="relative overflow-hidden rounded-xl bg-ink-950" style={{ aspectRatio: '4/3' }}>
            <video ref={video} playsInline muted className="h-full w-full -scale-x-100 object-cover" />
            {!on && <div className="absolute inset-0 flex items-center justify-center text-sm text-paper-300">Camera off</div>}
            {on && <div className="pointer-events-none absolute inset-[18%] rounded-[50%] border-2 border-dashed border-paper-100/70" />}
          </div>
          <div className="flex gap-2">
            {!on ? <button className="btn-primary" onClick={start}>Start camera</button> : <button className="btn-seal" disabled={busy} onClick={capture}>{busy ? 'Hold still, then turn slightly…' : 'Capture 3 frames'}</button>}
          </div>
          {res && <p className="mono">live={String(res.live)} · face {res.face_ratio} · motion {res.motion} · {res.reason}</p>}
          <p className="text-xs text-ink-500">Checks a face is present in every frame and that natural motion exists between frames (defeats printed photos).</p>
        </div>
      )}
    </Section>
  );
}

function References({ onChange, toast }: any) {
  const [refs, setRefs] = useState<any[]>([]); const [f, setF] = useState<any>({ relationship: 'manager' }); const [link, setLink] = useState('');
  const load = () => api<any[]>('/candidate/references').then(setRefs);
  useEffect(() => { load(); }, []);
  return (
    <Section title="Verified references">
      <form className="grid gap-2 md:grid-cols-5" onSubmit={async (e) => {
        e.preventDefault();
        try { const r = await api<any>('/candidate/references', { body: f }); setLink(r.verification_link); load(); toast('Reference agent sent a signed link', 'ok'); } catch (e: any) { toast(e.message, 'error'); }
      }}>
        <input className="input" placeholder="Name" required onChange={(e) => setF({ ...f, name: e.target.value })} />
        <input className="input" placeholder="Official email" type="email" required onChange={(e) => setF({ ...f, email: e.target.value })} />
        <input className="input" placeholder="Company" required onChange={(e) => setF({ ...f, company: e.target.value })} />
        <select className="input" onChange={(e) => setF({ ...f, relationship: e.target.value })}><option>manager</option><option>hr</option><option>peer</option></select>
        <button className="btn-primary">Send request</button>
      </form>
      {link && <div className="mt-3 rounded-lg bg-paper-200 p-3 text-sm">Sandbox outbox — open as the referee: <a className="mono break-all underline" href={link.replace(/^https?:\/\/[^/]+/, '')} target="_blank">{link}</a></div>}
      <div className="mt-4 divide-y divide-paper-300">
        {refs.map((r) => (
          <div key={r.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
            <span className="font-medium">{r.name}</span><span className="text-ink-500">{r.relationship} · {r.company}</span><span className="mono">{r.email}</span><Status s={r.status} />
            {r.analysis?.flags?.length > 0 && <span className="text-xs text-alarm">{r.analysis.flags.join(' · ')}</span>}
            {r.analysis?.free_mail && r.status === 'sent' && <span className="text-xs text-saffron">personal email domain — weaker signal</span>}
          </div>
        ))}
      </div>
    </Section>
  );
}

function Consent({ toast }: any) {
  const [reqs, setReqs] = useState<any[]>([]); const [audit, setAudit] = useState<any[]>([]); const [hours, setHours] = useState<Record<string, number>>({});
  const load = () => { api<any[]>('/candidate/access-requests').then(setReqs); api<any[]>('/candidate/audit').then(setAudit); };
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, []);
  async function decide(id: string, decision: string) {
    let bio = '';
    if (decision === 'grant') bio = await biometricConfirm('Approve document access');
    try { await api(`/candidate/access-requests/${id}`, { body: { decision, hours: hours[id] || 72, biometric_assertion: bio } }); toast(`Access ${decision}ed${bio ? ' · biometric confirmed' : ''}`, 'ok'); load(); }
    catch (e: any) { toast(e.message, 'error'); }
  }
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Section title="Access requests">
        {reqs.length === 0 && <p className="text-sm text-ink-500">No requests yet. When a verified employer asks to see documents, it appears here.</p>}
        <div className="space-y-3">
          {reqs.map((g) => (
            <div key={g.id} className="rounded-xl border border-paper-300 bg-white p-4">
              <div className="flex items-center gap-2"><span className="font-medium">{g.company}</span>{g.company_kyb === 'approved' && <span className="chip bg-seal-50 text-seal">KYB ✓</span>}<span className="ml-auto"><Status s={g.status} /></span></div>
              <div className="mt-1 text-sm text-ink-500">{g.job ? `For: ${g.job} · ` : ''}{g.reason}</div>
              <div className="mt-2 flex flex-wrap gap-1">{g.doc_types.map((d: string) => <span key={d} className="chip bg-paper-200">{d}</span>)}{g.reveal_identity_numbers && <span className="chip bg-saffron-50 text-saffron">reveal PAN</span>}</div>
              {g.expires_at && <div className="mt-1 text-xs text-ink-500">Expires {fmtDate(g.expires_at)}</div>}
              {g.status === 'pending' && (
                <div className="mt-3 space-y-2">
                  <div className="flex items-center gap-2 text-sm"><span>Access for</span>
                    <select className="input w-auto" value={hours[g.id] || 72} onChange={(e) => setHours({ ...hours, [g.id]: Number(e.target.value) })}>
                      <option value={24}>24 hours</option><option value={72}>3 days</option><option value={168}>7 days</option><option value={720}>30 days</option>
                    </select></div>
                  <SlideToConsent onConfirm={() => decide(g.id, 'grant')} />
                  <button className="btn-ghost w-full" onClick={() => decide(g.id, 'deny')}>Deny</button>
                </div>
              )}
              {g.status === 'granted' && <button className="btn-danger mt-3" onClick={() => decide(g.id, 'revoke')}>Revoke now</button>}
            </div>
          ))}
        </div>
      </Section>
      <Section title="Live audit trail" action={<span className="text-xs text-ink-500">hash-chained · append-only</span>}>
        <div className="max-h-[36rem] space-y-1 overflow-auto">
          {audit.map((e) => (
            <div key={e.seq} className="grid grid-cols-[auto_1fr] gap-x-3 rounded-lg px-2 py-1.5 text-sm hover:bg-paper-200">
              <span className="mono text-ink-300">#{e.seq}</span>
              <div>
                <span className={e.action.includes('view') || e.action.includes('reveal') ? 'font-medium text-saffron' : ''}>{e.action}</span>
                <span className="text-ink-500"> · {e.actor}</span>
                <div className="text-[11px] text-ink-300">{fmtDate(e.ts)} · <span className="mono">{e.hash}…</span></div>
              </div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}

function Jobs() {
  const [jobs, setJobs] = useState<any[]>([]);
  useEffect(() => { api<any[]>('/candidate/job-alerts').then(setJobs); }, []);
  return (
    <Section title="AI-curated job matches">
      {jobs.length === 0 && <p className="text-sm text-ink-500">The Matchmaker agent will surface roles here as your profile is verified.</p>}
      <div className="grid gap-3 md:grid-cols-2">
        {jobs.map((j) => (
          <div key={j.job_id} className="rounded-xl border border-paper-300 bg-white p-4">
            <div className="flex items-center gap-2"><span className="font-display text-lg">{j.title}</span><span className="ml-auto mono">{Math.round(j.score)}%</span></div>
            <div className="text-sm text-ink-500">{j.company} {j.company_kyb === 'approved' && '· KYB ✓'} · {j.location}{j.ctc_band[1] ? ` · up to ₹${j.ctc_band[1]}L` : ''}</div>
            <div className="mt-2"><Status s={j.status} />{j.interview_at && <span className="ml-2 text-sm">Interview proposed {j.interview_at}</span>}</div>
            <ul className="mt-2 space-y-0.5 text-xs text-ink-500">{j.reasons.slice(0, 3).map((r: string) => <li key={r}>• {r}</li>)}</ul>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Profile({ p, onSaved }: any) {
  const [f, setF] = useState<any>({ ...p, skills: (p.skills || []).join(', ') });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <Section title="Profile">
      <form className="grid gap-3 md:grid-cols-2" onSubmit={async (e) => {
        e.preventDefault();
        const body: any = { full_name: f.full_name, phone: f.phone, city: f.city, headline: f.headline, summary: f.summary,
          years_experience: Number(f.years_experience) || 0, expected_ctc_lpa: f.expected_ctc_lpa ? Number(f.expected_ctc_lpa) : null,
          skills: String(f.skills).split(',').map((s: string) => s.trim().toLowerCase()).filter(Boolean) };
        onSaved(await api('/candidate/profile', { method: 'PATCH', body }));
      }}>
        {[['full_name', 'Full name'], ['phone', 'Phone'], ['city', 'City'], ['headline', 'Headline'], ['years_experience', 'Years of experience'], ['expected_ctc_lpa', 'Expected CTC (LPA)']].map(([k, l]) => (
          <div key={k}><label className="label">{l}</label><input className="input" value={f[k] ?? ''} onChange={set(k)} /></div>
        ))}
        <div className="md:col-span-2"><label className="label">Skills (comma separated)</label><input className="input" value={f.skills} onChange={set('skills')} /></div>
        <div className="md:col-span-2"><label className="label">Summary</label><textarea className="input" rows={3} value={f.summary} onChange={set('summary')} /></div>
        <div className="md:col-span-2 text-xs text-ink-500">Current CTC is set only from a verified payslip. Employment & education entries become “verified” only through documents or references.</div>
        <div><button className="btn-primary">Save</button></div>
      </form>
    </Section>
  );
}
