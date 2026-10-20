#!/bin/sh
# Ship the pinned hls.js light ES module from this origin (strict CSP: no CDN, no workers).
# Named .js so nginx serves a JavaScript MIME type to the module loader.
set -eu
output_dir=${1:?Usage: vendor.sh OUTPUT_DIRECTORY}
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")/../node_modules/hls.js" && pwd)
mkdir -p "$output_dir"
sed '/sourceMappingURL=/d' "$source_dir/dist/hls.light.min.mjs" > "$output_dir/hls.js"
cp "$source_dir/LICENSE" "$output_dir/hls.LICENSE.txt"
