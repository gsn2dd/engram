# Base AMI build log

## 2026-10-24 — engram-agent-base-al2023-20261024T131234Z

| | |
|---|---|
| AMI | `ami-07e176550ed67b4b9` (eu-west-1, **private**, not shared) |
| Name | `engram-agent-base-al2023-20261024T131234Z` |
| Created | 2026-10-24T13:15:08Z |
| Arch / root | x86_64, 20 GiB gp3, `snap-0ed8d900a35b888e3` (unencrypted, so it can later be shared) |
| OS release | Amazon Linux **2023.12.20261021** (the newest release at test time) |
| Container | `ghcr.io/gsn2dd/engram:latest` |
| Built from | branch `base-ami-2026-10`, with the uncommitted `provision.sh` change (`dnf upgrade --releasever=latest` + `dnf-utils`) |

The build finished, but the worker hit its usage limit partway through the smoke
test. The smoke test below was run again from scratch on 2026-10-24 15:12 UTC.
The AMI was not rebuilt.

### Smoke test: `run-smoke-test.sh ami-07e176550ed67b4b9`

The test instance was `i-0b4c61bc8ff235051` (t3.small, SSM-only `engram-smoketest`
profile, IMDSv2 required). It launched at 15:12:26Z, the test ran at 15:13:35Z, and
the instance was terminated by the script's EXIT trap.

**Result: 38 passed, 0 failed.**

The checks MARKETPLACE_CHECKLIST.md asks for:

| Check | Result |
|---|---|
| No password authentication (drop-in **and** effective `sshd -T`) | PASS |
| `permitrootlogin no` (effective config) | PASS |
| No baked keys: no stale `authorized_keys`, no root `authorized_keys`, no private-key / `AKIA` / `sk-ant-` content in /root, /home, /etc/engram, /usr/local/bin | PASS |
| Nothing listening beyond loopback except sshd:22; 8080/8081 loopback-only; 5432 not published | PASS |
| Security watch on the newest release: 0 critical, 0 important, no reboot pending ("SERVER SECURITY: up to date") | PASS |
| `engram-start` present (also `update_server`, `engram-security-watch`, README.txt in ec2-user's home, watch timer enabled) | PASS |

Other checks: firstboot completed. The service was stable (0 restarts, container up
65s). engram.env was mode 600, with a 32-char DB password (not `pathpass`) and a
48-char ingest token and MCP token. Ingest health returned 200, and the ingest
endpoint gave 401 without a token and 200 with one. MCP gave 401 with no token and
with a wrong token, and 200 with the instance token. Claude Code installed (2.1.197)
with `engram` registered as an MCP server and the agent prompt seeded. The brain
started empty.

Fingerprints from this instance (compare when you launch a second one):
password `9caade5f47a4e7ed`, ingest token `88a61f7f1e59fc57`, MCP token `659d63a6ea288961`.

Not covered (by hand, still open): reboot persistence, a second instance with
different fingerprints, an nmap scan from another host in the VPC.

### Clean-up check (15:17 UTC)

- `i-0b4c61bc8ff235051`: **terminated** (confirmed with `ec2 wait instance-terminated`).
- Instances tagged `engram:role=smoke-test` / `Name=engram-smoketest`: only that one, terminated.
- Instances launched on 2026-10-24: only that one, terminated.
- The only non-terminated instances in the account/region are `play4gain-main`
  (running) and `flutter-dev` (stopped). Both existed before the test and were not touched.
- No unattached EBS volumes.

### Cost estimate

- Smoke test: t3.small for about 5 min ≈ $0.002, plus 20 GiB gp3 for about 5 min ≈ $0.0001. **Under 1 cent.**
- Build instance earlier today (similar size, about 15–20 min): **a few cents**.
- Keeping the AMI: EBS snapshot storage at $0.05/GB-month, billed on used blocks.
  The worst case is the full 20 GiB = **$1.00/month**, and it is likely about $0.15–0.30/month.
