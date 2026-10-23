"""Helpers shared by several test modules: a mocked user backend, the ETL as of a seq, and ETL's Python twin of the
trend procedures over the Riverton Rovers–Forgeham United recording (synthetic)."""
import sys
from functools import cache

import httpx

import riverton_forgeham
from doubles.fixture_data import FixtureMatchData
from narrative_engine.core.models import MatchClock
from narrative_engine.match_data import EtlBehind
from narrative_engine.match_data.etl_graphql import spell_rows, trend_rows

BASE = "http://backend.test"


class Backend:
    """GET with ETag/If-None-Match, like the user backend's read APIs."""
    def __init__(self, documents):
        self.documents, self.requests, self.down = documents, [], False

    def __call__(self, request):
        self.requests.append((request.url.path, request.headers.get("if-none-match")))
        if self.down:
            return httpx.Response(503)
        body = self.documents.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        etag = f'"{body["revision"]}"'
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304, headers={"ETag": etag})
        return httpx.Response(200, json=body, headers={"ETag": etag})


def client(backend):
    return httpx.AsyncClient(transport=httpx.MockTransport(backend))


class EtlAsOf(FixtureMatchData):
    """The ETL as of canonical seq `limit`: later MA3 rows, key events and unsettled actions do not
    exist yet, and SPADL reads past it are refused as the GraphQL client refuses them."""
    limit = None

    def _here(self, rows):
        return [r for r in rows if self.limit is None or r["eventSeq"] <= self.limit]

    async def events(self, match_id, start, end, until_sec=59):
        return self._here(await super().events(match_id, start, end, until_sec))

    async def event_seq(self, match_id, until, until_sec=59):
        bound = (until.periodId, until.timeMin, until_sec)
        return max((e["eventSeq"] for e in self._here(self.raw)
                    if (e["periodId"], e["timeMin"], e["timeSec"]) <= bound), default=None)

    def _converted(self, seq):
        if self.limit is not None and (seq or 0) > self.limit:
            raise EtlBehind(f"seq {seq} is past the ETL's {self.limit}")

    async def actions(self, match_id, after_seq, seq):
        self._converted(seq)
        return await super().actions(match_id, after_seq, seq)

    async def stats_at(self, match_id, seq):
        self._converted(seq)
        return await super().stats_at(match_id, seq)

    async def trends_at(self, match_id, seq):
        self._converted(seq)
        return await super().trends_at(match_id, seq)

    async def spells_at(self, match_id, seq):
        self._converted(seq)
        return await super().spells_at(match_id, seq)

    async def key_events(self, match_id, until, until_sec=59):
        seqs = {e["id"]: e["eventSeq"] for e in self.raw}
        return [k for k in await super().key_events(match_id, until, until_sec)
                if self.limit is None or seqs[k["id"]] <= self.limit]

    async def period_end_at(self, match_id, period_id):
        end = next((e for e in self._here(self.raw) if e["typeId"] == 30 and e["periodId"] == period_id), None)
        return (MatchClock(end["periodId"], end["timeMin"]), end["timeSec"]) if end else None


ETL = riverton_forgeham.ROOT / "etl"
sys.path += [str(ETL), str(ETL / "tests")]  # after ours: etl/ has its own `devtools`
import v2_stream  # noqa: E402  (ETL's test stream of the same recording)
from reference import pipeline, spadl, trends as reference  # noqa: E402


@cache
def etl_rows():
    stream = v2_stream.build()
    rows = pipeline.stream_outputs(stream, 60)
    rows["spadlActions"] = spadl.actions([m for m in stream if m.get("feed") == "MA3"],
                                         rows["matches"][0]["homeContestantId"])
    return rows


def served(procedure, seq):
    rows = etl_rows()
    final = len(rows["canonicalEvents"])
    return procedure(rows["matches"][0], rows["canonicalEvents"], rows["possessionSamples"], seq, final,
                     actions=rows["spadlActions"], raw=rows["rawEvents"])


@cache
def trends_at(seq):
    return trend_rows(served(reference.trends_at_seq, seq))


@cache
def spells_at(seq):
    return spell_rows(served(reference.spells_at_seq, seq))
