"""Owner admin API: health and the per-match purge (local/contracts.md §5). Locally it runs inside the
worker; on Azure (ETL_ROLE=admin) alone, against Azure SQL, behind a bearer token (ETL_ADMIN_TOKEN)."""
import hmac
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)


def purge_target(body):
    """match_id, or None for {"all": true}; exactly one of the two, else ValueError."""
    if not isinstance(body, dict) or ("match_id" in body) == (body.get("all") is True) or set(body) - {"match_id", "all"}:
        raise ValueError
    if body.get("all") is True:
        return None
    match_id = body["match_id"]
    if not isinstance(match_id, str) or not 0 < len(match_id) <= 64:
        raise ValueError
    return match_id



class SqlPurger:
    """The purge without a worker (Azure): Stream Analytics holds no per-match state to reload."""

    def __init__(self):
        self.lock = threading.Lock()

    def purge(self, match_id, repository):
        from datetime import datetime, timezone
        with self.lock:
            try:
                return repository.purge(match_id, None if match_id else datetime.now(timezone.utc))
            except Exception:
                repository.rollback()
                raise


def serve(worker, repository, port=8000, token=None, routes=()):
    """Start the admin server in a daemon thread; returns the server. With a token, POST needs
    `Authorization: Bearer <token>`. routes: extra (method, path predicate, handler) entries, e.g. the demo
    seeds (local_stream/demo_seeds.py) when DEMO_SEEDS=1; authorised like the purge."""

    class Handler(BaseHTTPRequestHandler):
        def _reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self):
            if token and not hmac.compare_digest(self.headers.get("Authorization", ""), f"Bearer {token}"):
                self._reply(401, {"detail": "Unauthorized"})
                return False
            return True

        def do_GET(self):
            if self.path == "/health":
                return self._reply(200, {"status": "ok", "role": "etl-stream"})
            if (route := self._route("GET")) is not None:
                return route(self) if self._authorized() else None
            self._reply(404, {"detail": "Not found"})

        def _route(self, method):
            return next((fn for m, matches, fn in routes if m == method and matches(self.path)), None)

        def do_POST(self):
            if (route := self._route("POST")) is not None:
                return route(self) if self._authorized() else None
            if self.path != "/admin/matches/purge":
                return self._reply(404, {"detail": "Not found"})
            if not self._authorized():
                return None
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096)))
                match_id = purge_target(body)
            except (ValueError, KeyError, TypeError):
                return self._reply(422, {"detail": 'Send exactly one of {"match_id": "…"} or {"all": true}'})
            try:
                match_ids, counts = worker.purge(match_id, repository)
            except Exception:
                log.exception("Purge of %s failed", match_id or "every match")
                return self._reply(503, {"detail": "Purge failed; retry"})
            log.info("Purged %s %s", match_ids, counts)
            self._reply(200, {"match_ids": match_ids, "purged": counts})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def demo_routes(worker, repository):
    """The demo seed routes when DEMO_SEEDS=1 (PLAN.md §10.6); a production release leaves it off."""
    if os.environ.get("DEMO_SEEDS") != "1":
        return ()
    from local_stream import demo_seeds
    return demo_seeds.routes(worker, demo_seeds.SqlSeeds(repository))


def main():
    """ETL_ROLE=admin: only this API, for Azure where Stream Analytics replaces the worker."""
    from local_stream.__main__ import connect
    from local_stream.repository import SqlRepository

    token = os.environ.get("ETL_ADMIN_TOKEN")
    if not token:  # Internal ingress is not enough: never serve the purge unauthenticated.
        raise SystemExit("ETL_ROLE=admin needs ETL_ADMIN_TOKEN")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    purger, repository = SqlPurger(), SqlRepository(connect)
    serve(purger, repository, int(os.environ.get("ETL_ADMIN_PORT", "8000")), token, demo_routes(purger, repository))
    threading.Event().wait()  # The server runs in a daemon thread.
