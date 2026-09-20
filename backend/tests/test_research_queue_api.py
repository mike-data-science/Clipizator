from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from backend import server


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "publikclip-home"))


def test_queue_selected_api_reports_dedupe_counts(monkeypatch):
    expected = {
        "queued_count": 2, "skipped_already_queued": 1, "skipped_already_analyzed": 1,
        "errors": [], "queue_item_ids": [10, 11],
    }
    monkeypatch.setattr(server.research_queue, "queue_selected", lambda creator_id: expected)
    response = TestClient(server.app).post("/api/analyzer/sources/7/research-queue")
    assert response.status_code == 200
    assert response.json() == expected


def test_worker_poll_includes_one_atomically_claimed_research_item(monkeypatch):
    claimed = {"type": "research_queue", "queue_item_id": 5, "job_id": "job-5", "url": "https://youtu.be/video", "claim_token": "token"}
    monkeypatch.setattr(server.research_queue, "claim_next", lambda worker_id: claimed)
    server.WORKER_QUEUE.clear()
    response = TestClient(server.app).get("/api/worker/jobs?worker_id=laptop-test")
    assert response.status_code == 200
    assert response.json()["jobs"] == [claimed]


def test_research_pipeline_marks_completion_and_failure(monkeypatch, tmp_path):
    job = SimpleNamespace(id="job-1", dir=tmp_path, source="media.mkv")
    transitions = []
    monkeypatch.setattr(server, "_broadcast_sync", lambda payload: None)
    monkeypatch.setattr(server.research_queue, "mark_analyzing", lambda item_id: transitions.append((item_id, "analyzing")))
    monkeypatch.setattr(server.research_queue, "mark_completed", lambda item_id: transitions.append((item_id, "completed")))
    monkeypatch.setattr(server.research_queue, "mark_failed", lambda item_id, error: transitions.append((item_id, f"failed:{error}")))
    monkeypatch.setattr(server.queue, "run_stages", lambda job, stages, emit: {})
    server._run_pipeline_thread(job, [object()], source="research_queue", research_queue_item_id=3)
    assert transitions == [(3, "analyzing"), (3, "completed")]

    transitions.clear()
    monkeypatch.setattr(server.queue, "run_stages", lambda job, stages, emit: (_ for _ in ()).throw(RuntimeError("analysis broke")))
    server._run_pipeline_thread(job, [object()], source="research_queue", research_queue_item_id=3)
    assert transitions == [(3, "analyzing"), (3, "failed:analysis broke")]



def test_research_and_clipping_stage_plans_are_distinct():
    research_names = [stage.name for stage in server._research_stages()]
    clipping_names = [stage.name for stage in server._stages()]
    assert research_names == ["ingest", "asr", "diarize", "events", "source_analysis"]
    assert "candidates" not in research_names
    assert "score" not in research_names
    assert "camera" not in research_names
    assert "render" not in research_names
    assert [name for name in ("candidates", "score", "camera", "render") if name in clipping_names] == [
        "candidates", "score", "camera", "render",
    ]


def test_scheduler_starts_only_one_claimed_research_analysis(monkeypatch, tmp_path):
    job = SimpleNamespace(id="job-r", dir=tmp_path, source="media.mkv", job_mode="research")
    (tmp_path / "media.mkv").write_bytes(b"source")
    claims = iter([
        {"queue_item_id": 3, "job_id": "job-r", "analysis_token": "token"},
        None,
    ])
    started = []
    monkeypatch.setattr(server.research_queue, "claim_next_analysis", lambda pid: next(claims))
    monkeypatch.setattr(server.queue, "get_job", lambda job_id: job)
    monkeypatch.setattr(server.threading, "Thread", lambda **kwargs: SimpleNamespace(start=lambda: started.append(kwargs)))
    claim = server._start_next_research_analysis()
    assert claim["queue_item_id"] == 3
    assert len(started) == 1
    assert [stage.name for stage in started[0]["args"][1]] == ["ingest", "asr", "diarize", "events", "source_analysis"]



@pytest.mark.parametrize("fails", [False, True])
def test_claimed_research_run_auto_schedules_next_after_terminal_state(monkeypatch, tmp_path, fails):
    job = SimpleNamespace(id="job-1", dir=tmp_path, source="media.mkv", job_mode="research")
    transitions = []
    next_runs = []
    monkeypatch.setattr(server, "_broadcast_sync", lambda payload: None)
    monkeypatch.setattr(server, "_start_next_research_analysis", lambda: next_runs.append(True))
    monkeypatch.setattr(server.research_queue, "mark_completed", lambda item_id, token: transitions.append(("completed", item_id, token)))
    monkeypatch.setattr(server.research_queue, "mark_failed", lambda item_id, error, token: transitions.append(("failed", item_id, token, error)))
    if fails:
        monkeypatch.setattr(server.queue, "run_stages", lambda *args: (_ for _ in ()).throw(RuntimeError("broken")))
    else:
        monkeypatch.setattr(server.queue, "run_stages", lambda *args: {})
    server._run_pipeline_thread(
        job, [object()], source="research_queue", research_queue_item_id=3,
        research_analysis_token="claim-token",
    )
    assert transitions[0][0] == ("failed" if fails else "completed")
    assert next_runs == [True]
