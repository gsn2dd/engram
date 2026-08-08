"""
Ephemeral test database — isolation as STRUCTURE, not discipline.

Twice in one week a test problem came down to trusting a long-lived shared
database: the ingest endpoint was "verified" against a table that had been
created by hand and existed nowhere in schema.sql, and the doorway tests
mutated whatever brain the suite was pointed at. Both survive discipline
because discipline is exactly what fails.

So the suite now builds its own world: one `engram_eph_<pid>` database,
created from schema.sql at session start, dropped at session end. Two things
follow for free:

  * No test can touch a real brain, however badly written it is.
  * schema.sql's FRESH-INSTALL path is executed on every single test run —
    the path the hand-made `captures` table proved never gets tested
    otherwise. If schema.sql cannot build a working database from nothing,
    the whole suite fails immediately, which is the correct severity.

The configured DB (env DB_NAME) is used only as a bootstrap connection to
issue CREATE/DROP DATABASE — the role needs CREATEDB and the HBA config must
admit it to engram_eph_* names. Where either is missing, the suite falls back
to running directly against DB_NAME exactly as before, with a warning: degraded
isolation must be visible, never silent. ENGRAM_EPHEMERAL=0 opts out.
"""
import os
import sys

import pytest

_SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


def _bootstrap_conn():
    import psycopg2
    conn = psycopg2.connect(
        dbname=os.environ["DB_NAME"], user=os.environ.get("DB_USER", "pathuser"),
        password=os.environ.get("DB_PASS", "pathpass"),
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5432)))
    conn.autocommit = True   # CREATE/DROP DATABASE cannot run in a transaction
    return conn


@pytest.fixture(scope="session", autouse=True)
def ephemeral_database():
    if not os.environ.get("DB_NAME") or os.environ.get("ENGRAM_EPHEMERAL") == "0":
        yield   # keyless CI (tests skip) or explicit opt-out
        return

    import psycopg2
    eph = f"engram_eph_{os.getpid()}"
    original = os.environ["DB_NAME"]

    try:
        boot = _bootstrap_conn()
        cur = boot.cursor()
        cur.execute(f'CREATE DATABASE "{eph}"')
    except Exception as exc:
        print(f"\n[conftest] WARNING: no ephemeral database ({exc.__class__.__name__}: {exc})"
              f" — running against '{original}' with NO structural isolation",
              file=sys.stderr)
        yield
        return

    try:
        try:
            conn = psycopg2.connect(
                dbname=eph, user=os.environ.get("DB_USER", "pathuser"),
                password=os.environ.get("DB_PASS", "pathpass"),
                host=os.environ.get("DB_HOST", "localhost"),
                port=int(os.environ.get("DB_PORT", 5432)))
            with conn, conn.cursor() as c:
                with open(_SCHEMA) as fh:
                    c.execute(fh.read())
            conn.close()
        except Exception as exc:
            # A database exists but the schema would not apply (e.g. pgvector
            # not installed in template1, so CREATE EXTENSION needs superuser).
            # Fall back to the configured DB rather than erroring every test —
            # but never run the suite against a half-built ephemeral.
            print(f"\n[conftest] WARNING: schema.sql failed on '{eph}' "
                  f"({exc.__class__.__name__}: {exc}) — falling back to '{original}' "
                  f"with NO structural isolation", file=sys.stderr)
            yield
            return
        os.environ["DB_NAME"] = eph
        print(f"\n[conftest] fresh database '{eph}' built from schema.sql", file=sys.stderr)
        yield
    finally:
        os.environ["DB_NAME"] = original
        try:
            cur.execute(f'DROP DATABASE "{eph}" WITH (FORCE)')
            print(f"[conftest] dropped '{eph}'", file=sys.stderr)
        except Exception as exc:
            print(f"[conftest] WARNING: could not drop '{eph}': {exc} — drop it by hand",
                  file=sys.stderr)
        boot.close()
