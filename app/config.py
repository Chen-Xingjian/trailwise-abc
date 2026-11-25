"""Explicit local configuration; no hosted service is enabled by default."""

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNTIME = (Path.home() / "Library/Caches/Trailwise/nepal-trail-rag/model-runtime"
                   if sys.platform == "darwin" else ROOT / "runtime")


def application_revision():
    digest = hashlib.sha256()
    for directory in (ROOT / "app", ROOT / "config"):
        for path in sorted(directory.rglob("*")):
            if path.suffix in {".py", ".json", ".js", ".mjs", ".html", ".css"}:
                digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


@dataclass(frozen=True)
class Settings:
    release_dir: Path = ROOT / "data/release"
    runtime_dir: Path = DEFAULT_RUNTIME
    embedding_mode: str = "hash"
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_device: str = "cpu"
    model_base_url: str = "http://127.0.0.1:1234/v1"
    model_id: str = ""
    model_timeout: float = 120
    max_tokens: int = 384
    temperature: float = 0
    api_key: str = ""
    monitor_sources: bool = False

    def __post_init__(self):
        parsed = urlparse(self.model_base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1", "localhost", "::1"
        }:
            raise ValueError("This local prototype only permits a loopback model endpoint.")
        if self.embedding_mode not in {"hash", "sentence-transformers"}:
            raise ValueError("EMBEDDING_MODE must be hash or sentence-transformers.")


def settings_from_env() -> Settings:
    load_dotenv(ROOT / ".env", override=False)
    return Settings(
        release_dir=Path(os.getenv("DATA_RELEASE_DIR", str(ROOT / "data/release"))).resolve(),
        runtime_dir=Path(os.getenv("RUNTIME_DIR", str(DEFAULT_RUNTIME))).expanduser().resolve(),
        embedding_mode=os.getenv("EMBEDDING_MODE", "hash"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B"),
        embedding_device=os.getenv("EMBEDDING_DEVICE", "cpu"),
        model_base_url=os.getenv("MODEL_BASE_URL", "http://127.0.0.1:1234/v1").rstrip("/"),
        model_id=os.getenv("MODEL_ID", ""),
        model_timeout=float(os.getenv("MODEL_TIMEOUT", "120")),
        max_tokens=int(os.getenv("MAX_TOKENS", "384")),
        temperature=float(os.getenv("TEMPERATURE", "0")),
        monitor_sources=os.getenv("ABC_SOURCE_WATCH") == "1",
        api_key=os.getenv("MODEL_API_KEY", ""),
    )
