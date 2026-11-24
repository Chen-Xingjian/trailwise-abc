"""Keep generated dependencies and models in the Mac's local application cache."""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Install the pinned Mac development dependencies")
    parser.add_argument("--cache-dir", type=Path, default=Path.home() / "Library/Caches/Trailwise/nepal-trail-rag")
    args = parser.parse_args()
    if sys.platform != "darwin" or sys.version_info[:2] != (3, 12):
        parser.error("Run this Mac setup with Python 3.12.")
    cache = args.cache_dir.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    venv = cache / "fresh-venv"
    if not (venv / "bin/python").exists():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    (cache / "model-runtime").mkdir(exist_ok=True)
    if args.install:
        subprocess.run([
            str(venv / "bin/python"), "-m", "pip", "install", "-c",
            str(ROOT / "requirements/constraints-mac.txt"), "-e",
            str(ROOT) + "[dev,embeddings,mlx,download]",
        ], cwd=ROOT, check=True)
    print(f"Local generated files: {cache}")
    print(f"Next: {venv / 'bin/python'} scripts/download_models.py")
    print(f"Then: {venv / 'bin/python'} scripts/launch_local.py --runtime-dir {cache / 'model-runtime'}")


if __name__ == "__main__":
    main()
