"""LLM backends: Gemini (BYO key, default) and Ollama (local fallback).

One interface: generate_json(prompt, schema, images) → dict, with disk
caching keyed on the complete request identity so re-runs never re-spend
— the M2 gate requires cache hits on identical inputs.

Key resolution: PUBLIKCLIP_GEMINI_API_KEY env var, then
PUBLIKCLIP_HOME/secrets.json {"gemini_api_key": "..."} (written by the
app's onboarding). Ollama needs no key — just a running daemon.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx

from .. import config

# The rolling alias, deliberately: Google retires pinned models for NEW api
# keys while still advertising them in ListModels (learned live — 404 "no
# longer available to new users" on gemini-1.5-flash with a fresh key).
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OLLAMA_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_NUM_PREDICT = config.DEFAULT_OLLAMA_NUM_PREDICT
LLM_TIMEOUT = 120.0


class LlmError(Exception):
    """User-actionable LLM failure (bad key, daemon down, model missing)."""


class AIProvider:
    """Provider abstraction: local-first Ollama and optional Gemini fallback."""

    backend = "provider"

    def generate_json(self, prompt: str, schema: dict, images: list[bytes] | None = None) -> dict:
        raise NotImplementedError

    def unload(self) -> None:
        return None

    def generation_metadata(self) -> dict[str, Any]:
        return {}


def gemini_api_key() -> str | None:
    key = os.environ.get("PUBLIKCLIP_GEMINI_API_KEY")
    if key:
        return key
    secrets_path = config.home_dir() / "secrets.json"
    if secrets_path.exists():
        try:
            return json.loads(secrets_path.read_text()).get("gemini_api_key")
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _cache_dir() -> Path:
    path = config.home_dir() / "llm-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_key(
    *,
    backend: str,
    model: str,
    prompt: str,
    schema: dict,
    images: list[bytes],
    generation_options: dict[str, Any],
    thinking: bool | str | None,
) -> str:
    """Hash every input that can change a provider response.

    Image bytes are represented by full SHA-256 identities so cache metadata
    stays small.  The version prevents legacy prompt-only keys from being
    accepted silently after the identity contract changed.
    """
    identity = {
        "version": 2,
        "backend": backend,
        "model": model,
        "prompt": prompt,
        "schema": schema,
        "images": [hashlib.sha256(image).hexdigest() for image in images],
        "generation_options": generation_options,
        "thinking": thinking,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:32]


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


class GeminiClient(AIProvider):
    backend = "gemini"

    def __init__(self, model: str = GEMINI_MODEL):
        self.model = model
        key = gemini_api_key()
        if not key:
            raise LlmError(
                "No Gemini API key found. Add one in Settings (or set "
                "PUBLIKCLIP_GEMINI_API_KEY), or switch to Ollama mode."
            )
        self._key = key

    def generate_json(
        self, prompt: str, schema: dict, images: list[bytes] | None = None
    ) -> dict:
        images = images or []
        generation_options = {
            "responseMimeType": "application/json",
            "temperature": 0.2,
        }
        cache_key = _cache_key(
            backend=self.backend,
            model=self.model,
            prompt=prompt,
            schema=schema,
            images=images,
            generation_options=generation_options,
            thinking=None,
        )
        cache_file = _cache_dir() / f"{cache_key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text())

        parts: list[dict[str, Any]] = [{"text": prompt}]
        for img in images:
            import base64

            parts.append(
                {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}}
            )
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                **generation_options,
                "responseSchema": schema,
            },
        }
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                res = httpx.post(
                    GEMINI_URL.format(model=self.model),
                    params={"key": self._key},
                    json=body,
                    timeout=LLM_TIMEOUT,
                )
                if res.status_code in (401, 403):
                    raise LlmError("Gemini rejected the API key. Check it in Settings.")
                if res.status_code == 429:
                    import time

                    # Surface the API's own words — a quota backoff and a
                    # "credits depleted" billing stop look identical as bare
                    # 429s but need opposite user actions.
                    try:
                        detail = res.json()["error"]["message"]
                    except Exception:  # noqa: BLE001
                        detail = "rate limited"
                    last_err = LlmError(f"Gemini 429: {detail}")
                    if ("credit" in detail.lower() or "billing" in detail.lower()) and "retry in" not in detail.lower():
                        raise last_err
                    
                    # If it says 'retry in X', parse the time, otherwise default to exponential backoff
                    import re
                    match = re.search(r'retry in ([\d\.]+)s', detail.lower())
                    sleep_time = float(match.group(1)) + 1.0 if match else 4 * (attempt + 1)
                    time.sleep(sleep_time)
                    continue
                res.raise_for_status()
                payload = res.json()
                text = payload["candidates"][0]["content"]["parts"][0]["text"]
                data = json.loads(_strip_fences(text))
                cache_file.write_text(json.dumps(data))
                return data
            except LlmError:
                raise
            except (httpx.HTTPError, KeyError, json.JSONDecodeError, IndexError) as err:
                last_err = err
        raise LlmError(f"Gemini call failed after retries: {last_err}")

    def generation_metadata(self) -> dict[str, Any]:
        return {
            "thinking_enabled": None,
            "generation_options": {
                "responseMimeType": "application/json",
                "temperature": 0.2,
            },
        }


class OllamaClient(AIProvider):
    backend = "ollama"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        num_predict: int = OLLAMA_NUM_PREDICT,
    ):
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or OLLAMA_URL).rstrip("/")
        try:
            res = httpx.get(f"{self.base_url}/api/tags", timeout=5.0)
            res.raise_for_status()
        except httpx.HTTPError as err:
            raise LlmError(
                "Ollama isn't running. Start it (`ollama serve`) or switch to Gemini mode."
            ) from err
        models = [m["name"] for m in res.json().get("models", [])]
        if not models:
            raise LlmError("Ollama has no models. Pull one, e.g. `ollama pull qwen3:8b`.")
        preferred = model or os.environ.get("OLLAMA_MODEL") or OLLAMA_MODEL
        self.model = preferred if preferred in models else _pick_ollama_model(models)
        if num_predict <= 0:
            raise LlmError("Ollama generation limit must be greater than zero.")
        self.num_predict = num_predict
        self.thinking_enabled = False if self.model.lower().startswith("qwen3") else None

    def generate_json(
        self, prompt: str, schema: dict, images: list[bytes] | None = None
    ) -> dict:
        input_images = images or []
        if images:
            # Text-only fallback: the caller records visual as signals_missing.
            images = []
        generation_options = {
            "temperature": 0.1,
            "num_predict": self.num_predict,
        }
        cache_key = _cache_key(
            backend=self.backend,
            model=self.model,
            prompt=prompt,
            schema=schema,
            images=input_images,
            generation_options=generation_options,
            thinking=self.thinking_enabled,
        )
        cache_file = _cache_dir() / f"{cache_key}.json"
        if cache_file.exists():
            return json.loads(cache_file.read_text())
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "format": schema,
            "stream": False,
            "options": generation_options,
        }
        if self.thinking_enabled is not None:
            # Ollama's supported Qwen3 control.  A literal /no_think suffix is
            # not sufficient to select the non-thinking template reliably.
            body["think"] = self.thinking_enabled
        try:
            res = httpx.post(f"{self.base_url}/api/chat", json=body, timeout=600.0)
            res.raise_for_status()
            data = json.loads(_strip_fences(res.json()["message"]["content"]))
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as err:
            raise LlmError(f"Ollama call failed: {err}") from err
        cache_file.write_text(json.dumps(data))
        return data

    def generation_metadata(self) -> dict[str, Any]:
        return {
            "thinking_enabled": self.thinking_enabled,
            "generation_options": {
                "temperature": 0.1,
                "num_predict": self.num_predict,
            },
        }

    def unload(self) -> None:
        """Evict the model from VRAM immediately (e.g. to free space for render)."""
        try:
            httpx.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "keep_alive": 0},
                timeout=5.0,
            )
        except httpx.HTTPError:
            pass


def _pick_ollama_model(models: list[str]) -> str:
    """Prefer capable general models, and among them the LARGEST — list
    order once handed us qwen2.5:3b while 7b sat right there.
    Qwen3 is listed first: best structured-output quality at 14B on a T4."""
    import re

    def size_of(name: str) -> float:
        m = re.search(r"(\d+(?:\.\d+)?)b", name.lower())
        return float(m.group(1)) if m else 0.0

    candidates = [
        name
        for prefix in ("qwen3", "qwen2.5", "llama3.1", "llama3", "gemma3", "gemma2", "mistral")
        for name in models
        if name.startswith(prefix)
    ]
    if candidates:
        return max(candidates, key=size_of)
    return models[0]


def make_client(
    llm_mode: str,
    gemini_model: str = GEMINI_MODEL,
    ollama_model: str | None = None,
    ollama_base_url: str | None = None,
    ollama_num_predict: int = OLLAMA_NUM_PREDICT,
):
    llm_mode = llm_mode or "ollama"
    if llm_mode == "ollama":
        try:
            return OllamaClient(
                model=ollama_model,
                base_url=ollama_base_url,
                num_predict=ollama_num_predict,
            )
        except LlmError:
            if gemini_api_key():
                return GeminiClient(model=gemini_model)
            raise
    if llm_mode == "gemini":
        return GeminiClient(model=gemini_model)
    raise LlmError(f"Unsupported llm_mode: {llm_mode}")
