#!/bin/sh
set -eu
app_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
release_dir=${DATA_RELEASE_DIR:-"$app_dir/documents/abc-six-day"}
if [ ! -f "$release_dir/manifest.json" ]; then
  echo "Set DATA_RELEASE_DIR to the reviewed ABC release directory."
  exit 1
fi
export ABC_SOURCE_WATCH="${ABC_SOURCE_WATCH:-1}"
export DATA_RELEASE_DIR="$release_dir"
exec "$app_dir/run-local.command"
