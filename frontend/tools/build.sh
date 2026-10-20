#!/bin/sh
# Static build from compiled output (npm run build → dist/): one content fingerprint keeps relative ES module imports together.
set -eu
source_dir=${2:-$(CDPATH= cd -- "$(dirname -- "$0")/../dist" && pwd)}
output_dir=${1:?Usage: build.sh OUTPUT_DIRECTORY [SOURCE_DIRECTORY]}
[ -f "$source_dir/match/index.html" ] || { echo 'Missing match entry point' >&2; exit 1; }

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi
}
fingerprint=$(
    cd "$source_dir"
    find match -type f -print | LC_ALL=C sort | while IFS= read -r file; do checksum "$file"; done | checksum | cut -c 1-20
)
asset_dir="$output_dir/app/$fingerprint"
mkdir -p "$asset_dir"
cp -R "$source_dir/match/." "$asset_dir/"
sed "s|/match/|/app/$fingerprint/|g" "$source_dir/match/index.html" > "$output_dir/index.html"
rm "$asset_dir/index.html"
printf 'Built /app/%s/\n' "$fingerprint"
