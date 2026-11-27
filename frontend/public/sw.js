// Minimal service worker: makes the app installable and shows a friendly page when offline.
const OFFLINE = '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>VerifyHire</title>' +
  '<body style="font-family:system-ui;background:#faf8f3;color:#141b2d;display:grid;place-items:center;height:100vh;margin:0;text-align:center">' +
  '<div><h2>VerifyHire</h2><p>You are offline. Please check your connection and try again.</p></div>';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.mode !== 'navigate') return; // API calls and assets always go straight to the network
  e.respondWith(fetch(e.request, { cache: 'no-cache' }).catch(() => new Response(OFFLINE, { headers: { 'Content-Type': 'text/html' } })));
});
