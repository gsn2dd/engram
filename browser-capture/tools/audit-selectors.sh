#!/usr/bin/env bash
# Audit Engram Capture's per-host selectors against a LIVE, logged-in page.
#
# WHY THIS EXISTS
#   capture.js says its per-host selectors are "the ONLY thing you should need to
#   tune" -- but claude.ai and chatgpt.com change their DOM without notice, and a
#   dead selector fails SILENTLY: the extension captures nothing and reports no
#   error. That is the failure shape this tooling exists to catch: an action that
#   "succeeded" with no error can still have done nothing -- only an observed
#   effect proves it.
#
# REQUIREMENTS
#   - chrome-agent  (uv tool install chrome-agent) -- needs Python >= 3.11
#   - a Chrome instance ALREADY LOGGED IN to the site, with a real conversation open
#     (a landing page has none of these nodes; you will get all-zeros and learn nothing)
#
# USAGE
#   chrome-agent launch                       # then log in + open a conversation by hand
#   ./audit-selectors.sh <instance-name>
#
# ONE round trip: every selector is counted inside a single Runtime.evaluate,
# rather than one CLI call per selector. That is the point of a CLI over an MCP
# server -- the program does the work, the model is not in the loop.
set -euo pipefail
INST="${1:-}"
[ -z "$INST" ] && { echo "usage: $0 <chrome-agent-instance>  (see: chrome-agent status)"; exit 2; }

read -r -d '' JS <<'EOJS' || true
(() => {
  const probe = (sels) => sels.map(s => {
    let n = -1; try { n = document.querySelectorAll(s).length; } catch (e) { n = -2; }
    return { sel: s, count: n };
  });
  const USER_SELS = ['[data-testid="user-message"]','div.font-user-message','.font-user-message'];
  const ASST_SELS = ['.font-claude-response','[data-testid="assistant-message"]','div.font-claude-message','.font-claude-message'];
  const CHATGPT   = ['[data-message-author-role]'];
  const ATTACH    = ['[data-testid*="attachment" i]','[data-testid*="file" i]','[data-testid*="paste" i]'];
  const GENERATING= ['[data-testid="stop-button"]','button[data-testid="stop-button"]'];
  // The diagnostic capture.js already prints when nothing matches -- reproduced
  // here so a FAILING audit hands you the replacement candidates immediately.
  const testids = [...new Set([...document.querySelectorAll('[data-testid]')]
                   .map(e => e.getAttribute('data-testid')))].sort();
  const classes = [...new Set([...document.querySelectorAll('[class]')]
                   .flatMap(e => [...e.classList])
                   .filter(c => /claude|user|message|response|prose/i.test(c)))].sort();
  return { host: location.host, url: location.href.slice(0, 120),
           user: probe(USER_SELS), assistant: probe(ASST_SELS),
           chatgpt: probe(CHATGPT), attachment: probe(ATTACH), generating: probe(GENERATING),
           testids_present: testids.slice(0, 60), candidate_classes: classes.slice(0, 60) };
})()
EOJS

chrome-agent "$INST" Runtime.evaluate \
  "$(python3 -c 'import json,sys; print(json.dumps({"expression": sys.stdin.read(), "returnByValue": True}))' <<< "$JS")" \
| python3 - <<'EOPY'
import json, sys
d = json.load(sys.stdin)
v = (d.get("result") or {}).get("result", {}).get("value")
if v is None:
    print("no value returned -- is the instance name right and a page open?"); print(json.dumps(d)[:500]); sys.exit(1)
print("host: %s\nurl:  %s\n" % (v["host"], v["url"]))
groups = [("user", "Claude USER_SELS"), ("assistant", "Claude ASST_SELS"),
          ("chatgpt", "ChatGPT"), ("attachment", "attachments"), ("generating", "isGenerating()")]
broken = []
for key, label in groups:
    rows = v.get(key) or []
    hit = any(r["count"] > 0 for r in rows)
    print("%-22s %s" % (label, "OK" if hit else "*** NO MATCH ***"))
    for r in rows:
        mark = "  " if r["count"] > 0 else ("!!" if r["count"] < 0 else "  ")
        print("   %s %-46s %s" % (mark, r["sel"], "ERROR" if r["count"] == -2 else r["count"]))
    if not hit: broken.append(label)
    print()
if broken:
    print("BROKEN: %s" % ", ".join(broken))
    print("\ndata-testids present on this page (replacement candidates):")
    print("  " + ", ".join(v.get("testids_present") or []) or "  (none)")
    print("\ncandidate classes matching claude|user|message|response|prose:")
    print("  " + ", ".join(v.get("candidate_classes") or []) or "  (none)")
    sys.exit(1)
print("All selector groups matched. Note: a group only proves itself on a page that")
print("ACTUALLY CONTAINS that thing -- 0 attachments on a chat with no attachments is")
print("not a failure, and isGenerating() only matches WHILE a response is streaming.")
EOPY
