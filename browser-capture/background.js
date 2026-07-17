// Engram Capture — background service worker.
// Receives exchanges from the content script and POSTs them to your self-hosted
// ingest endpoint. Shows a badge on the icon so you can SEE it working:
//   green number = exchanges sent OK   ·   red "!" = POST failed   ·   red "cfg" = not configured.

const CFG = { endpoint: '', token: '', contributor: 'david', enabled: true };
async function loadCfg() { Object.assign(CFG, await chrome.storage.sync.get(CFG)); }
loadCfg();
chrome.storage.onChanged.addListener(loadCfg);

const BACKLOG_KEY = 'engram_backlog';
let sentCount = 0;

function badge(text, color) {
  try { chrome.action.setBadgeBackgroundColor({ color }); chrome.action.setBadgeText({ text }); } catch (e) {}
}

async function post(exchange) {
  const body = JSON.stringify({ contributor: CFG.contributor, tier: 'transcript', ...exchange });
  const res = await fetch(CFG.endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + CFG.token },
    body,
  });
  if (!res.ok) throw new Error('ingest HTTP ' + res.status);
}

async function flushBacklog() {
  await loadCfg();
  const { [BACKLOG_KEY]: q = [] } = await chrome.storage.local.get(BACKLOG_KEY);
  if (!q.length || !CFG.endpoint) return;
  const rest = [];
  for (const ex of q) { try { await post(ex); sentCount++; } catch (e) { rest.push(ex); } }
  await chrome.storage.local.set({ [BACKLOG_KEY]: rest });
  if (sentCount) badge(String(sentCount), '#16a34a');
}

async function enqueue(exchange) {
  const { [BACKLOG_KEY]: q = [] } = await chrome.storage.local.get(BACKLOG_KEY);
  q.push(exchange);
  await chrome.storage.local.set({ [BACKLOG_KEY]: q.slice(-500) });
}

chrome.runtime.onMessage.addListener((msg) => {
  if (msg?.type !== 'engram_exchange') return;
  (async () => {
    await loadCfg();                       // <-- fix: ensure config is loaded before we check it (cold worker race)
    if (!CFG.enabled) return;
    if (!CFG.endpoint) { badge('cfg', '#dc2626'); return; }
    try { await post(msg.exchange); sentCount++; badge(String(sentCount), '#16a34a'); }
    catch (e) { await enqueue(msg.exchange); badge('!', '#dc2626'); }
  })();
  return true;                             // keep the worker alive for the async POST
});

chrome.alarms?.create('engram_flush', { periodInMinutes: 2 });
chrome.alarms?.onAlarm.addListener((a) => { if (a.name === 'engram_flush') flushBacklog(); });
