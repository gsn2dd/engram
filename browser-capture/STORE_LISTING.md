# Chrome Web Store listing — Engram Capture v0.2.0

Status (2026-10-24): **never submitted.** The publisher account (gsn2dd@gmail.com)
exists and its email was confirmed on 2026-07-17. There have been no review
emails because nothing has been uploaded yet. Everything below is ready. The
only steps left need David's Google login.

Upload file: `browser-capture/dist/engram-capture-0.2.0.zip` (build it with
`python3 tools/build_zip.py`; it packs only the 9 files the extension runs).

## Visibility: **Public**

The extension is part of the engram product on AWS Marketplace, and customers
of that listing cannot find an Unlisted extension. Public means a slower
review, and that is acceptable.

## What changed for v0.2.0 (the review-readiness pass)

- `optional_host_permissions` narrowed from `https://*/*` + `http://*/*` to
  `https://*/*` + `http://localhost/*` + `http://127.0.0.1/*`. Plain HTTP to
  any host on the internet was never needed. The AMI endpoint is
  `http://localhost:8081` through an SSM tunnel, and everything else is HTTPS.
  The options page rejects other `http://` endpoints with a clear message. The
  remaining `https://*/*` is optional and requested at runtime for one origin
  only, the endpoint the user types. It cannot be narrower, because each user
  runs their own server.
- No hardcoded `david` contributor default. Empty means the server falls back
  to its own default.
- `homepage_url` → the public GitHub repo.
- The privacy page now matches the code: settings are in `chrome.storage.sync`
  (they sync through the user's Google account), undelivered exchanges wait in
  `chrome.storage.local`, the extension does not read the page title, there are
  no per-site toggles, and localhost is allowed.
- Checked: no remote code, no `eval`/`new Function`, no remote scripts. Every
  requested permission is used: `storage` for settings and backlog, `alarms`
  for the 2-minute retry.

---

# Field values (paste these)

## Summary (manifest description, 132 max — set from the zip)
Auto-capture your claude.ai and ChatGPT conversations into your self-hosted engram memory.

## Description
```
Engram Capture saves your AI conversations to a server you own.

Working with an AI assistant produces a lot of thinking that vanishes the moment the tab closes. Engram Capture quietly records your conversations on claude.ai and ChatGPT and sends each finished exchange to an endpoint that YOU configure: your own server, your own database. There is no Engram cloud, no account, and no third party.

• Works on claude.ai, chatgpt.com and chat.openai.com
• You supply the endpoint and bearer token; the extension sends to nothing else
• Credential-shaped strings (API keys, tokens, private keys) are stripped in the browser before anything is sent
• Captures pasted / attached text too, with a switch to turn that off
• No analytics, no tracking, no ads

Pairs with Engram, the open-source memory server (github.com/gsn2dd/engram). Run it anywhere Docker runs, or launch it on AWS and point the extension at it. Requires your own endpoint that accepts a JSON POST with a bearer token: HTTPS, or http://localhost through a tunnel to your server.
```

## Category / Language
Productivity → Tools · English

## Single purpose
```
Capture the user's own conversations on claude.ai and ChatGPT and deliver them to an ingest endpoint the user configures on their own server, for personal archival and search.
```

## Permission justifications
**storage**
```
Stores the user's own settings (endpoint URL, bearer token, contributor name, on/off switches) and a queue of exchanges that could not yet be delivered to the user's endpoint.
```
**alarms**
```
A 2-minute alarm retries delivery of queued exchanges, so a capture is not lost when the user's server is briefly unreachable or the tab is closed mid-upload.
```
**Host permissions** (claude.ai, chatgpt.com, chat.openai.com + optional)
```
claude.ai, chatgpt.com and chat.openai.com: the extension's only purpose is reading the user's conversation text on these three sites; its content script runs nowhere else.
Optional https://*/*, http://localhost/*, http://127.0.0.1/*: never granted at install. When the user saves their endpoint URL on the options page, the extension calls chrome.permissions.request for that single origin only, so the background worker can POST to the user's own server. Each user runs their own server, so the origin cannot be known in advance. Plain http is limited to localhost for an SSH/SSM tunnel.
```

## Remote code
**No, I am not using remote code.**

## Data usage. Tick:
- [x] **Personal communications** (the chat text)
- [x] **Website content** (the conversation text on the page)
- [x] **Web history** (the URL and time of each captured conversation)

Leave the rest unticked. Then tick all three certifications:
- [x] I do not sell or transfer user data to third parties, outside of the approved use cases
- [x] I do not use or transfer user data for purposes that are unrelated to my item's single purpose
- [x] I do not use or transfer user data to determine creditworthiness or for lending purposes

(Data leaves the device only to the endpoint the user sets, so it counts as
"collected" under the store's definition. Ticking a category that turns out
not to apply does no harm. Leaving out one that does apply gets the
extension rejected.)

## Privacy policy URL
`https://www.play4gain.com/engram-privacy.html`. Use the `www` host: the
bare domain redirects to http. **The live page is the 7 August version.**
Copy the updated `browser-capture/privacy.html` over it before you submit, so
the policy matches v0.2.0. That step is not done yet (see the checklist).

## Test instructions for the reviewer
```
The extension needs a user-supplied endpoint. To test without one:
1. Open the extension's Options page.
2. Endpoint: https://httpbin.org/post   Token: test   Contributor: reviewer. Click Save and allow the permission prompt (for that one origin).
3. Click "Test connection": it shows "✓ Connected — HTTP 200".
4. Open any chat on claude.ai or chatgpt.com and send a message. When the answer finishes, the toolbar badge shows a green count. Tick "Debug" to see each captured exchange in the page console.
No account with us is needed; there is no developer server.
```

## Assets
- Store icon 128×128: `icons/icon128.png`
- Screenshot 1280×800: `store-assets/screenshot-1-options-1280x800.png`
- Small promo tile 440×280: `store-assets/promo-tile-440x280.png`
- Optional, and it would help: a second screenshot from a real Chrome showing
  the green badge after a capture.

---

# David: click by click

1. Go to **https://chrome.google.com/webstore/devconsole** and sign in as
   **gsn2dd@gmail.com**. The account needs 2-Step Verification turned on.
   Google will not let you publish without it.
2. **If it asks for the US$5 registration fee, pay it.** It is a one-off
   payment. If the dashboard opens straight to the item list, the fee is
   already paid.
3. **Account** (left menu): check that the contact email shows as verified.
   Answer the **trader / non-trader** question. Engram is sold on AWS
   Marketplace, so **trader** is the honest answer. A trader has to publish a
   contact address and phone number on the listing, so decide which ones you
   want shown.
4. **+ New item** → upload `engram-capture-0.2.0.zip`.
5. **Store listing** tab: paste the *Description* above. Category
   **Productivity → Tools**, language **English**. Upload the 128 icon, the
   1280×800 screenshot and the 440×280 small promo tile. Homepage URL:
   `https://github.com/gsn2dd/engram`. **Save draft.**
6. **Privacy** tab: paste the *Single purpose* text, then the three
   *Permission justifications* (storage, alarms, host permissions). Choose
   **"No, I am not using remote code"**. Tick the three data categories and
   the three certifications listed above. Paste the privacy policy URL.
   **Save draft.**
7. **Distribution** tab: **Free**. Visibility **Public**. Regions: **All
   regions**. **Save draft.**
8. **Test instructions** tab: paste the reviewer text above. **Save draft.**
9. Click **Submit for review**. When it asks, leave **"publish automatically
   after approval"** on.
10. Write down the **item ID**: the 32 letters in the item's dashboard URL.
    It is needed for the API setup below.

Review usually takes a few days. It can take longer, because the extension
reads page content on AI sites. If the review email asks a question, the
answer is: there is no developer server, the user supplies the destination,
and the source code is public.

## Once it is live
- Install it from the store, then **remove the unpacked copy**. The store
  copy has a different extension ID, so both would capture every message
  twice.
- The store copy starts with empty settings. Re-enter the endpoint and token.
  The token is in SSM `mindspace-ingest-token` (eu-west-1).

---

# Future versions without the dashboard: `tools/cws_publish.py`

```
python3 tools/cws_publish.py status     # read-only
python3 tools/cws_publish.py release    # build zip → upload → submit for review
```
Bump `version` in `manifest.json` first. The store refuses a version that is
not higher. Store-listing text and the privacy answers are still edited in the
dashboard. The API changes only the package.

## One-time OAuth setup (David, about 10 minutes)
1. In **console.cloud.google.com**, create a project (e.g. `chrome-webstore`)
   → **APIs & Services → Library** → enable **Chrome Web Store API**.
2. **OAuth consent screen**: User type **External**. App name e.g. "CWS
   publish". Add gsn2dd@gmail.com as a test user. Then click **Publish app**
   so the status reads **In production**. You do not need to submit it for
   verification. If you skip this step, the refresh token expires every 7 days.
3. **Credentials → Create credentials → OAuth client ID**: type **Web
   application**. Authorised redirect URI:
   `https://developers.google.com/oauthplayground`. Keep the client ID and
   secret.
4. Open **https://developers.google.com/oauthplayground** → gear icon → tick
   *Use your own OAuth credentials* → paste the ID and secret. In step 1,
   type the scope `https://www.googleapis.com/auth/chromewebstore` →
   **Authorize APIs** → sign in as gsn2dd@gmail.com (click through the
   "unverified app" warning) → **Exchange authorization code for tokens** →
   copy the **refresh token**.
5. Find the **publisher ID** under Dashboard → **Publisher → Settings**.
6. Put the values into SSM in eu-west-1. Run these on the box, not in a chat.
   That keeps the secrets out of transcripts.
   ```
   aws ssm put-parameter --region eu-west-1 --type SecureString --name /chrome-webstore/client_id     --value '...'
   aws ssm put-parameter --region eu-west-1 --type SecureString --name /chrome-webstore/client_secret --value '...'
   aws ssm put-parameter --region eu-west-1 --type SecureString --name /chrome-webstore/refresh_token --value '...'
   aws ssm put-parameter --region eu-west-1 --type String       --name /chrome-webstore/publisher_id  --value '...'
   aws ssm put-parameter --region eu-west-1 --type String       --name /chrome-webstore/engram-capture/item_id --value '<32-letter id>'
   ```
   Then `python3 tools/cws_publish.py status` should print the item's state.

---

# Keep it installed meanwhile (until the store version is live)

Chrome switches off or removes extensions that are not from the store when
they were installed by dragging in a `.crx`, or when their folder disappears.
An **unpacked** extension in a permanent folder stays:

1. Unzip `engram-capture-0.2.0.zip` into a folder that will not be cleaned
   up. For example `Documents\engram-capture` on Windows, or
   `~/Documents/engram-capture` on a Mac. **Not** Downloads, not a temp
   folder, not inside the zip.
2. Go to `chrome://extensions` → turn on **Developer mode** (top right) →
   **Load unpacked** → pick that folder.
3. Leave Developer mode on. If Chrome shows a "Disable developer mode
   extensions" bubble at startup, close it with the X. Do **not** click
   Disable.
4. Never move or delete that folder. Chrome drops the extension if the folder
   goes. To update, replace the files in place and press the reload ↻ icon
   on the extension's card.
