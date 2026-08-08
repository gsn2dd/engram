"""
Tests for the higher-level features:
fan-out perspectives, project scoping, distillation (supersede), and JSON fold.

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

# The embedding provider is pluggable, so this gate must be too — hardcoding
# OPENAI_API_KEY silently skipped the entire DB-backed suite on a brain
# configured for Gemini.
HAVE_EMBED = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                  or os.environ.get("OPENAI_API_KEY"))
HAVE_KEYS = bool(HAVE_EMBED and os.environ.get("ANTHROPIC_API_KEY"))


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

    def test_json_fold_is_recallable(self):
        import json
        from path_memory.fold import fold_json
        blob = {"shop": {"name": "Cyc Rentals", "hours": {"sat": "10am-4pm", "sun": "closed"}}}
        ids = fold_json(json.dumps(blob), person=self.ENT, project="alpha")
        self.assertEqual(len(ids), 3, "each JSON leaf should become exactly one memory")
        hits = recall("weekend opening time", person=self.ENT, project="alpha")
        self.assertTrue(any("sat" in (r["subject"] or "") for r in hits),
                        "a folded JSON leaf should be recallable by meaning, not just keyword")

    def test_json_fold_roundtrips(self):
        import json
        from path_memory.fold import fold_json, recall_json
        blob = {"shop": {"name": "Cyc", "open": True, "tables": 4,
                         "days": ["sat", "sun"]}}
        fold_json(json.dumps(blob), person=self.ENT, project="roundtrip")
        got = recall_json(person=self.ENT, project="roundtrip")
        self.assertEqual(got, blob, "folded JSON must reassemble to the original, types intact")

    def test_collapse_cuts_at_the_relevance_cliff(self):
        # A tight cluster of three on-topic memories, then a clear drop to
        # several off-topic ones. Collapse should return only the on-topic air.
        for i in range(3):
            Memory.save(f"espresso note {i}",
                        f"Detail {i} about pulling espresso shots and grind size on the cafe machine.",
                        person=self.ENT, project="collapse", perspectives=False)
        for i in range(5):
            Memory.save(f"unrelated note {i}",
                        f"Something about {['tax filing','bicycle tyres','garden compost','roof tiles','bus timetables'][i]}.",
                        person=self.ENT, project="collapse", perspectives=False)
        # increment_weight=False keeps both reads from strengthening the graph,
        # so the collapse is measured on a clean cold-brain field, not one the
        # first query already warmed.
        q = "how do I pull a good espresso shot"
        plain = recall(q, person=self.ENT, project="collapse", limit=5,
                       collapse=False, increment_weight=False)
        collapsed = recall(q, person=self.ENT, project="collapse", limit=5,
                           collapse=True, increment_weight=False)
        self.assertEqual(len(plain), 5, "fixed top-N returns the full quota, padding with off-topic noise")
        self.assertLess(len(collapsed), len(plain),
                        "collapse should drop the noise tail and return fewer than the quota")
        self.assertTrue(all("espresso" in (r["subject"] or "") for r in collapsed),
                        "collapse must keep only the on-topic cluster (the 'air'), not the 'wall'")

    def test_collapse_does_not_invent_a_cliff_in_a_flat_field(self):
        # Normalisation divides by the span, so six scores covering a range of
        # 0.0001 normalise to gaps of 0.2 each — clearing a 0.18 threshold. A
        # perfectly uniform field was cut after two results and reported as a
        # clean cliff. Every field has a largest gap; that is not a wall.
        from path_memory.recall import _collapse_field
        flat = [{"score": 0.7 + i * 1e-4, "cosine": 0.7, "id": i} for i in range(6)][::-1]
        kept, gap = _collapse_field(flat, limit=5)
        self.assertIsNone(gap, "a field with no structure must not report a cliff")
        self.assertEqual(len(kept), 5, "with no wall, collapse falls back to the top-N")

    def test_collapse_still_finds_a_real_cliff_at_any_limit(self):
        # Measured on a real brain: the genuine on-topic-to-noise drop was
        # 0.2316 (31% of the top score) while the largest drop inside either
        # cluster was 0.0357 (4.8%). The absolute floor has to sit between them
        # and must not depend on `limit`.
        from path_memory.recall import _collapse_field
        measured = [0.7421, 0.7280, 0.7272, 0.4956, 0.4599, 0.4583, 0.4524, 0.4351]
        for lim in (5, 8):
            kept, gap = _collapse_field(
                [{"score": s, "cosine": s, "id": i} for i, s in enumerate(measured)], limit=lim)
            self.assertEqual(len(kept), 3, f"real cliff must survive limit={lim}")
            self.assertIsNotNone(gap)

    def test_collapse_never_returns_more_than_the_limit(self):
        # The cliff is now searched across the whole candidate pool, so the cut
        # point can fall beyond `limit` and must be clamped.
        from path_memory.recall import _collapse_field
        pool = [{"score": 0.75 - i * 1e-3, "cosine": 0.7, "id": i} for i in range(8)]
        pool += [{"score": 0.20, "cosine": 0.2, "id": 100 + i} for i in range(6)]
        kept, _ = _collapse_field(pool, limit=5)
        self.assertLessEqual(len(kept), 5, "collapse must never exceed the requested limit")

    def test_collapse_does_not_call_a_model_on_the_read_path(self):
        # Recording the boundary is two cheap writes; NAMING it is a model call.
        # It used to happen synchronously inside recall, unbudgeted, once per
        # novel result set — so exploring a new brain with collapse on cost a
        # model call per query. Naming belongs in the dreaming pass.
        import path_memory.boundary as boundary
        for i in range(3):
            Memory.save(f"cliff note {i}", f"Detail {i} about pulling espresso shots and grind size.",
                        person=self.ENT, project="nocall", perspectives=False)
        for i, t in enumerate(["tax filing", "bicycle tyres", "roof tiles", "bus timetables"]):
            Memory.save(f"cliff noise {i}", f"Something about {t}.",
                        person=self.ENT, project="nocall", perspectives=False)
        called = []
        original = boundary._name_cluster
        boundary._name_cluster = lambda *a, **k: called.append(1) or {"name": "x", "gist": ""}
        try:
            recall("how do I pull a good espresso shot", person=self.ENT, project="nocall",
                   limit=5, collapse=True)
        finally:
            boundary._name_cluster = original
        self.assertEqual(called, [], "recall must not name a boundary synchronously")

    def test_folded_redaction_is_reported_not_silent(self):
        import json
        from path_memory.fold import fold_json, recall_json
        blob = {"svc": {"name": "billing", "retries": 3,
                        "pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIabc123\n-----END RSA PRIVATE KEY-----"}}
        fold_json(json.dumps(blob), person=self.ENT, project="foldredact")
        import io, contextlib
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            got = recall_json(person=self.ENT, project="foldredact")
        warning = err.getvalue()
        self.assertNotEqual(got, blob, "the credential leaf should have been scrubbed")
        self.assertIn("svc.pem", warning,
                      "a redacted leaf must be reported, not handed back as the real value")
        self.assertNotIn("svc.name", warning,
                         "untouched leaves must not be flagged — a warning that cries wolf gets ignored")

    def test_fold_redaction_can_be_turned_off_deliberately(self):
        import json
        from path_memory.fold import fold_json, recall_json
        blob = {"cfg": {"token": "sk-ant-abcdefghijklmnopqrstuvwxyz012345"}}
        fold_json(json.dumps(blob), person=self.ENT, project="foldraw", redact=False)
        self.assertEqual(recall_json(person=self.ENT, project="foldraw"), blob,
                         "an explicit redact=False must round-trip the value untouched")

    def test_creativity_injects_serendipity(self):
        # need more than `limit` candidates for near-misses to draw from
        for i in range(10):
            Memory.save(f"alpha note {i}", f"A note about subtopic {i} within the alpha workstream.",
                        person=self.ENT, project="alpha", perspectives=False)
        plain = recall("subtopic", person=self.ENT, project="alpha", limit=4, creativity=0.0)
        self.assertTrue(plain and all(not r.get("serendipity") for r in plain),
                        "creativity=0 must return only precise matches")
        creative = recall("subtopic", person=self.ENT, project="alpha", limit=4, creativity=0.75)
        self.assertTrue(any(r.get("serendipity") for r in creative),
                        "high creativity should inject at least one near-miss memory")
        self.assertTrue(any(not r.get("serendipity") for r in creative),
                        "creativity must still keep precise results (incl. the top hit)")

    def test_collapse_survives_an_almost_empty_brain(self):
        # A new user's first query runs against 0 then 1 memories. _collapse_field
        # has an early return for that case which once returned a bare list while
        # every other exit returned (results, gap) — so collapse raised
        # ValueError on exactly the first thing anyone does.
        empty = recall("nothing has been stored yet", person="nobody-here",
                       limit=5, collapse=True, increment_weight=False)
        self.assertEqual(empty, [], "collapse on an empty brain must return [], not raise")

        Memory.save("lone note", "The only memory in this corner of the brain, about sailing.",
                    person=self.ENT, project="lonely", perspectives=False)
        one = recall("sailing", person=self.ENT, project="lonely", limit=5,
                     collapse=True, increment_weight=False)
        self.assertEqual(len(one), 1, "collapse with a single candidate must return it, not raise")

    def test_recall_resolves_the_project_through_the_alias_registry(self):
        # Memory.save normalises the project; recall used to filter on the raw
        # string, so a memory was invisible under the very name it was written
        # with — no error, just nothing.
        Memory.save("alias probe", "Stored under a human-written project name.",
                    person=self.ENT, project="My Test Project", perspectives=False)
        got = recall("alias probe", person=self.ENT, project="My Test Project",
                     limit=3, increment_weight=False)
        self.assertTrue(got, "a memory must be recallable under the project name it was saved with")

    def test_use_history_cannot_outrank_relevance(self):
        # Warming one cluster used to hijack every later query: popularity was
        # weighted 0.7 against relevance at 0.1, so eight warmed memories
        # answered a question about something else entirely.
        for i in range(6):
            Memory.save(f"kettle note {i}", f"Note {i} on descaling the office kettle.",
                        person=self.ENT, project="rank", perspectives=False)
        for i in range(6):
            Memory.save(f"payroll note {i}", f"Note {i} on the monthly payroll submission deadline.",
                        person=self.ENT, project="rank", perspectives=False)
        recall("how do I descale the kettle", person=self.ENT, project="rank", limit=5)
        after = recall("when is the payroll deadline", person=self.ENT, project="rank",
                       limit=5, increment_weight=False)
        subjects = [r["subject"] or "" for r in after]
        self.assertGreaterEqual(
            sum(1 for s in subjects if "payroll" in s), 4,
            f"a warmed cluster must not answer an unrelated query; got {subjects}")

    def test_collapse_keeps_the_boundary_it_resolved(self):
        # The point of the feature: a resolution that used to be discarded is
        # kept, so the second identical question reuses the doorway instead of
        # paying for the same resolution again.
        from path_memory import boundary
        for i in range(3):
            Memory.save(f"kiln note {i}",
                        f"Detail {i} on firing stoneware in the kiln, cone 6 glaze schedules.",
                        person=self.ENT, project="kiln", perspectives=False)
        for i in range(5):
            Memory.save(f"offtopic {i}",
                        f"Notes on {['payroll','tyre pressure','hedge trimming','gutters','ferry times'][i]}.",
                        person=self.ENT, project="kiln", perspectives=False)

        q = "how hot should I fire stoneware"
        first = recall(q, person=self.ENT, project="kiln", limit=5,
                       collapse=True, increment_weight=False)
        key = first[0].get("collapse_key")
        self.assertIsNotNone(key, "a clean collapse must record the boundary it resolved")

        conn = get_conn(); cur = conn.cursor()
        try:
            cur.execute("SELECT name, member_ids, query_count FROM collapse_keys WHERE key=%s", (key,))
            name, member_ids, count_before = cur.fetchone()
            self.assertEqual(sorted(member_ids), sorted(r["id"] for r in first),
                             "the stored doorway must be exactly the set that was resolved")

            # Re-resolving the same set must land on the SAME key, not mint a
            # rival — that is what makes the usage count meaningful.
            again = recall(q, person=self.ENT, project="kiln", limit=5,
                           collapse=True, increment_weight=False)
            self.assertEqual(again[0].get("collapse_key"), key,
                             "the same resolved set must reuse its key, not create a second one")
            cur.execute("SELECT query_count FROM collapse_keys WHERE key=%s", (key,))
            self.assertGreater(cur.fetchone()[0], count_before,
                               "a doorway that re-forms should record that it re-formed")

            # The exact-lookup half: rows by id, no scan, no scoring.
            rows = boundary.members(cur, member_ids)
            self.assertEqual(len(rows), len(member_ids))
            self.assertTrue(all("kiln" in (r["subject"] or "") for r in rows),
                            "the doorway must yield the on-topic cluster, not the noise")

            if name:
                self.assertIsNotNone(boundary.by_name(cur, name),
                                     "a named doorway must be reachable by its handle alone")
            conn.commit()
        finally:
            cur.close(); conn.close()


if __name__ == "__main__":
    unittest.main()
