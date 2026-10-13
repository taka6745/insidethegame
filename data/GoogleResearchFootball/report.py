#!/usr/bin/env python3
"""Build the committed benchmark graphic and small data example from a real run."""

import argparse
import gzip
import json
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle


def frames(path):
    with gzip.open(path, "rt") as f:
        return [r for line in f if (r := json.loads(line))["kind"] == "frame"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument(
        "--host", help="Measured host label, e.g. Apple M4 / Docker ARM64"
    )
    args = parser.parse_args()
    dest = Path(__file__).resolve().parent
    report = json.loads((args.run / "benchmark.json").read_text())
    report["measurement_host"] = args.host or report["architecture"]
    if not report["branch_test"]:
        parser.error("The graphic needs a run with the checkpoint branch test enabled")
    (dest / "benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
    shutil.copyfile(args.run / "validation.json", dest / "validation.json")
    game = args.run / "game-01"
    with gzip.open(game / "raw.jsonl.gz", "rt") as f:
        first = json.loads(next(f))
    passes = json.loads((game / "passes.json").read_text())
    sample = {
        "synthetic": True,
        "upstream_commit": report["upstream_commit"],
        "frame": first,
        "pass": next((p for p in passes if p["completed"]), None),
    }
    (dest / "sample.json").write_text(json.dumps(sample, indent=2) + "\n")
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "svg.fonttype": "none",
            "text.color": "#dce8f0",
            "axes.labelcolor": "#dce8f0",
            "xtick.color": "#9cb0c0",
            "ytick.color": "#dce8f0",
            "axes.edgecolor": "#31475a",
        }
    )
    fig, (ax, pitch) = plt.subplots(
        2, 1, figsize=(10, 7.2), height_ratios=[1, 1.6], facecolor="#101f2c"
    )
    for a in (ax, pitch):
        a.set_facecolor("#101f2c")
    fig.suptitle(
        "Synthetic football · measured, exported, replayed",
        fontsize=19,
        x=0.08,
        ha="left",
        y=0.97,
    )
    modes = ["headless_no_export", "verbose_export"]
    values = [report["median_wall_seconds"][m] for m in modes]
    ax.barh([1, 0], values, color=["#53cbbb", "#64a7ff"], height=0.4)
    for y, v, mode in zip([1, 0], values, modes):
        times = [r["wall_seconds"] for r in report["runs"] if r["mode"] == mode]
        ax.plot(times, [y] * len(times), "o", color="#ffffff", ms=4)
        ax.text(v + 1.7, y, f"{v:.1f}s median", va="center", fontsize=12)
    ax.set_yticks([1, 0], ["Headless", "Verbose export"])
    ax.set_xlim(0, max(values) * 1.5)
    ax.set_xlabel(
        "Wall seconds per complete scenario · dots = individual runs", labelpad=10
    )
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.text(
        0,
        1.12,
        f"{len(report['runs']) // 2} seeds · CPU only · {report['measurement_host']}",
        transform=ax.transAxes,
        fontsize=10,
        color="#9cb0c0",
    )
    pitch.add_patch(
        Rectangle((-55, -36), 110, 72, fill=False, edgecolor="#456274", lw=1.4)
    )
    pitch.plot([0, 0], [-36, 36], color="#456274", lw=1)
    pitch.add_patch(Circle((0, 0), 9.15, fill=False, edgecolor="#456274"))
    for x in (-55, 38.5):
        pitch.add_patch(
            Rectangle((x, -20.16), 16.5, 40.32, fill=False, edgecolor="#456274")
        )
    for name, color in [("original", "#53cbbb"), ("alternative", "#ffbc66")]:
        rows = frames(args.run / "branch" / f"{name}.jsonl.gz")
        xy = [r["ball_position_m"][:2] for r in rows]
        pitch.plot(
            [p[0] for p in xy],
            [p[1] for p in xy],
            color=color,
            lw=2.1,
            label="Original + exact replay" if name == "original" else "Changed action",
        )
        pitch.scatter(*xy[-1], s=50, color=color, zorder=3)
    pitch.set_title(
        "Same saved moment → different ball paths", loc="left", fontsize=14, pad=14
    )
    pitch.set_xlim(-59, 59)
    pitch.set_ylim(-40, 40)
    pitch.set_aspect("equal")
    pitch.axis("off")
    pitch.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.015),
        ncol=2,
        frameon=False,
        labelcolor="#dce8f0",
    )
    fig.text(
        0.08,
        0.027,
        "The 90-minute match clock is accelerated. This is simulator behaviour, not a real-match prediction.",
        fontsize=9,
        color="#9cb0c0",
    )
    fig.subplots_adjust(left=0.17, right=0.93, top=0.86, bottom=0.1, hspace=0.48)
    fig.savefig(dest / "benchmark.svg", facecolor=fig.get_facecolor())
    fig.savefig(args.run / "benchmark.png", dpi=160, facecolor=fig.get_facecolor())
    plt.close(fig)


if __name__ == "__main__":
    main()
