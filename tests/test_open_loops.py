"""
Open loops — what was concluded and never done.

The failure being guarded against is the one that motivated the feature: a root
cause diagnosed correctly on 2026-08-08, written down with its one-line fix, and
never applied — rediscovered from scratch eight days and 192 skipped runs later
by an agent holding the original in its own memory.

Two properties matter more than any other and both are tested here:
SILENCE IS NOT COMPLETION (nothing closes a loop except evidence), and the
detector must not cry wolf (a list of maybes is a list nobody reads, which is
how the original was missed).
"""
import os
import unittest

HAVE_DB = bool(os.environ.get("DB_NAME"))


class TestMarkers(unittest.TestCase):
    """The cheap prefilter. It exists to avoid paying for a judgement on every
    memory, not to make the judgement."""

    def test_it_catches_the_real_phrasings(self):
        from path_memory.open_loops import MARKERS
        for text in (
            "THE FIX is to remove the crontab's flock wrapper, not the script's.",
            "STILL MANUAL before Marketplace submission: reboot persistence check",
            "Status: plan, NOT STARTED. Written 2026-08-08.",
            "Next step: convert the regression checks to behavioural ones",
            "this remains open until the bank statement arrives",
        ):
            self.assertTrue(MARKERS.search(text), f"missed: {text[:50]}")

    def test_it_is_a_filter_not_a_verdict(self):
        """Deliberately over-inclusive: it fires on prose that merely SOUNDS
        like a commitment. The model is the part that says no, and this test
        documents that the prefilter alone must never be trusted."""
        from path_memory.open_loops import MARKERS
        self.assertTrue(MARKERS.search("the fix is already deployed and verified"))


@unittest.skipUnless(HAVE_DB, "needs a database")
class TestClosing(unittest.TestCase):

    def setUp(self):
        from path_memory.db import get_conn
        self.conn = get_conn()
        cur = self.conn.cursor()
        cur.execute("""INSERT INTO memories (subject, body, tier)
                       VALUES ('a finding with an unapplied fix', 'body', 'curated'),
                              ('the memory that replaced it', 'body', 'curated')
                       RETURNING id""")
        self.a, self.b = [r[0] for r in cur.fetchall()]
        cur.execute("""INSERT INTO open_loops (memory_id, action, status)
                       VALUES (%s, 'remove the wrapper', 'open')""", (self.a,))
        self.conn.commit()
        cur.close()

    def tearDown(self):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM memories WHERE id = ANY(%s)", ([self.a, self.b],))
        self.conn.commit()
        cur.close()
        self.conn.close()

    def _status(self, mid):
        cur = self.conn.cursor()
        cur.execute("SELECT status FROM open_loops WHERE memory_id = %s", (mid,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None

    def test_supersession_closes_a_loop(self):
        """A superseding memory is by definition a later statement about the
        same thing, so it is real evidence rather than an assumption."""
        from path_memory import open_loops as L
        cur = self.conn.cursor()
        cur.execute("UPDATE memories SET superseded_by = %s WHERE id = %s",
                    (self.b, self.a))
        self.conn.commit()
        cur.close()
        self.assertEqual(L.close_superseded(), 1)
        self.assertEqual(self._status(self.a), "closed")

    def test_age_alone_never_closes_a_loop(self):
        """THE central property. The motivating failure was a conclusion going
        quiet for eight days; if quiet counted as done, this feature would
        reproduce the exact bug it exists to prevent."""
        from path_memory import open_loops as L
        cur = self.conn.cursor()
        cur.execute("UPDATE memories SET created_at = now() - interval '400 days' "
                    "WHERE id = %s", (self.a,))
        self.conn.commit()
        cur.close()
        L.close_superseded()
        self.assertEqual(self._status(self.a), "open",
                         "an old loop is more important, not less — never expired")
        self.assertIn(self.a, [o["memory_id"] for o in L.open_loops(limit=500)])

    def test_explicit_close_works_once(self):
        from path_memory import open_loops as L
        self.assertTrue(L.close(self.a, "done in commit abc123"))
        self.assertEqual(self._status(self.a), "closed")
        self.assertFalse(L.close(self.a), "closing twice must not re-close")

    def test_closed_loops_leave_the_list(self):
        from path_memory import open_loops as L
        L.close(self.a, "done")
        self.assertNotIn(self.a, [o["memory_id"] for o in L.open_loops(limit=500)])

    def test_not_actionable_is_recorded_so_it_is_never_re_judged(self):
        """Without this the detector re-reads the whole corpus every run and the
        budget never reaches new material."""
        from path_memory import open_loops as L
        cur = self.conn.cursor()
        cur.execute("""INSERT INTO open_loops (memory_id, status)
                       VALUES (%s, 'not_actionable')""", (self.b,))
        self.conn.commit()
        cur.close()
        self.assertEqual(self._status(self.b), "not_actionable")
        self.assertNotIn(self.b, [o["memory_id"] for o in L.open_loops(limit=500)])


if __name__ == "__main__":
    unittest.main()
