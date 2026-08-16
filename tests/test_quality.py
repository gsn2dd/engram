"""
Write-time warnings — advisory, never blocking.

The case that motivated all of this: 1,899 of 2,719 curated memories on a real
brain were `L2 <file> :: <function> :: <date>` records, one subject template
differing only by date. Asked for one by its exact subject, recall returned a
sibling first. These tests pin the behaviour that would have said so at memory
number two.
"""
import os
import unittest

HAVE_DB = bool(os.environ.get("DB_NAME"))


@unittest.skipUnless(HAVE_DB, "needs a database")
class TestQualityWarnings(unittest.TestCase):

    def setUp(self):
        from path_memory.db import get_conn
        self.conn = get_conn()
        self.made = []
        # memories.project is a foreign key into the project registry, so a
        # test that writes a project must register it first — the same rule
        # Memory.save follows.
        cur = self.conn.cursor()
        cur.execute("INSERT INTO projects (slug) VALUES ('qtest') "
                    "ON CONFLICT DO NOTHING")
        self.conn.commit()
        cur.close()

    def tearDown(self):
        cur = self.conn.cursor()
        if self.made:
            cur.execute("DELETE FROM memories WHERE id = ANY(%s)", (self.made,))
        self.conn.commit()
        cur.close()
        self.conn.close()

    def _add(self, subject, body="a body long enough to be ordinary", project="qtest",
             vec=None):
        cur = self.conn.cursor()
        if vec is None:
            cur.execute("""INSERT INTO memories (subject, body, project, tier)
                           VALUES (%s, %s, %s, 'curated') RETURNING id""",
                        (subject, body, project))
        else:
            cur.execute("""INSERT INTO memories (subject, body, project, tier, embedding)
                           VALUES (%s, %s, %s, 'curated', %s::vector) RETURNING id""",
                        (subject, body, project, vec))
        mid = cur.fetchone()[0]
        self.conn.commit()
        cur.close()
        self.made.append(mid)
        return mid

    def _codes(self, mid):
        from path_memory import quality
        return {w["code"] for w in quality.inspect(self.conn, mid)}

    def test_templated_subject_is_flagged(self):
        """Digits carry the variation, so they are normalised before comparing.
        Without that every date-stamped sibling looks unique and the check that
        exists for exactly this case never fires."""
        for day in range(1, 9):
            self._add(f"L2 tools/widget_builder.py :: [AUTO-DIFF] :: 2026-07-0{day}")
        last = self._add("L2 tools/widget_builder.py :: [AUTO-DIFF] :: 2026-07-09")
        self.assertIn("templated_subject", self._codes(last))

    def test_a_distinctive_subject_is_not_flagged(self):
        """The warning must stay quiet on ordinary writes. One that fires on
        good input is one people learn to ignore."""
        mid = self._add("Banbury hub went live after the anchor-order fix")
        self.assertNotIn("templated_subject", self._codes(mid))

    def test_missing_project_is_flagged(self):
        mid = self._add("A perfectly reasonable and distinctive subject line",
                        project=None)
        self.assertIn("no_project", self._codes(mid))

    def test_path_like_subject_is_flagged(self):
        """Observed on the real corpus: a captured memory whose subject was a
        bare gs:// URL. Nobody asks a question shaped like that."""
        mid = self._add("gs://some-bucket/reports/street_hustle/")
        self.assertIn("weak_subject", self._codes(mid))

    def test_long_body_is_flagged(self):
        mid = self._add("A distinctive subject about one specific thing", "x" * 2500)
        self.assertIn("long_body", self._codes(mid))

    def test_inspect_never_raises_on_a_missing_memory(self):
        from path_memory import quality
        self.assertEqual(quality.inspect(self.conn, 999999999), [])

    def test_warnings_do_not_block_the_write(self):
        """The whole contract. A memory that triggers every warning is still
        stored, and still has its id."""
        mid = self._add("gs://x/y/", "x" * 3000, project=None)
        self.assertTrue(len(self._codes(mid)) >= 3)
        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM memories WHERE id = %s", (mid,))
        self.assertEqual(cur.fetchone()[0], 1)
        cur.close()


class TestNormalisation(unittest.TestCase):
    """No database needed — the normalisation is the part with the logic in it."""

    def test_digits_collapse_so_dated_siblings_match(self):
        from path_memory.quality import _norm_prefix
        a = _norm_prefix("L2 tools/build.py :: [AUTO-DIFF] :: 2026-07-25")
        b = _norm_prefix("L2 tools/build.py :: [AUTO-DIFF] :: 2026-08-01")
        self.assertEqual(a, b)

    def test_different_files_do_not_collapse(self):
        from path_memory.quality import _norm_prefix
        a = _norm_prefix("L2 tools/build.py :: [AUTO-DIFF] :: 2026-07-25")
        b = _norm_prefix("L2 tools/assemble.py :: [AUTO-DIFF] :: 2026-07-25")
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
