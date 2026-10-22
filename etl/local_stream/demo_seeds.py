"""Demo seeds (PLAN.md §10.6): export one match's ETL rows, or load them under a new matchId.

Restore writes rows in the shapes the stream writes, then has the worker reload its state from SQL as after a
restart, so the run carries on from the seed's seq; no core code knows a demo exists. Mounted on the admin
API only with DEMO_SEEDS=1; a production release leaves it off."""
import hashlib
import json
import logging
import threading
import time
from urllib.parse import parse_qs, urlsplit

from local_stream.repository import MATCH_TABLES, TIME_COLUMNS, _json_value, sql_value
from reference import pipeline

log = logging.getLogger(__name__)
# State tables are replaced after the data rows (Azure insert triggers).
SEED_STATE = ("matchProgress", "matchProgressMarks", "spadlProgress", "localStreamWindows")
MAX_SEED_BYTES = 512 * 1024 * 1024
JSON_CHUNK_ROWS = 5000  # rows per OPENJSON insert
# Canonical seq columns: no row may come from past the seed's seq (rawEvents.seq counts MA3 rows instead).
SEQ_COLUMNS = (("canonicalEvents", "seq"), ("rawEvents", "eventSeq"), ("spadlActions", "seq"),
               ("matchProgress", "seq"), ("matchProgressMarks", "seq"), ("spadlProgress", "seq"))


class RestoreRefused(ValueError):
    pass


def _json_time(column, value):
    """An exported time as the naive UTC ISO text SQL stores; one with an offset is moved to UTC first."""
    if column in TIME_COLUMNS and isinstance(value, str):
        parsed = pipeline.parse_time(value)
        return (parsed if parsed.tzinfo is None else sql_value(column, value)).isoformat(timespec="microseconds")
    return value


class SqlSeeds:
    """Seed reads and writes over the ETL's SQL connection."""

    def __init__(self, repository):
        self.repository = repository
        self.lock = threading.Lock()  # the shared connection (schema, export); restores open their own

    def _present(self, cur):
        cur.execute(f"SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo') AND name IN "
                    f"({', '.join(['%s'] * len(MATCH_TABLES))})", MATCH_TABLES)
        present = {name for (name,) in cur.fetchall()}
        return [t for t in MATCH_TABLES if t in present]

    def schema(self):
        """Fingerprint of the match tables' columns: a seed restores only into the schema it came from."""
        with self.lock:
            conn = self.repository.conn
            cur = conn.cursor()
            present = self._present(cur)
            cur.execute(f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE "
                        f"TABLE_SCHEMA = 'dbo' AND TABLE_NAME IN ({', '.join(['%s'] * len(present))})",
                        tuple(present))
            columns = sorted(list(row) for row in cur.fetchall())
            conn.commit()
        return hashlib.sha256(json.dumps(columns).encode()).hexdigest()[:16]

    def export(self, match_id):
        """Every row this ETL holds for one match, by table."""
        with self.lock:
            conn = self.repository.conn
            cur, tables = conn.cursor(), {}
            for table in self._present(cur):
                cur.execute(f"SELECT * FROM dbo.{table} WHERE matchId = %s", (match_id,))
                columns = [c[0] for c in cur.description]
                tables[table] = [{c: _json_value(v) for c, v in zip(columns, row)} for row in cur.fetchall()]
            conn.commit()
        return tables

    def restore(self, match_id, tables, max_seq):
        """Load a seed under a new matchId in one transaction on its own connection, so several matches restore
        at once. Refused for a known or tombstoned match, rows of another match, or rows past the seed's seq.
        Returns rows per table."""
        conn = self.repository.connect()
        try:
            return self._restore(conn, match_id, tables, max_seq)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _restore(self, conn, match_id, tables, max_seq):
        cur = conn.cursor()
        present = self._present(cur)
        unknown = set(tables) - set(present)
        if unknown:
            raise RestoreRefused(f"Unknown tables {sorted(unknown)}")
        for table, rows in tables.items():
            if any(row.get("matchId") != match_id for row in rows):
                raise RestoreRefused(f"{table} holds rows of another match")
        for table, column in SEQ_COLUMNS:
            if any((row.get(column) or 0) > max_seq for row in tables.get(table, [])):
                raise RestoreRefused(f"{table} past the seed's seq")
        cur.execute("SELECT 1 FROM dbo.purgedMatches WHERE matchId = %s UNION ALL "
                    "SELECT 1 FROM dbo.matches WHERE matchId = %s", (match_id, match_id))
        if cur.fetchone():
            conn.commit()
            raise RestoreRefused(f"{match_id} is already known or purged")
        counts, types = {}, self._types(cur, present)
        order = [t for t in present if t not in SEED_STATE] + [t for t in present if t in SEED_STATE]
        for table in order:
            rows = tables.get(table, [])
            if table in SEED_STATE:
                cur.execute(f"DELETE FROM dbo.{table} WHERE matchId = %s", (match_id,))
            for columns in {tuple(row) for row in rows}:
                part = [{c: _json_time(c, row[c]) for c in columns} for row in rows if tuple(row) == columns]
                # One OPENJSON statement per chunk: a multi-row VALUES list is compiled per batch, about
                # 1 s per thousand rows on SQL Server.
                shape = ", ".join(f"[{c}] {types[table][c]} '$.\"{c}\"'" for c in columns)
                names = ", ".join(f"[{c}]" for c in columns)
                for i in range(0, len(part), JSON_CHUNK_ROWS):
                    cur.execute(f"INSERT dbo.{table} ({names}) SELECT {names} FROM OPENJSON(%s) WITH ({shape})",
                                (json.dumps(part[i:i + JSON_CHUNK_ROWS]),))
            counts[table] = len(rows)
        conn.commit()
        return counts

    def _types(self, cur, present):
        """{table: {column: SQL type for OPENJSON WITH}} of the match tables."""
        cur.execute(f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, "
                    f"NUMERIC_SCALE, DATETIME_PRECISION FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = 'dbo' "
                    f"AND TABLE_NAME IN ({', '.join(['%s'] * len(present))})", tuple(present))
        types = {}
        for table, column, kind, length, precision, scale, time_precision in cur.fetchall():
            if kind in ("nvarchar", "varchar", "char", "nchar"):
                kind = f"{kind}({'max' if length == -1 else length})"
            elif kind in ("decimal", "numeric"):
                kind = f"{kind}({precision},{scale})"
            elif kind == "datetime2":
                kind = f"datetime2({time_precision})"
            types.setdefault(table, {})[column] = kind
        return types

    def rollback(self):
        with self.lock:
            self.repository.rollback()


def export(worker, seeds, match_id):
    """(schema fingerprint, rows by table)."""
    with worker.lock:
        try:
            return seeds.schema(), seeds.export(match_id)
        except Exception:
            seeds.rollback()
            raise


def restore(worker, seeds, match_id, tables, max_seq, schema):
    """Load a seed, then reload the worker's match and window state from SQL (as after a restart)."""
    began = time.monotonic()
    try:  # The rows go in outside the worker's lock (their own transaction); only the reload takes it.
        if schema != seeds.schema():
            raise RestoreRefused("The seed was exported from another ETL schema; record it again")
        counts = seeds.restore(match_id, tables, max_seq)
    except Exception:
        seeds.rollback()
        raise
    written = time.monotonic()
    if hasattr(worker, "load"):
        worker.load()
    log.info("Restore of %s wrote rows in %.1fs, reloaded state in %.1fs", match_id, written - began,
             time.monotonic() - written)
    return counts


def routes(worker, seeds):
    """Admin routes for admin.serve(routes=…): GET /admin/matches/export?match_id=…, POST /admin/matches/restore."""

    def do_export(handler):
        match_id = (parse_qs(urlsplit(handler.path).query).get("match_id") or [""])[0]
        if not 0 < len(match_id) <= 64:
            return handler._reply(422, {"detail": "Invalid match_id"})
        try:
            schema, tables = export(worker, seeds, match_id)
            return handler._reply(200, {"match_id": match_id, "schema": schema, "tables": tables})
        except Exception:
            log.exception("Export of %s failed", match_id)
            return handler._reply(503, {"detail": "Export failed; retry"})

    def do_restore(handler):
        try:
            length = int(handler.headers.get("Content-Length") or 0)
            if length > MAX_SEED_BYTES:
                return handler._reply(413, {"detail": "Seed too large"})
            body = json.loads(handler.rfile.read(length))
            match_id, tables, max_seq, schema = body["match_id"], body["tables"], int(body["max_seq"]), body["schema"]
            if not isinstance(match_id, str) or not 0 < len(match_id) <= 64 or not isinstance(tables, dict) \
                    or not isinstance(schema, str):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return handler._reply(422, {"detail": 'Send {"match_id", "max_seq", "schema", "tables": {table: [rows]}}'})
        try:
            counts = restore(worker, seeds, match_id, tables, max_seq, schema)
        except RestoreRefused as exc:
            return handler._reply(409, {"detail": str(exc)})
        except Exception:
            log.exception("Restore of %s failed", match_id)
            return handler._reply(503, {"detail": "Restore failed; retry"})
        log.info("Restored %s %s", match_id, counts)
        return handler._reply(200, {"match_id": match_id, "restored": counts})

    return (("GET", lambda path: path.startswith("/admin/matches/export?match_id="), do_export),
            ("POST", lambda path: path == "/admin/matches/restore", do_restore))
