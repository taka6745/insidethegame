import json

import pytest

from backend.adapters.replay_source import FixtureEventSource


@pytest.mark.parametrize("change", ["wrong_match", "unknown_player", "conflicting_revision", "real_data", "invalid_preset"])
def test_invalid_recording_contracts_rejected(change):
    original = FixtureEventSource()
    spec = json.loads(original.content)
    if change == "wrong_match":
        spec["events"][0]["matchId"] = "another-match"
    elif change == "unknown_player":
        spec["events"][0]["playerId"] = "unknown"
    elif change == "conflicting_revision":
        duplicate = spec["events"][0].copy()
        duplicate["typeName"] = "foul"
        spec["events"].append(duplicate)
    elif change == "real_data":
        spec["synthetic"] = False
    else:
        spec["presets"][0]["rule"]["match_id"] = "another-match"
    with pytest.raises(ValueError):
        original.with_recording(json.dumps(spec).encode(), "new.json")


def test_filename_keeps_only_basename():
    original = FixtureEventSource()
    source = original.with_recording(original.content, "C:\\recordings\\sample.json")
    assert source.filename == "sample.json"
