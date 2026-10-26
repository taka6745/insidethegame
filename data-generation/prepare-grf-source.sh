#!/usr/bin/env bash
# Disposable per-fixture GRF source: copy the installed instrumented source without build
# output, apply the fixture's cosmetics plus telemetry/realism/tactics patches, build. See README.md, Grf demo.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
fixture="${1:?usage: prepare-grf-source.sh <fixture> [dest]}"
dest="${2:-$root/.local/grf-demo-source-$fixture}"
native="${GRF_NATIVE_SOURCE:-$root/.local/gfootball-native-source}"
python="${GRF_PYTHON:-$root/.local/grf-native315/bin/python}"
[[ ! -e "$dest" ]] || { echo "$dest already exists" >&2; exit 1; }
rsync -a --exclude build/ --exclude '*.egg-info' --exclude __pycache__ --exclude CMakeCache.txt \
  --exclude CMakeFiles/ --exclude Makefile --exclude cmake_install.cmake --exclude '*.a' \
  --exclude '*.dylib' --exclude _gameplayfootball.so "$native/" "$dest/"
for patch in prepare_cosmetics prepare_telemetry prepare_realism prepare_tactics; do
  (cd "$root/data-generation" && GRF_FIXTURE="$fixture" "$python" -m "grf_demo.$patch" "$dest")
done
engine="$dest/third_party/gfootball_engine"
cp -R "$dest/third_party/fonts" "$engine/fonts"
ln -s third_party/gfootball_engine "$dest/gfootball_engine"
(cd "$engine" && cmake . && nice make -j"${GRF_JOBS:-2}")
ln -s libgame.dylib "$engine/_gameplayfootball.so"
echo "GRF_SOURCE=$dest"
