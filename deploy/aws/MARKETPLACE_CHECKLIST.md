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
- [ ] Share the AMI with the AWS Marketplace scanning account before submitting

## 3. Security posture to state in the listing

Say this plainly rather than letting a customer discover it:

> The Engram MCP endpoint has no authentication of its own. It is bound to
> loopback and reached through an SSM port-forward or an SSH tunnel. Do not
> expose port 8080 to a network you do not control.

- [x] IMDSv2 required
- [x] EBS encrypted at rest
- [x] Least-privilege instance role — SSM core, plus read on this stack's own
      parameter path only
- [x] Security group has **no** inbound rules unless SSH is explicitly requested

## 4. Smoke test before submitting

Launch `cloudformation/engram.yaml` against a fresh build and confirm:

- [ ] `systemctl is-active engram` reports active within ~2 minutes of boot
- [ ] `/etc/engram/engram.env` exists, mode `0600`, and the password is **not**
      `pathpass`
- [ ] Two instances from the same AMI have **different** generated passwords —
      the single most important check here, and the easiest to get wrong
- [ ] The brain starts **empty** (no demo seed)
- [ ] SSM port-forward works, and `claude mcp add --transport sse engram
      http://localhost:8080/sse` connects and lists 6 tools
- [ ] `remember` then `recall` round-trips
- [ ] Reboot: the brain survives, and first-boot config is **not** regenerated
- [ ] `nmap` from another host in the VPC shows no open port

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
