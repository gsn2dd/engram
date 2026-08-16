"""
stop_reason handling at every Anthropic call site.

These pin a class of bug that produces no error and no crash: the API returns
HTTP 200 with a plausible but INCOMPLETE response, and code that reads
`.content` without asking why the model stopped treats the fragment as the
answer. Nothing downstream can tell the difference afterwards.

An audit on 2026-08-08 found only one of nine call sites across our codebases
handling truncation. These cover the two in engram that mattered most.

The Anthropic client is stubbed, so these cost nothing and make no API call.
They do set a DUMMY key, because the call sites read the environment variable
before they touch the client — see TestClassifyTruncation for what that cost.
"""
import os
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
    silently became 'thing' — a wrong classification presented as a decision.

    THE KEY MUST BE SET even though the client is stubbed. classify_noun reads
    os.environ["ANTHROPIC_API_KEY"] *before* it uses the client, so without one
    it raises KeyError and takes the same `except` branch as a failed call.
    That is not a hypothetical: this class had no key handling, and in CI (which
    has no secrets) all three tests took the exception path — reaching the
    heuristic through a KeyError rather than through anything they were written
    to test. One failed honestly and turned CI red; the other two passed for
    that wrong reason.

    Mutation testing then found the deeper version of the same problem, which
    the missing key had been hiding: even WITH a key, the truncation tests used
    fragments ("plac", "banana") that the NOUN_TYPES membership check rejects on
    its own. Delete the stop_reason guard entirely and they still pass. They
    were testing the vocabulary check and calling it truncation coverage. See
    test_a_truncated_but_VALID_looking_label_is_still_rejected for the case that
    actually distinguishes the two.
    """

    def setUp(self):
        self._saved = sys.modules.get("anthropic")
        self._saved_key = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "test-key-not-used"

    def tearDown(self):
        if self._saved is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._saved
        if self._saved_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = self._saved_key

    def test_a_truncated_but_VALID_looking_label_is_still_rejected(self):
        """The only version of this test that can actually fail.

        A fragment like "plac" is caught by the NOUN_TYPES membership check
        whether or not stop_reason is consulted, so a test built on one passes
        identically with the truncation guard removed — verified by mutation.
        It proves the vocabulary check works and says nothing about truncation.

        The case the guard exists for is a fragment that IS a valid label: the
        model begins "place holder is not..." and max_tokens cuts it to exactly
        "place". Membership sees a legitimate answer; only stop_reason knows the
        model was mid-sentence. Here the memory is plainly a project, so
        accepting the fragment yields "place" and consulting stop_reason yields
        the heuristic's "project".
        """
        from path_memory import classify
        _stub_anthropic("place", "max_tokens")
        got = classify.classify_noun(None, "engram",
                                     "The open-source memory engine codebase and its release process.")
        self.assertEqual(got, "project",
                         "a truncated answer must be discarded even when the fragment "
                         "happens to be a valid label")

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


class TestCompleteTextHelper(unittest.TestCase):
    """The shared gate every engram call site now goes through."""

    def test_truncation_and_refusal_and_pause_all_return_none(self):
        from path_memory.llm import complete_text
        for stop in ("max_tokens", "model_context_window_exceeded", "refusal", "pause_turn"):
            with self.subTest(stop=stop):
                self.assertIsNone(complete_text(_Msg("a fragment", stop), quiet=True),
                                  f"{stop} must never yield usable text")

    def test_a_clean_response_returns_its_text(self):
        from path_memory.llm import complete_text
        self.assertEqual(complete_text(_Msg("  the answer  ", "end_turn")), "the answer")

    def test_empty_text_is_none(self):
        from path_memory.llm import complete_text
        self.assertIsNone(complete_text(_Msg("   ", "end_turn")))

    def test_non_text_blocks_are_skipped_not_indexed(self):
        # content[0] is not guaranteed to be a text block. Blind indexing was
        # the other half of this bug class.
        from path_memory.llm import complete_text

        class _Thinking:
            type = "thinking"
            thinking = "pondering"

        msg = _Msg("the answer", "end_turn")
        msg.content = [_Thinking(), _Block("the answer")]
        self.assertEqual(complete_text(msg), "the answer")

    def test_missing_content_does_not_raise(self):
        from path_memory.llm import complete_text
        msg = _Msg("", "end_turn")
        msg.content = []
        self.assertIsNone(complete_text(msg))
