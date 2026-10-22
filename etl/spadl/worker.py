"""SPADL post-processor: converts each match's committed MA3 rows into final SPADL actions.

The same code runs locally (a thread in etl-stream) and on Azure (ETL_ROLE=spadl, its own Container App);
Stream Analytics is unchanged. It reads only SQL: matchProgress.seq (the watermark P) and rawEvents with
eventSeq <= P, which are then complete. Per match and step it restarts from the last stored non-dribble action,
converts the rows since (reference.spadl), stores the actions that are final at P and sets spadlProgress = P,
in one transaction. Stateless: a restart or a second replica recomputes the same rows (inserts ignore
duplicates). Writes hold the purge lock shared and skip tombstoned matches, so a purge is never undone.
Idle, the poll backs off; on Azure it then closes SQL and waits for the hub to receive (serverless auto-pause).
"""
import json
import logging
import os
import threading
import time

from reference import spadl

log = logging.getLogger(__name__)
COLUMNS = ["matchId", *spadl.COLUMNS]
BATCH = 2000 // len(COLUMNS)


class SpadlRepository:
    def __init__(self, connect):
        self.connect, self._conn = connect, None

    @property
    def conn(self):
        """Opened on first use, and again after close()."""
        if self._conn is None:
            self._conn = self.connect()
        return self._conn

    def close(self):
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def pending(self):
        """[(matchId, watermark P, spadlSeq, home contestant)] for live matches whose SPADL lags P."""
        cur = self.conn.cursor()
        cur.execute("""SELECT p.matchId, p.seq, ISNULL(s.seq, 0), m.homeContestantId
                       FROM dbo.matchProgress AS p
                       JOIN dbo.matches AS m ON m.matchId = p.matchId
                       LEFT JOIN dbo.spadlProgress AS s ON s.matchId = p.matchId
                       WHERE p.seq > ISNULL(s.seq, 0)
                         AND NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS g WHERE g.matchId = p.matchId)
                       ORDER BY p.matchId""")
        rows = cur.fetchall()
        self.conn.commit()
        return rows

    def tail(self, match_id, upto):
        """(MA3 messages from the restart row with eventSeq <= upto, the restart (actionId, finalSeq), last
        stored actionId)."""
        cur = self.conn.cursor()
        cur.execute("""SELECT TOP (1) a.actionId, r.seq, a.finalSeq
                       FROM dbo.spadlActions AS a
                       JOIN dbo.rawEvents AS r ON r.matchId = a.matchId AND r.id = a.originalEventId
                       WHERE a.matchId = %s ORDER BY a.actionId DESC""", (match_id,))
        restart = cur.fetchone()
        cur.execute("SELECT MAX(actionId) FROM dbo.spadlActions WHERE matchId = %s", (match_id,))
        (last,) = cur.fetchone()
        cur.execute("""SELECT payload FROM dbo.rawEvents
                       WHERE matchId = %s AND seq >= %s AND eventSeq <= %s
                       ORDER BY seq""", (match_id, restart[1] if restart else 0, upto))
        messages = [json.loads(p) for (p,) in cur.fetchall()]
        self.conn.commit()
        return messages, ((restart[0], restart[2]) if restart else (0, 0)), (-1 if last is None else last)

    def write(self, match_id, actions, upto):
        """Store final actions and spadlSeq = upto together; skipped (False) for a purged match."""
        cur = self.conn.cursor()
        cur.execute("EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Shared', @LockOwner = N'Transaction'")
        cur.execute("""SELECT COUNT(*) FROM dbo.matches AS m WHERE m.matchId = %s
                         AND NOT EXISTS (SELECT 1 FROM dbo.purgedMatches AS g WHERE g.matchId = m.matchId)""", (match_id,))
        if not cur.fetchone()[0]:
            self.conn.rollback()
            return False
        row = "(" + ", ".join(["%s"] * len(COLUMNS)) + ")"
        for i in range(0, len(actions), BATCH):  # Multi-row inserts, within SQL Server's 2,100 parameters.
            chunk = actions[i:i + BATCH]
            cur.execute(f"INSERT dbo.spadlActions ({', '.join(COLUMNS)}) VALUES {', '.join([row] * len(chunk))}",
                        tuple(match_id if c == "matchId" else a[c] for a in chunk for c in COLUMNS))
        cur.execute("""MERGE dbo.spadlProgress AS t USING (SELECT %s AS matchId, %s AS seq) AS s ON t.matchId = s.matchId
                       WHEN MATCHED AND s.seq > t.seq THEN UPDATE SET seq = s.seq
                       WHEN NOT MATCHED THEN INSERT (matchId, seq) VALUES (s.matchId, s.seq);""", (match_id, upto))
        self.conn.commit()
        return True

    def rollback(self):
        try:
            if self._conn is not None:
                self._conn.rollback()
        except Exception:
            self.close()  # Reconnects on next use.


class SpadlWorker:
    """poll_seconds doubles while idle, up to max_poll_seconds. With `activity` (a callable whose value changes
    when new input arrives: Event Hubs' last enqueued sequence numbers), after idle_seconds without work it closes
    its SQL connection and polls only `activity`, so a serverless database can auto-pause."""

    def __init__(self, repository, poll_seconds=0.5, max_poll_seconds=5.0, idle_seconds=300.0, activity=None,
                 clock=time.monotonic):
        self.repository, self.poll_seconds, self.max_poll_seconds = repository, poll_seconds, max(poll_seconds, max_poll_seconds)
        self.idle_seconds, self.activity, self.clock = idle_seconds, activity, clock

    def step(self):
        """Advance every lagging match to its watermark; returns {matchId: actions stored}."""
        done = {}
        for match_id, upto, _, home in self.repository.pending():
            messages, (first, floor), last = self.repository.tail(match_id, upto)
            actions = [a for a in spadl.final_actions(messages, home, first, floor) if a["actionId"] > last]
            if self.repository.write(match_id, actions, upto):
                done[match_id] = len(actions)
        return done

    def run(self, stop=None):
        stop = stop or threading.Event()
        wait, idle_since = self.poll_seconds, None
        while not stop.is_set():
            try:
                busy = self.step()
            except Exception as exc:
                log.warning("SPADL step failed; retrying (%s: %s)", type(exc).__name__, exc)
                self.repository.rollback()
                busy = None
            if busy:
                wait, idle_since = self.poll_seconds, None
                continue
            idle_since = self.clock() if idle_since is None else idle_since
            if self.activity and self.clock() - idle_since >= self.idle_seconds:
                self.sleep_until_activity(stop)
                wait, idle_since = self.poll_seconds, None
            else:
                stop.wait(wait)
                wait = min(wait * 2, self.max_poll_seconds)

    def sleep_until_activity(self, stop):
        """Close SQL and wait until `activity` changes (or fails: then SQL is checked again)."""
        try:
            mark = self.activity()
        except Exception as exc:
            log.warning("SPADL activity check failed; polling SQL (%s)", type(exc).__name__)
            return
        self.repository.close()
        log.info("SPADL idle: SQL connection closed until new input arrives")
        while not stop.wait(self.max_poll_seconds):
            try:
                if self.activity() != mark:
                    break
            except Exception as exc:
                log.warning("SPADL activity check failed; polling SQL (%s)", type(exc).__name__)
                break
        log.info("SPADL resumed")


def hub_activity(connection_string, hub):
    """Last enqueued sequence number per partition of the match-events hub: changes whenever a feed sends.
    Reads partition properties only; consumes nothing."""
    from azure.eventhub import EventHubConsumerClient
    client = EventHubConsumerClient.from_connection_string(connection_string, consumer_group="$Default",
                                                           eventhub_name=hub)
    return lambda: tuple(client.get_partition_properties(p)["last_enqueued_sequence_number"]
                         for p in sorted(client.get_partition_ids()))


def settings():
    env = os.environ.get
    return {"poll_seconds": float(env("ETL_SPADL_POLL_SECONDS", "0.5")),
            "max_poll_seconds": float(env("ETL_SPADL_MAX_POLL_SECONDS", "5")),
            "idle_seconds": float(env("ETL_SPADL_IDLE_SECONDS", "300"))}


def start(connect):
    """The etl-stream task: a daemon thread on its own connection (local SQL does not pause: no activity check)."""
    worker = SpadlWorker(SpadlRepository(connect), **settings())
    threading.Thread(target=worker.run, daemon=True, name="spadl").start()
    return worker


def main():
    """ETL_ROLE=spadl (Azure): only the post-processor, against Azure SQL; idle until the hub receives."""
    from local_stream.__main__ import connect
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    hub = os.environ.get("ETL_EVENTHUB_CONNECTION_STRING")
    activity = hub_activity(hub, os.environ.get("ETL_EVENTHUB_NAME", "match-events")) if hub else None
    log.info("SPADL post-processor started (idle wake-up: %s)", "Event Hubs" if activity else "none")
    SpadlWorker(SpadlRepository(connect), activity=activity, **settings()).run()
