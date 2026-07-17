const FIELDS = ['endpoint', 'token', 'contributor'];
const CHECKS = ['enabled', 'debug'];
const DEFAULTS = { endpoint: '', token: '', contributor: 'david', enabled: true, debug: false };

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
      const origin = new URL(cfg.endpoint).origin + '/*';
      const granted = await chrome.permissions.request({ origins: [origin] });
      if (!granted) { status.textContent = 'Permission for the endpoint was declined.'; status.style.color = '#dc2626'; return; }
    }
  } catch (e) { status.textContent = 'Invalid endpoint URL.'; status.style.color = '#dc2626'; return; }

  chrome.storage.sync.set(cfg, () => {
    status.textContent = 'Saved.'; status.style.color = '#16a34a';
    setTimeout(() => (status.textContent = ''), 2000);
  });
});

document.getElementById('test').addEventListener('click', async () => {
  const s = document.getElementById('teststatus');
  const endpoint = document.getElementById('endpoint').value.trim();
  const token = document.getElementById('token').value.trim();
  const contributor = document.getElementById('contributor').value.trim() || 'david';
  if (!endpoint) { s.textContent = 'Set the endpoint URL first.'; s.style.color = '#dc2626'; return; }
  try { await chrome.permissions.request({ origins: [new URL(endpoint).origin + '/*'] }); } catch (e) {}
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
