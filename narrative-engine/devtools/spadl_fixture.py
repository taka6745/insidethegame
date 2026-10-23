"""Write the SPADL test fixture for a replay file with the ETL's converter (etl/reference/spadl.py).

    python devtools/spadl_fixture.py tests/fixtures/itg-syn-0001.jsonl tests/fixtures/itg-syn-0001-spadl.json

Rows hold the `spadlActions` fields the engine reads (`render.ACTION_FIELDS`). A replay without
canonical seqs (the seeder's itg-syn-0001) uses its MA3 `seq` as `eventSeq`, as `FixtureMatchData`
does. Developer tooling only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "etl"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reference import spadl  # noqa: E402
from narrative_engine.context.render import ACTION_FIELDS  # noqa: E402


def main(replay, out):
    messages = [json.loads(line) for line in Path(replay).read_text(encoding="utf-8").splitlines()]
    ma1 = next(m for m in messages if m["feed"] == "MA1")
    home = next(c["id"] for c in ma1["contestant"] if c["position"] == "home")
    ma3 = [{**m, "eventSeq": m.get("eventSeq", m["seq"])} for m in messages if m["feed"] == "MA3"]
    actions = [{k: a[k] for k in ACTION_FIELDS.split()} for a in spadl.actions(ma3, home)]
    Path(out).write_text(json.dumps({
        "description": f"SYNTHETIC: SPADL actions converted by etl/reference/spadl.py from {Path(replay).name} "
                       "(narrative-engine/devtools/spadl_fixture.py). Read rows with finalSeq <= seq.",
        "matchId": ma1["matchId"], "homeContestantId": home, "actions": actions}, separators=(",", ":")) + "\n",
        encoding="utf-8")
    print(f"{len(actions)} actions -> {out}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
