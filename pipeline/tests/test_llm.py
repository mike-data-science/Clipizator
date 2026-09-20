import json

import pytest

from publikclip_pipeline import config, pilot
from publikclip_pipeline.scoring import llm


SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer"}},
    "required": ["score"],
}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "home"))


def _mock_ollama(monkeypatch):
    requests = []
    monkeypatch.setattr(
        llm.httpx,
        "get",
        lambda *args, **kwargs: FakeResponse({"models": [
            {"name": "qwen3:14b"},
            {"name": "qwen3:8b"},
        ]}),
    )

    def post(*args, **kwargs):
        requests.append(kwargs["json"])
        return FakeResponse({"message": {"content": '{"score": 7}'}})

    monkeypatch.setattr(llm.httpx, "post", post)
    return requests


def test_qwen3_explicitly_disables_thinking_and_caps_generation(monkeypatch):
    requests = _mock_ollama(monkeypatch)
    client = llm.OllamaClient(model="qwen3:14b", num_predict=512)

    assert client.generate_json("score this", SCHEMA) == {"score": 7}

    assert requests == [{
        "model": "qwen3:14b",
        "messages": [{"role": "user", "content": "score this"}],
        "format": SCHEMA,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 512},
        "think": False,
    }]


def test_model_identifiers_cannot_share_cache_entries():
    common = {
        "backend": "ollama",
        "prompt": "same prompt",
        "schema": SCHEMA,
        "images": [],
        "generation_options": {"temperature": 0.1, "num_predict": 512},
        "thinking": False,
    }
    assert llm._cache_key(model="qwen3:14b", **common) != llm._cache_key(
        model="qwen3:8b", **common
    )


def test_thinking_modes_cannot_share_cache_entries():
    common = {
        "backend": "ollama",
        "model": "qwen3:14b",
        "prompt": "same prompt",
        "schema": SCHEMA,
        "images": [],
        "generation_options": {"temperature": 0.1, "num_predict": 512},
    }
    assert llm._cache_key(thinking=True, **common) != llm._cache_key(
        thinking=False, **common
    )


def test_structured_response_parsing_and_cache_hit_still_work(monkeypatch):
    requests = _mock_ollama(monkeypatch)
    client = llm.OllamaClient(model="qwen3:14b", num_predict=512)

    first = client.generate_json("score this", SCHEMA)
    second = client.generate_json("score this", SCHEMA)

    assert first == second == {"score": 7}
    assert len(requests) == 1
    cached = list(llm._cache_dir().glob("*.json"))
    assert len(cached) == 1
    assert json.loads(cached[0].read_text()) == {"score": 7}


def test_scoring_provenance_records_thinking_mode_and_generation_limit(monkeypatch):
    _mock_ollama(monkeypatch)
    client = llm.OllamaClient(model="qwen3:14b", num_predict=512)
    generation = client.generation_metadata()
    provenance = pilot.stage_provenance("score", {
        "model": client.model,
        "llm_mode": client.backend,
        "llm_generation": generation,
    })

    assert generation["thinking_enabled"] is False
    assert generation["generation_options"]["num_predict"] == 512
    assert provenance["models"][0]["generation"] == generation


def test_generation_limit_is_configurable_and_old_settings_remain_compatible():
    assert config.Settings.from_json({}).ollama_num_predict == 512
    assert config.Settings.from_json({"ollama_num_predict": 768}).ollama_num_predict == 768
