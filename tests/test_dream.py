"""
Regression tests for the dreaming pass.

Every bug covered here is a TIMER bug: it does nothing visible on the run that
introduces it and only shows up as cost, silence or duplication days later.
That is exactly the class of defect that comes back, because nothing about a
normal run looks wrong. They are pinned here rather than left to observation.

These use the database but stub the model call, so they cost nothing to run and
work without an API key.
"""
import os
import unittest

import psycopg2

from path_memory import dream
from path_memory.db import get_conn

HAVE_DB = bool(os.environ.get("DB_NAME"))


@unittest.skipUnless(HAVE_DB, "needs a reachable engram database")
class TestDreamWatermarks(unittest.TestCase):
    """The per-project reading watermark."""

    A = "dream-test-alpha"
    B = "dream-test-beta"

    def setUp(self):
        self.conn = get_conn()
        self.cur = self.conn.cursor()
        dream._ensure_state(self.cur)
        self._clean()

    def tearDown(self):
        self._clean()
        self.conn.commit()
        self.cur.close()
        self.conn.close()

    def _restore_project_fk(self):
        """Put the constraint back however the test ended. Leaving it off would
        silently weaken every later test in the file."""
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("DELETE FROM memories WHERE project IS NOT NULL AND project NOT IN "
                        "(SELECT slug FROM projects)")
            cur.execute("""ALTER TABLE memories ADD CONSTRAINT memories_project_registered
                           FOREIGN KEY (project) REFERENCES projects(slug)
                           ON UPDATE CASCADE""")
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            cur.close()
            conn.close()

    def _clean(self):
        self.cur.execute("DELETE FROM dream_watermarks WHERE project = ANY(%s)",
                         ([self.A, self.B],))
        self.cur.execute("SELECT id FROM memories WHERE project = ANY(%s)",
                         ([self.A, self.B],))
        ids = [r[0] for r in self.cur.fetchall()]
        if ids:
            self.cur.execute("DELETE FROM memory_topics WHERE memory_id = ANY(%s)", (ids,))
            self.cur.execute("DELETE FROM memory_projects WHERE memory_id = ANY(%s)", (ids,))
            self.cur.execute("DELETE FROM memory_links WHERE from_id = ANY(%s) OR to_id = ANY(%s)",
                             (ids, ids))
            self.cur.execute("DELETE FROM memories WHERE id = ANY(%s)", (ids,))
        self.cur.execute("DELETE FROM topics WHERE project = ANY(%s)", ([self.A, self.B],))
        # The fairness test's stub tags whatever it is shown, including other
        # projects' memories that happen to be unread in a shared test database.
        self.cur.execute("DELETE FROM memory_topics WHERE slug = 'shared-subject'")
        self.cur.execute("DELETE FROM topics WHERE slug = 'shared-subject'")
        # Every reference must go before the project row itself can, or the FK
        # test cannot reach the state it exists to reproduce.
        self.cur.execute("DELETE FROM memory_projects WHERE project = ANY(%s)",
                         ([self.A, self.B],))
        self.cur.execute("DELETE FROM project_aliases WHERE canonical = ANY(%s) OR alias = ANY(%s)",
                         ([self.A, self.B], [self.A, self.B]))
        self.cur.execute("DELETE FROM projects WHERE slug = ANY(%s)", ([self.A, self.B],))
        self.conn.commit()

    def _add(self, project, n):
        ids = []
        self.cur.execute(
            "INSERT INTO projects (slug, display_name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (project, project))
        for i in range(n):
            self.cur.execute(
                """INSERT INTO memories (subject, body, project, origin)
                   VALUES (%s,%s,%s,'contribution') RETURNING id""",
                (f"{project} note {i}", f"Body {i} about the {project} workstream.", project))
            ids.append(self.cur.fetchone()[0])
        self.conn.commit()
        return ids

    def test_advancing_one_project_does_not_skip_another(self):
        # The original bug. One global watermark was advanced from whichever
        # project's batch ran last; the reading loop walks the biggest project
        # first, so every smaller project's memories fell permanently behind it
        # and were never read.
        a_ids = self._add(self.A, 3)
        b_ids = self._add(self.B, 3)
        dream._advance(self.cur, self.A, max(a_ids))
        self.conn.commit()
        self.assertEqual(dream._watermark(self.cur, self.A), max(a_ids))
        self.assertEqual(dream._watermark(self.cur, self.B), 0,
                         "advancing one project must not move another project's watermark")
        self.cur.execute(
            """SELECT count(*) FROM memories m
               LEFT JOIN dream_watermarks w ON w.project = m.project
               WHERE m.project = %s AND m.id > coalesce(w.last_memory_id,0)""", (self.B,))
        self.assertEqual(self.cur.fetchone()[0], len(b_ids),
                         "the other project's memories must all still be unread")

    def test_watermark_never_goes_backwards(self):
        ids = self._add(self.A, 2)
        dream._advance(self.cur, self.A, max(ids))
        dream._advance(self.cur, self.A, min(ids))
        self.conn.commit()
        self.assertEqual(dream._watermark(self.cur, self.A), max(ids),
                         "a later batch must not rewind the watermark")

    def test_a_read_batch_with_no_topics_still_advances(self):
        # "Nothing to say" must advance; otherwise the same batch is re-read
        # every run forever, spending a model call each time and never reaching
        # anything newer.
        ids = self._add(self.A, 4)
        original, dream._extract = dream._extract, lambda listing, project: []
        try:
            dream.extract_topics(self.cur, dream._Budget(2), project=self.A)
        finally:
            dream._extract = original
        self.conn.commit()
        self.assertEqual(dream._watermark(self.cur, self.A), max(ids),
                         "a batch that was read but yielded nothing must still advance")

    def test_a_failed_extraction_does_not_advance(self):
        # The other half of the same distinction: if the CALL failed, those
        # memories were never read and must not be skipped.
        self._add(self.A, 4)
        original, dream._extract = dream._extract, lambda listing, project: None
        try:
            dream.extract_topics(self.cur, dream._Budget(2), project=self.A)
        finally:
            dream._extract = original
        self.conn.commit()
        self.assertEqual(dream._watermark(self.cur, self.A), 0,
                         "a failed model call must leave the batch unread")

    def test_every_project_gets_read_not_just_the_biggest(self):
        # `found` collects one entry per (memory, topic) PAIR, so the old
        # `len(found) >= limit` break tripped on the first project's first batch
        # and ended the whole loop. One project was read per run — always the
        # largest — and the model budget went mostly unspent. Smaller projects
        # sat unread indefinitely behind it.
        big = self._add(self.A, 60)
        small = self._add(self.B, 4)
        calls = []

        def fake(listing, project):
            calls.append(project)
            ids = [int(line.split()[1]) for line in listing.splitlines()
                   if line.startswith("id: ")]
            return [{"id": i, "topics": ["shared subject"]} for i in ids]

        # The budget has to cover every project carrying unread rows, not just
        # this test's two — the point being proved is that the loop keeps going
        # round, not that it happens to reach B first.
        self.cur.execute(
            """SELECT count(DISTINCT m.project) FROM memories m
               LEFT JOIN dream_watermarks w ON w.project = m.project
               WHERE m.project IS NOT NULL AND NOT m.archived
                 AND m.origin IS DISTINCT FROM 'recycle'
                 AND m.id > coalesce(w.last_memory_id, 0)""")
        budget = dream._Budget(self.cur.fetchone()[0] + 2)
        original, dream._extract = dream._extract, fake
        try:
            dream.extract_topics(self.cur, budget, batch=40)
        finally:
            dream._extract = original
        self.conn.commit()
        self.assertIn(self.B, calls,
                      f"the smaller project must be read too; only read {calls}")
        self.assertGreater(dream._watermark(self.cur, self.B), 0,
                           "the smaller project's watermark should have moved")
        self.assertEqual(dream._watermark(self.cur, self.B), max(small))
        # And the big one is not starved either: it gets a second turn once
        # every project has had a first.
        self.assertEqual(dream._watermark(self.cur, self.A), max(big),
                         "a project with more than one batch should get another turn")

    def test_unregistered_project_does_not_break_the_pass(self):
        # topics.project is a foreign key into the registry; memories.project is
        # free text. Inserting the raw value raised a FK violation which,
        # because the pass shares one transaction, rolled back every topic the
        # whole run had found — not just the offending one.
        #
        # engram's own schema constrains memories.project to the registry, so
        # this state cannot arise here. It arises on brains that predate that
        # constraint — mindspace, which this engine also runs against, has 459
        # memories with no registry row. The constraint is dropped for the
        # duration of this test to reproduce that shape honestly, rather than
        # asserting the fix works on a schema where the bug is unreachable.
        ids = self._add(self.A, 4)
        try:
            self.cur.execute(
                "ALTER TABLE memories DROP CONSTRAINT IF EXISTS memories_project_registered")
        except psycopg2.errors.InsufficientPrivilege:
            # The app user does not own the table on every deployment. Skipping
            # is honest; claiming a pass without having reproduced the shape
            # would not be.
            self.conn.rollback()
            self.skipTest("needs table ownership to drop the project FK")
        self.cur.execute("DELETE FROM projects WHERE slug = %s", (self.A,))
        self.conn.commit()
        self.addCleanup(self._restore_project_fk)
        fake = [{"id": i, "topics": ["shared subject"]} for i in ids]
        original, dream._extract = dream._extract, lambda listing, project: fake
        try:
            found = dream.extract_topics(self.cur, dream._Budget(2), project=self.A)
        finally:
            dream._extract = original
        self.conn.commit()
        self.assertTrue(found, "topics must be recorded even for an unregistered project")
        self.cur.execute("SELECT count(*) FROM projects WHERE slug = %s", (self.A,))
        self.assertEqual(self.cur.fetchone()[0], 1,
                         "the project should have been registered rather than rejected")


@unittest.skipUnless(HAVE_DB, "needs a reachable engram database")
class TestSummaryFreshness(unittest.TestCase):
    """A topic must be re-summarised only when its membership actually changes."""

    P = "dream-test-fresh"
    SLUG = "some-subject"

    def setUp(self):
        self.conn = get_conn()
        self.cur = self.conn.cursor()
        self._clean()

    def tearDown(self):
        self._clean()
        self.cur.close()
        self.conn.close()

    def _clean(self):
        self.cur.execute("SELECT id FROM memories WHERE project = %s", (self.P,))
        ids = [r[0] for r in self.cur.fetchall()]
        if ids:
            self.cur.execute("DELETE FROM memory_topics WHERE memory_id = ANY(%s)", (ids,))
            self.cur.execute("DELETE FROM memory_links WHERE from_id = ANY(%s) OR to_id = ANY(%s)",
                             (ids, ids))
            self.cur.execute("UPDATE memories SET superseded_by = NULL WHERE id = ANY(%s)", (ids,))
            self.cur.execute("DELETE FROM memories WHERE id = ANY(%s)", (ids,))
        self.cur.execute("DELETE FROM topics WHERE project = %s", (self.P,))
        self.cur.execute("DELETE FROM projects WHERE slug = %s", (self.P,))
        self.conn.commit()

    def test_an_unchanged_topic_is_not_rewritten(self):
        # The count-based freshness test compared every tagged row (unbounded,
        # and including the summary's own tag) against the previous summary's
        # member list (capped at 30, summaries excluded). Past 30 members those
        # two could never agree, so the topic was rewritten on every single run.
        self.cur.execute(
            "INSERT INTO projects (slug, display_name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
            (self.P, self.P))
        self.cur.execute(
            "INSERT INTO topics (project, slug, label, source) VALUES (%s,%s,%s,'discovered')",
            (self.P, self.SLUG, "some subject"))
        members = []
        for i in range(35):
            self.cur.execute(
                """INSERT INTO memories (subject, body, project, origin)
                   VALUES (%s,%s,%s,'contribution') RETURNING id""",
                (f"member {i}", f"Body {i}.", self.P))
            mid = self.cur.fetchone()[0]
            members.append(mid)
            self.cur.execute(
                """INSERT INTO memory_topics (memory_id, project, slug, confidence, assigned_by)
                   VALUES (%s,%s,%s,1.0,'read')""", (mid, self.P, self.SLUG))

        # The summary the previous run wrote, covering the 30 it selected, plus
        # the self-tag that inflated the old count.
        covered = members[:30]
        self.cur.execute(
            """INSERT INTO memories (subject, body, project, origin, derived_from, derived_depth)
               VALUES (%s,%s,%s,'recycle',%s,1) RETURNING id""",
            (f"Topic summary: {self.SLUG}", "gist", self.P, covered))
        summary_id = self.cur.fetchone()[0]
        self.cur.execute(
            """INSERT INTO memory_topics (memory_id, project, slug, confidence, assigned_by)
               VALUES (%s,%s,%s,1.0,'dream')""", (summary_id, self.P, self.SLUG))
        self.conn.commit()

        written = dream.summarise_topics(self.cur, dream._Budget(5))
        mine = [w for w in written if w["project"] == self.P]
        self.assertEqual(mine, [],
                         "a topic whose membership has not changed must not be re-summarised")


if __name__ == "__main__":
    unittest.main()
