"""Download pinned public model snapshots into the ignored project runtime directory."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
default_runtime = Path.home() / "Library/Caches/Trailwise/nepal-trail-rag/model-runtime" if sys.platform == "darwin" else ROOT / "runtime"
runtime = Path(os.getenv("RUNTIME_DIR", str(default_runtime))).expanduser().resolve()
runtime.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(runtime / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import truststore  # noqa: E402

truststore.inject_into_ssl()  # Use verified macOS/system trust; never disable TLS verification.

from huggingface_hub import snapshot_download  # noqa: E402

models = json.loads((ROOT / "config/model_pins.json").read_text())["models"]
results = []
for model in models:
    model_id, revision = model["model_id"], model["revision"]
    print(f"Downloading {model_id} at {revision}", flush=True)
    snapshot = snapshot_download(
        model_id,
        revision=revision,
        allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.jinja", "LICENSE", "README.md"],
        ignore_patterns=["onnx/*", "openvino/*", "*.bin", "*.h5"],
        max_workers=2,
    )
    results.append({"role": model["role"], "model_id": model_id, "revision": revision, "snapshot_path": snapshot})
    (runtime / "model_snapshots.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"Ready: {model_id}", flush=True)
