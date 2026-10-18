"""PostgreSQL persistence for the disposable, single-run filter lab."""
from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb


class PostgresLabRepository:
    def __init__(self, store):
        self.store = store

    def initialize(self, source_hash, recording_text=None, recording_filename=None):
        with self.store.connect() as conn:
            conn.execute((Path(__file__).parents[2] / "migrations/002_filter_lab.sql").read_text())
            conn.execute((Path(__file__).parents[2] / "migrations/003_lab_recording.sql").read_text())
            conn.execute("INSERT INTO filter_lab_run (run_id, source_hash, recording_text, recording_filename) VALUES (%s,%s,%s,%s) "
                         "ON CONFLICT (singleton) DO NOTHING", (uuid4(), source_hash, recording_text, recording_filename))

    def load(self):
        with self.store.connect() as conn:
            run = conn.execute("SELECT * FROM filter_lab_run").fetchone()
            run["run_id"] = str(run["run_id"])
            rows = conn.execute("SELECT calculation_id,label,rule,result FROM filter_lab_calculations "
                                "WHERE run_id=%s ORDER BY calculation_id", (run["run_id"],)).fetchall()
        return run, rows

    def register(self, run_id, label, rule, result):
        with self.store.connect() as conn:
            conn.execute("INSERT INTO filter_lab_calculations (run_id,calculation_id,label,rule,result) "
                         "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (run_id,calculation_id) DO NOTHING",
                         (run_id, result["calculation_id"], label, Jsonb(rule), Jsonb(result)))

    def progress(self, run_id, position, status, results=()):
        with self.store.connect() as conn:
            cursor = conn.execute("UPDATE filter_lab_run SET position=%s,status=%s WHERE run_id=%s",
                                  (position, status, run_id))
            if cursor.rowcount != 1:
                raise RuntimeError("The lab run was replaced; restart the backend")
            for result in results:
                conn.execute("UPDATE filter_lab_calculations SET result=%s WHERE run_id=%s AND calculation_id=%s",
                             (Jsonb(result), run_id, result["calculation_id"]))

    def reset(self, source_hash):
        with self.store.connect() as conn:
            previous = conn.execute("SELECT recording_text,recording_filename FROM filter_lab_run").fetchone()
            conn.execute("DELETE FROM filter_lab_run")
            conn.execute("INSERT INTO filter_lab_run (run_id,source_hash,recording_text,recording_filename) "
                         "VALUES (%s,%s,%s,%s)",
                         (uuid4(), source_hash, previous["recording_text"], previous["recording_filename"]))

    def replace_recording(self, source_hash, content, filename):
        with self.store.connect() as conn:
            conn.execute("DELETE FROM filter_lab_run")
            conn.execute("INSERT INTO filter_lab_run (run_id,source_hash,recording_text,recording_filename) "
                         "VALUES (%s,%s,%s,%s)",
                         (uuid4(), source_hash, content.decode("utf-8") if content is not None else None, filename))
            return str(conn.execute("SELECT run_id FROM filter_lab_run").fetchone()["run_id"])
