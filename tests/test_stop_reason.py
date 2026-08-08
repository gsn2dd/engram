"""
stop_reason handling at every Anthropic call site.

These pin a class of bug that produces no error and no crash: the API returns
HTTP 200 with a plausible but INCOMPLETE response, and code that reads
`.content` without asking why the model stopped treats the fragment as the
answer. Nothing downstream can tell the difference afterwards.

An audit on 2026-08-08 found only one of nine call sites across our codebases
handling truncation. These cover the two in engram that mattered most.

The Anthropic client is stubbed, so these cost nothing and need no API key.
"""
import sys
import types
import unittest


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Msg:
    def __init__(self, text, stop_reason):
        self.content = [_Block(text)]
        self.stop_reason = stop_reason


def _stub_anthropic(text, stop_reason):
    """Install a fake `anthropic` module whose messages.create returns a
    response with the given stop_reason. Both call sites import it inside the
    function, so replacing sys.modules is enough."""
    class _Messages:
        def create(self, **kwargs):
            return _Msg(text, stop_reason)

    class _Client:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    module = types.ModuleType("anthropic")
    module.Anthropic = _Client
    sys.modules["anthropic"] = module


class TestPerspectiveTruncation(unittest.TestCase):
    """A lens is a SEARCH HANDLE — it gets embedded and matched against future
    queries. A truncated one is worse than none: the memory keeps its literal
    embedding either way, but a mangled handle actively misdirects recall."""

    def setUp(self):
        self._saved = sys.modules.get("anthropic")

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._saved

    def test_a_truncated_lens_is_discarded(self):
        import os
        os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
        from path_memory import perspectives
        _stub_anthropic("The memory is really about the ten", "max_tokens")
        self.assertIsNone(
            perspectives._generate("lens", None, "subject", "body"),
            "a lens cut off at max_tokens must not be stored as a complete handle")

    def test_a_refused_lens_is_discarded(self):
        import os
        os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
        from path_memory import perspectives
        _stub_anthropic("", "refusal")
        self.assertIsNone(perspectives._generate("lens", None, "subject", "body"))

    def test_a_complete_lens_is_returned(self):
        import os
        os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
        from path_memory import perspectives
        _stub_anthropic("A complete lens.", "end_turn")
        self.assertEqual(perspectives._generate("lens", None, "subject", "body"),
                         "A complete lens.")


class TestClassifyTruncation(unittest.TestCase):
    """max_tokens=5 on a one-word answer makes truncation a live possibility,
    and the old code hid it: 'project' cut short failed the membership test and
    silently became 'thing' — a wrong classification presented as a decision."""

    def setUp(self):
        self._saved = sys.modules.get("anthropic")

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._saved

    def test_truncation_falls_back_to_the_heuristic_not_to_thing(self):
        from path_memory import classify
        # A place-flavoured memory, with the model's answer cut short.
        _stub_anthropic("plac", "max_tokens")
        got = classify.classify_noun(None, "The town of Banbury",
                                     "Notes about the town and its river and streets.")
        self.assertEqual(got, "place",
                         "a truncated label must fall back to the heuristic, not silently to 'thing'")

    def test_an_unrecognised_label_also_falls_back(self):
        from path_memory import classify
        _stub_anthropic("banana", "end_turn")
        got = classify.classify_noun(None, "The city of Hoi An",
                                     "Notes about the city, its river and streets.")
        self.assertEqual(got, "place",
                         "an off-vocabulary answer must go to the heuristic, not to 'thing'")

    def test_a_valid_label_is_used(self):
        from path_memory import classify
        _stub_anthropic("project", "end_turn")
        self.assertEqual(classify.classify_noun(None, "engram", "The memory engine."),
                         "project")


if __name__ == "__main__":
    unittest.main()
