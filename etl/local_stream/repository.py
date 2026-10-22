"""SQL Server writes for the local stream worker. One transaction per Event Hubs batch."""
import json
from datetime import date, datetime, timezone
from decimal import Decimal

from reference import pipeline

TABLES = pipeline.TABLES
# Every table holding one match's data; a purge empties those that exist (Azure SQL has no local* tables).
MATCH_TABLES = (*TABLES, "matchProgress", "matchProgressMarks", "spadlActions", "spadlProgress",
                "localStreamWindows")
TIME_COLUMNS = {"eventTime", "windowEnd", "scheduledKickoff"}


def _json_value(value):
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def sql_value(column, value):
    if column in TIME_COLUMNS and isinstance(value, str):
        return pipeline.parse_time(value).astimezone(timezone.utc).replace(tzinfo=None)
    return value


def naive(t):
    return t.astimezone(timezone.utc).replace(tzinfo=None)


class SqlRepository:
    def __init__(self, connect):
        self.connect = connect
        self.conn = connect()

    def reconnect(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.conn = self.connect()

    def load(self):
        """Closed windows, checkpoints, raw messages still in open windows, per-match progress and tombstones."""
        cur = self.conn.cursor()
        cur.execute("SELECT matchId, closedUntil FROM dbo.localStreamWindows")
        closed = {m: t.replace(tzinfo=timezone.utc) for m, t in cur.fetchall()}
        cur.execute("SELECT partitionId, sequenceNumber FROM dbo.localStreamCheckpoints")
        checkpoints = dict(cur.fetchall())
        cur.execute("""SELECT r.payload FROM dbo.rawEvents r
                       LEFT JOIN dbo.localStreamWindows w ON w.matchId = r.matchId
                       WHERE r.eventTime > ISNULL(w.closedUntil, '0001-01-01')
                         AND r.ingestedAt > DATEADD(day, -1, sysutcdatetime())
                       ORDER BY r.matchId, r.seq""")
        pending = [json.loads(p) for (p,) in cur.fetchall()]
        cur.execute("""SELECT m.matchId, TRY_CAST(JSON_VALUE(m.capabilities, '$.periods') AS int), m.status,
                              ISNULL((SELECT MAX(seq) FROM dbo.canonicalEvents e WHERE e.matchId = m.matchId), 0),
                              ISNULL(p.seq, 0),
                              ISNULL((SELECT MAX(sampleId) FROM dbo.possessionSamples s WHERE s.matchId = m.matchId), 0),
                              (SELECT MIN(seq) FROM dbo.canonicalEvents e WHERE e.matchId = m.matchId AND e.deleted = 0
                                 AND e.eventType = 'period_end'
                                 AND e.periodId = TRY_CAST(JSON_VALUE(m.capabilities, '$.periods') AS int))
                       FROM dbo.matches m LEFT JOIN dbo.matchProgress p ON p.matchId = m.matchId""")
        matches = {m: {"periods": periods, "status": status, "seq": seq, "watermark": watermark, "sample": sample,
                       "final": final}
                   for m, periods, status, seq, watermark, sample, final in cur.fetchall()}
        cur.execute("SELECT matchId FROM dbo.purgedMatches")
        purged = {m for (m,) in cur.fetchall()}
        cur.execute("SELECT cutoffAt FROM dbo.purgeCutoff")
        cutoff = next((t.replace(tzinfo=timezone.utc) for (t,) in cur.fetchall()), None)
        self.conn.commit()
        return {"closed": closed, "checkpoints": checkpoints, "pending": pending, "matches": matches,
                "purged": purged, "cutoff": cutoff}

    def seen(self, match_id, event_id):
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM dbo.rawEvents WHERE matchId = %s AND id = %s", (match_id, event_id))
        return cur.fetchone() is not None

    def write(self, out, closed, checkpoint=None, progress=None):
        """Rows, outbox, closed windows, match progress and the Event Hubs checkpoint commit together.
        progress: {matchId: (watermark seq, status)}."""
        cur = self.conn.cursor()
        for table in TABLES:
            # Multi-row inserts: one round trip per ~2,000 parameters, not one per row.
            groups = {}
            for row in out.rows.get(table, []):
                groups.setdefault(tuple(row), []).append(row)
            for columns, rows in groups.items():
                size = max(1, min(1000, 2000 // len(columns)))  # SQL Server: 2,100 parameters, 1,000 rows
                for i in range(0, len(rows), size):
                    part = rows[i:i + size]
                    values = ", ".join(["(" + ", ".join(["%s"] * len(columns)) + ")"] * len(part))
                    cur.execute(f"INSERT dbo.{table} ({', '.join(columns)}) VALUES {values}",
                                tuple(sql_value(c, row[c]) for row in part for c in columns))
        for n in out.notifications:
            body = pipeline.notification_body(n)
            cur.execute("INSERT dbo.localStreamOutbox (messageId, notificationType, body) VALUES (%s, %s, %s)",
                        (body["messageId"], body["messageType"], json.dumps(body, separators=(",", ":"))))
        for match_id, end in closed.items():
            cur.execute("""MERGE dbo.localStreamWindows AS t USING (SELECT %s AS matchId, %s AS closedUntil) AS s
                           ON t.matchId = s.matchId
                           WHEN MATCHED THEN UPDATE SET closedUntil = s.closedUntil
                           WHEN NOT MATCHED THEN INSERT (matchId, closedUntil) VALUES (s.matchId, s.closedUntil);""",
                        (match_id, naive(end)))
        for match_id, (seq, status) in (progress or {}).items():
            cur.execute("""MERGE dbo.matchProgress AS t USING (SELECT %s AS matchId, %s AS seq) AS s
                           ON t.matchId = s.matchId
                           WHEN MATCHED THEN UPDATE SET seq = s.seq
                           WHEN NOT MATCHED THEN INSERT (matchId, seq) VALUES (s.matchId, s.seq);""", (match_id, seq))
            cur.execute("UPDATE dbo.matches SET status = %s WHERE matchId = %s", (status, match_id))
        if checkpoint:
            cur.execute("""MERGE dbo.localStreamCheckpoints AS t USING (SELECT %s AS p, %s AS s) AS s
                           ON t.partitionId = s.p
                           WHEN MATCHED THEN UPDATE SET sequenceNumber = s.s
                           WHEN NOT MATCHED THEN INSERT (partitionId, sequenceNumber) VALUES (s.p, s.s);""",
                        checkpoint)
        self.conn.commit()

    def purge(self, match_id=None, cutoff=None):
        """Tombstone, then delete one match's rows, progress, window and outbox (or every match's, with
        cutoff recorded). Checkpoints and configuration stay. Returns (match ids, rows per store).
        The exclusive lock waits for Azure SQL's insert triggers (sql/azure/asa-progress.sql)."""
        cur, counts = self.conn.cursor(), {}
        cur.execute("EXEC sp_getapplock @Resource = N'etl-purge', @LockMode = N'Exclusive', @LockOwner = N'Transaction'")
        cur.execute(f"SELECT name FROM sys.tables WHERE schema_id = SCHEMA_ID('dbo') AND name IN "
                    f"({', '.join(['%s'] * (len(MATCH_TABLES) + 1))})", (*MATCH_TABLES, "localStreamOutbox"))
        present = {name for (name,) in cur.fetchall()}
        tables = [t for t in MATCH_TABLES if t in present]
        if match_id is None:
            cur.execute(" UNION ".join(f"SELECT matchId FROM dbo.{t}" for t in tables))
            match_ids = sorted(m for (m,) in cur.fetchall())
            cur.execute("""MERGE dbo.purgeCutoff AS t USING (SELECT CAST(1 AS bit) AS singleton, %s AS cutoffAt) AS s
                           ON t.singleton = s.singleton
                           WHEN MATCHED THEN UPDATE SET cutoffAt = s.cutoffAt
                           WHEN NOT MATCHED THEN INSERT (singleton, cutoffAt) VALUES (1, s.cutoffAt);""", (naive(cutoff),))
        else:
            match_ids = [match_id]
        for m in match_ids:
            cur.execute("INSERT dbo.purgedMatches (matchId) VALUES (%s)", (m,))
        where, params = ("", ()) if match_id is None else (" WHERE matchId = %s", (match_id,))
        for table in tables:
            cur.execute(f"DELETE FROM dbo.{table}{where}", params)
            counts[table] = cur.rowcount
        if "localStreamOutbox" in present:
            cur.execute("DELETE FROM dbo.localStreamOutbox" + ("" if match_id is None else
                        " WHERE JSON_VALUE(body, '$.matchId') = %s"), params)
            counts["localStreamOutbox"] = cur.rowcount
        self.conn.commit()
        return match_ids, counts

    def reset_checkpoint(self, partition_id):
        """Forget a partition's position after the hub was reset (its sequence numbers restart)."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM dbo.localStreamCheckpoints WHERE partitionId = %s", (partition_id,))
        self.conn.commit()

    def rollback(self):
        try:
            self.conn.rollback()
        except Exception:
            self.reconnect()

    def pending_notifications(self, limit=100):
        cur = self.conn.cursor()
        cur.execute("SELECT TOP (%s) seq, messageId, notificationType, body FROM dbo.localStreamOutbox "
                    "WHERE sentAt IS NULL ORDER BY seq", (limit,))
        rows = cur.fetchall()
        self.conn.commit()
        return rows

    def mark_sent(self, seqs):
        cur = self.conn.cursor()
        for seq in seqs:
            cur.execute("UPDATE dbo.localStreamOutbox SET sentAt = %s WHERE seq = %s",
                        (naive(datetime.now(timezone.utc)), seq))
        self.conn.commit()
