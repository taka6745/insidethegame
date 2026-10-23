"""Trend thresholds from the shipped recordings (python -m devtools.calibrate_trends).

Prints notableAt / highAt / changeAt per enabled indicator, as the newest trendDefinitions seed should hold them:
every served value (reference/trends.py) at the end of each minute of each shipped recording, both teams pooled.
- notableAt and highAt mark the outer 20% and 10% of the values in the definition's direction: the first observed
  value whose tail (values at or beyond it) holds at most that share, so a count is never notable at its mode.
- changeAt is the 90th percentile of |value - baseline| where the baseline window (prev10) is full.
Single-window trends (the fade, territory by game state) use their own window; everything else last5.
"""
import sys
from pathlib import Path

ETL = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ETL), str(ETL / "tests")]

from reference import trends  # noqa: E402
import v2_stream  # noqa: E402
from support import outputs  # noqa: E402

TAILS = {"notableAt": 0.20, "highAt": 0.10}
CHANGE_QUANTILE = 0.90


def served(fixture):
    """Every trendsAtSeq row at the end of each match minute of one run."""
    rows = outputs(v2_stream.build(fixture=fixture))
    events = rows["canonicalEvents"]
    ends = {}
    for e in events:
        ends[(e["periodId"], e["matchTimeSeconds"] // 60)] = e["seq"]
    out = []
    for seq in sorted(ends.values()):
        now = trends.trends_at_seq(rows["matches"][0], events, rows["possessionSamples"], seq, len(events),
                                   actions=rows["spadlActions"], raw=rows["rawEvents"])
        full = {r["contestantId"] for r in now if r["window"] == "prev10" and r["minutes"] == 10}
        out += [{**r, "baselineFull": r["contestantId"] in full} for r in now]
    return out


def tail(values, share, low):
    """The value closest to the centre whose tail (values at or beyond it) holds at most `share` of all."""
    found = None
    for v in sorted(set(values), reverse=not low):
        if sum(x <= v if low else x >= v for x in values) / len(values) > share:
            break
        found = v
    return found


def quantile(values, q):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else None


def main():
    rows = [r for fixture in v2_stream.FIXTURES for r in served(fixture)]
    for d in trends.definitions():
        if d["family"] not in ("indicator", "composite"):
            continue
        window = trends.SINGLE.get(d["trendId"], "last5")
        mine = [r for r in rows if r["trendId"] == d["trendId"] and r["window"] == window
                and r["minutes"] >= trends.FULL[window] and r["value"] is not None]
        if not mine:
            print(f"{d['trendId']}: no values")
            continue
        low = d.get("direction") == "low"
        values = [r["value"] for r in mine]
        deltas = [abs(r["delta"]) for r in mine if r["delta"] is not None and r["baselineFull"]]
        found = {k: tail(values, share, low) for k, share in TAILS.items()}
        change = quantile(deltas, CHANGE_QUANTILE)
        print(f"{d['trendId']}: n {len(values)} notableAt {rounded(found['notableAt'])} "
              f"highAt {rounded(found['highAt'])} changeAt {rounded(change)}")


def rounded(value):
    return None if value is None else round(value, 3)


if __name__ == "__main__":
    main()
