#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$script_dir/../.." && pwd)"
python="$repo_dir/.local/grf-native315/bin/python"
[[ -x "$python" ]] || { echo 'Run data/GoogleResearchFootball/setup-native.sh first.' >&2; exit 1; }
run_name="${GRF_RUN_NAME:-full-4k-$(date -u +%Y%m%dT%H%M%SZ)}"
case "$run_name" in *[!a-zA-Z0-9_-]*|'') echo 'Use a simple GRF_RUN_NAME.' >&2; exit 2;; esac
mkdir -p "$repo_dir/.local/grf-runs"
caffeinate -is "$python" "$script_dir/render.py" --output "$repo_dir/.local/grf-runs/$run_name" "$@"
