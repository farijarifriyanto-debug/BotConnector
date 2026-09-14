// Replaces Electron's contextBridge/ipcRenderer with plain fetch()/SSE calls
// against the local `botconnector ui` HTTP server (webui/server.cjs).
// desktop.js is loaded unmodified after this file and only ever talks to
// window.botconnector — this file exists purely to give that same object an
// HTTP transport instead of an IPC one, so no view code changes.
(() => {
  let sessionSecret = null;
  const sessionReady = fetch('/api/session', { credentials: 'omit' })
    .then(r => r.json())
    .then(j => { sessionSecret = j.secret; })
    .catch(e => { console.error('BotConnector UI: failed to establish local session', e); });

  async function call(path, { method = 'GET', body } = {}) {
    await sessionReady;
    const headers = { 'X-BotConnector-Session': sessionSecret || '' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined, credentials: 'omit' });
    let data = null;
    try { data = await res.json(); } catch { /* empty body is fine for e.g. DELETE */ }
    if (!res.ok) throw new Error((data && data.error) || `Request failed: ${res.status}`);
    return data;
  }
  const get = (p) => call(p);
  const post = (p, body = {}) => call(p, { method: 'POST', body });
  const del = (p) => call(p, { method: 'DELETE' });

  // ---------- server-sent event bus (download/runtime-install progress) ----------
  const listeners = { 'download:progress': new Set(), 'runtime:install-progress': new Set() };
  sessionReady.then(() => {
    if (!sessionSecret) return;
    const es = new EventSource(`/api/events?s=${encodeURIComponent(sessionSecret)}`);
    es.onmessage = (ev) => {
      try {
        const { type, payload } = JSON.parse(ev.data);
        for (const cb of (listeners[type] || [])) cb(payload);
      } catch {}
    };
  });
  function on(type, cb) { listeners[type].add(cb); return () => listeners[type].delete(cb); }

  // ---------- chat streaming (fetch-based SSE consumption; POST, not GET, so EventSource can't be used) ----------
  const chatListeners = { delta: new Set(), reasoning: new Set(), toolcall: new Set(), toolresult: new Set(), done: new Set(), error: new Set() };
  function onChat(kind, cb) { chatListeners[kind].add(cb); return () => chatListeners[kind].delete(cb); }
  async function streamChat({ requestId, messages, options }) {
    await sessionReady;
    const res = await fetch('/api/chat/stream', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-BotConnector-Session': sessionSecret || '' }, body: JSON.stringify({ requestId, messages, options }), credentials: 'omit' });
    if (!res.ok || !res.body) { for (const cb of chatListeners.error) cb({ requestId, error: `stream failed: ${res.status}` }); return; }
    const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = '';
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true });
      const frames = buf.split('\n\n'); buf = frames.pop() || '';
      for (const frame of frames) {
        const line = frame.split('\n').find(l => l.startsWith('data:')); if (!line) continue;
        try {
          const msg = JSON.parse(line.slice(5).trim());
          const kind = msg.type?.replace('chat:', '');
          for (const cb of (chatListeners[kind] || [])) cb(msg);
        } catch {}
      }
    }
  }

  window.botconnector = {
    overview: () => get('/api/overview'),
    openExternal: (u) => { try { window.open(u, '_blank', 'noopener,noreferrer'); } catch {} return Promise.resolve(true); },

    getSettings: () => get('/api/settings'),
    setSettings: (v) => post('/api/settings', v),
    setHfToken: (t) => post('/api/settings/hf-token', { token: t }),
    ensureApiToken: () => post('/api/settings/api-token'),
    clearApiToken: () => del('/api/settings/api-token'),
    pickModelsDir: () => post('/api/settings/models-dir'),

    cloudStatus: () => get('/api/cloud/status'),
    cloudSetKey: (p) => post('/api/cloud/key', p),
    cloudRemoveKey: (provider) => del(`/api/cloud/key/${encodeURIComponent(provider)}`),
    cloudModels: (o) => post('/api/cloud/models', o || {}),
    cloudUsage: () => get('/api/cloud/usage'),
    cloudBudgetSet: (p) => post('/api/cloud/budget', p),
    cloudChat: (p) => post('/api/cloud/chat', p),

    mcpList: () => get('/api/mcp'),
    mcpSave: (c) => post('/api/mcp', c),
    mcpRemove: (id) => del(`/api/mcp/${encodeURIComponent(id)}`),
    mcpTest: (id) => post(`/api/mcp/${encodeURIComponent(id)}/test`),
    mcpInvoke: ({ id, tool, args }) => post(`/api/mcp/${encodeURIComponent(id)}/invoke`, { tool, args }),

    searchModels: (i) => post('/api/models/search', i),
    modelDetails: (id) => post('/api/models/details', { id }),
    installedModels: () => get('/api/models/installed'),
    revealModel: (p) => post('/api/models/reveal', { path: p }),
    deleteModel: (dir) => post('/api/models/delete', { dir }),
    downloadModel: (p) => post('/api/models/download', p),

    downloads: () => get('/api/downloads'),
    pauseDownload: (id) => post(`/api/downloads/${encodeURIComponent(id)}/pause`),
    resumeDownload: (id) => post(`/api/downloads/${encodeURIComponent(id)}/resume`),
    cancelDownload: (id) => post(`/api/downloads/${encodeURIComponent(id)}/cancel`),
    onDownloadProgress: (cb) => on('download:progress', cb),

    pickBinary: () => post('/api/dialog/file', { title: 'Choose llama-server.exe', filterName: 'llama-server', extensions: ['exe'] }),
    pickModel: () => post('/api/dialog/file', { title: 'Choose a GGUF model', filterName: 'GGUF', extensions: ['gguf'] }),
    latestRuntime: () => get('/api/runtime/latest'),
    resolveRuntime: (c) => post('/api/runtime/resolve', c),
    verifyRuntime: () => get('/api/runtime/verify'),
    managedRuntime: () => get('/api/runtime/managed-status'),
    installRuntime: (c) => post('/api/runtime/install', c),
    startRuntime: (c) => post('/api/runtime/start', c),
    startInstalled: (c) => post('/api/runtime/start-installed', c),
    stopRuntime: () => post('/api/runtime/stop'),
    runtimeStatus: () => get('/api/runtime/status'),
    runtimeLogs: () => get('/api/runtime/logs'),
    onRuntimeInstallProgress: (cb) => on('runtime:install-progress', cb),

    chat: (m) => post('/api/chat/complete', m),
    pickImage: () => post('/api/chat/pick-image'),
    streamChat: (p) => { streamChat(p); },
    onChatDelta: (cb) => onChat('delta', cb),
    onChatReasoning: (cb) => onChat('reasoning', cb),
    onChatToolCall: (cb) => onChat('toolcall', cb),
    onChatToolResult: (cb) => onChat('toolresult', cb),
    onChatDone: (cb) => onChat('done', cb),
    onChatError: (cb) => onChat('error', cb),
  };
})();
