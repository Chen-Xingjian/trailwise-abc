#!/bin/sh
set -eu
task_root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
task_python="$HOME/Library/Caches/Trailwise/nepal-trail-rag/fresh-venv/bin/python"
if [ ! -x "$task_python" ]; then
  echo "Run Python 3.12 scripts/setup_mac.py --install first. See README.md."
  exit 1
fi
cd "$task_root"
exec "$task_python" scripts/launch_local.py
