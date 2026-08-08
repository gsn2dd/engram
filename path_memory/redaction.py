"""Shared secret scrubber for the collective mindspace ingest.

Server-side, stricter counterpart to the browser extension's redact.js (never trust
the client). Same canonical pattern set; run before anything is stored. Preserves a
type label ([REDACTED_OPENAI_KEY]) so later analysis knows what was removed without
retaining the secret. Bump REDACTION_VERSION when patterns change; it's stored per row.
"""
import re

REDACTION_VERSION = "rv1"

# (compiled_regex, replacement)
_PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"ssh-(?:rsa|ed25519|dss) [A-Za-z0-9+/=]{40,}"), "[REDACTED_SSH_KEY]"),
    # Order matters: sk-ant- must be tried before the generic sk- pattern, or
    # Anthropic keys get scrubbed under the OpenAI label. The secret is gone
    # either way, but the label is the only thing retained — so it has to be
    # right for anyone later asking "what kind of key leaked, and where from?"
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"), "[REDACTED_ANTHROPIC_KEY]"),
    (re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"), "[REDACTED_OPENAI_KEY]"),
    (re.compile(r"AIza[0-9A-Za-z_-]{30,}"), "[REDACTED_GOOGLE_KEY]"),          # Gemini/Google
    (re.compile(r"BSA[A-Za-z0-9_-]{20,}"), "[REDACTED_BRAVE_KEY]"),
    (re.compile(r"(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"), "[REDACTED_STRIPE_KEY]"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"A(?:KIA|SIA)[0-9A-Z]{16}"), "[REDACTED_AWS_KEY_ID]"),
    (re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"), "[REDACTED_SLACK_TOKEN]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"), "[REDACTED_JWT]"),
    # DB URLs with inline credentials: scheme://user:pass@host
    (re.compile(r"\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):([^\s:/@]+)@"), r"\1:[REDACTED_DB_PASSWORD]@"),
    # Signed-URL / query tokens
    (re.compile(r"([?&](?:X-Amz-Signature|signature|sig|token|access_token|api_key|key)=)[^&\s\"']+", re.I), r"\1[REDACTED]"),
    # AWS secret access keys (40-char base64-ish) after an obvious label
    (re.compile(r"(?i)(aws_?secret_?access_?key|secret_?access_?key)(\s*[:=]\s*)(['\"]?)([A-Za-z0-9/+=]{40})\3"), r"\1\2\3[REDACTED_AWS_SECRET]\3"),
    # Cookies / session ids
    (re.compile(r"(?i)(cookie|session[_-]?id|sessid|set-cookie)(\s*[:=]\s*)([^\s;,]{8,})"), r"\1\2[REDACTED]"),
    # Generic key/secret/password/token = value in env/JSON/YAML
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|bearer)\b(\s*[:=]\s*)(['\"]?)([^\s'\"]{6,})\3"), r"\1\2\3[REDACTED]\3"),
]


def scrub(text):
    """Return (scrubbed_text, redaction_version)."""
    out = str(text or "")
    # Postgres text cannot hold a NUL byte, and psycopg2 raises ValueError
    # rather than returning an error the caller can act on. Ingested content
    # comes from the wild — browser captures, transcripts, pasted files — so a
    # single stray NUL would otherwise abort the write with an exception that
    # says nothing about which memory caused it.
    out = out.replace("\x00", "")
    for rx, rep in _PATTERNS:
        out = rx.sub(rep, out)
    return out, REDACTION_VERSION


if __name__ == "__main__":
    sample = ("key sk-abcdefghijklmnopqrstuvwx here, AKIAIOSFODNN7EXAMPLE, "
              "postgres://u:hunter2@db:5432/x  password: hunter2  and AIzaSyA0123456789012345678901234567")
    s, v = scrub(sample)
    print(v, "->", s)
