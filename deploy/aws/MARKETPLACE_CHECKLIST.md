# AWS Marketplace listing checklist

Working notes for getting the Engram AMI listed. Two halves: the seller account
(paperwork, slow, do it first because it gates everything) and the AMI itself
(technical, fast, already largely handled by `provision.sh`).

## 1. Seller registration — start this early

The technical work is days; this half can take weeks, mostly waiting on
verification. Nothing can be submitted until it's done.

- [ ] AWS account in good standing, registered as a seller in the AWS
      Marketplace Management Portal
- [ ] Sign in to the portal with an **IAM role**, not root credentials — this is
      an explicit requirement, not a suggestion
- [ ] Tax form. Non-US seller ⇒ **W-8**, not W-9
- [ ] Bank account in an eligible jurisdiction that can receive **USD**
- [ ] **KYC** — required for selling to EMEA customers and for UK/EU bank
      accounts. This is the slowest step; expect to supply company documents
- [ ] Bank account verification completed

Free and BYOL listings still require most of the above once any payment
relationship exists. A genuinely free listing is the fastest route to being
*published*, which is the point of a first listing.

## 2. AMI policy compliance

Handled by `provision.sh` unless noted:

- [x] Supported, non-end-of-life OS — Amazon Linux 2023, resolved from the
      public SSM parameter at build time so it can't silently age out
- [x] `dnf -y update` at build time — the scan reports known vulnerabilities
- [x] **No password authentication** — explicitly set, not merely inherited
      from the base image's defaults
- [x] No baked-in credentials. The published container image carries a
      well-known Postgres password for laptop use; the AMI generates an
      instance-unique one on first boot instead
- [x] `authorized_keys`, shell history, SSH host keys and cloud-init state all
      removed before the snapshot
- [x] No service listening on a public interface — 8080 is loopback-only, 5432
      is never published
- [ ] Run the AMI scan and clear every finding. Budget for a second build:
      first-time scans usually surface something
- [ ] Share the AMI with the AWS Marketplace scanning account before
      submitting: launch permission on the AMI AND createVolumePermission on
      its snapshot, both to account 679593333241 — the AMI share alone is not
      enough for the scanner to read the disk

## 3. Security posture to state in the listing

Say this plainly rather than letting a customer discover it:

> The Engram MCP endpoint has no authentication of its own. It is bound to
> loopback and reached through an SSM port-forward or an SSH tunnel. Do not
> expose port 8080 to a network you do not control.

- [x] IMDSv2 required
- [x] Source AMI snapshot UNENCRYPTED — a Marketplace requirement, not an
      oversight. An encrypted snapshot (default KMS key) cannot be shared with
      the scanning account at all; the first build had this exactly backwards
      and the share silently could never have worked. Customers still get
      encryption at rest: the CloudFormation template encrypts the volume at
      LAUNCH, which is where it protects the customer's data rather than our
      empty image.
- [x] Least-privilege instance role — SSM core, plus read on this stack's own
      parameter path only
- [x] Security group has **no** inbound rules unless SSH is explicitly requested

## 4. Smoke test before submitting

`./smoke-test.sh` automates this — run it on the instance via Session Manager
(see the header of that file for the exact invocation).

**Verified 2026-08-07 on `ami-0721a41e97e07dabb`, 18/18 on two instances:**

- [x] `engram.service` active AND stable — restart count and container age are
      both checked. "Active" alone is not enough: an earlier run reported 13
      passes against a container restarting every 10 seconds
- [x] `/etc/engram/engram.env` exists, mode `0600`, password is **not** `pathpass`
- [x] Two instances have **different** credentials — the single most important
      check here. Instance A `fb2cf150…`/`5391bf7a…` vs B `ea6eee23…`/`fb4efa6b…`,
      all four distinct
- [x] The brain starts **empty** (no demo seed)
- [x] Postgres 5432 not publicly bound; 8080 and 8081 loopback-only
- [x] Ingest endpoint: health 200, no-token 401, instance-token 200
- [x] Reboot: brain survives, and the env-file hash is **unchanged** — first
      boot is genuinely idempotent, not just "seems to work"
- [x] No stale `authorized_keys`; password authentication disabled
- [ ] `nmap` from another host in the VPC shows no open port — not yet done
- [ ] `remember`/`recall` round-trip through MCP on a launched instance. The
      full ingest→embed→store chain was proven locally, but an instance needs a
      customer-supplied embedding key to do it, so it is untested on the AMI

## 4a. Known gaps to close before listing

- **No embedding key delivery.** `engram.env` ships empty `ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY` fields and the comment recommends SSM Parameter Store. The
  IAM role already grants read on `/engram/<stack>/*` — but nothing actually
  fetches from it. Today a customer must hand-edit the env file and restart.
  That is a poor first hour for a paid product.
- **No authentication on the MCP surface.** It is why 8080 must stay on
  loopback. `ingest_server.py` now has a working bearer-token pattern to copy.

## 5. Listing content

- [ ] Product title, short and long description
- [ ] Categories — Machine Learning, Developer Tools
- [ ] Pricing. Start free or BYOL: the first listing is for distribution and
      credibility, not revenue
- [ ] Support contact and a support policy
- [ ] EULA — the standard AWS Marketplace contract is fine; a custom EULA adds
      review time for no benefit here
- [ ] Usage instructions, leading with the port-forward (customers will
      otherwise hunt for an open port that deliberately isn't there)
- [ ] **Keep the honesty from the README.** The listing should say that the
      distinctive behaviour — memory that improves with use and forgets cleanly
      — is a bet still being tested. Marketplace listings attract scrutiny, and
      overclaiming is the fastest way to lose the credibility the listing exists
      to build.

## Notes

- Sellers are capped at 75 public AMI listings by default. Not a constraint
  here; noted so it isn't a surprise later.
- Self-service listing now supports AMI products with CloudFormation templates,
  so `cloudformation/engram.yaml` can be submitted as the launch experience
  rather than only as documentation.
