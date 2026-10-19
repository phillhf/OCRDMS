"""Schlanker Client für die Ollama-REST-API mit JSON-Schema-Ausgabe."""

from __future__ import annotations

import json
import logging

import requests

log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int = 600):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def list_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            raise OllamaError(f"Ollama nicht erreichbar unter {self.base_url}: {e}") from e
        return [m["name"] for m in r.json().get("models", [])]

    def check(self) -> None:
        models = self.list_models()
        if self.model not in models:
            raise OllamaError(
                f"Modell '{self.model}' ist in Ollama nicht vorhanden. Verfügbar: {', '.join(models) or '–'}"
            )

    def chat_json(self, system: str, user: str, schema: dict) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": schema,
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_ctx": 8192},
        }
        try:
            r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        except requests.RequestException as e:
            raise OllamaError(f"Ollama-Anfrage fehlgeschlagen: {e}") from e
        if r.status_code != 200:
            raise OllamaError(f"Ollama-Fehler {r.status_code}: {r.text[:300]}")
        data = r.json()
        log.debug("Ollama: %s Prompt-Token in %.1f s, %s Antwort-Token in %.1f s",
                  data.get("prompt_eval_count"), data.get("prompt_eval_duration", 0) / 1e9,
                  data.get("eval_count"), data.get("eval_duration", 0) / 1e9)
        content = data.get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise OllamaError(f"Ungültige JSON-Antwort des Modells: {content[:300]}") from e
