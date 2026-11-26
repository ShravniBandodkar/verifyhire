// VerifyHire desktop (Windows & macOS) — Electron shell around the web client with native extras:
// OS tray + notifications, encrypted local cache (OS keychain via safeStorage), Touch ID prompt,
// batch folder/ZIP ingest, and a configurable server URL.
const { app, BrowserWindow, Tray, Menu, Notification, ipcMain, dialog, safeStorage, systemPreferences, shell, nativeImage } = require('electron');
const fs = require('fs');
const path = require('path');

const DEFAULT_SERVER = process.env.VH_SERVER_URL || 'https://verifyhire-ndua.onrender.com';
const userData = () => app.getPath('userData');
const settingsFile = () => path.join(userData(), 'settings.json');
const cacheDir = () => path.join(userData(), 'vault-cache');

let win = null;
let tray = null;

function readSettings() {
  try { return JSON.parse(fs.readFileSync(settingsFile(), 'utf8')); } catch { return {}; }
}
function writeSettings(s) {
  fs.mkdirSync(userData(), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(s, null, 2));
}
const serverUrl = () => (readSettings().serverUrl || DEFAULT_SERVER).replace(/\/$/, '');

function createWindow() {
  win = new BrowserWindow({
    width: 1360, height: 900, minWidth: 980, minHeight: 640, title: 'VerifyHire',
    icon: path.join(__dirname, 'build', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, sandbox: true,
      additionalArguments: [`--vh-server=${serverUrl()}`],
    },
  });
  win.loadURL(serverUrl() + '/');
  // External links open in the user's browser; in-app navigation stays on our origin only.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith(serverUrl())) return { action: 'allow' };
    shell.openExternal(url); return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith(serverUrl())) { e.preventDefault(); shell.openExternal(url); } });
  win.webContents.session.setPermissionRequestHandler((_wc, perm, cb) => cb(['media', 'notifications', 'clipboard-sanitized-write'].includes(perm)));
  win.on('close', (e) => { if (!app.isQuitting && process.platform === 'darwin') { e.preventDefault(); win.hide(); } });
}

function buildTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'build', 'tray.png'));
  tray = new Tray(icon);
  tray.setToolTip('VerifyHire');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Open VerifyHire', click: () => { win.show(); win.focus(); } },
    { label: 'Batch ingest documents…', click: ingestDialog },
    { type: 'separator' },
    { label: `Server: ${serverUrl()}`, enabled: false },
    { label: 'Change server URL…', click: changeServer },
    { type: 'separator' },
    { label: 'Quit', click: () => { app.isQuitting = true; app.quit(); } },
  ]));
  tray.on('click', () => { win.isVisible() ? win.focus() : win.show(); });
}

function buildMenu() {
  const tpl = [
    ...(process.platform === 'darwin' ? [{ role: 'appMenu' }] : []),
    { label: 'File', submenu: [
      { label: 'Batch ingest documents (files / folder / ZIP)…', accelerator: 'CmdOrCtrl+O', click: ingestDialog },
      { label: 'Change server URL…', click: changeServer },
      { label: 'Clear encrypted local cache', click: () => { fs.rmSync(cacheDir(), { recursive: true, force: true }); notify('Cache cleared', 'Local encrypted vault cache removed.'); } },
      { type: 'separator' }, process.platform === 'darwin' ? { role: 'close' } : { role: 'quit' },
    ] },
    { role: 'editMenu' }, { role: 'viewMenu' }, { role: 'windowMenu' },
    { label: 'Help', submenu: [{ label: 'API documentation', click: () => shell.openExternal(serverUrl() + '/docs') }] },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(tpl));
}

function notify(title, body) {
  if (Notification.isSupported()) {
    const n = new Notification({ title, body, icon: path.join(__dirname, 'build', 'icon.png') });
    n.on('click', () => { win.show(); win.focus(); });
    n.show();
  }
}

async function changeServer() {
  const r = await dialog.showMessageBox(win, {
    type: 'question', buttons: ['Use localhost:8000', 'Use default (cloud)', 'Cancel'], defaultId: 1,
    message: 'Which VerifyHire server should the desktop app connect to?', detail: `Current: ${serverUrl()}`,
  });
  if (r.response === 2) return;
  writeSettings({ ...readSettings(), serverUrl: r.response === 0 ? 'http://localhost:8000' : DEFAULT_SERVER });
  app.relaunch(); app.exit(0);
}

const ALLOWED = /\.(pdf|docx|jpe?g|png|zip|txt)$/i;
function collect(p, out) {
  const st = fs.statSync(p);
  if (st.isDirectory()) { for (const f of fs.readdirSync(p)) collect(path.join(p, f), out); }
  else if (ALLOWED.test(p) && st.size < 15 * 1024 * 1024 && out.length < 40) out.push(p);
}

async function ingestDialog() {
  const r = await dialog.showOpenDialog(win, {
    title: 'Select documents, a folder or a ZIP to ingest',
    properties: ['openFile', 'openDirectory', 'multiSelections'],
    filters: [{ name: 'Documents', extensions: ['pdf', 'docx', 'jpg', 'jpeg', 'png', 'zip', 'txt'] }],
  });
  if (r.canceled) return;
  const files = [];
  r.filePaths.forEach((p) => collect(p, files));
  const payload = files.map((f) => ({ name: path.basename(f), data: fs.readFileSync(f) }));
  win.show();
  win.webContents.send('vh:ingest', payload);
}

// ---------- IPC ----------
ipcMain.handle('vh:notify', (_e, { title, body }) => { notify(String(title).slice(0, 120), String(body || '').slice(0, 300)); });

ipcMain.handle('vh:biometric', async (_e, reason) => {
  // macOS: Touch ID. Windows: return null so the renderer uses WebAuthn, which Chromium routes to Windows Hello.
  if (process.platform === 'darwin' && systemPreferences.canPromptTouchID()) {
    try { await systemPreferences.promptTouchID(String(reason || 'confirm this action')); return true; } catch { return false; }
  }
  return null;
});

ipcMain.handle('vh:cache:set', (_e, key, value) => {
  if (!safeStorage.isEncryptionAvailable()) return false;
  fs.mkdirSync(cacheDir(), { recursive: true });
  const safe = String(key).replace(/[^a-z0-9_-]/gi, '_');
  fs.writeFileSync(path.join(cacheDir(), safe + '.bin'), safeStorage.encryptString(String(value)));
  return true;
});

ipcMain.handle('vh:cache:get', (_e, key) => {
  try {
    const safe = String(key).replace(/[^a-z0-9_-]/gi, '_');
    return safeStorage.decryptString(fs.readFileSync(path.join(cacheDir(), safe + '.bin')));
  } catch { return null; }
});

app.setAppUserModelId('com.verifyhire.desktop');
app.whenReady().then(() => {
  createWindow(); buildMenu(); buildTray();
  app.on('activate', () => { win ? win.show() : createWindow(); });
});
app.on('before-quit', () => { app.isQuitting = true; });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
