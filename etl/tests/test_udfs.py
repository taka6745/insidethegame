"""Run the Stream Analytics JavaScript UDFs in Node and compare with the Python rules."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from etltools import opta
from seeder.generate import MatchBuilder

UDFS = Path(__file__).resolve().parents[1] / "stream-analytics" / "udfs"
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
    assert json.loads(info["payload"]) == MATCH[0]
    for message, out in zip(MATCH[1:], outputs[1:]):
        assert out["has"] == [int(opta.has_q(message, i)) for i in ids]
        assert out["values"] == [opta.q_value(message, i) for i in ids]
        assert json.loads(out["json"]) == message
