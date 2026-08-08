"""
Tests for the MCP bearer gate.

These drive the ASGI interface directly — no server, no sockets, no `mcp`
package — so the auth logic is provable on any machine including keyless CI.
The end-to-end path (uvicorn + FastMCP behind the gate) is exercised by the
container smoke test at image-build time.
"""
import asyncio
import unittest

from authgate import BearerGate

TOKEN = "a-perfectly-reasonable-test-token"


def _run(scope, token=TOKEN):
    """Push one request through the gate; return (status, reached_app)."""
    state = {"status": None, "reached_app": False}

    async def inner_app(scope, receive, send):
        state["reached_app"] = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            state["status"] = message["status"]

    asyncio.run(BearerGate(inner_app, token)(scope, receive, send))
    return state["status"], state["reached_app"]


def _http_scope(headers):
    return {"type": "http", "method": "GET", "path": "/sse", "headers": headers}


class TestBearerGate(unittest.TestCase):
    def test_no_header_is_rejected(self):
        status, reached = _run(_http_scope([]))
        self.assertEqual(status, 401)
        self.assertFalse(reached, "an unauthenticated request must never reach the app")

    def test_wrong_token_is_rejected(self):
        status, reached = _run(_http_scope([(b"authorization", b"Bearer wrong-token-entirely-x")]))
        self.assertEqual(status, 401)
        self.assertFalse(reached)

    def test_wrong_scheme_is_rejected(self):
        # Basic auth carrying the right secret is still not bearer auth.
        status, reached = _run(_http_scope([(b"authorization", b"Basic " + TOKEN.encode())]))
        self.assertEqual(status, 401)
        self.assertFalse(reached)

    def test_correct_token_passes_through(self):
        status, reached = _run(
            _http_scope([(b"authorization", b"Bearer " + TOKEN.encode())]))
        self.assertEqual(status, 200)
        self.assertTrue(reached)

    def test_correct_token_survives_other_headers_and_case(self):
        # ASGI lower-cases header names, but order and neighbours vary by client.
        status, reached = _run(_http_scope([
            (b"accept", b"text/event-stream"),
            (b"authorization", b"Bearer " + TOKEN.encode()),
            (b"user-agent", b"some-mcp-client/1.0"),
        ]))
        self.assertEqual(status, 200)
        self.assertTrue(reached)

    def test_lifespan_scope_passes_without_auth(self):
        # Refusing the lifespan scope would stop the server from even starting;
        # only HTTP requests carry credentials.
        reached = {"v": False}

        async def inner_app(scope, receive, send):
            reached["v"] = True

        asyncio.run(BearerGate(inner_app, TOKEN)({"type": "lifespan"}, None, None))
        self.assertTrue(reached["v"])


if __name__ == "__main__":
    unittest.main()
