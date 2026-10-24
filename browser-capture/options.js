const FIELDS = ['endpoint', 'token', 'contributor'];
const CHECKS = ['enabled', 'debug', 'capture_attachments'];
const DEFAULTS = { endpoint: '', token: '', contributor: '', enabled: true, debug: false, capture_attachments: true };

// The manifest only allows HTTPS endpoints, or plain HTTP to this computer
// (localhost / 127.0.0.1, e.g. an SSM tunnel to your server). Returns the
// origin pattern to request, or throws with a message for the user.
function endpointOrigin(endpoint) {
  let u;
  try { u = new URL(endpoint); } catch (e) { throw new Error('Invalid endpoint URL.'); }
  const loopback = u.hostname === 'localhost' || u.hostname === '127.0.0.1';
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && loopback)) {
    throw new Error('Use an https:// endpoint (plain http:// is only allowed for localhost / 127.0.0.1).');
  }
  return u.origin + '/*';
}

chrome.storage.sync.get(DEFAULTS, (cfg) => {
  FIELDS.forEach((k) => (document.getElementById(k).value = cfg[k] || ''));
  CHECKS.forEach((k) => (document.getElementById(k).checked = !!cfg[k]));
});

document.getElementById('save').addEventListener('click', async () => {
  const cfg = {};
  FIELDS.forEach((k) => (cfg[k] = document.getElementById(k).value.trim()));
  CHECKS.forEach((k) => (cfg[k] = document.getElementById(k).checked));

  // The background worker fetches the endpoint cross-origin, which needs host
  // permission for that origin — request it at save time.
  const status = document.getElementById('status');
  try {
    if (cfg.endpoint) {
      const granted = await chrome.permissions.request({ origins: [endpointOrigin(cfg.endpoint)] });
      if (!granted) { status.textContent = 'Permission for the endpoint was declined.'; status.style.color = '#dc2626'; return; }
    }
  } catch (e) { status.textContent = e.message; status.style.color = '#dc2626'; return; }

  chrome.storage.sync.set(cfg, () => {
    status.textContent = 'Saved.'; status.style.color = '#16a34a';
    setTimeout(() => (status.textContent = ''), 2000);
  });
});

document.getElementById('test').addEventListener('click', async () => {
  const s = document.getElementById('teststatus');
  const endpoint = document.getElementById('endpoint').value.trim();
  const token = document.getElementById('token').value.trim();
  const contributor = document.getElementById('contributor').value.trim();
  if (!endpoint) { s.textContent = 'Set the endpoint URL first.'; s.style.color = '#dc2626'; return; }
  let origin;
  try { origin = endpointOrigin(endpoint); } catch (e) { s.textContent = e.message; s.style.color = '#dc2626'; return; }
  try { await chrome.permissions.request({ origins: [origin] }); } catch (e) {}
  s.textContent = 'Testing…'; s.style.color = '#888';
  try {
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
      body: JSON.stringify({ contributor, tier: 'transcript', source: 'extension-test',
        conversation_id: 'test-' + Date.now(), url: 'test', captured_at: new Date().toISOString(),
        prompt: 'Engram Capture connection test', answer: 'ok' }),
    });
    if (res.ok) { s.textContent = '✓ Connected — HTTP ' + res.status + ' accepted.'; s.style.color = '#16a34a'; }
    else { s.textContent = '✗ HTTP ' + res.status + ' — ' + (res.status === 401 ? 'bad token' : 'endpoint rejected it'); s.style.color = '#dc2626'; }
  } catch (e) {
    s.textContent = '✗ Could not reach endpoint (' + e.message + ') — permission not granted, or wrong URL.';
    s.style.color = '#dc2626';
  }
});
