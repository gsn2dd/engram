# Testing Engram Capture with a real browser (chrome-agent)

The extension fails **silently** when a selector dies: it captures nothing and
reports no error. Reading the code cannot tell you whether `.font-claude-response`
still exists on claude.ai today — only a live page can. `chrome-agent` drives a
real Chrome over the Chrome DevTools Protocol from the shell, which makes that
checkable, and repeatable.

    uv tool install chrome-agent      # needs Python >= 3.11, and Chrome/Chromium installed
    chrome-agent --help
    chrome-agent guide --path         # its own agent manual, ships with the package

## Where this can run

**Not on the EC2 box.** No Chrome in the AL2023 repos, host Python is 3.9, and —
the real blocker — every check below needs a browser **already logged in** to
claude.ai or chatgpt.com. Session cookies for those accounts should not live on a
server that hosts public websites. Run it on the machine you actually browse from.

## 1. Are the selectors still alive?

    chrome-agent launch               # log in and open a REAL conversation by hand
    chrome-agent status               # note the instance name
    ./audit-selectors.sh <instance>

Counts every selector group from `capture.js` in ONE `Runtime.evaluate` round
trip, and on failure prints the page's actual `data-testid`s and candidate class
names — i.e. the replacements — instead of just saying "no match". Exit 1 if any
group is broken, so it can gate CI or a cron.

Read the zeros carefully: a group only proves itself on a page that **contains
that thing**. Zero attachments on a chat with no attachments is not a failure,
and `isGenerating()` only matches **while a response is streaming**.

## 2. Does the extension actually do anything? (end-to-end)

Selectors matching is necessary, not sufficient. The extension's real job is to
POST a capture to the ingest endpoint. Prove that on a **different channel** than
the one you acted on.

**Read this before you conclude "no POST fired".** This is MV3: `capture.js` is a
content script running in the PAGE, but the `fetch()` to the ingest endpoint lives
in `background.js`, which the manifest declares as a **`service_worker`**. The
service worker is a **separate CDP target from the page**, so an `attach` to the
page target will never see the ingest request, and its absence there means
nothing. Getting this wrong produces a confident false negative — the exact trap
these tools exist to avoid.

    # load the extension under test into a fresh browser
    chrome-agent launch -- --load-extension=/path/to/browser-capture

    # PAGE target: the content script's own diagnostics
    chrome-agent attach <instance> +Runtime.consoleAPICalled > /tmp/engram-console.jsonl &

    # find the service-worker target, then watch ITS network
    chrome-agent <instance> Target.getTargets | grep -i service_worker
    chrome-agent attach <instance> --target <sw-target-id> +Network.requestWillBeSent \
      > /tmp/engram-ingest.jsonl &

    # act: browse a real conversation, then read both channels
    grep -a "engram-capture" /tmp/engram-console.jsonl   # did the content script see messages?
    grep -a "execute-api"    /tmp/engram-ingest.jsonl    # did the worker actually POST?

Note MV3 service workers **idle out** and restart on demand, so the worker target
may not exist until a capture is attempted — check again after browsing, rather
than concluding it is absent.

`capture.js` already prints `[engram-capture] DIAGNOSTIC data-testids: [...]`
when its selectors miss (capture.js:46-51, and :100 for attachments). Subscribing
to `Runtime.consoleAPICalled` turns that existing diagnostic into something a
script can read, with no changes to the extension.

## Why observe rather than assert

`Network.requestWillBeSent` firing at the ingest URL is the only evidence the
capture pipeline ran. The extension returning without an error is not evidence —
that is exactly how bugs 1 and 2 in mindspace 3090 hid. See mindspace 4456/4457
for the method and the tool, 4453 for why the deterministic checker is the point.
