#!/usr/bin/env bash
# Existing instrumented native runtime; see docs/grf-demo.md for setup and provenance.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
python="${GRF_PYTHON:-$root/.local/grf-native315/bin/python}"
output="${1:-$root/.local/grf-demo-$(date -u +%Y%m%dT%H%M%SZ)}"
[[ -x "$python" ]] || { echo 'Set GRF_PYTHON to an instrumented GRF Python runtime.' >&2; exit 1; }
export PYTHONPATH="$root/data-generation${GRF_SOURCE:+:$GRF_SOURCE}${PYTHONPATH:+:$PYTHONPATH}"
"$python" -m grf_demo.capture --output "$output" --seed "${GRF_SEED:-7}"
"$python" -m grf_demo.translate "$output"
"$python" -m grf_demo.package "$output" "$output/recording.json"
echo "Video: $output/match.mp4"
echo "Events: $output/recording.json"
