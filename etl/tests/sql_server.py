"""Disposable SQL Server databases for the SQL tests (never a shared stack). Each test creates and drops its own:
    ETL_TEST_SQL_PASSWORD=… [ETL_TEST_SQL_HOST=127.0.0.1 ETL_TEST_SQL_PORT=1433] pytest tests/test_sql_*.py
"""
import os
import re
import uuid
from pathlib import Path

import pytest

pymssql = pytest.importorskip("pymssql")
enabled = pytest.mark.skipif(not os.environ.get("ETL_TEST_SQL_PASSWORD"), reason="set ETL_TEST_SQL_PASSWORD")
ETL = Path(__file__).resolve().parents[1]
STREAM_SCRIPTS = [*sorted((ETL / "sql" / "migrations").glob("*.sql")), ETL / "local_stream" / "state.sql"]


class Connector:
    """Calling it opens a new connection (the code under test owns its connections). `shared` is one connection
    the test's own reads and writes reuse: a login costs ~0.3 s on an emulated SQL Server."""

    def __init__(self, database="master", autocommit=False):
        self.database, self.autocommit, self._shared = database, autocommit, None

    def __call__(self):
        return pymssql.connect(server=os.environ.get("ETL_TEST_SQL_HOST", "127.0.0.1"),
                               port=os.environ.get("ETL_TEST_SQL_PORT", "1433"), user="sa",
                               password=os.environ["ETL_TEST_SQL_PASSWORD"], database=self.database,
                               autocommit=self.autocommit)

    @property
    def shared(self):
        if self._shared is None:
            self._shared = self()
        return self._shared

    def close(self):
        if self._shared is not None:
            self._shared.close()
            self._shared = None


def database(prefix, scripts):
    """Fixture body: a fresh database with `scripts` applied (batches split at GO); dropped afterwards."""
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    with Connector(autocommit=True)() as master:
        master.cursor().execute(f"CREATE DATABASE [{name}]")
    with Connector(name, autocommit=True)() as conn:
        for script in scripts:
            for batch in re.split(r"^GO\s*$", script.read_text(encoding="utf-8"), flags=re.M):
                if batch.strip():
                    conn.cursor().execute(batch)
    connect = Connector(name)
    yield connect
    connect.close()
    with Connector(autocommit=True)() as master:
        master.cursor().execute(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [{name}]")


def query(connect, sql, *params):
    conn = connect.shared
    cur = conn.cursor(as_dict=True)
    cur.execute(sql, params)
    rows = cur.fetchall() if cur.description else []
    conn.commit()
    return rows


def stats(connect, match_id, seq):
    return query(connect, "EXEC dbo.statsAtSeq @matchId = %s, @seq = %s", match_id, seq)


def convert(connect):
    """One post-processor step (every lagging match to its watermark), on the test's post-processor connection."""
    if not hasattr(connect, "spadl"):
        from spadl.worker import SpadlRepository, SpadlWorker
        connect.spadl = SpadlWorker(SpadlRepository(connect))
    return connect.spadl.step()
