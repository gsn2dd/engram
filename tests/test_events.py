"""
Shown vs used — the distinction the engine could not previously make.

The failure these guard against is not a crash. It is a brain that learns from
exposure, decides it likes what it already surfaces, and surfaces it harder —
while every counter looks healthy.
"""
import os
import unittest

HAVE_DB = bool(os.environ.get("DB_NAME"))


@unittest.skipUnless(HAVE_DB, "needs a database")
class TestRecallEvents(unittest.TestCase):

    def setUp(self):
        from path_memory.db import get_conn
        self.conn = get_conn()
        cur = self.conn.cursor()
        cur.execute("""INSERT INTO memories (subject, body, tier)
                       VALUES ('ev subject a', 'body a', 'curated'),
                              ('ev subject b', 'body b', 'curated')
                       RETURNING id""")
        self.ids = [r[0] for r in cur.fetchall()]
        self.conn.commit()
        cur.close()

    def tearDown(self):
        cur = self.conn.cursor()
        cur.execute("DELETE FROM recall_events WHERE source = 'unittest'")
        cur.execute("DELETE FROM memories WHERE id = ANY(%s)", (self.ids,))
        self.conn.commit()
        cur.close()
        self.conn.close()

    def _results(self):
        return [{"id": self.ids[0], "score": 0.9},
                {"id": self.ids[1], "score": 0.4}]

    def test_record_captures_rank_and_score(self):
        """'It was there but ranked 9th' is a different failure from 'it was
        never returned', and only the ranks distinguish them."""
        from path_memory import events
        eid = events.record("a query", self._results(), source="unittest")
        self.assertIsNotNone(eid)
        cur = self.conn.cursor()
        cur.execute("SELECT shown, used FROM recall_events WHERE id = %s", (eid,))
        shown, used = cur.fetchone()
        cur.close()
        self.assertEqual([s["id"] for s in shown], self.ids)
        self.assertEqual([s["rank"] for s in shown], [1, 2])
        self.assertIsNone(used, "a fresh event must be unjudged, not judged-empty")

    def test_serendipity_picks_are_not_recorded_as_shown(self):
        """Sparks are prompts, not retrievals. They already never strengthen the
        graph; they must not enter the use ledger either, or attribution would
        credit a memory that was deliberately offered as a guess."""
        from path_memory import events
        results = self._results()
        results[1]["serendipity"] = True
        eid = events.record("q", results, source="unittest")
        cur = self.conn.cursor()
        cur.execute("SELECT shown FROM recall_events WHERE id = %s", (eid,))
        shown = cur.fetchone()[0]
        cur.close()
        self.assertEqual([s["id"] for s in shown], [self.ids[0]])

    def test_mark_used_strengthens_only_what_was_used(self):
        from path_memory import events
        eid = events.record("q", self._results(), source="unittest")
        events.mark_used(eid, [self.ids[0]])
        cur = self.conn.cursor()
        cur.execute("SELECT id, success_count FROM memories WHERE id = ANY(%s) ORDER BY id",
                    (self.ids,))
        counts = dict(cur.fetchall())
        cur.close()
        self.assertEqual(counts[self.ids[0]], 1, "the used memory must be reinforced")
        self.assertEqual(counts[self.ids[1]], 0,
                         "a memory that was merely shown must NOT be reinforced")

    def test_an_empty_attribution_is_recorded_not_skipped(self):
        """'Nothing shown was useful' is the most informative outcome available —
        a recall that failed while looking like it worked. It must be
        distinguishable from 'not yet judged'."""
        from path_memory import events
        eid = events.record("q", self._results(), source="unittest")
        events.mark_used(eid, [])
        cur = self.conn.cursor()
        cur.execute("SELECT used, attributed_at FROM recall_events WHERE id = %s", (eid,))
        used, at = cur.fetchone()
        cur.close()
        self.assertEqual(used, [])
        self.assertIsNotNone(at)

    def test_unattributed_respects_the_settling_delay(self):
        """Attribution needs the conversation that FOLLOWED the recall. An event
        judged the instant it is written is being judged before the answer
        exists."""
        from path_memory import events
        eid = events.record("q", self._results(), source="unittest")
        fresh = [e["id"] for e in events.unattributed(older_than_seconds=3600)]
        self.assertNotIn(eid, fresh)
        now = [e["id"] for e in events.unattributed(older_than_seconds=0)]
        self.assertIn(eid, now)

    def test_recording_never_raises(self):
        """This sits on the read path. A lost event is a gap in a dataset; a
        raised exception is a broken brain."""
        from path_memory import events
        self.assertIsNone(events.record("q", []))
        self.assertIsNone(events.record("q", [{"no_id_key": 1}], source="unittest"))


class TestSuccessBonusShape(unittest.TestCase):
    """The ranking term is built but OFF. These pin both halves of that."""

    def test_success_bonus_defaults_to_off(self):
        """It stays off until the bench says otherwise. Shipping an unmeasured
        ranking term is the exact mistake that put USE_BONUS at 0.5."""
        from path_memory.recall import DEFAULT_POLICY
        self.assertEqual(DEFAULT_POLICY["success_bonus"], 0.0)

    def test_the_term_saturates(self):
        """The signal is 'has this ever helped', not 'how many times'. A linear
        term would let one well-worn memory dominate every query — which is
        precisely how raw weight failed."""
        bonus = 0.3
        def mult(net):
            return 1.0 + bonus * (net / (net + 2.0)) if net > 0 else 1.0
        first = mult(1) - mult(0)
        later = mult(10) - mult(9)
        self.assertGreater(first, later * 5,
                           "the first success must matter far more than the tenth")
        self.assertLess(mult(1000), 1.0 + bonus, "the term must stay bounded")


if __name__ == "__main__":
    unittest.main()
