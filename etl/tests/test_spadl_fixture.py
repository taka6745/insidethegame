"""fixtures/spadl-riverton-forgeham.json: the spadlActions rows ETL GraphQL serves for one Riverton Rovers–Forgeham United run (the
hand-off for backend and engine tests). A snapshot (matchId, s) reads the rows with finalSeq <= s; `snapshots`
lists sample seqs with their row counts. Regenerate after a deliberate conversion change:
    python tests/test_spadl_fixture.py --regenerate
"""
import json
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reference import spadl  # noqa: E402
import v2_stream  # noqa: E402

PATH = Path(__file__).parent / "fixtures" / "spadl-riverton-forgeham.json"
SEQS = [1, 100, 500, 1000, 2500, 5000, 7500, 10000]


def build():
    stream = v2_stream.build()
    match_id, home = stream[0]["matchId"], next(c["id"] for c in stream[0]["contestant"] if c["position"] == "home")
    rows = [{"matchId": match_id, **a} for a in spadl.actions([m for m in stream if m.get("feed") == "MA3"], home)]
    final = sum(m.get("type") == "MatchEvent" for m in stream)
    snapshots = [{"seq": s, "actions": sum(r["finalSeq"] <= s for r in rows)} for s in [*SEQS, final]]
    return {"description": "SYNTHETIC: SPADL actions converted by etl/reference/spadl.py from the checked-in "
                           "Riverton Rovers–Forgeham United GRF recording (tests/v2_stream.py run 1a2b3c4d). Rows as ETL GraphQL "
                           "spadlActions serves them; read rows with finalSeq <= seq.",
            "matchId": match_id, "homeContestantId": home, "finalSeq": final, "snapshots": snapshots, "actions": rows}


def render(data):
    head = json.dumps({k: v for k, v in data.items() if k != "actions"}, separators=(",", ":"))[:-1]
    lines = ",\n".join(json.dumps(r, separators=(",", ":")) for r in data["actions"])
    return f'{head},"actions":[\n{lines}\n]}}\n'


def test_fixture_is_the_current_conversion():
    data = build()
    assert json.loads(PATH.read_text(encoding="utf-8")) == data
    assert [s["actions"] for s in data["snapshots"]] == sorted(s["actions"] for s in data["snapshots"])
    assert data["snapshots"][-1]["actions"] == len(data["actions"])


def test_schema_lists_every_column():
    schema = json.loads((Path(__file__).parents[1] / "contracts" / "spadl-action.schema.json").read_text())
    assert schema["required"] == list(schema["properties"]) == ["matchId", *spadl.COLUMNS]
    assert schema["properties"]["typeName"]["enum"] == [t for t in spadl.ACTIONTYPES if t != "non_action"]
    assert schema["properties"]["resultName"]["enum"] == spadl.RESULTS
    assert schema["properties"]["bodypartName"]["enum"] == spadl.BODYPARTS
    assert schema["properties"]["startZone"]["enum"] == spadl.ZONES


if __name__ == "__main__" and "--regenerate" in sys.argv:
    PATH.write_text(render(build()), encoding="utf-8")
    print(f"wrote {PATH}")
