"""Pooled connections and versioned migrations for the Accounts and Match App databases."""
import importlib.util
import os
import threading
from pathlib import Path

from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

MIGRATIONS = Path(__file__).parent.parent / "migrations"
LOCK = 7_310_001  # pg_advisory_xact_lock key: one migrator at a time per database.


class Store:
    def __init__(self, accounts_dsn, match_dsn, schema="user_backend", *, pool_size=None):
        self.accounts_dsn, self.match_dsn, self.schema = accounts_dsn, match_dsn, schema
        self.pool_size = pool_size or int(os.getenv("POSTGRES_POOL_SIZE", "10"))
        self._pools, self._lock = {}, threading.Lock()

    def _pool(self, name, dsn, **kwargs):
        with self._lock:
            if name not in self._pools:
                # Opening a connection costs a TCP and authentication round trip; reuse them.
                self._pools[name] = ConnectionPool(dsn, min_size=1, max_size=self.pool_size, timeout=10, open=True,
                                                   kwargs={"row_factory": dict_row, "connect_timeout": 5, **kwargs})
            return self._pools[name]

    def connect(self):
        """One transaction on a pooled Match App connection: commit on success, roll back on error."""
        return self._pool("match", self.match_dsn, options=f"-c search_path={self.schema}").connection()

    def connect_accounts(self):
        return self._pool("accounts", self.accounts_dsn).connection()

    def close(self):
        with self._lock:
            pools, self._pools = list(self._pools.values()), {}
        for pool in pools:
            pool.close()

    def initialize(self):
        """Apply each migration file once, in name order (Match App: migrations/*.sql and data
        migrations/NNN_*.py in this schema; Accounts: migrations/accounts/*.sql)."""
        with self.connect() as conn:
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(self.schema)))
            migrate(conn, sorted([*MIGRATIONS.glob("*.sql"), *MIGRATIONS.glob("[0-9]*.py")], key=lambda p: p.name))
        with self.connect_accounts() as conn:
            migrate(conn, sorted((MIGRATIONS / "accounts").glob("*.sql")))

    def profiles(self):
        with self.connect_accounts() as conn:
            return conn.execute("SELECT id, display_name, selections FROM demo_profiles ORDER BY id").fetchall()

    def ready(self):
        self.profiles()
        with self.connect() as conn:
            conn.execute("SELECT 1 FROM schema_migrations LIMIT 1")


def migrate(conn, files):
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, "
                 "applied_at timestamptz NOT NULL DEFAULT now())")
    applied = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}
    for path in files:
        if path.name not in applied:
            if path.suffix == ".py":
                # A data migration: its migrate(conn) runs in this transaction.
                spec = importlib.util.spec_from_file_location(f"migration_{path.stem}", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.migrate(conn)
            else:
                conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
