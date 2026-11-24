"""Validate the exact reviewed release without downloading or invoking any model."""

import argparse
import json
from pathlib import Path

from app.config import ROOT
from app.release import load_release

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--release", type=Path, default=ROOT / "data/release")
args = parser.parse_args()
release = load_release(args.release)
print(json.dumps({"valid": True, "release_id": release.manifest["release_id"],
                  "facts": len(release.facts), "sources": len(release.sources),
                  "atomic_chunks": len(release.chunks), "production_ready": False}, indent=2))
