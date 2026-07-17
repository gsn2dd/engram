# Engram Capture (browser extension)

Auto-captures your **claude.ai** and **ChatGPT** conversations into your self-hosted
[engram](../) memory, so the ideas you work out in the browser become part of the same
recallable, cross-agent history as everything else — and you can look back to find
*when* something changed or *where* a bug started.

Manifest V3, Chrome/Edge/Brave. Nothing leaves the browser except a POST to the ingest
endpoint **you** configure (your server). Secrets are redacted in-browser first.

## Install (unpacked, for now)
1. `chrome://extensions` → enable **Developer mode** → **Load unpacked** → pick this folder.
2. Click the extension → **Options**: set your **ingest endpoint URL**, a **bearer token**,
   your **contributor id** (e.g. `david`), tick **Capturing enabled**. Approve the endpoint
   permission prompt.
3. Open a claude.ai / ChatGPT chat. Finished exchanges post to your endpoint. Tick **Debug**
   to log exactly what it captured to the page console.

## What it sends
One POST per finished exchange (`Authorization: Bearer <token>`):
```json
{
  "contributor": "david",
  "tier": "transcript",
  "source": "claude.ai",            // or "chatgpt.com"
  "conversation_id": "…",
  "url": "https://claude.ai/chat/…",
  "captured_at": "2026-07-14T13:40:00Z",
  "prompt": "<user text, secrets redacted>",
  "answer": "<assistant text, secrets redacted>"
}
```

## The ingest endpoint (server side — the other half)
A small authenticated HTTP endpoint that: checks the bearer token → scrubs secrets again →
resolves any in-repo code to a **GitHub permalink** (`owner/repo@sha/path#Lx-Ly`) instead of
inlining it → embeds (Gemini) → `remember(...)` into engram with `tier=transcript`,
`contributor`, `source`, `url`, and the **original `captured_at` timestamp**. Recall keeps
`tier=transcript` out of default results (opt in with `--full`) so the firehose never dilutes
curated memory. Contract is above; see `../../worldtownguide/docs/TRANSCRIPT_ARCHIVE_DESIGN.md`.

## Tuning the DOM extraction
`capture.js` has one `EXTRACTORS` map — the only thing you should need to edit. claude.ai and
ChatGPT change their markup often; if capture goes quiet, turn on Debug, check the console, and
update the selectors for that host. ChatGPT uses `data-message-author-role` (stable-ish);
claude.ai needs the `data-testid` / class fallbacks tuned against the live page.

## Privacy
Your conversations go only to your endpoint. In-browser redaction covers common key/token
shapes, but treat the store as sensitive and keep the endpoint token secret.
