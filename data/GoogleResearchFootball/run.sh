#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$script_dir/../.." && pwd)"
output_root="$repo_dir/.local/grf-runs"
mkdir -p "$output_root"
# Override only the run name, not arbitrary container mount paths.
run_name="${GRF_RUN_NAME:-$(date -u +%Y%m%dT%H%M%SZ)}"
case "$run_name" in *[!a-zA-Z0-9_-]*|'') echo 'Use a simple GRF_RUN_NAME (letters, digits, _ or -).' >&2; exit 2;; esac
docker build -t insidethegame-grf:research "$script_dir"
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  -v "$script_dir:/work:ro" -v "$output_root:/outputs" \
  insidethegame-grf:research run.py --output "/outputs/$run_name" "$@"
printf 'Saved to %s/%s\n' "$output_root" "$run_name"
