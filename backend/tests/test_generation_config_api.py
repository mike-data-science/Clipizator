import json

import pytest
from fastapi.testclient import TestClient

from backend import server
from publikclip_pipeline import config
from publikclip_pipeline.jobs import queue


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "home"))


def test_profile_and_project_config_api_save_load_preview():
    client = TestClient(server.app)
    job = queue.create_job("file", "/tmp/source.mp4", json.dumps(config.Settings().to_json()))
    profile_response = client.post("/api/style-profiles", json={
        "name": "API profile", "scope": "custom",
        "config": {"captions": {"preset_id": "classic"}},
    })
    assert profile_response.status_code == 201
    profile = profile_response.json()

    payload = {
        "style_profile_id": profile["id"],
        "captions": {"fill": "cyan"},
        "broll": {"mode": "conservative", "presentation": "mixed"},
    }
    save_response = client.put(f"/api/jobs/{job.id}/generation-config", json=payload)
    assert save_response.status_code == 200
    loaded = client.get(f"/api/jobs/{job.id}/generation-config").json()
    preview = client.post(
        f"/api/jobs/{job.id}/generation-config/preview",
        json={**payload, "captions": {"fill": "yellow"}},
    ).json()

    assert loaded["config"] == {**payload, "config_version": 1}
    assert loaded["resolved_config"]["captions"] == {
        **loaded["resolved_config"]["captions"],
        "preset_id": "classic", "fill": "cyan",
    }
    assert preview["resolved_config"]["captions"]["fill"] == "yellow"
    assert client.get(f"/api/style-profiles/{profile['id']}").status_code == 200


def test_api_validation_error_is_additive_400():
    client = TestClient(server.app)
    job = queue.create_job("file", "/tmp/source.mp4", json.dumps(config.Settings().to_json()))
    response = client.put(
        f"/api/jobs/{job.id}/generation-config",
        json={"broll": {"mode": "unsupported"}},
    )
    assert response.status_code == 400
