"""Start the pinned MLX model and semantic RAG app on loopback only."""

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def live_status(opener):
    try:
        with opener.open("http://127.0.0.1:8765/api/status", timeout=4) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError):
        return None


def verify_service(status, release, model_paths, revision):
    embedding = status.get("embedding", {})
    model = status.get("model", {})
    generation = status.get("generation_config", {})
    matches = (
        status.get("application_revision") == revision
        and status.get("release_id") == release.manifest["release_id"]
        and status.get("indexed_fact_count") == len(release.facts)
        and embedding.get("mode") == "sentence-transformers"
        and embedding.get("message", "").startswith("sentence-transformers:" + model_paths["embedding"] + ":")
        and status.get("index", {}).get("fingerprint") == release.index_fingerprint(embedding["message"])
        and model.get("connected") and model.get("model_id") == model_paths["generator"]
        and generation.get("temperature") == 0 and generation.get("max_tokens") == 384
    )
    if not matches:
        raise RuntimeError("Port 8765 serves another configuration. Stop that launcher before starting this release.")


def show_chat(open_browser):
    url = "http://127.0.0.1:8765/"
    print(f"Trailwise is ready: {url}", flush=True)
    if open_browser:
        webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, default=Path.home() / "Library/Caches/Trailwise/nepal-trail-rag/model-runtime")
    parser.add_argument("--no-browser", action="store_true", help="Leave the browser closed")
    args = parser.parse_args()
    from app.config import application_revision
    from app.release import load_release

    release_dir = Path(os.getenv("DATA_RELEASE_DIR") or ROOT / "documents/abc-six-day").resolve()
    release = load_release(release_dir)
    revision = application_revision()
    runtime = args.runtime_dir.expanduser().resolve()
    snapshots_file = runtime / "model_snapshots.json"
    if not snapshots_file.exists():
        raise SystemExit("Download the pinned models first: python scripts/download_models.py")
    snapshots = {x["model_id"]: x for x in json.loads(snapshots_file.read_text())}
    pins = json.loads((ROOT / "config/model_pins.json").read_text())["models"]
    paths = {}
    for pin in pins:
        snapshot = snapshots.get(pin["model_id"], {})
        path = Path(snapshot.get("snapshot_path", "/missing"))
        if snapshot.get("revision") != pin["revision"] or not (path / "config.json").exists():
            raise SystemExit(f"Missing pinned snapshot: {pin['model_id']}")
        paths[pin["role"]] = str(path)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    status = live_status(opener)
    if status is not None:
        verify_service(status, release, paths, revision)
        show_chat(not args.no_browser)
        return
    for port in (8081, 8765):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is already in use. Stop its existing service first.")
    env = {**os.environ, "DATA_RELEASE_DIR": str(release_dir), "HF_HOME": str(runtime / "hf"), "RUNTIME_DIR": str(runtime), "HF_HUB_OFFLINE": "1",
           "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false",
           "MODEL_BASE_URL": "http://127.0.0.1:8081/v1", "MODEL_ID": paths["generator"],
           "EMBEDDING_MODE": "sentence-transformers", "EMBEDDING_MODEL": paths["embedding"],
           "EMBEDDING_DEVICE": "cpu", "MAX_TOKENS": "384", "TEMPERATURE": "0"}
    children = []

    def stop(*_):
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        model = subprocess.Popen([
            sys.executable, "-m", "mlx_lm", "server", "--model", paths["generator"],
            "--host", "127.0.0.1", "--port", "8081", "--allowed-origins", "http://127.0.0.1:8765",
            "--temp", "0", "--max-tokens", "384", "--chat-template-args", '{"enable_thinking":false}',
            "--decode-concurrency", "1", "--prompt-concurrency", "1", "--prompt-cache-size", "2",
        ], cwd=ROOT, env=env)
        children.append(model)
        ready = False
        for _ in range(180):
            if model.poll() is not None:
                raise RuntimeError("The MLX model server stopped during startup.")
            try:
                with opener.open("http://127.0.0.1:8081/v1/models", timeout=2) as response:
                    ready = response.status == 200
                if ready:
                    break
            except (urllib.error.URLError, TimeoutError):
                time.sleep(1)
        if not ready:
            raise RuntimeError("The local model server did not become ready.")
        app = subprocess.Popen([
            sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
            "--port", "8765", "--workers", "1",
        ], cwd=ROOT, env=env)
        children.append(app)
        for _ in range(240):
            if app.poll() is not None or model.poll() is not None:
                raise RuntimeError("A local service stopped before the chat was ready.")
            status = live_status(opener)
            if status is not None:
                verify_service(status, release, paths, revision)
                break
            time.sleep(1)
        else:
            raise RuntimeError("Timed out waiting for the chat to load the release.")
        show_chat(not args.no_browser)
        while app.poll() is None and model.poll() is None:
            time.sleep(1)
        if app.poll() not in (None, 0) or model.poll() not in (None, 0):
            raise RuntimeError("A local service stopped. See its output above.")
    except KeyboardInterrupt:
        pass
    finally:
        stop()


if __name__ == "__main__":
    main()
