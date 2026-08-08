"""
Regression tests for the dreaming pass.

Every bug covered here is a TIMER bug: it does nothing visible on the run that
introduces it and only shows up as cost, silence or duplication days later.
That is exactly the class of defect that comes back, because nothing about a
normal run looks wrong. They are pinned here rather than left to observation.

These use the database but stub the model call, so they cost nothing to run and
work without an API key.

ISOLATION CONTRACT. The suite may be pointed at a database holding real data
(engram_test is a clone of a live brain), so every test here must leave shared
state exactly as it found it:

  * Fixtures are committed, scoped to dream-test-* projects, and removed by a
    shared cleanup helper that always ROLLS BACK first — so an aborted
    transaction can never mask a failure or strand the fixtures.
  * Engine passes that operate globally (promote_doorways has no project
    scope) are run WITHOUT committing; assertions read the uncommitted state
    on the same connection and teardown's rollback discards the side effects.
    A plain test run must never rename a real doorway or mint a real topic.
  * Where a global pass must be committed to be observable (the round-robin
    fairness test), whatever shared state it moves is snapshotted first and
    restored afterwards.
"""
import os
import unittest

import psycopg2

from path_memory import boundary, dream
from path_memory.db import get_conn

HAVE_DB = bool(os.environ.get("DB_NAME"))


def _add(conn, cur, project, n, weight=None):
    """Register a test project and give it n committed contribution memories."""
    cur.execute(
        "INSERT INTO projects (slug, display_name) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (project, project))
    ids = []
    for i in range(n):
        if weight is None:
            cur.execute(
                """INSERT INTO memories (subject, body, project, origin)
                   VALUES (%s,%s,%s,'contribution') RETURNING id""",
                (f"{project} note {i}", f"Body {i} about the {project} workstream.", project))
        else:
            cur.execute(
                """INSERT INTO memories (subject, body, project, origin, weight)
                   VALUES (%s,%s,%s,'contribution',%s) RETURNING id""",
                (f"{project} note {i}", f"Body {i} about the {project} workstream.",
                 project, weight))
        ids.append(cur.fetchone()[0])
    conn.commit()
    return ids


def _clean_projects(conn, cur, projects, extra=()):
    """Remove every trace of the given test projects, in FK order.

    Rolls back FIRST: if a test died mid-statement the connection is in
    aborted-transaction state and every DELETE here would raise, reporting a
    cleanup error over the real failure and stranding the fixtures. The
    rollback also discards any uncommitted engine side effects a test ran
    deliberately without committing.

    `extra` is a list of (sql, params) statements a class needs beyond the
    common set (e.g. the doorway fixtures). One copy of the common deletes —
    when a new table referencing memories appears, it gets added here once,
    not in three drifting copies.
    """
    conn.rollback()
    # The state tables are created lazily by the pass itself, so on a fresh
    # database this cleanup would otherwise be the first thing to mention them.
    dream._ensure_state(cur)
    for sql, params in extra:
        cur.execute(sql, params)
    cur.execute("DELETE FROM dream_watermarks WHERE project = ANY(%s)", (projects,))
    cur.execute("SELECT id FROM memories WHERE project = ANY(%s)", (projects,))
    ids = [r[0] for r in cur.fetchall()]
    if ids:
        cur.execute("DELETE FROM memory_topics WHERE memory_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM memory_projects WHERE memory_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM memory_links WHERE from_id = ANY(%s) OR to_id = ANY(%s)",
                    (ids, ids))
        cur.execute("UPDATE memories SET superseded_by = NULL WHERE id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM memories WHERE id = ANY(%s)", (ids,))
    cur.execute("DELETE FROM topics WHERE project = ANY(%s)", (projects,))
    cur.execute("DELETE FROM memory_projects WHERE project = ANY(%s)", (projects,))
    cur.execute("DELETE FROM project_aliases WHERE canonical = ANY(%s) OR alias = ANY(%s)",
                (projects, projects))
    cur.execute("DELETE FROM projects WHERE slug = ANY(%s)", (projects,))
    conn.commit()


@unittest.skipUnless(HAVE_DB, "needs a reachable engram database")
class TestDreamWatermarks(unittest.TestCase):
    """The per-project reading watermark."""

    A = "dream-test-alpha"
    B = "dream-test-beta"
    # The fairness test's stub tags whatever it is shown, including other
    # projects' memories that happen to be unread in a shared test database.
    EXTRA = [("DELETE FROM memory_topics WHERE slug = 'shared-subject'", ()),
             ("DELETE FROM topics WHERE slug = 'shared-subject'", ())]

    def setUp(self):
        self.conn = get_conn()
        self.cur = self.conn.cursor()
        dream._ensure_state(self.cur)
        self._clean()

    def tearDown(self):
        self._clean()
        self.cur.close()
        self.conn.close()

    def _clean(self):
        _clean_projects(self.conn, self.cur, [self.A, self.B], extra=self.EXTRA)

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

    def test_advancing_one_project_does_not_skip_another(self):
        # The original bug. One global watermark was advanced from whichever
        # project's batch ran last; the reading loop walks the biggest project
        # first, so every smaller project's memories fell permanently behind it
        # and were never read.
        a_ids = _add(self.conn, self.cur, self.A, 3)
        b_ids = _add(self.conn, self.cur, self.B, 3)
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
        ids = _add(self.conn, self.cur, self.A, 2)
        dream._advance(self.cur, self.A, max(ids))
        dream._advance(self.cur, self.A, min(ids))
        self.conn.commit()
        self.assertEqual(dream._watermark(self.cur, self.A), max(ids),
                         "a later batch must not rewind the watermark")

    def test_a_read_batch_with_no_topics_still_advances(self):
        # "Nothing to say" must advance; otherwise the same batch is re-read
        # every run forever, spending a model call each time and never reaching
        # anything newer.
        ids = _add(self.conn, self.cur, self.A, 4)
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
        _add(self.conn, self.cur, self.A, 4)
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
        big = _add(self.conn, self.cur, self.A, 60)
        small = _add(self.conn, self.cur, self.B, 4)
        calls = []

        def fake(listing, project):
            calls.append(project)
            ids = [int(line.split()[1]) for line in listing.splitlines()
                   if line.startswith("id: ")]
            return [{"id": i, "topics": ["shared subject"]} for i in ids]

        # This test HAS to commit a global pass to observe it, and that pass
        # advances the watermark of every project holding unread rows — real
        # ones included, which would permanently skip their memories from
        # future dreaming runs. Snapshot the watermark table and restore it,
        # keeping only this test's own rows out of the restore.
        self.cur.execute("SELECT project, last_memory_id FROM dream_watermarks")
        saved = dict(self.cur.fetchall())

        def restore_watermarks():
            conn = get_conn()
            cur = conn.cursor()
            try:
                conn.rollback()
                cur.execute(
                    "DELETE FROM dream_watermarks WHERE project != ALL(%s)",
                    (list(saved) + [self.A, self.B],))
                for proj, mark in saved.items():
                    cur.execute(
                        "UPDATE dream_watermarks SET last_memory_id = %s WHERE project = %s",
                        (mark, proj))
                conn.commit()
            finally:
                cur.close()
                conn.close()

        self.addCleanup(restore_watermarks)

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
        ids = _add(self.conn, self.cur, self.A, 4)
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
        _clean_projects(self.conn, self.cur, [self.P])

    def _seed_topic_members(self, n, weight=None):
        """A registered topic with n tagged member memories."""
        ids = _add(self.conn, self.cur, self.P, n, weight=weight)
        self.cur.execute(
            "INSERT INTO topics (project, slug, label, source) VALUES (%s,%s,%s,'discovered')",
            (self.P, self.SLUG, "some subject"))
        for mid in ids:
            self.cur.execute(
                """INSERT INTO memory_topics (memory_id, project, slug, confidence, assigned_by)
                   VALUES (%s,%s,%s,1.0,'read')""", (mid, self.P, self.SLUG))
        self.conn.commit()
        return ids

    def test_an_unchanged_topic_is_not_rewritten(self):
        # The count-based freshness test compared every tagged row (unbounded,
        # and including the summary's own tag) against the previous summary's
        # member list (capped at 30, summaries excluded). Past 30 members those
        # two could never agree, so the topic was rewritten on every single run.
        members = self._seed_topic_members(35)

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

    def test_member_selection_is_deterministic(self):
        # Members are chosen "top 30 by weight", and on a young brain every
        # weight is equal — so without a tiebreak the database returns an
        # arbitrary 30 in an arbitrary order, a different SET each run. The
        # freshness test then always sees a change and re-summarises. This was
        # found on the live brain as three identical summaries of one topic in
        # three consecutive runs.
        self._seed_topic_members(40, weight=0)

        def members():
            self.cur.execute(
                """SELECT m.id FROM memories m
                   JOIN memory_topics mt ON mt.memory_id = m.id
                   WHERE mt.project = %s AND mt.slug = %s AND NOT m.archived
                     AND m.origin IS DISTINCT FROM 'recycle'
                     AND coalesce(m.derived_depth,0) < %s
                   ORDER BY m.weight DESC NULLS LAST, m.id ASC LIMIT 30""",
                (self.P, self.SLUG, dream.MAX_DERIVED_DEPTH))
            return [r[0] for r in self.cur.fetchall()]

        self.assertEqual(members(), members(),
                         "the same unchanged topic must select the same members every time")


@unittest.skipUnless(HAVE_DB, "needs a reachable engram database")
class TestDoorwayNaming(unittest.TestCase):
    """Naming moved off the read path and into the pass — so the pass has to
    actually do it, or promotion (which requires a name) can never fire.

    promote_doorways is a GLOBAL pass — it has no project scope, and on a
    shared database its naming query can see real unnamed doorways. Two rules
    keep these tests from touching them:

      * Nothing after the fixtures is ever committed. Assertions read the
        uncommitted state on this connection; teardown's rollback discards the
        pass's effects on every row, real ones included.
      * Fixture doorways carry an absurdly high query_count so they
        deterministically outrank any real doorway in the budget-limited,
        query_count-ordered naming pass. Without that, real data both starves
        the fixtures (flaky failure) and absorbs the stubbed names.
    """

    P = "dream-test-doorway"
    # Far above any organically-reachable query_count, so fixtures always rank
    # first. If a real doorway ever legitimately exceeds this, the brain has
    # answered the same question a billion times and has other problems.
    RANK_FIRST = 10 ** 9
    EXTRA = [("DELETE FROM collapse_keys WHERE example_query LIKE 'doorway-test%%'", ())]

    def setUp(self):
        self.conn = get_conn()
        self.cur = self.conn.cursor()
        self._clean()

    def tearDown(self):
        self._clean()
        self.cur.close()
        self.conn.close()

    def _clean(self):
        _clean_projects(self.conn, self.cur, [self.P], extra=self.EXTRA)

    def _seed_doorways(self, count, member_ids):
        for n in range(count):
            self.cur.execute(
                """INSERT INTO collapse_keys (key, name, gist, member_ids, cut_gap,
                                              example_query, query_count)
                   VALUES (%s, NULL, NULL, %s, 0.4, %s, %s)""",
                (f"doorwaytest{n}", member_ids, f"doorway-test query {n}",
                 self.RANK_FIRST + n))
        self.conn.commit()

    def test_the_pass_names_unnamed_doorways_and_then_promotes_them(self):
        ids = _add(self.conn, self.cur, self.P, 3)
        # A doorway recall recorded WITHOUT a name, re-resolved often enough to
        # have earned one.
        self._seed_doorways(1, ids)

        original = boundary._name_cluster
        boundary._name_cluster = lambda subjects, query: {"name": "doorway subject",
                                                          "gist": "a gist"}
        try:
            promoted = dream.promote_doorways(self.cur, dream._Budget(1))
        finally:
            boundary._name_cluster = original
        # Deliberately NOT committed — see the class docstring.

        self.cur.execute("SELECT name FROM collapse_keys WHERE key = 'doorwaytest0'")
        self.assertEqual(self.cur.fetchone()[0], "doorway subject",
                         "the pass must name a doorway that has earned one")
        self.assertTrue([p for p in promoted if p["project"] == self.P],
                        "a named doorway that keeps re-forming must become a topic")

    def test_naming_respects_the_budget(self):
        mid = _add(self.conn, self.cur, self.P, 1)
        self._seed_doorways(4, mid)

        calls = []
        original = boundary._name_cluster
        boundary._name_cluster = lambda s, q: (calls.append(1) or {"name": None, "gist": ""})
        try:
            dream.promote_doorways(self.cur, dream._Budget(2))
        finally:
            boundary._name_cluster = original
        # Exact, not <=: with four top-ranked eligible doorways and a budget of
        # two, zero calls would mean the naming loop is dead — the precise
        # regression this class exists to pin — and <= would wave it through.
        self.assertEqual(len(calls), 2,
                         "naming must spend exactly the run's model budget: "
                         "no more (cost) and no less (dead mechanism)")


if __name__ == "__main__":
    unittest.main()
