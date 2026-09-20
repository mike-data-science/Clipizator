import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import server


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "publikclip-home"))


def make_job(source):
    return server.queue.create_job("url", source, json.dumps(server.config.Settings().to_json()))


def test_deleting_one_duplicate_removes_only_its_owned_records_and_directory():
    remove = make_job("https://youtu.be/delete123")
    keep = make_job("https://www.youtube.com/watch?v=delete123")
    (remove.dir / "stage.json").write_text("fixture")
    response = TestClient(server.app).delete(f"/api/jobs/{remove.id}")
    assert response.status_code == 200
    assert server.queue.get_job(remove.id) is None
    assert not remove.dir.exists()
    assert server.queue.get_job(keep.id) is not None
    with server.queue._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM generation_configs WHERE job_id=?", (remove.id,)).fetchone()[0] == 0


def test_projects_listing_exposes_review_only_duplicate_group():
    first = make_job("https://youtu.be/review123")
    second = make_job("https://www.youtube.com/watch?v=review123")
    projects = {item["id"]: item for item in TestClient(server.app).get("/api/jobs").json()}
    assert projects[first.id]["duplicate"]["preferred_job_id"] in {first.id, second.id}
    assert set(projects[first.id]["duplicate"]["job_ids"]) == {first.id, second.id}


def test_delete_refuses_a_path_outside_configured_jobs_directory(monkeypatch, tmp_path):
    outside = tmp_path / "outside-job"
    outside.mkdir()
    fake = SimpleNamespace(id="outside", dir=outside, job_mode="clipping")
    monkeypatch.setattr(server.queue, "get_job", lambda job_id: fake)
    response = TestClient(server.app).delete("/api/jobs/outside")
    assert response.status_code == 400
    assert outside.exists()


def test_delete_refuses_active_projects():
    active = make_job("https://youtu.be/active123")
    server.queue.set_job_status(active.id, "running")
    response = TestClient(server.app).delete(f"/api/jobs/{active.id}")
    assert response.status_code == 409
    assert server.queue.get_job(active.id) is not None
