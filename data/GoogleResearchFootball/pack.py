#!/usr/bin/env python3
"""Pack a rendered match's complete data into a standard, lossless ZIP."""

import argparse
import gzip
import hashlib
import json
import subprocess
import time
import zipfile
from pathlib import Path

CHUNK = 4 * 1024 * 1024


def pack(run, output):
    # Exclusive creation protects existing archives and leaves all sources intact.
    sources = sorted((run / "data").iterdir())
    sources += [run / "frame-times.jsonl", run / "render.json"]
    sources += sorted((run / "checkpoints").iterdir())
    sources += [
        p for p in (run / "validation.json", run / "720p-result.json") if p.exists()
    ]
    manifest = {}
    started = time.monotonic()
    with zipfile.ZipFile(
        output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for source in sources:
            if not source.is_file():
                continue
            name = source.relative_to(run).as_posix()
            opener = gzip.open if source.suffix == ".gz" else open
            if source.suffix == ".gz":
                name = name[:-3]
            digest = hashlib.sha256()
            size = lines = 0
            reported = time.monotonic()
            print(f"Packing {name}", flush=True)
            with (
                opener(source, "rb") as incoming,
                archive.open(name, "w", force_zip64=True) as target,
            ):
                while chunk := incoming.read(CHUNK):
                    target.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                    lines += chunk.count(b"\n")
                    if time.monotonic() - reported >= 30:
                        print(f"  {name}: {size / 1e9:.2f} GB read", flush=True)
                        reported = time.monotonic()
            manifest[name] = {
                "source": source.relative_to(run).as_posix(),
                "source_bytes": source.stat().st_size,
                "bytes": size,
                "lines": lines,
                "sha256": digest.hexdigest(),
                "compressed_bytes": archive.getinfo(name).compress_size,
            }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
        archive.writestr(
            "README.txt",
            (
                "Synthetic Google Research Football match data.\n"
                "Open this standard ZIP with your normal ZIP extractor. ZIP64 supports the large CSV/JSON files.\n"
                "Every CSV/JSON byte is preserved: no rows, columns or precision were removed.\n"
                "Original .gz files are decompressed inside this archive: players.csv, raw.jsonl, etc.\n"
                "manifest.json records SHA-256 hashes and byte/line counts of these uncompressed contents.\n"
                "data/summary.json and render.json retain their original .gz file hashes for provenance.\n"
                "frame-times.jsonl maps video frames to the simulation; checkpoints/ holds saved engine states.\n"
                "Video is separate. See render.json for source revision and simulation configuration.\n"
            ),
        )

    # Verify through the system extractor, independently of Python's ZIP writer.
    for name, expected in manifest.items():
        digest = hashlib.sha256()
        size = lines = 0
        print(f"Verifying {name}", flush=True)
        process = subprocess.Popen(
            ["unzip", "-p", str(output), name], stdout=subprocess.PIPE
        )
        with process.stdout:
            while chunk := process.stdout.read(CHUNK):
                digest.update(chunk)
                size += len(chunk)
                lines += chunk.count(b"\n")
        if process.wait() != 0 or (size, lines, digest.hexdigest()) != (
            expected["bytes"],
            expected["lines"],
            expected["sha256"],
        ):
            raise RuntimeError(f"Extracted content differs: {name}")
    with output.open("rb") as f:
        checksum = hashlib.file_digest(f, "sha256").hexdigest()
    result = {
        "archive": output.name,
        "bytes": output.stat().st_size,
        "sha256": checksum,
        "elapsed_seconds": time.monotonic() - started,
        "verified_with": "unzip -p; SHA-256, bytes and lines match every source's uncompressed contents",
        "files": manifest,
    }
    output.with_suffix(".verification.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "files"}), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pack(args.run, args.output)
