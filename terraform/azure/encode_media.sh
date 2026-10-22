#!/usr/bin/env bash
# Re-encode a packaged HLS dir segment by segment at a lower bitrate for Azure (secondary fixtures).
# Keeps each segment's name, timestamps (-copyts), 2 s length and leading keyframe; copies match.m3u8.
# Usage: encode_media.sh SRC_HLS_DIR DST_HLS_DIR BITRATE MAXRATE BUFSIZE [JOBS]
set -euo pipefail
src=$1 dst=$2 rate=$3 maxrate=$4 bufsize=$5 jobs=${6:-5}
mkdir -p "$dst"
export rate maxrate bufsize dst
find "$src" -name '*.ts' -print0 | xargs -0 -P "$jobs" -I{} sh -c '
  out="$dst/$(basename "$1")"
  [ -s "$out" ] && exit 0
  ffmpeg -v error -y -copyts -i "$1" -map 0 -c:v libx264 -preset veryfast -threads 2 -vf scale=-2:720 -r 25 \
    -b:v "$rate" -maxrate "$maxrate" -bufsize "$bufsize" -g 50 -keyint_min 50 -sc_threshold 0 \
    -force_key_frames "expr:eq(n,0)" -c:a copy -muxdelay 0 -muxpreload 0 -f mpegts "$out.tmp" && mv "$out.tmp" "$out"
' _ {}
cp "$src/match.m3u8" "$dst/match.m3u8"
