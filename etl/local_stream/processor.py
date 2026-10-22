"""Incremental Stream Analytics stand-in: the reference rules applied one message at a time.

MA1, POS and MatchEvent v2 messages map to rows directly; MA3 also feeds the minute windows.

Rows and key/period notifications come from reference.pipeline for each message. Minute
statistics accumulate in event-time tumbling windows that close when a later window's event
arrives (one ordered partition per match) or when the stream goes idle. An event whose window
has already closed joins the next one, like Stream Analytics' "adjust" late-arrival policy.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from reference import opta, pipeline


@dataclass
class Output:
    rows: dict = field(default_factory=lambda: defaultdict(list))
    notifications: list = field(default_factory=list)

    def extend(self, other):
        for table, rows in other.rows.items():
            self.rows[table] += rows
        self.notifications += other.notifications


class StreamProcessor:
    def __init__(self, window_seconds=60, closed=None):
        self.window = window_seconds
        self.closed = dict(closed or {})  # matchId -> last closed windowEnd
        # matchId -> windowEnd -> {(contestant, period, minute): stats}
        self.open = defaultdict(dict)

    def process(self, message):
        """Rows and notifications for one MA1/MA3/POS/MatchEvent message, including windows it closes."""
        single = pipeline.stream_outputs([message], self.window)
        out = Output()
        for table in pipeline.TABLES:
            if table != "minuteStats":
                out.rows[table] += single[table]
        if message.get("feed") != "MA3":
            return out
        end = self._window_end(message)
        out.extend(self._close(message["matchId"], before=end))
        out.notifications += [n for n in single["notifications"] if n["messageType"] != "MinuteClosed"]
        self._add(message, end)
        return out

    def restore(self, message):
        """Rebuild an open window after a restart (no rows or notifications re-emitted)."""
        self._add(message, self._window_end(message))

    def flush(self, match_id=None):
        """Close every open window (idle stream or shutdown)."""
        out = Output()
        for match in [match_id] if match_id else list(self.open):
            out.extend(self._close(match))
        return out

    def _window_end(self, message):
        end = pipeline.window_end(pipeline.parse_time(message["timeStamp"]), self.window)
        closed = self.closed.get(message["matchId"])
        return closed + timedelta(seconds=self.window) if closed and end <= closed else end

    def _add(self, message, end):
        key = (message["contestantId"], message["periodId"], message["timeMin"])
        stats = self.open[message["matchId"]].setdefault(end, {}).setdefault(
            key, dict.fromkeys(opta.STAT_COLUMNS, 0))
        for column, delta in opta.stat_deltas(message).items():
            stats[column] += delta

    def _close(self, match_id, before=None):
        out = Output()
        windows = self.open.get(match_id, {})
        for end in sorted(e for e in windows if before is None or e < before):
            closed_minutes = {}
            for (contestant, period, minute), stats in windows.pop(end).items():
                out.rows["minuteStats"].append({"matchId": match_id, "contestantId": contestant, "periodId": period,
                                                "timeMin": minute, "windowEnd": end.isoformat(), **stats})
                closed_minutes[period] = max(closed_minutes.get(period, -1), minute)
            for period, minute in sorted(closed_minutes.items()):
                out.notifications.append({"messageType": "MinuteClosed", "matchId": match_id, "periodId": period,
                                          "timeMin": minute, "windowEnd": end.isoformat()})
            self.closed[match_id] = end
        if not windows:
            self.open.pop(match_id, None)
        return out
