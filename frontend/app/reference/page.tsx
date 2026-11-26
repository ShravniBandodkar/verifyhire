'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { Seal } from '@/components/ui';

export default function ReferencePage() {
  const [token, setToken] = useState('');
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState('');
  const [f, setF] = useState<any>({ confirm: true, rating: 5, feedback: '' });
  const [done, setDone] = useState<string>('');
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get('token') || '';
    setToken(t);
    api(`/public/reference/${t}`).then(setD).catch((e) => setErr(e.message));
  }, []);
  return (
    <div className="mx-auto max-w-xl px-5 py-12">
      <div className="flex items-center gap-2"><Seal /><span className="font-display text-xl">VerifyHire</span><span className="text-sm text-ink-500">· Reference verification</span></div>
      <div className="card mt-6 p-6">
        {err && <p className="text-alarm">{err}</p>}
        {done && <p className="text-seal">Thank you. The Reference agent recorded your response: <b>{done}</b>.</p>}
        {d && !done && (d.status !== 'sent' ? <p>This link has already been used.</p> : (
          <form className="space-y-4" onSubmit={async (e) => {
            e.preventDefault();
            try { const r = await api<any>(`/public/reference/${token}`, { body: { ...f, rating: Number(f.rating) } }); setDone(r.status); } catch (e: any) { setErr(e.message); }
          }}>
            <p>Hi {d.referee}, <b>{d.candidate}</b> listed you as their {d.relationship} at <b>{d.company}</b>. This takes under a minute.</p>
            <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.checked })} /> {d.questions[0]}</label>
            <div><label className="label">{d.questions[2]}</label>
              <div className="flex gap-2">{[1, 2, 3, 4, 5].map((n) => <button type="button" key={n} onClick={() => setF({ ...f, rating: n })} className={'h-10 w-10 rounded-lg border ' + (f.rating === n ? 'border-ink-900 bg-ink-900 text-paper-100' : 'border-paper-300')}>{n}</button>)}</div></div>
            <div><label className="label">{d.questions[1]} {d.questions[3]}</label><textarea className="input" rows={4} required value={f.feedback} onChange={(e) => setF({ ...f, feedback: e.target.value })} /></div>
            <button className="btn-primary w-full">Submit verification</button>
            <p className="text-xs text-ink-500">Signed single-use link. Your response is checked against your company domain and our reference-ring detector, then attached to the candidate’s profile as a tamper-proof badge.</p>
          </form>
        ))}
      </div>
    </div>
  );
}
