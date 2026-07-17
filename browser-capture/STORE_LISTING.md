# Chrome Web Store listing — Engram Capture v0.1.7
Publish as **Unlisted** (link-only). Public adds review friction for zero benefit on a personal tool.

## Name
Engram Capture

## Summary (132 char max)
Auto-capture your Claude and ChatGPT conversations into your own self-hosted memory. You choose the endpoint; nothing is shared.

## Category / Language
Productivity / English (UK)

## Description
Engram Capture saves your AI conversations to a server you own.

Working with an AI assistant produces a lot of thinking that vanishes the moment the tab closes. Engram Capture quietly records conversations on claude.ai and ChatGPT and posts them to an HTTPS endpoint that YOU configure — your own server, your own database. There is no Engram cloud, no account, and no third party.

- Works on claude.ai, chatgpt.com and chat.openai.com
- You supply the endpoint and bearer token; the extension talks to nothing else
- Secrets (API keys, tokens) are stripped client-side before anything leaves the browser
- No analytics, no tracking, no ads

Requires your own HTTPS endpoint that accepts a JSON POST with a bearer token.

## Single purpose
Capture the user's own AI-assistant conversations and deliver them to a user-specified
self-hosted endpoint for personal archival and search.

## Permission justifications
- storage  — persists the user's own endpoint URL, bearer token, and per-site enable
             toggles. Local only (chrome.storage).
- alarms   — schedules a periodic flush so a capture is not lost if a tab is closed
             before an upload completes.
- host permissions (claude.ai, chatgpt.com, chat.openai.com) — the extension's entire
             purpose is reading conversation text on exactly these three AI-assistant
             sites. It requests no other hosts and injects no content elsewhere.

## Data usage disclosures (tick these)
Collects: "Website content" — YES. Conversation text the user is already viewing.
- [x] Not sold to third parties
- [x] Not used or transferred for purposes unrelated to the item's single purpose
- [x] Not used or transferred to determine creditworthiness / for lending
Data is transmitted ONLY to the endpoint the user configures. The developer operates no
collection server and receives nothing.

## Privacy policy URL
https://play4gain.com/engram-privacy.html   (must be live BEFORE submitting)
