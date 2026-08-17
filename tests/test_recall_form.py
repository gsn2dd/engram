"""
The recall form — lossless at rest, lossy on the way out.

Guarding the two properties that make it safe: retrieval is untouched (the
embedding is still the full body), and the injected text is actually shorter
than what it replaces. The second is not automatic — asked for 400 characters,
the model averaged 768 on real memories, which would have made this feature
COST context instead of saving it.
"""
import unittest

from path_memory.recall_form import _trim, preview, TARGET_CHARS


class TestTrim(unittest.TestCase):

    def test_short_text_is_untouched(self):
        self.assertEqual(_trim("Already brief.", 400), "Already brief.")

    def test_long_text_is_cut_to_a_sentence_boundary(self):
        text = ("First sentence carries the conclusion. " * 30).strip()
        out = _trim(text, 200)
        self.assertLessEqual(len(out), 200)
        self.assertTrue(out.endswith("."), "must not end mid-sentence")

    def test_a_limit_in_a_prompt_is_not_a_limit(self):
        """The model overshot 400 by ~2x on real data. Enforcement is code."""
        self.assertLessEqual(len(_trim("x" * 5000, TARGET_CHARS)), TARGET_CHARS + 1)

    def test_unbreakable_text_still_respects_the_cap(self):
        out = _trim("nosentenceboundaryanywhere" * 100, 120)
        self.assertLessEqual(len(out), 121)


class TestPreview(unittest.TestCase):

    def test_the_form_is_used_when_present(self):
        row = {"recall_form": "The conclusion, with the numbers.", "body": "x" * 5000}
        self.assertEqual(preview(row), "The conclusion, with the numbers.")

    def test_falls_back_to_truncation_when_absent(self):
        """Permanent fallback: a brain with no model key, or one whose backfill
        has not reached a memory, must still show something readable."""
        row = {"recall_form": None, "body": "y" * 500}
        out = preview(row, chars=220)
        self.assertTrue(out.startswith("y"))
        self.assertTrue(out.endswith("..."))
        self.assertEqual(len(out), 223)

    def test_blank_form_is_treated_as_absent(self):
        row = {"recall_form": "   ", "body": "body text here"}
        self.assertEqual(preview(row), "body text here")


if __name__ == "__main__":
    unittest.main()
