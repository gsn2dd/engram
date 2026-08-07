"""
Engram ingest endpoint — the surface the Engram Capture browser extension posts
conversations to.

Why this exists separately from the MCP server: MCP is how an *agent* attaches
to the brain. This is how a *browser* feeds it. The extension has always been
able to point at any HTTPS endpoint, but until now the only working endpoint was
a private API-Gateway → Lambda → S3 → cron chain in one AWS account. Anyone
running engram from the AMI had nothing to point at. This closes that.

It is also engram's first authenticated surface. The MCP server has no auth at
all, which is why it must stay on loopback; this one requires a bearer token, so
it is the piece that can eventually front a real interface.

Deliberately stdlib-only — no new dependency in the container for one small
endpoint.

    POST /
    Authorization: Bearer <ENGRAM_INGEST_TOKEN>
    {"exchange_id": "...", "prompt": "...", "answer": "...",
     "url": "https://claude.ai/chat/...", "title": "...", "contributor": "david"}

Runs only when ENGRAM_INGEST_TOKEN is set. No token, no listener — an
unauthenticated ingest surface must never appear by default.
"""

import hashlib
import hmac
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from path_memory.memory import Memory
from path_memory.db import get_conn

TOKEN = os.environ.get("ENGRAM_INGEST_TOKEN", "")
HOST = os.environ.get("ENGRAM_INGEST_HOST", "0.0.0.0")
PORT = int(os.environ.get("ENGRAM_INGEST_PORT", "8081"))
MAX_BODY = int(os.environ.get("ENGRAM_INGEST_MAX_BODY", str(512 * 1024)))
PROJECT = os.environ.get("ENGRAM_INGEST_PROJECT") or None

# Server-side secret scrub. The extension already redacts client-side, but this
# endpoint accepts posts from anywhere the token reaches, so it does not get to
# assume a well-behaved client. Structural pattern-matching is the right tool
# here — these are fixed credential shapes, not meaning.
_SCRUBS = [
    (re.compile(r"\b(sk-ant-[A-Za-z0-9_\-]{16,})"), "[REDACTED:anthropic-key]"),
    (re.compile(r"\b(sk-[A-Za-z0-9]{32,})"), "[REDACTED:openai-key]"),
    (re.compile(r"\b(AKIA[0-9A-Z]{16})\b"), "[REDACTED:aws-key-id]"),
    (re.compile(r"\b(ghp_[A-Za-z0-9]{20,})"), "[REDACTED:github-token]"),
    (re.compile(r"\b(AIza[0-9A-Za-z_\-]{20,})"), "[REDACTED:google-key]"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{20,}"), r"\1[REDACTED]"),
    (re.compile(r"-----BEGIN[^-]*PRIVATE KEY-----.*?-----END[^-]*PRIVATE KEY-----",
                re.DOTALL), "[REDACTED:private-key]"),
]


def scrub(text: str) -> str:
    for pattern, replacement in _SCRUBS:
        text = pattern.sub(replacement, text)
    return text


def claim_exchange(exchange_id: str) -> bool:
    """
    Atomically claim an exchange. True = it is ours to store; False = someone
    already has it.

    This must be a claim, not a lookup. The extension re-posts on retry and
    rescans pages, so the same exchange genuinely arrives twice — and a
    pre-flight SELECT loses that race every time, because the second request
    arrives while the first is still embedding and therefore sees nothing
    committed. Measured, not theorised: the first version of this file stored
    a duplicate on exactly that path.
    """
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO captures (exchange_id) VALUES (%s) "
            "ON CONFLICT (exchange_id) DO NOTHING RETURNING exchange_id",
            (exchange_id,),
        )
        claimed = cur.fetchone() is not None
        conn.commit()
        return claimed
    finally:
        conn.close()


def release_claim(exchange_id: str) -> None:
    """Give the id back after a failed save, so the extension's retry can win it."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM captures WHERE exchange_id = %s", (exchange_id,))
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"[ingest] could not release claim {exchange_id}: {exc}",
              file=sys.stderr, flush=True)


def store_exchange(exchange_id, subject, body, contributor, url, title):
    """
    The slow half: embed and save. Runs off the request thread.

    Embedding a capture costs several provider round-trips (the perspective
    fan-out indexes each memory from multiple angles), which overruns a
    browser's patience. The extension keeps its own backlog and re-posts, so
    the honest contract is "accepted", not "stored".
    """
    try:
        memory_id = Memory.save(
            subject=subject,
            body=body,
            person=contributor,
            origin="discovery",
            project=PROJECT,
            source_links=[{"url": url, "title": title, "exchange_id": exchange_id}],
        )
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE captures SET memory_id = %s WHERE exchange_id = %s",
                    (memory_id, exchange_id))
        conn.commit()
        conn.close()
        print(f"[ingest] stored exchange {exchange_id} as memory {memory_id}",
              file=sys.stderr, flush=True)
    except Exception as exc:
        print(f"[ingest] save failed for {exchange_id}: {exc}", file=sys.stderr, flush=True)
        release_claim(exchange_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "engram-ingest/1.0"

    def _reply(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _authorised(self) -> bool:
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        # Constant-time: a timing oracle on the ingest token is a cheap thing to
        # avoid and an annoying thing to explain later.
        return hmac.compare_digest(header[len(prefix):].strip(), TOKEN)

    def do_OPTIONS(self):
        self._reply(204, {})

    def do_GET(self):
        # Health only. Says nothing about the brain to an unauthenticated caller.
        if self.path.rstrip("/") in ("", "/health"):
            self._reply(200, {"ok": True, "service": "engram-ingest"})
        else:
            self._reply(404, {"error": "not found"})

    def do_POST(self):
        if not self._authorised():
            self._reply(401, {"error": "bad or missing bearer token"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._reply(400, {"error": "bad content-length"})
            return
        if length <= 0 or length > MAX_BODY:
            self._reply(413, {"error": f"body must be 1..{MAX_BODY} bytes"})
            return

        try:
            payload = json.loads(self.rfile.read(length))
        except Exception:
            self._reply(400, {"error": "body is not valid JSON"})
            return

        # An empty POST is how the extension's "Test" button checks its config,
        # so it must succeed without writing anything.
        prompt = (payload.get("prompt") or "").strip()
        answer = (payload.get("answer") or "").strip()
        if not prompt and not answer:
            self._reply(200, {"ok": True, "stored": False, "note": "empty payload accepted"})
            return

        url = (payload.get("url") or "").strip()
        title = (payload.get("title") or "").strip()
        contributor = (payload.get("contributor") or "capture").strip()

        exchange_id = (payload.get("exchange_id") or "").strip()
        if not exchange_id:
            exchange_id = hashlib.sha256(f"{url}|{prompt}|{answer}".encode()).hexdigest()[:32]

        try:
            if not claim_exchange(exchange_id):
                self._reply(200, {"ok": True, "stored": False, "note": "already captured"})
                return

            subject = title or (prompt[:70] + ("…" if len(prompt) > 70 else "")) or "captured exchange"
            body = f"Q: {scrub(prompt)}\n\nA: {scrub(answer)}"

            threading.Thread(
                target=store_exchange,
                args=(exchange_id, scrub(subject), body, contributor, url, title),
                daemon=True,
            ).start()
            self._reply(202, {"ok": True, "accepted": True, "exchange_id": exchange_id})
        except Exception as exc:
            # Never leak internals to the caller; the operator gets the detail.
            print(f"[ingest] accept failed: {exc}", file=sys.stderr, flush=True)
            self._reply(500, {"error": "could not accept the exchange"})

    def log_message(self, fmt, *args):
        # Default logging writes the full request line, which for this service
        # would put conversation-bearing URLs in the container log.
        print(f"[ingest] {self.command} {self.address_string()} {fmt % args}",
              file=sys.stderr, flush=True)


def main():
    if not TOKEN:
        print("[ingest] ENGRAM_INGEST_TOKEN is not set — ingest endpoint disabled",
              file=sys.stderr, flush=True)
        return
    if len(TOKEN) < 24:
        print("[ingest] refusing to start: ENGRAM_INGEST_TOKEN is shorter than 24 chars",
              file=sys.stderr, flush=True)
        sys.exit(1)

    print(f"[ingest] listening on {HOST}:{PORT}", file=sys.stderr, flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
