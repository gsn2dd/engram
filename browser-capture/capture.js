// Engram Capture — content script. Observes the conversation and streams
// finished turns to the background worker. Site DOMs change often; the
// per-host selectors below are the ONLY thing you should need to tune.
// Turn on debug in the options page to log exactly what it captures.
(function () {
  const HOST = location.hostname;

  // --- Per-host extractors ------------------------------------------------
  // Return an array of {role:'user'|'assistant', text} in document order.
  const EXTRACTORS = {
    'chatgpt.com': extractChatGPT,
    'chat.openai.com': extractChatGPT,
    'claude.ai': extractClaude,
  };

  function extractChatGPT() {
    // ChatGPT marks each turn with data-message-author-role (stable-ish).
    return [...document.querySelectorAll('[data-message-author-role]')].map((el) => ({
      role: el.getAttribute('data-message-author-role') === 'user' ? 'user' : 'assistant',
      text: (el.innerText || '').trim(),
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
    return tagged.map((t) => ({ role: t.role, text: (t.el.innerText || '').trim() }));
  }

  const extractor = EXTRACTORS[HOST];
  if (!extractor) return;

  // While the model is still streaming, don't finalise a turn — the answer is
  // still growing (and may briefly read just "Thinking"). Best-effort per-host
  // signal; the stability gate below is the real backstop if this misses.
  function isGenerating() {
    return !!document.querySelector(
      '[data-testid="stop-button"], button[data-testid="stop-button"], ' +
      'button[aria-label="Stop generating"], button[aria-label="Stop streaming"], ' +
      'button[aria-label="Stop response"], .result-streaming'
    );
  }

  // --- Dedup + pairing ----------------------------------------------------
  const sent = new Set();      // exchanges already POSTed (conv+user+answer hash)
  const lastText = new Map();  // stabKey -> { text, stable } — how many consecutive scans the answer has been unchanged
  function hash(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return h; }
  function convId() {
    const m = location.pathname.match(/([0-9a-f-]{16,})/i);
    return m ? m[1] : location.pathname;
  }

  let debug = false;
  chrome.storage.sync.get({ debug: false }, (c) => { debug = !!c.debug; });

  // Text-stability is the ground truth. isGenerating() only lets a settled answer
  // emit sooner; if that indicator is stuck on (some sites keep the stop control
  // in the DOM), the answer still emits once its text stops changing for a while.
  const STABLE_WHEN_IDLE = 1;   // scans of unchanged text needed when not "generating"
  const STABLE_WHEN_BUSY = 4;   // ... when the streaming indicator is (perhaps wrongly) still on

  let stabT = null;
  function scan() {
    let turns;
    try { turns = extractor().filter((t) => t.text && t.text.length > 1); } catch (e) { return; }
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
      const sentKey = stabKey + ':' + hash(asst.text);
      if (sent.has(sentKey)) continue;
      const prev = lastText.get(stabKey);
      if (!prev || prev.text !== asst.text) {
        if (debug) console.log('[engram-capture] answer still changing — waiting (len ' + asst.text.length + ')');
        lastText.set(stabKey, { text: asst.text, stable: 0 });
        pending = true; continue;
      }
      // Text unchanged since last scan — count how long it has held steady.
      prev.stable += 1;
      const need = generating ? STABLE_WHEN_BUSY : STABLE_WHEN_IDLE;
      if (prev.stable < need) {
        if (debug) console.log('[engram-capture] answer steady ' + prev.stable + '/' + need + (generating ? ' (indicator still says generating)' : ''));
        pending = true; continue;
      }
      if (debug) console.log('[engram-capture] answer stable — emitting exchange');
      sent.add(sentKey);
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
    if (pending) { clearTimeout(stabT); stabT = setTimeout(scan, 1600); }
  }

  // Debounced observe: SPAs stream tokens, so wait for quiet before scanning.
  let t = null;
  const obs = new MutationObserver(() => { clearTimeout(t); t = setTimeout(scan, 1500); });
  obs.observe(document.body, { childList: true, subtree: true, characterData: true });
  setTimeout(scan, 3000);
})();
