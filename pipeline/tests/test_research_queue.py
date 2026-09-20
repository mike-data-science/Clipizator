import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from publikclip_pipeline import creator_sources, research_queue
from publikclip_pipeline.jobs import queue


def _catalog(*entries):
    return {
        "channel_id": "UCresearchCreator", "uploader_id": "ResearchCreator", "channel": "Research Creator",
        "channel_url": "https://www.youtube.com/@ResearchCreator", "entries": list(entries),
    }


def _video(video_id, views):
    return {
        "id": video_id, "title": f"Title {video_id}", "view_count": views, "duration": 35,
        "upload_date": "20260101", "webpage_url": f"https://www.youtube.com/shorts/{video_id}",
    }


def _seed(monkeypatch, tmp_path, count=3, selected=(0,)):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path))
    raw = _catalog(*(_video(f"research{i:04d}", 1000 - i) for i in range(count)))
    detail = creator_sources.refresh_creator("@ResearchCreator", lambda url, progress: raw)
    ids = [item["id"] for item in detail["videos"]]
    creator_sources.set_selection(detail["id"], [ids[index] for index in selected], True, "manual")
    return creator_sources.creator_detail(detail["id"])


def test_queues_only_selected_and_persists_job_provenance(monkeypatch, tmp_path):
    detail = _seed(monkeypatch, tmp_path, count=3, selected=(0, 2))
    result = research_queue.queue_selected(detail["id"])
    assert result["queued_count"] == 2
    items = research_queue.list_items()
    assert {item["creator_video_id"] for item in items} == {detail["videos"][0]["id"], detail["videos"][2]["id"]}
    job = queue.get_job(items[0]["job_id"])
    provenance = json.loads(job.source_provenance_json)
    assert job.job_mode == "research"
    assert provenance["platform"] == "youtube"
    assert provenance["external_video_id"].startswith("research")
    assert provenance["creator_source_id"] == detail["id"]
    assert provenance["creator_video_id"] == items[0]["creator_video_id"]
    assert provenance["canonical_url"].startswith("https://www.youtube.com/shorts/")
    assert provenance["catalog_metadata"]["content_type"] is None  # duplicate across both mocked tabs: do not guess
    assert provenance["catalog_metadata"]["tab_origin"] == "videos,shorts"
    assert provenance["catalog_metadata"]["derived_performance_label"] in {"strong", "average", "weak", "unclassified"}
    assert (job.dir / "source_provenance.json").exists()


def test_queue_dedupes_active_items(monkeypatch, tmp_path):
    detail = _seed(monkeypatch, tmp_path)
    first = research_queue.queue_selected(detail["id"])
    second = research_queue.queue_selected(detail["id"])
    assert first["queued_count"] == 1
    assert second["queued_count"] == 0
    assert second["skipped_already_queued"] == 1
    assert len(research_queue.list_items()) == 1


def test_claim_is_atomic_and_does_not_duplicate_worker_work(monkeypatch, tmp_path):
    detail = _seed(monkeypatch, tmp_path)
    research_queue.queue_selected(detail["id"])
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(research_queue.claim_next, ("worker-a", "worker-b")))
    claimed = [item for item in claims if item]
    assert len(claimed) == 1
    assert claimed[0]["creator_video_id"] == detail["videos"][0]["id"]


def test_successful_state_transitions_update_creator_video(monkeypatch, tmp_path):
    detail = _seed(monkeypatch, tmp_path)
    research_queue.queue_selected(detail["id"])
    claimed = research_queue.claim_next("worker-a")
    research_queue.report_worker_status(claimed["queue_item_id"], claimed["claim_token"], "downloading")
    research_queue.report_worker_status(claimed["queue_item_id"], claimed["claim_token"], "uploading")
    research_queue.mark_uploaded(claimed["queue_item_id"], claimed["claim_token"])
    research_queue.mark_analyzing(claimed["queue_item_id"])
    research_queue.mark_completed(claimed["queue_item_id"])
    item = research_queue.list_items()[0]
    source_video = creator_sources.creator_detail(detail["id"])["videos"][0]
    assert item["status"] == "completed"
    assert item["completed_at"] is not None
    assert source_video["analysis_job_id"] == item["job_id"]
    assert source_video["analysis_status"] == "analyzed"


@pytest.mark.parametrize("failure", ["download failed", "upload failed", "analyzer failed"])
def test_failures_are_persisted_and_retryable(monkeypatch, tmp_path, failure):
    detail = _seed(monkeypatch, tmp_path)
    research_queue.queue_selected(detail["id"])
    claimed = research_queue.claim_next("worker-a")
    if failure == "analyzer failed":
        research_queue.mark_uploaded(claimed["queue_item_id"], claimed["claim_token"])
        research_queue.mark_analyzing(claimed["queue_item_id"])
        research_queue.mark_failed(claimed["queue_item_id"], failure)
    else:
        research_queue.report_worker_status(claimed["queue_item_id"], claimed["claim_token"], "failed", failure)
    failed = research_queue.list_items()[0]
    assert failed["status"] == "failed"
    assert failed["failure_reason"] == failure
    retried = research_queue.retry(failed["id"])
    assert retried["status"] == "queued"
    assert retried["failure_reason"] is None


def test_completed_analysis_is_skipped_and_queue_survives_new_connections(monkeypatch, tmp_path):
    detail = _seed(monkeypatch, tmp_path)
    research_queue.queue_selected(detail["id"])
    persisted_before_claim = research_queue.list_items()
    assert len(persisted_before_claim) == 1
    claimed = research_queue.claim_next("worker-a")
    research_queue.mark_uploaded(claimed["queue_item_id"], claimed["claim_token"])
    assert research_queue.recoverable_analyses() == [(claimed["queue_item_id"], claimed["job_id"])]
    research_queue.mark_completed(claimed["queue_item_id"])
    again = research_queue.queue_selected(detail["id"])
    assert again["queued_count"] == 0
    assert again["skipped_already_analyzed"] == 1
    assert research_queue.list_items()[0]["status"] == "completed"



def _upload_next_research_item(worker_id="worker"):
    claimed = research_queue.claim_next(worker_id)
    assert claimed is not None
    research_queue.mark_uploaded(claimed["queue_item_id"], claimed["claim_token"])
    return claimed


def test_only_one_research_analysis_can_be_claimed(monkeypatch, tmp_path):
    detail = _seed(monkeypatch, tmp_path, count=2, selected=(0, 1))
    research_queue.queue_selected(detail["id"])
    _upload_next_research_item("worker-a")
    _upload_next_research_item("worker-b")
    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(research_queue.claim_next_analysis, (101, 102)))
    active = [claim for claim in claims if claim]
    assert len(active) == 1
    assert [item["status"] for item in research_queue.list_items()].count("analyzing") == 1
    assert [item["status"] for item in research_queue.list_items()].count("waiting_for_analysis") == 1


@pytest.mark.parametrize("outcome", ["completed", "failed"])
def test_next_waiting_analysis_is_eligible_after_terminal_outcome(monkeypatch, tmp_path, outcome):
    detail = _seed(monkeypatch, tmp_path, count=2, selected=(0, 1))
    research_queue.queue_selected(detail["id"])
    _upload_next_research_item("worker-a")
    _upload_next_research_item("worker-b")
    first = research_queue.claim_next_analysis(101)
    assert first is not None
    if outcome == "completed":
        assert research_queue.mark_completed(first["queue_item_id"], first["analysis_token"])
    else:
        assert research_queue.mark_failed(first["queue_item_id"], "analysis failed", first["analysis_token"])
    second = research_queue.claim_next_analysis(101)
    assert second is not None
    assert second["queue_item_id"] != first["queue_item_id"]


def test_restart_recovery_keeps_live_claim_and_reclaims_only_abandoned_work(monkeypatch, tmp_path):
    detail = _seed(monkeypatch, tmp_path)
    research_queue.queue_selected(detail["id"])
    _upload_next_research_item()
    first = research_queue.claim_next_analysis(4242)
    assert first is not None
    assert research_queue.recover_interrupted_analyses(lambda pid: pid == 4242) == 0
    assert research_queue.claim_next_analysis(5151) is None
    assert research_queue.recover_interrupted_analyses(lambda pid: False) == 1
    resumed = research_queue.claim_next_analysis(5151)
    assert resumed is not None
    assert resumed["queue_item_id"] == first["queue_item_id"]
    assert research_queue.claim_next_analysis(6161) is None


def test_retry_candidate_failed_research_reuses_uploaded_job_and_checkpoints(monkeypatch, tmp_path):
    detail = _seed(monkeypatch, tmp_path)
    research_queue.queue_selected(detail["id"])
    claimed = _upload_next_research_item()
    job = queue.get_job(claimed["job_id"])
    (job.dir / "media.mkv").write_bytes(b"source")
    (job.dir / "asr.json").write_text('{"stage":"asr","schema_version":1,"data":{"segments":[]}}')
    research_queue.mark_analyzing(claimed["queue_item_id"])
    research_queue.mark_failed(
        claimed["queue_item_id"],
        "candidates: No candidate moments found — the video may be too short or too quiet.",
    )
    retried = research_queue.retry(claimed["queue_item_id"])
    assert retried["status"] == "waiting_for_analysis"
    assert (job.dir / "asr.json").exists()
    assert queue.get_job(job.id).job_mode == "research"
    assert research_queue.claim_next("worker-again") is None
    assert research_queue.claim_next_analysis(999) is not None


def test_queue_status_mapping_reports_real_running_stage_only(monkeypatch, tmp_path):
    detail = _seed(monkeypatch, tmp_path)
    research_queue.queue_selected(detail["id"])
    claimed = _upload_next_research_item()
    waiting = research_queue.list_items()[0]
    assert waiting["status"] == "waiting_for_analysis"
    assert waiting["progress_stage"] is None
    analysis = research_queue.claim_next_analysis(101)
    with queue._connect() as conn:
        conn.execute(
            "INSERT INTO stage_runs(job_id,stage,status,schema_version,started_at) VALUES (?,?,?,?,?)",
            (claimed["job_id"], "source_analysis", "running", 3, 1.0),
        )
    item = research_queue.list_items()[0]
    assert item["status"] == "analyzing"
    assert item["progress_stage"] == "source_analysis"
    assert analysis is not None
