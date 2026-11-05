"""Ollama client. Every call sets the context window and decoding options explicitly."""
from __future__ import annotations

from dataclasses import dataclass

import requests

from nsight.config import Settings


class ModelUnavailable(RuntimeError):
    pass


@dataclass
class Completion:
    text: str
    promptTokens: int
    outputTokens: int
    durationMs: int


class OllamaClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def listModels(self) -> list[str]:
        try:
            r = requests.get(f"{self.settings.ollamaUrl}/api/tags", timeout=5)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise ModelUnavailable(f"can't reach ollama at {self.settings.ollamaUrl}") from exc
        return sorted(m.get("name", "") for m in r.json().get("models", []))

    def resolveModel(self, model: str) -> str:
        """Return the installed name for a model, or raise if it isn't pulled."""
        names = self.listModels()
        for candidate in (model, f"{model}:latest"):
            if candidate in names:
                return candidate
        raise ModelUnavailable(
            f"model '{model}' isn't pulled. installed: {', '.join(names) or 'none'}")

    def complete(self, prompt: str, model: str, *, prefill: str | None = None,
                 stop: list[str] | None = None, maxTokens: int = 900) -> Completion:
        s = self.settings
        options = {
            "temperature": s.temperature,
            "num_predict": maxTokens,
            "num_ctx": s.numCtx,
            "repeat_last_n": s.repeatLastN,
            "repeat_penalty": s.repeatPenalty,
        }
        if stop:
            options["stop"] = stop
        payload: dict = {"model": model, "stream": False, "options": options}
        if prefill:
            # raw mode with gemma's chat template so the prefill lands inside the model turn
            payload["raw"] = True
            payload["prompt"] = (f"<start_of_turn>user\n{prompt}<end_of_turn>\n"
                                 f"<start_of_turn>model\n{prefill}")
        else:
            payload["prompt"] = prompt
        try:
            r = requests.post(f"{s.ollamaUrl}/api/generate", json=payload,
                              timeout=s.requestTimeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise ModelUnavailable(f"generation failed: {exc}") from exc
        data = r.json()
        text = data.get("response", "")
        if prefill:
            text = prefill + text
        return Completion(
            text=text,
            promptTokens=int(data.get("prompt_eval_count") or 0),
            outputTokens=int(data.get("eval_count") or 0),
            durationMs=int((data.get("total_duration") or 0) / 1_000_000),
        )
