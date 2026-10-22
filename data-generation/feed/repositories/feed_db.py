"""The feed's own Postgres database: recordings catalogue, runs and purge tombstones."""
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
RUN_COLUMNS = ("run_id::text AS run_id, match_id, fixture, kickoff, created_at, status, position, seq, hold_seconds, "
               "resume_seconds, start_point, hold_point")
DEMO_COLUMNS = "fixtures, main_fixture, stagger_seconds, max_active_runs, start_points, skip_targets, revision"


class FeedRepository:
    def __init__(self, url):
        self.url = url

    def _connect(self):
        return psycopg.connect(self.url, row_factory=dict_row)

    def migrate(self):
        """Create the database if needed, then apply new migrations in order."""
        params = conninfo_to_dict(self.url)
        name = params.get("dbname")
        with psycopg.connect(make_conninfo(self.url, dbname="postgres"), autocommit=True) as admin:
            if name and not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone():
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        with self._connect() as db:
            db.execute("SELECT pg_advisory_xact_lock(7262001)")
            db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, "
                       "applied_at timestamptz NOT NULL DEFAULT now())")
            applied = {r["version"] for r in db.execute("SELECT version FROM schema_migrations")}
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.stem not in applied:
                    db.execute(path.read_text())
                    db.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))

    def sync_recordings(self, entries):
        with self._connect() as db:
            for e in entries:
                db.execute(
                    "INSERT INTO recordings (fixture, source_match_id, description, teams, duration_seconds, "
                    "capabilities, synthetic, sha256) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (fixture) DO UPDATE SET source_match_id = excluded.source_match_id, "
                    "description = excluded.description, teams = excluded.teams, "
                    "duration_seconds = excluded.duration_seconds, capabilities = excluded.capabilities, "
                    "synthetic = excluded.synthetic, sha256 = excluded.sha256, updated_at = now()",
                    (e["fixture"], e["source_match_id"], e["description"], Jsonb(e["teams"]),
                     e["duration_seconds"], Jsonb(e["capabilities"]), e["synthetic"], e["sha256"]))
            db.execute("DELETE FROM recordings WHERE NOT (fixture = ANY(%s))", ([e["fixture"] for e in entries],))

    def recordings(self):
        with self._connect() as db:
            return db.execute("SELECT fixture, source_match_id, description, teams, duration_seconds, "
                              "capabilities, synthetic FROM recordings ORDER BY fixture").fetchall()

    def create_run(self, run_id, match_id, fixture, kickoff, hold_seconds=None, resume_seconds=None, start_point=None,
                   hold_point=None):
        with self._connect() as db:
            if db.execute("SELECT 1 FROM purged_matches WHERE match_id = %s", (match_id,)).fetchone():
                return None
            return db.execute(f"INSERT INTO runs (run_id, match_id, fixture, kickoff, status, hold_seconds, "
                              f"resume_seconds, start_point, hold_point) VALUES (%s, %s, %s, %s, 'scheduled', %s, %s, %s, %s) "
                              f"RETURNING {RUN_COLUMNS}",
                              (run_id, match_id, fixture, kickoff, hold_seconds, resume_seconds, start_point,
                               hold_point)).fetchone()

    def release(self, match_id, kickoff):
        """Start a run that waited for its seed to be restored; None if it was not waiting."""
        with self._connect() as db:
            return db.execute(f"UPDATE runs SET kickoff = %s, resume_seconds = NULL WHERE match_id = %s "
                              f"AND resume_seconds IS NOT NULL RETURNING {RUN_COLUMNS}", (kickoff, match_id)).fetchone()

    def shift_kickoff(self, match_id, seconds):
        """Demo fast-forward: the run's clock reads `seconds` later. None if the run is gone or finished."""
        with self._connect() as db:
            return db.execute(f"UPDATE runs SET kickoff = kickoff - make_interval(secs => %s) WHERE match_id = %s "
                              f"AND status <> 'finished' RETURNING {RUN_COLUMNS}", (seconds, match_id)).fetchone()

    def runs(self):
        with self._connect() as db:
            # A purge interrupted between tombstone and delete must not revive its runs.
            return db.execute(
                f"SELECT {RUN_COLUMNS} FROM runs WHERE match_id NOT IN (SELECT match_id FROM purged_matches) "
                "AND created_at > COALESCE((SELECT cutoff FROM purge_cutoff), '-infinity') "
                "ORDER BY kickoff, match_id").fetchall()

    def progress(self, run_id, position, seq, status):
        with self._connect() as db:
            db.execute("UPDATE runs SET position = %s, seq = %s, status = %s WHERE run_id = %s",
                       (position, seq, status, run_id))

    def tombstone(self, match_ids, *, cutoff=False):
        """cutoff: also record now (the database clock, as created_at) as the `all` cut-off."""
        with self._connect() as db:
            for match_id in match_ids:
                db.execute("INSERT INTO purged_matches (match_id) VALUES (%s) ON CONFLICT DO NOTHING", (match_id,))
            if cutoff:
                db.execute("INSERT INTO purge_cutoff (cutoff) VALUES (now()) "
                           "ON CONFLICT (singleton) DO UPDATE SET cutoff = excluded.cutoff")

    def demo_settings(self):
        with self._connect() as db:
            return db.execute(f"SELECT {DEMO_COLUMNS} FROM demo_settings").fetchone()

    def save_demo_settings(self, settings, expected_revision):
        """None when another editor saved first."""
        with self._connect() as db:
            return db.execute(
                f"UPDATE demo_settings SET fixtures = %s, main_fixture = %s, stagger_seconds = %s, "
                f"max_active_runs = %s, start_points = %s, skip_targets = COALESCE(%s, skip_targets), "
                f"revision = revision + 1 WHERE revision = %s RETURNING {DEMO_COLUMNS}",
                (list(settings["fixtures"]), settings["main_fixture"], settings["stagger_seconds"],
                 settings["max_active_runs"], Jsonb(settings["start_points"]),
                 Jsonb(settings["skip_targets"]) if settings.get("skip_targets") is not None else None,
                 expected_revision)).fetchone()

    def delete_runs(self, match_ids):
        with self._connect() as db:
            return db.execute("DELETE FROM runs WHERE match_id = ANY(%s)", (list(match_ids),)).rowcount
