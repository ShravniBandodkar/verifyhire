'use client';

declare global {
  interface Window {
    vhDesktop?: {
      apiBase?: string;
      notify: (title: string, body: string) => void;
      biometric: (reason: string) => Promise<boolean | null>;
      cache: { set: (k: string, v: string) => Promise<boolean>; get: (k: string) => Promise<string | null> };
      onIngest?: (cb: (files: { name: string; data: Uint8Array }[]) => void) => void;
      platform: string;
    };
  }
}

export const API_BASE: string =
  (typeof window !== 'undefined' && window.vhDesktop?.apiBase) || process.env.NEXT_PUBLIC_API_BASE || '';

export type User = { id: string; email: string; full_name: string; role: string; company_id: string | null };

const store = {
  get(k: string) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k: string, v: string) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  del(k: string) { try { localStorage.removeItem(k); } catch { /* storage unavailable */ } },
};

export function getToken() { return store.get('vh_token'); }
export function getUser(): User | null {
  const u = store.get('vh_user');
  try { return u ? JSON.parse(u) : null; } catch { return null; }
}
export function setSession(token: string, user: User) { store.set('vh_token', token); store.set('vh_user', JSON.stringify(user)); }
export function logout() { store.del('vh_token'); store.del('vh_user'); window.location.href = '/'; }

export class ApiError extends Error { status: number; constructor(s: number, m: string) { super(m); this.status = s; } }

export async function api<T = any>(path: string, opts: { method?: string; body?: any; form?: FormData; raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const t = getToken();
  if (t) headers['Authorization'] = `Bearer ${t}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.body); }
  const r = await fetch(`${API_BASE}/api/v1${path}`, { method: opts.method || (body ? 'POST' : 'GET'), headers, body });
  if (r.status === 401 && t) { logout(); }
  if (!r.ok) {
    let msg = r.statusText;
    try { const j = await r.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch { /* not json */ }
    throw new ApiError(r.status, msg);
  }
  if (opts.raw) return r as any;
  return r.json();
}

export function homeFor(role: string) {
  return role === 'candidate' ? '/candidate/' : role === 'admin' ? '/admin/' : '/employer/';
}

export const fmtDate = (s?: string | null) => (s ? new Date(s.endsWith('Z') ? s : s + 'Z').toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : '');

/** Platform biometric gate: Electron (Touch ID / Windows Hello) → WebAuthn platform authenticator → none. */
export async function biometricConfirm(reason: string): Promise<string> {
  if (typeof window === 'undefined') return '';
  if (window.vhDesktop?.biometric) {
    try {
      const r = await window.vhDesktop.biometric(reason);
      if (r !== null) return r ? 'desktop-touch-id' : '';  // null → fall through to WebAuthn (Windows Hello)
    } catch { /* fall through */ }
  }
  try {
    if (!window.PublicKeyCredential || !(await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable())) return '';
    const challenge = crypto.getRandomValues(new Uint8Array(32));
    const existing = store.get('vh_webauthn_id');
    if (existing) {
      const id = Uint8Array.from(atob(existing), (c) => c.charCodeAt(0));
      await navigator.credentials.get({ publicKey: { challenge, allowCredentials: [{ id, type: 'public-key' }], userVerification: 'required', timeout: 60000 } });
      return 'webauthn-assertion';
    }
    const u = getUser();
    const cred = (await navigator.credentials.create({
      publicKey: {
        challenge, rp: { name: 'VerifyHire' },
        user: { id: new TextEncoder().encode(u?.id || 'user'), name: u?.email || 'user', displayName: u?.full_name || 'User' },
        pubKeyCredParams: [{ type: 'public-key', alg: -7 }, { type: 'public-key', alg: -257 }],
        authenticatorSelection: { authenticatorAttachment: 'platform', userVerification: 'required' }, timeout: 60000,
      },
    })) as PublicKeyCredential | null;
    if (cred) store.set('vh_webauthn_id', btoa(String.fromCharCode(...new Uint8Array(cred.rawId))));
    return cred ? 'webauthn-registration' : '';
  } catch { return ''; }
}
