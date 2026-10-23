"""create_message() falls back to the Claude Code CLI only on billing errors."""
import json
import types

import pytest

from path_memory import llm


class _Client:
    def __init__(self, exc=None):
        self.calls = 0
        self.exc = exc
        self.messages = types.SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls += 1
        if self.exc:
            raise self.exc
        return "api-response"


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "_api_out_of_credit", False)
    monkeypatch.setattr(llm, "_CAP_FILE", str(tmp_path / "calls.json"))
    monkeypatch.setattr(llm, "_cli_exe", lambda: "/bin/claude")
    seen = {}

    def fake_run(cmd, input, **kw):
        seen["cmd"], seen["input"] = cmd, input
        out = {"is_error": False, "result": "fallback text"}
        if "--json-schema" in cmd:
            out["structured_output"] = {"name": "x"}
        return types.SimpleNamespace(stdout=json.dumps(out), stderr="")

    monkeypatch.setattr(llm._subprocess, "run", fake_run)
    return seen


KW = dict(model="claude-haiku-4-5", max_tokens=10,
          messages=[{"role": "user", "content": "hi"}])


def test_api_used_when_it_works(_fresh):
    assert llm.create_message(_Client(), **KW) == "api-response"
    assert "cmd" not in _fresh


def test_billing_error_falls_back_and_sticks(_fresh):
    client = _Client(Exception("Your credit balance is too low to access the Anthropic API"))
    msg = llm.create_message(client, **KW)
    assert llm.complete_text(msg) == "fallback text"
    assert "--setting-sources" in _fresh["cmd"] and _fresh["input"] == "hi"
    llm.create_message(client, **KW)
    assert client.calls == 1          # API not retried once out of credit


def test_other_errors_are_not_swallowed():
    with pytest.raises(ValueError):
        llm.create_message(_Client(ValueError("bad request")), **KW)


def test_structured_output_passes_schema(_fresh):
    llm._api_out_of_credit = True
    msg = llm.create_message(None, output_config={"format": {"schema": {"type": "object"}}}, **KW)
    assert json.loads(llm.complete_text(msg)) == {"name": "x"}


def test_daily_cap(monkeypatch):
    llm._api_out_of_credit = True
    monkeypatch.setenv("ENGRAM_CLI_DAILY_CAP", "1")
    llm.create_message(None, **KW)
    with pytest.raises(RuntimeError, match="daily cap"):
        llm.create_message(None, **KW)
