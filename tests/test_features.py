"""
Tests for the best-of-both features ported from the mindspace lineage:
fan-out perspectives, project scoping, and distillation (supersede).

These exercise Memory.save() and recall(), which need OPENAI_API_KEY (query +
content embeddings) and ANTHROPIC_API_KEY (lens generation + classification),
so they SKIP automatically in keyless CI and run wherever the keys are set.
They expect the schema applied and a reachable DB (the usual DB_* env vars).
"""
import os
import unittest

from path_memory.memory import Memory
from path_memory.recall import recall
from path_memory.db import get_conn

HAVE_KEYS = bool(os.environ.get("OPENAI_API_KEY") and os.environ.get("ANTHROPIC_API_KEY"))


@unittest.skipUnless(HAVE_KEYS, "needs OPENAI_API_KEY + ANTHROPIC_API_KEY")
class TestBestOfBoth(unittest.TestCase):
    ENT = "test-engram-features"

    def tearDown(self):
        c = get_conn(); cur = c.cursor()
        cur.execute("SELECT id FROM memories WHERE person = %s", (self.ENT,))
        ids = [r[0] for r in cur.fetchall()]
        if ids:
            # memory_links has no ON DELETE CASCADE; clear it first.
            cur.execute("DELETE FROM memory_links WHERE from_id = ANY(%s) OR to_id = ANY(%s)", (ids, ids))
            # memories delete cascades perspectives, entities, path_edge_summary.
            cur.execute("DELETE FROM memories WHERE id = ANY(%s)", (ids,))
        c.commit(); cur.close(); c.close()

    def test_perspectives_are_generated_on_save(self):
        mid = Memory.save("dog walking idea",
                          "A weekend dog-walking service for busy people in my town.",
                          person=self.ENT, project="alpha")
        c = get_conn(); cur = c.cursor()
        cur.execute("SELECT count(DISTINCT perspective) FROM memory_perspectives WHERE memory_id = %s", (mid,))
        n = cur.fetchone()[0]; cur.close(); c.close()
        self.assertGreaterEqual(n, 1, "expected fan-out perspective lenses to be generated on save")

    def test_perspectives_can_be_disabled(self):
        mid = Memory.save("quiet save", "No lenses for this one.",
                          person=self.ENT, project="alpha", perspectives=False)
        c = get_conn(); cur = c.cursor()
        cur.execute("SELECT count(*) FROM memory_perspectives WHERE memory_id = %s", (mid,))
        n = cur.fetchone()[0]; cur.close(); c.close()
        self.assertEqual(n, 0, "perspectives=False must not generate any lenses")

    def test_project_scoping_filters(self):
        Memory.save("alpha widget note", "Notes about the alpha project widget design.",
                    person=self.ENT, project="alpha", perspectives=False)
        in_alpha = recall("widget design", person=self.ENT, project="alpha")
        in_beta  = recall("widget design", person=self.ENT, project="beta")
        self.assertTrue(any(r["person"] == self.ENT for r in in_alpha),
                        "memory should be found within its own project")
        self.assertEqual([r for r in in_beta if r["person"] == self.ENT], [],
                         "memory must NOT leak into a different project")

    def test_supersede_sets_pointer_and_factor(self):
        old = Memory.save("auth approach v1", "We use server sessions for auth.",
                          person=self.ENT, project="alpha", perspectives=False)
        new = Memory.save("auth approach v2", "We moved to JWT tokens for auth.",
                          person=self.ENT, project="alpha", perspectives=False)
        Memory.supersede(old, new)
        c = get_conn(); cur = c.cursor()
        cur.execute("SELECT superseded_by FROM memories WHERE id = %s", (old,))
        self.assertEqual(cur.fetchone()[0], new, "supersede must record the replacement pointer")
        cur.close(); c.close()
        # The old memory stays recallable but carries the pointer through recall.
        res = {r["id"]: r for r in recall("authentication approach",
                                          person=self.ENT, project="alpha", limit=5)}
        if old in res:
            self.assertEqual(res[old]["superseded_by"], new)


if __name__ == "__main__":
    unittest.main()
