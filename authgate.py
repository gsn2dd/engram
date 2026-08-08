"""
Bearer-token gate for the MCP endpoint.

The MCP server had no authentication of any kind: anything that could reach
port 8080 could read and write the entire brain. That was survivable only
because every deployment kept the port on loopback and reached it over an SSM
port-forward — and it made loopback a hard ceiling. A shared team brain, an
agent on another machine, any hosted version: all of it was blocked on this
module existing.

This is a plain ASGI wrapper around the SSE app rather than anything inside
the MCP framework, for two reasons:

  * It guards EVERY http path in one place. The SSE transport serves /sse and
    /messages/…; a gate bolted onto one handler quietly misses the other, and
    the next transport the framework adds would bypass it entirely.
  * It is stdlib-only and importable without the `mcp` package, so the auth
    logic is testable on any host — including this repo's own CI — without the
    server's dependency stack.

Same trust model as ingest_server.py: a bearer token is a password, so it gets
a constant-time comparison, and a plain-HTTP public interface would send it in
cleartext — TLS or a tunnel stays mandatory. Auth is the prerequisite for
binding beyond loopback, not a substitute for transport security.
"""
import hmac
import json


class BearerGate:
    """Reject any HTTP request whose Authorization header does not carry the
    expected bearer token. Non-HTTP scopes (lifespan) pass through untouched —
    refusing those would stop the server from even starting."""

    def __init__(self, app, token: str):
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        supplied = ""
        for name, value in scope.get("headers") or []:
            if name == b"authorization":
                header = value.decode("latin-1")
                if header.startswith("Bearer "):
                    supplied = header[len("Bearer "):].strip()
                break

        if not hmac.compare_digest(supplied, self.token):
            body = json.dumps({"error": "bad or missing bearer token"}).encode()
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode()),
                                    (b"www-authenticate", b"Bearer")]})
            await send({"type": "http.response.body", "body": body})
            return

        await self.app(scope, receive, send)
