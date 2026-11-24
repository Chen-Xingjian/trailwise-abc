"""A loopback-only chat-completion client; no remote fallback or invented answers."""

import re
import time

import httpx

from app.config import Settings


class LocalLLM:
    def __init__(self, settings: Settings):
        self.settings = settings
        headers = {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}
        self.client = httpx.Client(base_url=settings.model_base_url + "/", headers=headers, trust_env=False)
        self._last_probe = 0.0
        self._status = {"connected": False, "model_id": None, "message": "Local model not checked yet."}

    def status(self, force: bool = False) -> dict:
        if not force and time.monotonic() - self._last_probe < 10:
            return self._status
        self._last_probe = time.monotonic()
        try:
            response = self.client.get("models", timeout=2)
            response.raise_for_status()
            ids = [x["id"] for x in response.json().get("data", [])]
            chosen = self.settings.model_id or (ids[0] if ids else "")
            if not chosen or (self.settings.model_id and chosen not in ids):
                raise ValueError("Configured model is not listed by the local server.")
            self._status = {"connected": True, "model_id": chosen, "message": "Local model server is available."}
        except (httpx.HTTPError, ValueError, KeyError):
            self._status = {"connected": False, "model_id": None, "message": "Start the configured local model server to enable generated answers."}
        return self._status

    def complete(self, messages: list[dict]) -> dict:
        status = self.status()
        if not status["connected"]:
            raise RuntimeError(status["message"])
        response = self.client.post("chat/completions", json={
            "model": status["model_id"], "messages": messages,
            "temperature": self.settings.temperature, "max_tokens": self.settings.max_tokens,
            "stream": False, "chat_template_kwargs": {"enable_thinking": False},
        }, timeout=self.settings.model_timeout)
        response.raise_for_status()
        body = response.json()
        answer = body["choices"][0]["message"].get("content") or ""
        answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()
        if not answer:
            raise RuntimeError("Local model returned no visible answer.")
        return {"answer": answer, "model_id": status["model_id"], "usage": body.get("usage", {}),
                "finish_reason": body["choices"][0].get("finish_reason"),
                "system_fingerprint": body.get("system_fingerprint")}

    def close(self):
        self.client.close()
