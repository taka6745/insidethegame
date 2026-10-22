"""Azure parity on all three recordings: the reference (what Stream Analytics writes, plus the watermark
and status Azure SQL derives from its marks) equals the local stream worker row for row, and the
JavaScript UDFs equal the reference."""
import json
import shutil
import subprocess
from functools import cache
from pathlib import Path

import pytest

import v2_stream
from local_stream.worker import StreamWorker
from reference import pipeline
from test_local_stream import Clock, FakeRepository, bodies, canonical

UDFS = Path(__file__).resolve().parents[1] / "stream-analytics" / "udfs"


@cache
def stream(fixture):
    return v2_stream.build(fixture=fixture)


def reference_progress(messages, quiet):
    rows = pipeline.stream_outputs(messages, 60)
    marks = pipeline.progress_marks(messages, quiet)
    match = rows["matches"][0]
    seq = pipeline.watermark(marks, rows, match["matchId"])
    return seq, pipeline.match_status(match, rows["canonicalEvents"], seq)


@pytest.mark.parametrize("fixture", v2_stream.FIXTURES)
def test_local_stream_equals_reference(fixture):
    messages = stream(fixture)
    match_id = messages[0]["matchId"]
    repo, clock = FakeRepository(), Clock()
    worker = StreamWorker(repo, 60, clock=clock)
    worker.load()
    step, start = len(messages) // 40, 0
    for end in [*range(step, len(messages), step), len(messages)]:  # Watermark and status along the way.
        worker.handle("0", [(i, json.dumps(m)) for i, m in enumerate(messages[start:end], start)])
        start = end
        assert repo.progress.get(match_id, (0, "scheduled")) == reference_progress(messages[:end], quiet=False), end
    clock.now += 1000
    worker.handle("0", [])  # Quiet spell: the last event completes, open windows close.
    expected = pipeline.stream_outputs(messages, 60)
    assert repo.progress[match_id] == reference_progress(messages, quiet=True) == (len(expected["canonicalEvents"]), "finished")
    for table in pipeline.TABLES:
        assert canonical(repo.rows(table)) == canonical(expected[table]), table
    assert repo.outbox == bodies(expected["notifications"])


HARNESS = """
const fs = require("fs");
const load = name => new Function(fs.readFileSync(process.argv.at(-1) + "/" + name + ".js", "utf8") + "; return main;")();
const [canonicalEvent, matchTeams, matchPlayers] = ["canonicalEvent", "matchTeams", "matchPlayers"].map(load);
const messages = JSON.parse(fs.readFileSync(0, "utf8"));
console.log(JSON.stringify({teams: matchTeams(messages[0]), players: matchPlayers(messages[0]),
  events: messages.filter(m => m.type === "MatchEvent").map(m => canonicalEvent({...m, PartitionId: 0}))}));
"""


def normal(rows):
    """SQL values: booleans as bits, qualifiers as parsed JSON."""
    out = []
    for row in rows:
        row = {k: int(v) if isinstance(v, bool) else v for k, v in row.items()}
        if "qualifiers" in row:
            row["qualifiers"] = json.loads(row["qualifiers"])
        out.append(row)
    return out


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("fixture", v2_stream.FIXTURES)
def test_udfs_equal_reference_rows(fixture):
    messages = stream(fixture)
    result = subprocess.run(["node", "-e", HARNESS, str(UDFS)], input=json.dumps(messages),
                            capture_output=True, text=True, check=True)
    actual, expected = json.loads(result.stdout), pipeline.stream_outputs(messages, 60)
    assert normal(actual["teams"]) == normal(expected["matchTeams"])
    assert normal(actual["players"]) == normal(expected["matchPlayers"])
    assert normal(actual["events"]) == normal(expected["canonicalEvents"])
