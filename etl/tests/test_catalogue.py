"""The SPADL stat catalogue reference on a whole Riverton Rovers–Forgeham United run, against its recorded golden values.

fixtures/catalogue-golden.json holds the full rows at the final seq and (statId, value, available) at 20
prefixes; local/contracts/README.md §4 lists the full-time values. Regenerate after a deliberate definition change or a re-rendered recording:
    python tests/test_catalogue.py --regenerate
"""
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reference import catalogue, spadl  # noqa: E402
import v2_stream  # noqa: E402
from support import GOLDEN_PATH, golden, outputs, reference  # noqa: E402

KINDS = ["goals", "shots", "passes", "corners", "cards", "tackles", "interceptions", "fouls", "fouls_won", "offsides",
         "throw_ins", "free_kicks", "goal_kicks", "kick_offs", "penalties", "keeper_claims", "clearances", "take_ons",
         "ball_recoveries", "headed_passes", "headed_shots", "headed_contacts", "saves", "shots_on_target",
         "blocked_shots", "aerials_won", "successful_take_ons", "pass_accuracy", "possession",
         # Added with SPADL:
         "passes_completed", "crosses", "crosses_completed", "cross_accuracy", "dribbles", "corners_crossed",
         "corners_short", "free_kicks_crossed", "free_kicks_short", "free_kick_shots", "final_third_entries",
         "box_entries", "shots_saved"]
RETIRED = {"kick_offs", "ball_recoveries", "aerials_won"}
PREFIXES = [0, 1, 2, 50, 97, 500, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 7000, 8000, 9000, 10000, 11000]


STREAM = v2_stream.build()
ROWS = outputs(STREAM)
FINAL = len(ROWS["canonicalEvents"])


def values(stats):
    return [[s["statId"], s["value"], s["available"]] for s in stats]


def by_id(stats):
    return {s["statId"]: s for s in stats}


def test_definitions_keep_every_old_id_in_order():
    assert [d["statId"] for d in catalogue.definitions()] == KINDS
    assert [s["statId"] for s in reference(FINAL, ROWS, FINAL)] == [
        f"{scope}:{k}" for scope in ("all", "riverton", "forgeham") for k in KINDS]


def test_final_seq_equals_golden():
    g = golden()
    assert g["final_seq"] == FINAL and reference(FINAL, ROWS, FINAL) == g["final"]
    stats = by_id(reference(FINAL, ROWS, FINAL))
    value = lambda i: stats[i]["value"]
    assert (value("all:goals"), value("riverton:goals"), value("forgeham:goals")) == (2, 1, 1)
    assert (value("riverton:shots"), value("riverton:shots_on_target")) == (9, 3)
    assert (value("riverton:saves"), value("forgeham:saves")) == (1, 3)
    # Real saves: 1 United keeper_save row is a touch of a shot going wide.
    assert (value("all:shots_saved"), value("riverton:shots_saved"), value("forgeham:shots_saved")) == (3, 1, 2)
    assert (value("riverton:passes"), value("forgeham:passes")) == (941, 462)
    assert (value("riverton:interceptions"), value("all:dribbles"), value("all:crosses")) == (37, 1011, 130)
    assert (round(value("riverton:possession")), round(value("forgeham:possession"))) == (64, 36)
    for kind in RETIRED | {"headed_contacts"}:
        assert stats[f"all:{kind}"]["available"] is False and stats[f"all:{kind}"]["value"] is None


def test_prefixes_equal_golden():
    g = golden()
    assert len(g["prefixes"]) == len(PREFIXES) + 1
    for seq, expected in g["prefixes"].items():
        assert values(reference(int(seq), ROWS, FINAL)) == expected, seq


def test_snapshot_bounds():
    assert reference(FINAL + 1, ROWS, FINAL) == [] and reference(10, ROWS, 9) == [] and reference(-1, ROWS, FINAL) == []
    assert catalogue.stats_at_seq(None, [], [], [], 0, 0, actions=[], raw=[]) == []


def test_actions_count_only_once_final():
    """A snapshot reads actions with finalSeq <= seq: an action that arrived but is not final is not counted."""
    seq = next(a["seq"] for a in ROWS["spadlActions"] if a["finalSeq"] > a["seq"] and a["typeName"] == "pass")
    early = by_id(reference(seq, ROWS, FINAL))
    counted = sum(a["finalSeq"] <= seq and a["typeName"] in spadl.PASS_FAMILY for a in ROWS["spadlActions"])
    assert early["all:passes"]["value"] == counted


def regenerate():
    final = reference(FINAL, ROWS, FINAL)
    prefixes = {str(s): values(reference(s, ROWS, FINAL)) for s in [*PREFIXES, FINAL]}
    GOLDEN_PATH.write_text(json.dumps({"final_seq": FINAL, "final": final, "prefixes": prefixes}, separators=(",", ":")),
                           encoding="utf-8")
    print(f"wrote {GOLDEN_PATH}")


if __name__ == "__main__" and "--regenerate" in sys.argv:
    regenerate()
