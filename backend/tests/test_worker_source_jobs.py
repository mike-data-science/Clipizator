import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import server


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "publikclip-home"))
    server.WORKER_QUEUE.clear()


def test_youtube_job_waits_for_worker_then_upload_resumes_full_pipeline(monkeypatch):
    started = []
    stages = [SimpleNamespace(name=name) for name in ("ingest", "asr", "render")]
    monkeypatch.setattr(server, "_stages", lambda: stages)
    monkeypatch.setattr(
        server.threading,
        "Thread",
        lambda **kwargs: SimpleNamespace(start=lambda: started.append(kwargs)),
    )
    selected_config = server.generation_config.system_default_config()
    selected_config["music"]["mode"] = "low"

    with TestClient(server.app) as client:
        created = client.post("/api/jobs", json={
            "source": "https://www.youtube.com/watch?v=worker-test",
            "generation_config": selected_config,
        })
        assert created.status_code == 200
        job_id = created.json()["job_id"]
        assert created.json()["status"] == "waiting_for_worker"
        assert started == []
        assert server.queue.get_job(job_id).status == "waiting_for_worker"
        assert server.generation_config.get_project_config(job_id)["config"]["music"]["mode"] == "low"

        claimed = client.get("/api/worker/jobs?worker_id=laptop-test")
        assert claimed.status_code == 200
        assert claimed.json()["jobs"] == [{
            "type": "source", "job_id": job_id,
            "url": "https://www.youtube.com/watch?v=worker-test",
            "role": "source", "resume_pipeline": True,
        }]

        downloading = client.post(
            f"/api/worker/source/{job_id}/status", json={"status": "downloading"},
        )
        assert downloading.status_code == 200
        assert server.queue.get_job(job_id).status == "downloading"

        uploading = client.post(
            f"/api/worker/source/{job_id}/status", json={"status": "uploading"},
        )
        assert uploading.status_code == 200
        assert server.queue.get_job(job_id).status == "uploading"

        uploaded = client.post(
            f"/api/worker/upload-source/{job_id}",
            data={"resume_pipeline": "true"},
            files={
                "video": ("source.mkv", b"video", "video/x-matroska"),
                "metadata": ("meta.json", json.dumps({
                    "id": "worker-test", "webpage_url": "https://www.youtube.com/watch?v=worker-test",
                    "thumbnail": "https://example.test/worker-thumbnail.jpg",
                }), "application/json"),
            },
        )
        assert uploaded.status_code == 200
        uploaded_job = server.queue.get_job(job_id)
        assert uploaded_job.source_type == "file"
        provenance = json.loads(uploaded_job.source_provenance_json)
        assert provenance["original_source_url"] == "https://www.youtube.com/watch?v=worker-test"
        assert provenance["thumbnail_url"] == "https://example.test/worker-thumbnail.jpg"
        assert len(started) == 1
        assert started[0]["args"][1] == stages


def test_file_upload_still_starts_without_worker_queue(monkeypatch):
    started = []
    monkeypatch.setattr(
        server.threading,
        "Thread",
        lambda **kwargs: SimpleNamespace(start=lambda: started.append(kwargs)),
    )

    with TestClient(server.app) as client:
        response = client.post(
            "/api/jobs/upload",
            files={"video": ("source.mp4", b"video", "video/mp4")},
        )

    assert response.status_code == 200
    assert server.WORKER_QUEUE == []
    assert len(started) == 1
