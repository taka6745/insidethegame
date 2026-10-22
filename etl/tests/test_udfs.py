"""Run the Stream Analytics JavaScript UDFs in Node and compare with the Python rules."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

import v2_stream
from reference import opta, pipeline
from seeder.generate import MatchBuilder

UDFS = Path(__file__).resolve().parents[1] / "stream-analytics" / "udfs"
TSC = os.environ.get("TSC") or shutil.which("tsc") or next(
    (str(p) for p in [UDFS.parents[2] / "frontend" / "node_modules" / ".bin" / "tsc"] if p.exists()), None)
MATCH = MatchBuilder("udf-test", seed=7).build()

HARNESS = """
const fs = require("fs");
const load = name => new Function(fs.readFileSync(process.argv.at(-1) + "/" + name + ".js", "utf8") + "; return main;")();
const [hasQ, qValue, toJson, matchInfo] = ["hasQ", "qValue", "toJson", "matchInfo"].map(load);
const messages = JSON.parse(fs.readFileSync(0, "utf8"));
const ids = [9, 28, 31, 32, 33, 55, 82, 901];
console.log(JSON.stringify(messages.map(m => m.feed === "MA1"
  ? { info: matchInfo({ ...m, EventProcessedUtcTime: "x", PartitionId: 0 }) }
  : { has: ids.map(i => hasQ(m.qualifier, i)), values: ids.map(i => qValue(m.qualifier, i)),
      json: toJson({ ...m, EventEnqueuedUtcTime: "x" }) })));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_udfs_match_python_rules():
    result = subprocess.run(["node", "-e", HARNESS, str(UDFS)], input=json.dumps(MATCH),
                            capture_output=True, text=True, check=True)
    outputs = json.loads(result.stdout)
    ids = [9, 28, 31, 32, 33, 55, 82, 901]
    info = outputs[0]["info"]
    assert (info["homeContestantId"], info["awayContestantId"], info["synthetic"]) == ("c-riv", "c-har", 1)
    assert json.loads(info["payload"]) == MATCH[0] and info["capabilities"] is None
    for message, out in zip(MATCH[1:], outputs[1:]):
        assert out["has"] == [int(opta.has_q(message, i)) for i in ids]
        assert out["values"] == [opta.q_value(message, i) for i in ids]
        assert json.loads(out["json"]) == message


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_match_info_carries_multi_match_columns():
    ma1 = v2_stream.build()[0]
    result = subprocess.run(["node", "-e", HARNESS, str(UDFS)], input=json.dumps([ma1]),
                            capture_output=True, text=True, check=True)
    info = json.loads(result.stdout)[0]["info"]
    expected = pipeline.match_rows(ma1)[0]
    assert {k: info[k] for k in ("fixture", "sourceMatchId", "runId")} == {k: expected[k] for k in ("fixture", "sourceMatchId", "runId")}
    assert json.loads(info["capabilities"]) == json.loads(expected["capabilities"])


@pytest.mark.skipif(not (shutil.which("node") and TSC), reason="node or tsc not installed")
def test_generated_udfs_match_typescript_sources():
    """Every udfs/*.js is exactly what build.ts compiles from src/*.ts."""
    result = subprocess.run(["node", str(UDFS / "build.ts"), "--check"], env={**os.environ, "TSC": TSC},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
