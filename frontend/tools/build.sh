#!/bin/sh
# Static build from compiled output (npm run build → dist/): one content fingerprint over match/ and shared/ keeps
# relative ES module imports together under /app/{fingerprint}/.
set -eu
source_dir=${2:-$(CDPATH= cd -- "$(dirname -- "$0")/../dist" && pwd)}
output_dir=${1:?Usage: build.sh OUTPUT_DIRECTORY [SOURCE_DIRECTORY]}
[ -f "$source_dir/match/index.html" ] || { echo 'Missing match entry point' >&2; exit 1; }

checksum() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$@"; else shasum -a 256 "$@"; fi
}
modules=$(cd "$source_dir" && for dir in match shared; do [ -d "$dir" ] && echo "$dir"; done)
fingerprint=$(
    cd "$source_dir"
    find $modules -type f -print | LC_ALL=C sort | while IFS= read -r file; do checksum "$file"; done | checksum | cut -c 1-20
)
asset_dir="$output_dir/app/$fingerprint"
mkdir -p "$asset_dir"
for dir in $modules; do cp -R "$source_dir/$dir" "$asset_dir/"; done
sed "s|/match/|/app/$fingerprint/match/|g" "$source_dir/match/index.html" > "$output_dir/index.html"
rm "$asset_dir/match/index.html"
# A tab opened before a deploy still asks for its old fingerprint; nginx falls back to this build (app/current)
# instead of a 404, so nobody needs a hard refresh after a deploy.
ln -sfn "$fingerprint" "$output_dir/app/current"
printf 'Built /app/%s/\n' "$fingerprint"
