#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$root"
python_bin="$HOME/Library/Caches/Trailwise/nepal-trail-rag/fresh-venv/bin/python"
if [ ! -x "$python_bin" ]; then
  echo "Run python3.12 scripts/setup_mac.py --install first. See README.md." >&2
  exit 1
fi
export DATA_RELEASE_DIR="${DATA_RELEASE_DIR:-$root/documents/abc-six-day}"
export ABC_SOURCE_WATCH="${ABC_SOURCE_WATCH:-1}"
exec "$python_bin" -m scripts.launch_local "$@"
