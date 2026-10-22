"""The replay golden set in fixture mode: real tools and clip builder over the shipped recording; key-moment
cases over the archived recording and the narrative fixtures bound to it."""
import asyncio
import json
from pathlib import Path

import pytest

from benchmarks import replay_eval

ROOT = Path(__file__).resolve().parents[2]
RECORDING = ROOT / "data-generation/recordings/riverton-forgeham-grf.json"
ARCHIVE = ROOT / "narrative-engine/fixtures/archive/riverton-forgeham-grf.json"
NARRATIVES = ROOT / "narrative-engine/fixtures/grf-narratives.json"
CASES = Path(replay_eval.__file__).with_name("replay_cases.json")


@pytest.mark.skipif(not (RECORDING.exists() and ARCHIVE.exists() and NARRATIVES.exists()), reason="Run from the repository checkout")
def test_fixture_agent_passes_every_golden_case_without_hard_failures(tmp_path):
    output = tmp_path / "report.json"
    code = asyncio.run(replay_eval.main(["--agent", "fixture", "--recording", str(RECORDING),
                                         "--archive", str(ARCHIVE), "--narratives", str(NARRATIVES), "--output", str(output)]))
    report = json.loads(output.read_text())
    assert code == 0 and report["hard_failures"] == 0
    # Cases marked "fixture": false exercise the model's language handling beyond the double's phrasings.
    model_only = {c["id"] for c in json.loads(CASES.read_text())["cases"] if c.get("fixture") is False}
    assert not [r["id"] for r in report["results"] if r["id"] not in model_only and not r["quality"].get("pass")]
    clips = [clip for result in report["results"] for clip in result["clips"]]
    assert clips and all(clip["end"] <= result["at_video"] for result in report["results"] for clip in result["clips"])
