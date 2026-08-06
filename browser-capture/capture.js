// Engram Capture — content script. Observes the conversation and streams
// finished turns to the background worker. Site DOMs change often; the
// per-host selectors below are the ONLY thing you should need to tune.
// Turn on debug in the options page to log exactly what it captures.
(function () {
  const HOST = location.hostname;

  // --- Per-host extractors ------------------------------------------------
  // Return an array of {role:'user'|'assistant', el} in document order.
  // Text is pulled centrally (turnText below) so attachment-augmentation
  // for the user role is shared across hosts instead of duplicated per site.
  const EXTRACTORS = {
    'chatgpt.com': extractChatGPT,
    'chat.openai.com': extractChatGPT,
    'claude.ai': extractClaude,
  };

  function extractChatGPT() {
    // ChatGPT marks each turn with data-message-author-role (stable-ish).
    return [...document.querySelectorAll('[data-message-author-role]')].map((el) => ({
      role: el.getAttribute('data-message-author-role') === 'user' ? 'user' : 'assistant',
      el,
    }));
  }

  function extractClaude() {
    // claude.ai gives the two roles DIFFERENT hooks and changes them often, so
    // pick the best-matching selector for each role INDEPENDENTLY — otherwise a
    // matching user selector can win with zero assistants and nothing ever pairs.
    const USER_SELS = ['[data-testid="user-message"]', 'div.font-user-message', '.font-user-message'];
    const ASST_SELS = ['.font-claude-response', '[data-testid="assistant-message"]', 'div.font-claude-message', '.font-claude-message'];
    const pick = (sels) => {
      for (const s of sels) { const n = [...document.querySelectorAll(s)]; if (n.length) return { sel: s, nodes: n }; }
      return { sel: null, nodes: [] };
    };
    const u = pick(USER_SELS);
    const a = pick(ASST_SELS);
    if (debug) console.log('[engram-capture] claude  user:', u.sel, '(' + u.nodes.length + ')  |  assistant:', a.sel, '(' + a.nodes.length + ')');
    // Diagnostic: when we can see the user but not the assistant, dump the hooks
    // present so the assistant selector can be identified from the real DOM.
    if (debug && u.nodes.length && !a.nodes.length && !extractClaude._dumped) {
      extractClaude._dumped = true;
      const ids = [...new Set([...document.querySelectorAll('[data-testid]')].map((e) => e.getAttribute('data-testid')))];
      const cls = [...new Set([...document.querySelectorAll('[class]')].flatMap((e) => [...e.classList])
        .filter((c) => /claude|assistant|response|message|prose|markdown|font-/i.test(c)))];
      console.log('[engram-capture] DIAGNOSTIC data-testids:', JSON.stringify(ids));
      console.log('[engram-capture] DIAGNOSTIC candidate classes:', JSON.stringify(cls));
      // Also: what does the block right AFTER the last user message look like?
      const lastU = u.nodes[u.nodes.length - 1];
      let sib = lastU.closest('div')?.parentElement;
      console.log('[engram-capture] DIAGNOSTIC container after user:', sib ? (sib.tagName + '.' + sib.className).slice(0, 300) : 'n/a');
    }
    if (!u.nodes.length && !a.nodes.length) return [];
    const tagged = [...u.nodes.map((el) => ({ el, role: 'user' })), ...a.nodes.map((el) => ({ el, role: 'assistant' }))];
    tagged.sort((x, y) => (x.el.compareDocumentPosition(y.el) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1));
    return tagged;
  }

  const extractor = EXTRACTORS[HOST];
  if (!extractor) return;

  // --- Attachments / pasted content ---------------------------------------
  // A big paste often renders as a separate "file chip" component next to
  // the typed text, NOT inside the user-message node's own subtree — so
  // plain innerText on the message misses it entirely. Widen outward from
  // the message element one ancestor level at a time and grab anything that
  // looks like a file/paste/attachment preview, stopping at the first level
  // that finds something (keeps us from bleeding into a neighbouring turn).
  const ATTACH_SELS = [
    '[data-testid*="attachment" i]',
    '[data-testid*="file" i]',
    '[data-testid*="paste" i]',
    '[class*="attachment" i]',
    '[class*="file-thumbnail" i]',
    '[class*="file-preview" i]',
  ];
  function nearbyAttachmentText(msgEl) {
    const seen = new Set();
    const parts = [];
    let scope = msgEl.parentElement;
    for (let level = 0; level < 3 && scope; level++, scope = scope.parentElement) {
      for (const sel of ATTACH_SELS) {
        for (const el of scope.querySelectorAll(sel)) {
          if (msgEl.contains(el) || el.contains(msgEl)) continue; // stuff already inside the message text itself
          const txt = (el.innerText || '').trim();
          if (txt.length > 20 && !seen.has(txt)) { seen.add(txt); parts.push(txt); }
        }
      }
      if (parts.length) break; // found something at this level — don't widen further and risk another turn
    }
    if (debug && parts.length) console.log('[engram-capture] found ' + parts.length + ' attachment block(s) near user message');
    // Diagnostic (once): typed text present but short, and nothing matched —
    // dump nearby hooks so the ATTACH_SELS list above can be re-tuned.
    if (debug && !parts.length && !nearbyAttachmentText._dumped) {
      const p2 = msgEl.parentElement?.parentElement;
      if (p2) {
        const ids = [...new Set([...p2.querySelectorAll('[data-testid]')].map((e) => e.getAttribute('data-testid')))];
        if (ids.length) {
          nearbyAttachmentText._dumped = true;
          console.log('[engram-capture] DIAGNOSTIC nearby data-testids (no attachment match):', JSON.stringify(ids));
        }
      }
    }
    return parts.join('\n\n');
  }

  function turnText(role, el) {
    let text = (el.innerText || '').trim();
    if (role === 'user' && captureAttachments) {
      const extra = nearbyAttachmentText(el);
      if (extra) text = text ? text + '\n\n[Pasted/attached content]\n' + extra : extra;
    }
    return text;
  }

  // While the model is still streaming, don't finalise a turn — the answer is
  // still growing (and may briefly read just "Thinking"). Best-effort per-host
  // signal; the settle timer below is the real backstop if this misses.
  function isGenerating() {
    return !!document.querySelector(
      '[data-testid="stop-button"], button[data-testid="stop-button"], ' +
      'button[aria-label="Stop generating"], button[aria-label="Stop streaming"], ' +
      'button[aria-label="Stop response"], .result-streaming'
    );
  }

  // --- Dedup + pairing ----------------------------------------------------
  // posted: stabKeys (one per user turn) we've already finalised and sent.
  // Keying finalisation on the TURN, not on a hash of the answer text, is
  // what stops growth-snapshot spam: earlier versions re-armed on every text
  // change and would fire again each time a mid-stream pause looked "stable"
  // for a moment, posting 2-3 separate truncated prefixes of the same answer.
  const posted = new Set();
  const lastText = new Map();  // stabKey -> { text, changedAt } — real-time settle tracking
  function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h; }
  function convId() {
    const m = location.pathname.match(/([0-9a-f-]{16,})/i);
    return m ? m[1] : location.pathname;
  }

  let debug = false;
  // capture_attachments: include pasted/attached content (the v0.1.8 feature) in the user turn.
  // Default ON to preserve existing behaviour; switch OFF in options for privacy. Live via onChanged
  // so toggling takes effect on the next captured turn without a page reload.
  let captureAttachments = true;
  chrome.storage.sync.get({ debug: false, capture_attachments: true }, (c) => {
    debug = !!c.debug;
    captureAttachments = c.capture_attachments !== false;
  });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== 'sync') return;
    if (changes.debug) debug = !!changes.debug.newValue;
    if (changes.capture_attachments) captureAttachments = changes.capture_attachments.newValue !== false;
  });

  // Text-stability is judged by ELAPSED REAL TIME unchanged, not scan count —
  // scan cadence varies with DOM activity, so a scan-count gate of "1" (the
  // old default when not "generating") could fire on a single quiet moment
  // mid-stream. A wall-clock settle window is robust to that regardless of
  // how often mutations happen to fire.
  const SETTLE_MS = 2500;       // real ms unchanged required when not "generating"
  const SETTLE_MS_BUSY = 5000;  // ... when the streaming indicator is (perhaps wrongly) still on

  let stabT = null;
  function scan() {
    let turns;
    try {
      turns = extractor()
        .map((t) => ({ role: t.role, text: turnText(t.role, t.el) }))
        .filter((t) => t.text && t.text.length > 1);
    } catch (e) { return; }
    const generating = isGenerating();
    let pending = false;
    // Pair user -> following assistant into exchanges.
    for (let i = 0; i < turns.length; i++) {
      if (turns[i].role !== 'user') continue;
      const user = turns[i];
      let asst = null;
      for (let j = i + 1; j < turns.length; j++) { if (turns[j].role === 'assistant') { asst = turns[j]; break; } }
      if (!asst) { if (debug) console.log('[engram-capture] user turn has no following assistant yet'); continue; }
      const stabKey = convId() + ':' + hash(user.text);
      if (posted.has(stabKey)) continue; // this turn's final answer already captured
      const prev = lastText.get(stabKey);
      const now = Date.now();
      if (!prev || prev.text !== asst.text) {
        if (debug) console.log('[engram-capture] answer growing/changing — waiting (len ' + asst.text.length + ')');
        lastText.set(stabKey, { text: asst.text, changedAt: now });
        pending = true; continue;
      }
      const need = generating ? SETTLE_MS_BUSY : SETTLE_MS;
      const elapsed = now - prev.changedAt;
      if (elapsed < need) {
        if (debug) console.log('[engram-capture] answer unchanged ' + elapsed + 'ms/' + need + 'ms' + (generating ? ' (indicator still says generating)' : ''));
        pending = true; continue;
      }
      if (debug) console.log('[engram-capture] answer settled — emitting exchange (len ' + asst.text.length + ')');
      posted.add(stabKey);
      const exchange = {
        source: HOST.replace('chat.openai.com', 'chatgpt.com'),
        conversation_id: convId(),
        url: location.href,
        captured_at: new Date().toISOString(),
        prompt: self.__engramRedact(user.text),
        answer: self.__engramRedact(asst.text),
      };
      if (debug) console.log('[engram-capture] exchange', exchange);
      chrome.runtime.sendMessage({ type: 'engram_exchange', exchange });
    }
    // Something changed since the last scan — re-scan soon so a freshly-finished
    // answer gets its confirming second look even if the DOM goes quiet.
    if (pending) { clearTimeout(stabT); stabT = setTimeout(scan, 1200); }
  }

  // Debounced observe: SPAs stream tokens, so wait for quiet before scanning.
  let t = null;
  const obs = new MutationObserver(() => { clearTimeout(t); t = setTimeout(scan, 1500); });
  obs.observe(document.body, { childList: true, subtree: true, characterData: true });
  setTimeout(scan, 3000);
})();
