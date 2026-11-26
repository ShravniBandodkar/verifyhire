// Safe bridge between the web client and native desktop capabilities (contextIsolation on).
const { contextBridge, ipcRenderer } = require('electron');

const serverArg = process.argv.find((a) => a.startsWith('--vh-server='));

contextBridge.exposeInMainWorld('vhDesktop', {
  platform: process.platform,
  apiBase: serverArg ? serverArg.split('=')[1] : '',
  notify: (title, body) => ipcRenderer.invoke('vh:notify', { title, body }),
  biometric: (reason) => ipcRenderer.invoke('vh:biometric', reason),
  cache: {
    set: (k, v) => ipcRenderer.invoke('vh:cache:set', k, v),
    get: (k) => ipcRenderer.invoke('vh:cache:get', k),
  },
  onIngest: (cb) => {
    const handler = (_e, files) => cb(files.map((f) => ({ name: f.name, data: f.data })));
    ipcRenderer.removeAllListeners('vh:ingest');
    ipcRenderer.on('vh:ingest', handler);
  },
});
