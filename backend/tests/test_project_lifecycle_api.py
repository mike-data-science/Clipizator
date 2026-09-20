import json

import pytest
from fastapi.testclient import TestClient

from backend import server


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "publikclip-home"))


def make_job(source: str = "https://youtu.be/project"):
    return server.queue.create_job("url", source, json.dumps(server.config.Settings().to_json()))


def test_projects_api_keeps_lifecycle_jobs_and_excludes_research():
    waiting = make_job()
    server.queue.set_job_status(waiting.id, "waiting_for_worker")

    processing = make_job()
    server.queue.mark_stage(processing.id, "asr", "running", 1)

    completed = make_job()
    clips = completed.dir / "clips"
    clips.mkdir()
    clip = clips / "clip_00.mp4"
    clip.write_bytes(b"rendered")
    (completed.dir / "render.json").write_text(json.dumps({"data": {"outputs": [{"path": str(clip)}]}}))
    # Historical rendered job: legacy status has no modern terminal state.
    server.queue.set_job_status(completed.id, "pending")

    failed = make_job()
    server.queue.set_job_status(failed.id, "failed", "asr: unavailable")
    server.queue.mark_stage(failed.id, "asr", "failed", 1, "unavailable")

    research = server.queue.create_job(
        "url", "https://youtu.be/research", json.dumps(server.config.Settings().to_json()), job_mode="research",
    )

    response = TestClient(server.app).get("/api/jobs")
    assert response.status_code == 200
    projects = {project["id"]: project for project in response.json()}
    assert set(projects) == {waiting.id, processing.id, completed.id, failed.id}
    assert projects[waiting.id]["status"] == "waiting_for_worker"
    assert projects[waiting.id]["current_stage"] == "worker_queued"
    assert projects[processing.id]["current_stage"] == "asr"
    assert projects[completed.id]["rendered"] is True
    assert projects[completed.id]["clip_count"] == 1
    assert projects[failed.id]["error"] == "asr: unavailable"
    assert research.id not in projects

    detail = TestClient(server.app).get(f"/api/jobs/{processing.id}/lifecycle")
    assert detail.status_code == 200
    detail_stages = {stage["id"]: stage for stage in detail.json()["stages"]}
    assert detail.json()["current_stage"] == "asr"
    assert detail_stages["asr"]["state"] == "active"
