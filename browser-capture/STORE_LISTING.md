# Chrome Web Store listing — Engram Capture v0.1.9

## Visibility — decide before submitting

The previous draft said **Unlisted**, with the reasoning "public adds review
friction for zero benefit on a personal tool". That reasoning has expired: the
extension is now part of a product going to AWS Marketplace, and an unlisted
extension cannot be found by the customers that listing creates.

**Recommendation: Public.** Accept the slower review. An AMI whose capture
extension can only be installed from a secret link is a worse product than one
whose extension is in the store. Keep Unlisted only if the Marketplace listing
is being shelved.

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

Pairs with Engram, the open-source memory brain — run it anywhere Docker runs,
or launch it on AWS and point the extension at it. Requires your own endpoint
that accepts a JSON POST with a bearer token.

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
- optional host permissions — requested at runtime for the one endpoint origin the
             user types in, so the extension may POST to it. Never pre-granted.

## Data usage disclosures (tick these)
Collects: "Website content" — YES. Conversation text the user is already viewing.
- [x] Not sold to third parties
- [x] Not used or transferred for purposes unrelated to the item's single purpose
- [x] Not used or transferred to determine creditworthiness / for lending
Data is transmitted ONLY to the endpoint the user configures. The developer operates no
collection server and receives nothing.

## Privacy policy URL
https://www.play4gain.com/engram-privacy.html — **LIVE** (published 2026-08-07,
source of truth is `browser-capture/privacy.html` in this repo).

Use the `www` host. The apex `play4gain.com` 301-redirects to `http://www.` —
an HTTPS-to-HTTP downgrade that is worth fixing in the Apache config, but the
`www` URL serves HTTPS correctly today.

---

# Submission checklist

## 1. Developer account — do this first
- [ ] Register at the Chrome Web Store Developer Dashboard (**one-off US$5 fee**)
- [ ] Verify the publisher email
- [ ] Decide the publisher identity: personal name or a trading name. It is shown
      on the listing and is awkward to change later

## 2. Assets
- [x] **Screenshot** — `store-assets/screenshot-1-options-1280x800.png`. The real
      options page rendered headlessly, showing the AMI's default configuration
      (loopback endpoint through the SSM tunnel) with a placeholder token.
- [x] **Small promo tile** — `store-assets/promo-tile-440x280.png`
- [x] Store icon 128×128 — `icons/icon128.png`
- [ ] **Optional but better:** a second screenshot taken in a real Chrome with
      the extension installed and a capture actually landing. A genuine in-use
      shot is more persuasive to a reviewer than a rendered options page, and
      it is a two-minute job on a machine with the extension loaded.

## 3. Pre-submit verification
- [x] Privacy policy live and reachable over HTTPS
- [x] `manifest.json` version matches this document (0.1.9)
- [ ] Load unpacked in a clean Chrome profile and confirm: options save, Test
      button returns OK against a real endpoint, a capture lands
- [ ] Confirm nothing in the zip but extension files — no `.git`, no notes,
      no keys
- [ ] Re-read the permission justifications against the shipped manifest. A
      mismatch between what is requested and what is justified is the most
      common rejection

## 4. Expect a review round
Extensions that read page content on AI sites and post it off-box attract
scrutiny. The defence is already true and should be stated plainly: there is no
developer-operated server, the destination is user-supplied, and the source is
public at github.com/gsn2dd/engram.
