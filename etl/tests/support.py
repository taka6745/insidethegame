"""Helpers shared by the ETL tests (and devtools.calibrate_trends)."""
import json
from pathlib import Path

from reference import catalogue, pipeline, spadl

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "catalogue-golden.json"


def outputs(stream, live=False):
    """ETL's rows for a run: the stream's tables plus its SPADL actions (live: only those final so far)."""
    rows = pipeline.stream_outputs(stream, 60)
    convert = spadl.final_actions if live else spadl.actions
    rows["spadlActions"] = convert([m for m in stream if m.get("feed") == "MA3"], rows["matches"][0]["homeContestantId"])
    return rows


def reference(seq, rows, watermark):
    return catalogue.stats_at_seq(rows["matches"][0], rows["matchTeams"], rows["canonicalEvents"],
                                  rows["possessionSamples"], seq, watermark, actions=rows["spadlActions"],
                                  raw=rows["rawEvents"])


def golden():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def canonical(rows):
    return sorted(json.dumps(r, sort_keys=True) for r in rows)


def bodies(notifications):
    """First body per MessageId, as Service Bus duplicate detection keeps it."""
    out = {}
    for n in notifications:
        out.setdefault(pipeline.message_id_for(n), pipeline.notification_body(n))
    return out


class FakeRepository:
    """SQL double: tables with IGNORE_DUP_KEY semantics, outbox keyed by MessageId, progress and tombstones."""
    KEYS = {"matches": ("matchId",), "matchTeams": ("matchId", "contestantId"), "matchPlayers": ("matchId", "playerId"),
            "canonicalEvents": ("matchId", "seq"), "possessionSamples": ("matchId", "sampleId"),
            "rawEvents": ("matchId", "id"), "keyEvents": ("matchId", "id"),
            "minuteStats": ("matchId", "contestantId", "periodId", "timeMin", "windowEnd")}

    def __init__(self):
        self.tables, self.outbox, self.closed, self.checkpoints, self.fail = {}, {}, {}, {}, False
        self.progress, self.purged, self.cutoff = {}, set(), None

    def load(self):
        pending = [json.loads(r["payload"]) for r in self.tables.get("rawEvents", {}).values()
                   if pipeline.parse_time(r["eventTime"]) > self.closed.get(r["matchId"], pipeline.parse_time("0001-01-01T00:00:00Z"))]
        matches = {}
        for m in self.rows("matches"):
            mid = m["matchId"]
            events = [e for e in self.rows("canonicalEvents") if e["matchId"] == mid]
            periods = json.loads(m["capabilities"] or "{}").get("periods")
            watermark, status = self.progress.get(mid, (0, "scheduled"))
            matches[mid] = {"periods": periods, "status": status, "seq": max((e["seq"] for e in events), default=0),
                            "watermark": watermark,
                            "sample": max((s["sampleId"] for s in self.rows("possessionSamples") if s["matchId"] == mid), default=0),
                            "final": min((e["seq"] for e in events if e["eventType"] == "period_end" and not e["deleted"]
                                          and e["periodId"] == periods), default=None)}
        return {"closed": dict(self.closed), "checkpoints": dict(self.checkpoints), "matches": matches,
                "pending": sorted(pending, key=lambda m: (m["matchId"], m["seq"])),
                "purged": set(self.purged), "cutoff": self.cutoff}

    def seen(self, match_id, event_id):
        return (match_id, event_id) in self.tables.get("rawEvents", {})

    def write(self, out, closed, checkpoint=None, progress=None):
        if self.fail:
            raise ConnectionError("database down")
        for table, rows in out.rows.items():
            for row in rows:
                self.tables.setdefault(table, {}).setdefault(tuple(row[k] for k in self.KEYS[table]), row)
        for n in out.notifications:
            self.outbox.setdefault(pipeline.message_id_for(n), pipeline.notification_body(n))
        self.closed.update(closed)
        self.progress.update(progress or {})
        if checkpoint:
            self.checkpoints[checkpoint[0]] = checkpoint[1]

    def purge(self, match_id=None, cutoff=None):
        ids = sorted({r["matchId"] for rows in self.tables.values() for r in rows.values()} | set(self.progress)
                     ) if match_id is None else [match_id]
        if match_id is None:
            self.cutoff = cutoff
        self.purged |= set(ids)
        counts = {}
        for table, rows in self.tables.items():
            gone = [k for k, r in rows.items() if r["matchId"] in ids]
            for key in gone:
                del rows[key]
            counts[table] = len(gone)
        self.outbox = {k: b for k, b in self.outbox.items() if b["matchId"] not in ids}
        for m in ids:
            self.closed.pop(m, None)
            self.progress.pop(m, None)
        return ids, counts

    def schema(self):
        return "fake-schema"

    def export(self, match_id):
        tables = {t: [dict(r) for r in rows.values() if r["matchId"] == match_id] for t, rows in self.tables.items()}
        if match_id in self.progress:
            seq, status = self.progress[match_id]
            tables["matchProgress"] = [{"matchId": match_id, "seq": seq, "status": status}]
        if match_id in self.closed:
            tables["localStreamWindows"] = [{"matchId": match_id, "closedUntil": self.closed[match_id].isoformat()}]
        return tables

    def restore(self, match_id, tables, max_seq):
        from local_stream.demo_seeds import RestoreRefused
        if match_id in self.purged or any(r["matchId"] == match_id for r in self.rows("matches")):
            raise RestoreRefused("known")
        if any(r["seq"] > max_seq for r in tables.get("canonicalEvents", [])):
            raise RestoreRefused("past the seed")
        for table, rows in tables.items():
            if table == "matchProgress":
                self.progress[match_id] = rows[0]["seq"], rows[0]["status"]
            elif table == "localStreamWindows":
                self.closed[match_id] = pipeline.parse_time(rows[0]["closedUntil"])
            else:
                for row in rows:
                    self.tables.setdefault(table, {})[tuple(row[k] for k in self.KEYS[table])] = dict(row)
        return {t: len(r) for t, r in tables.items()}

    def reset_checkpoint(self, partition_id):
        self.checkpoints.pop(partition_id, None)

    def rollback(self):
        pass

    def rows(self, table):
        return list(self.tables.get(table, {}).values())


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def feed(worker, messages, batch=250, start=0):
    for i in range(0, len(messages), batch):
        worker.handle("0", [(start + i + j, json.dumps(m)) for j, m in enumerate(messages[i:i + batch])])


def settle(worker, clock):
    clock.now += 1000
    worker.handle("0", [])


def var_row(match_id, n, seq, team, own_goal=False, outcome="goal-overturned"):
    """A rawEvents row for an MA3 VAR decision (type 900, qualifier 901; 28 for an own goal)."""
    qualifier = [{"qualifierId": 901, "value": outcome}] + ([{"qualifierId": 28}] if own_goal else [])
    payload = {"feed": "MA3", "matchId": match_id, "id": 9_000_000 + n, "typeId": 900, "contestantId": team,
               "eventSeq": seq, "qualifier": qualifier}
    return {"matchId": match_id, "id": 9_000_000 + n, "seq": 90_000 + n, "eventId": 900 + n, "typeId": 900,
            "periodId": 2, "timeMin": 80, "timeSec": 0, "contestantId": team, "playerId": None, "outcome": 1,
            "x": None, "y": None, "eventTime": "2026-10-20 16:30:00", "payload": json.dumps(payload), "eventSeq": seq}
