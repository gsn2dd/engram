// Engram Capture — client-side secret scrubbing.
// Redacts common credential shapes BEFORE anything leaves the browser.
// (The ingest server should scrub again — never trust one layer.)
(function () {
  const PATTERNS = [
    [/sk-[A-Za-z0-9_-]{20,}/g, '[REDACTED_OPENAI_KEY]'],
    [/AIza[0-9A-Za-z_-]{30,}/g, '[REDACTED_GOOGLE_KEY]'],
    [/gh[pousr]_[A-Za-z0-9]{30,}/g, '[REDACTED_GITHUB_TOKEN]'],
    [/AKIA[0-9A-Z]{16}/g, '[REDACTED_AWS_KEY_ID]'],
    [/xox[baprs]-[A-Za-z0-9-]{10,}/g, '[REDACTED_SLACK_TOKEN]'],
    [/eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g, '[REDACTED_JWT]'],
    [/-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----/g, '[REDACTED_PRIVATE_KEY]'],
    [/(password|passwd|secret|api[_-]?key|token)(\s*[:=]\s*)(['"]?)([^\s'"]{6,})\3/gi, '$1$2$3[REDACTED]$3'],
  ];
  self.__engramRedact = function (text) {
    let out = String(text || '');
    for (const [re, rep] of PATTERNS) out = out.replace(re, rep);
    return out;
  };
})();
