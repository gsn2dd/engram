# Agent server: what goes in the image

The single list of what a new owner's server contains (first owner: David's sister).
Decided with David on 2026-10-24 (mindspace 5239, 5243, 5248, 5251, 5258, 5259).
Build work for Clip Sender items lives in `/home/ec2-user/clips/TODO.md`; the image ships that code.

## Rules
- A distilled, clean image. NEVER a copy of play4gain-main: none of David's memories, projects,
  media, emails, keys or logins.
- Amazon Linux 2023 at its newest release at build time.
- Every item below is set up or offered by `start` on first login, as a guided step.

## Delivery
1. The owner sends their 12-digit AWS account ID.
2. The AMI is shared privately with that account (cross-account share; unencrypted snapshot or a shared KMS key).
3. They launch it with `cloudformation/engram.yaml`.
4. AWS Marketplace listing later, from the same image (seller registration and KYC take weeks).

## Prerequisites (tell the owner before they start)
- An AWS account (card + phone verification), with a budget alert set on day one.
- A region near them (eu-west-2 London or eu-west-1 Ireland).
- Their own Claude subscription (the assistant runs on it).
- An Android phone for Clip Sender (no iPhone app; iPhone/laptop use the browser send page).
- A Google account, if they want YouTube; `start` walks them through their own Google sign-in setup.

## Base
- [ ] Controller model: the home-folder chat acts for the owner; project folders are scoped (`start`).
- [ ] Morning routine: chats attach to projects by folder.
- [ ] Security watch + `update_server` + red login banner. Add: snapshot before update, roll back on failure (review item 5).
- [ ] Empty mindspace memory, private to the owner.

## Clip Sender + clips server (code only, no media)
- [ ] Clips server and the Clip Sender app; owner issues employee logins (roles + invite codes; QR = server address + one-time invite).
- [ ] ONE starting project: **Miscellaneous**.
- [ ] **Arrivals + triage**: everything sent lands in Arrivals; nothing goes to the video editor by default.
- [ ] **Functions drop-down by Execute**: employees see only the functions their role allows; the owner sees all, plus "Free instruction" and direct chat by voice note.
- [ ] Functions to ship:
  - [ ] YouTube maker (video editor + private upload; publishing only on the owner's say-so). Needs her own Google OAuth client.
  - [ ] Letters: photo of a letter, then summary, draft reply, approval, PDF, posting (UK: PC2Paper; France: La Poste) only on the owner's OK per letter.
  - [ ] Voice notes to memory.
  - [ ] Shop catalogue (optional: sell-your-stuff page with Guess the price / Make an offer).
- [ ] Browser send page, as Clip Sender's "send from a browser" option.
- [ ] Open: how the phone reaches the server safely (domain + TLS, or a tunnel), since the image opens no inbound ports.

## Access for the owner (David, 2026-10-24: "she needs a putty session to talk directly and the latest clip sender to send the data")
- [ ] **Direct terminal (PuTTY on Windows, Termius on a phone)** to talk to the assistant (`start`).
- [ ] **Latest Clip Sender APK**, paired to HER server (QR = server address + one-time invite), uploading to HER S3 bucket (created at launch, private, encrypted) via her clips server, as on David's box.
- CONFIRMED by David (2026-10-24): her laptop is **Windows** (PuTTY), her phone is **Android** (Clip Sender), and **Tailscale** is the way in.
- Way in: **Tailscale** (free personal plan), the private network David already uses for his phone. Her laptop and phone join her own tailnet; PuTTY and Clip Sender reach the server's private address. Port 22 and the clips API never face the internet, so the image keeps "no inbound ports", and one setup solves both the terminal and the Clip Sender reachability problem.
- Fallback with no install: **AWS Session Manager** terminal in the browser from the AWS console (works today with the CloudFormation template).
- Not recommended: opening port 22 to the internet, even with a key (her home IP changes; it invites scanning).
- `start` / prerequisites then add: install Tailscale on laptop + phone; PuTTY (Windows) and the SSH key it generates as a .ppk.

## Skills and tools
- [ ] AWS cost review and clean-up (aws-cost-review).
- [ ] Idle shrink: start-work / end-work, generalised to her instance.
- [ ] Safety guards: big-file scan guard, secret redaction, secrets only in SSM.
- [ ] Phone notification when a job finishes.
- [ ] Engram Capture browser extension (once it is in the Chrome Web Store).
- [ ] Optional: Pirate Games for family.

## From the October 2026 landscape review (docs/AGENT_LANDSCAPE_REVIEW_2026-10.md), not yet decided
- Chat with the assistant from the phone (owner only).
- Trust labels on memories (owner / agent / outside content).
- Scheduled jobs that wake the assistant only when needed.
- One "check my setup" command.

## Left out
WorldTownGuide pipeline, waiting-lists, voice-clone GPU stack, legal-case and bank material.
