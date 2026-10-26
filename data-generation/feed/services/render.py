"""Stamps one run's identity and wall-clock times onto a fixture's stream (etl/README.md Contracts)."""
from datetime import timedelta

from grf_demo.opta_stream import schedule, stamp


class RunRenderer:
    def __init__(self, stream, *, run_id, match_id, kickoff, video):
        self.stream, self.run_id, self.match_id, self.kickoff, self.video = stream, run_id, match_id, kickoff, video
        # MA3 keeps the ETL window rule: each period starts 0.5 s after a minute boundary.
        self.ma3 = schedule([dict(row) for row in stream.ma3], kickoff)

    def ma1(self, now):
        header = self.stream.ma1
        return {**header, "matchId": self.match_id, "runId": self.run_id, "scheduledKickoff": stamp(self.kickoff),
                "timeStamp": stamp(now), "capabilities": {**header["capabilities"], "video": self.video}}

    def item(self, item):
        at = stamp(self.kickoff + timedelta(seconds=item.at))
        if item.kind == "event":
            seq = item.index + 1
            return {"type": "MatchEvent", "version": 2, "matchId": self.match_id, "seq": seq, "timeStamp": at,
                    "synthetic": True, "event": {**self.stream.events[item.index], "match_id": self.match_id}}
        if item.kind == "MA3":
            return {**self.ma3[item.index], "matchId": self.match_id}
        return {**self.stream.pos[item.index], "matchId": self.match_id, "timeStamp": at}
