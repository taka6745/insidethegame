#!/usr/bin/env bash
# Tested native Apple Silicon rendering environment. No GitHub Actions involved.
set -euo pipefail
script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_dir="$(cd "$script_dir/../.." && pwd)"
source_dir="$repo_dir/.local/gfootball-native-source"
venv_dir="$repo_dir/.local/grf-native315"
[[ "$(uname -s)" == Darwin ]] || { echo 'This setup is for macOS.' >&2; exit 1; }
HOMEBREW_NO_AUTO_UPDATE=1 brew install python@3.15 sdl2 sdl2_image sdl2_ttf sdl2_gfx boost-python3 cmake ffmpeg
[[ -f "$(brew --prefix boost-python3)/lib/libboost_python315.dylib" ]] || {
  echo 'Boost.Python must match Python 3.15; inspect the installed Homebrew version.' >&2; exit 1;
}
if [[ ! -d "$source_dir" ]]; then
  git clone https://github.com/google-research/football.git "$source_dir"
  git -C "$source_dir" checkout 3d9e754720a95621bba6475c4d3b0d56fe919014
fi
[[ "$(git -C "$source_dir" rev-parse HEAD)" == 3d9e754720a95621bba6475c4d3b0d56fe919014 ]] || {
  echo 'Existing source has a different revision; preserving it.' >&2; exit 1;
}
for patch in telemetry.patch render.patch; do
  if git -C "$source_dir" apply --check "$script_dir/$patch" 2>/dev/null; then
    git -C "$source_dir" apply "$script_dir/$patch"
  else
    git -C "$source_dir" apply --reverse --check "$script_dir/$patch"
  fi
done
if [[ ! -d "$venv_dir" ]]; then
  "$(brew --prefix python@3.15)/bin/python3.15" -m venv "$venv_dir"
fi
"$venv_dir/bin/pip" install -r "$script_dir/native-requirements.txt"
PATH="$venv_dir/bin:$PATH" "$venv_dir/bin/pip" install --no-deps --no-build-isolation "$source_dir"
echo 'Ready: data/GoogleResearchFootball/render.sh --seconds 5400'
