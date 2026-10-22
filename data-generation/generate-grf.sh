#!/usr/bin/env bash
# Existing instrumented runtime, prepared by prepare-grf-source.sh for GRF_FIXTURE; see docs/components/grf-demo.md.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
python="${GRF_PYTHON:-$root/.local/grf-native315/bin/python}"
export GRF_FIXTURE="${GRF_FIXTURE:-riverton-forgeham}"
output="${1:-$root/.local/grf-demo-$GRF_FIXTURE-$(date -u +%Y%m%dT%H%M%SZ)}"
[[ -x "$python" ]] || { echo 'Set GRF_PYTHON to an instrumented GRF Python runtime.' >&2; exit 1; }
export PYTHONPATH="$root/data-generation${GRF_SOURCE:+:$GRF_SOURCE}${PYTHONPATH:+:$PYTHONPATH}"
"$python" -m grf_demo.capture --output "$output" --seed "${GRF_SEED:-37}"
"$python" -m grf_demo.translate "$output"
"$python" -m grf_demo.package "$output" "$output/recording.json"
echo "Video: $output/match.mp4"
echo "Events: $output/recording.json"
