"""Owns only Accounts reads and Match App viewer state. No upstream data store."""
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .domain import RuleError


class Store:
    def __init__(self, accounts_dsn, match_dsn, schema="user_backend"):
        self.accounts_dsn, self.match_dsn, self.schema = accounts_dsn, match_dsn, schema

    def connect(self):
        conn = psycopg.connect(self.match_dsn, row_factory=dict_row, connect_timeout=5)
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema)))
        return conn

    def initialize(self):
        # One idempotent foundation migration; add versioned migrations before schema changes.
        with self.connect() as conn:
            conn.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
            conn.execute((Path(__file__).parent.parent / "migrations/001_viewers.sql").read_text())

    def profiles(self):
        with psycopg.connect(self.accounts_dsn, row_factory=dict_row, connect_timeout=5) as conn:
            return conn.execute("SELECT id, display_name, team, fan_style FROM demo_profiles ORDER BY id").fetchall()

    def ready(self):
        self.profiles()
        with self.connect() as conn:
            conn.execute("SELECT 1 FROM viewers LIMIT 1")

    def start(self, match_id, profile_id):
        profile = next((p for p in self.profiles() if p["id"] == profile_id), None)
        if profile is None:
            raise RuleError("profile_not_found", "Unknown demo profile", 404)
        token = uuid.uuid4()
        initial = {"team": profile["team"], "fan_style": profile["fan_style"], "pins": []}
        with self.connect() as conn:
            row = conn.execute(
                "INSERT INTO viewers (match_id, profile_id, token, state) VALUES (%s,%s,%s,%s) "
                "ON CONFLICT (match_id, profile_id) DO UPDATE SET token=EXCLUDED.token RETURNING *",
                (match_id, profile_id, token, Jsonb(initial)),
            ).fetchone()
        return row

    def read(self, token, match_id):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM viewers WHERE token=%s AND match_id=%s", (token, match_id)).fetchone()
        if row is None:
            raise RuleError("session_replaced", "Start a new session; this session is no longer active")
        return row

    def change(self, token, match_id, update):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM viewers WHERE token=%s AND match_id=%s FOR UPDATE", (token, match_id)).fetchone()
            if row is None:
                raise RuleError("session_replaced", "This session is no longer active")
            update(row["state"])
            conn.execute("UPDATE viewers SET state=%s WHERE token=%s", (Jsonb(row["state"]), token))
        return row
