"""Composition root: python -m local_stream (settings from the environment, see README)."""
import logging
import os
import threading

from local_stream import admin
from local_stream.adapters import consume, send_outbox
from local_stream.repository import SqlRepository
from local_stream.worker import StreamWorker
from spadl import worker as spadl_worker


class Qmark:
    """mssql-python takes `?` parameters; the repository writes pymssql's `%s`. Wraps a connection or cursor."""

    def __init__(self, inner):
        self.inner = inner

    def cursor(self):
        return Qmark(self.inner.cursor())

    def execute(self, sql, params=()):
        return self.inner.execute(sql.replace("%s", "?"), params) if params else self.inner.execute(sql)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def connect():
    if os.environ.get("ETL_SQL_AUTH") == "managed-identity":  # Azure SQL is Entra-only.
        import mssql_python
        return Qmark(mssql_python.connect(
            f"Server=tcp:{os.environ['ETL_SQL_HOST']},1433;Database={os.environ.get('ETL_SQL_DATABASE', 'insidethegame')};"
            "Authentication=ActiveDirectoryMSI;Encrypt=yes;TrustServerCertificate=no", autocommit=False))
    import pymssql
    return pymssql.connect(server=os.environ.get("ETL_SQL_HOST", "sql"), port=os.environ.get("ETL_SQL_PORT", "1433"),
                           user=os.environ.get("ETL_SQL_USER", "sa"), password=os.environ["ETL_SQL_PASSWORD"],
                           database=os.environ.get("ETL_SQL_DATABASE", "insidethegame"), autocommit=False)


def main():
    if os.environ.get("ETL_ROLE") == "admin":
        return admin.main()
    if os.environ.get("ETL_ROLE") == "spadl":
        return spadl_worker.main()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    worker = StreamWorker(SqlRepository(connect), window_seconds=int(os.environ.get("ETL_WINDOW_SECONDS", "60")),
                          idle_seconds=float(os.environ.get("ETL_IDLE_SECONDS", "75")),
                          watermark_idle_seconds=float(os.environ.get("ETL_WATERMARK_IDLE_SECONDS", "3")))
    # The admin purge uses its own connection; the worker lock keeps it apart from batch commits.
    repository = SqlRepository(connect)
    admin.serve(worker, repository, int(os.environ.get("ETL_ADMIN_PORT", "8000")),
                routes=admin.demo_routes(worker, repository))
    spadl_worker.start(connect)  # SPADL post-processor (on Azure: its own app, ETL_ROLE=spadl)
    threading.Thread(target=send_outbox, daemon=True, args=(
        SqlRepository(connect), os.environ["ETL_SERVICEBUS_CONNECTION_STRING"],
        os.environ.get("ETL_NOTIFICATIONS_TOPIC", "match-notifications"))).start()
    consume(worker, os.environ["ETL_EVENTHUB_CONNECTION_STRING"], os.environ.get("ETL_EVENTHUB_NAME", "match-events"),
            os.environ.get("ETL_EVENTHUB_CONSUMER_GROUP", "stream-analytics"))


if __name__ == "__main__":
    main()
