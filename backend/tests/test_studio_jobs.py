import json
from types import SimpleNamespace

from backend.studio_jobs import duplicate_groups, list_project_jobs


def job(tmp_path, name, title="media", source="https://youtube.com/watch?v=abc", status="pending", job_mode="clipping"):
    directory = tmp_path / name
    directory.mkdir()
    return SimpleNamespace(id=name, dir=directory, title=title, source=source, source_type="url", status=status, error=None, created_at=0, job_mode=job_mode)


def checkpoint(item, stage, data):
    (item.dir / f"{stage}.json").write_text(json.dumps({"data": data}))


def rendered(item):
    clips = item.dir / "clips"
    clips.mkdir()
    clip = clips / "clip_00.mp4"
    clip.write_bytes(b"rendered clip fixture")
    checkpoint(item, "render", {"outputs": [{"path": str(clip)}]})


def test_all_normal_project_lifecycles_are_listed(tmp_path):
    download = job(tmp_path, "01-download")
    checkpoint(download, "ingest", {"title": "Downloaded video"})
    transcript = job(tmp_path, "02-transcript")
    checkpoint(transcript, "asr", {"segments": []})
    done = job(tmp_path, "03-done", title="A finished video")
    rendered(done)
    result = list_project_jobs([download, transcript, done])
    assert [r["id"] for r in result] == [done.id, transcript.id, download.id]
    assert result[0]["clip_count"] == 1
    assert result[0]["rendered"] is True
    assert result[1]["clip_count"] == 0


def test_missing_empty_and_malformed_renders_remain_visible(tmp_path):
    items = [job(tmp_path, str(i)) for i in range(5)]
    checkpoint(items[0], "render", {"outputs": []})
    checkpoint(items[1], "render", {"outputs": [{"path": "/missing/clip.mp4"}]})
    (items[2].dir / "render.json").write_text("{unfinished")
    checkpoint(items[3], "render", ["invalid data"])
    checkpoint(items[4], "render", {"outputs": "invalid outputs"})
    assert all(not item["rendered"] for item in list_project_jobs(items))


def test_url_fragments_use_local_ingest_title(tmp_path):
    item = job(tmp_path, "01", title="watch?v=abc")
    rendered(item)
    checkpoint(item, "ingest", {"title": "The actual podcast title"})
    assert list_project_jobs([item])[0]["title"] == "The actual podcast title"


def test_local_metadata_and_campaign_titles(tmp_path):
    item = job(tmp_path, "01")
    rendered(item)
    (item.dir / "media.info.json").write_text(json.dumps({"title": "Local metadata title"}))
    assert list_project_jobs([item])[0]["title"] == "Local metadata title"
    assert list_project_jobs([item], {item.id: "Campaign title"})[0]["title"] == "Campaign title"


def test_urls_without_metadata_never_become_watch_titles(tmp_path):
    item = job(tmp_path, "01", title="watch?v=abc")
    rendered(item)
    assert list_project_jobs([item])[0]["title"] == "Clipped video · 01"


def test_relocated_clips_and_newest_first(tmp_path):
    older, newer = job(tmp_path, "01"), job(tmp_path, "02")
    rendered(older)
    rendered(newer)
    checkpoint(newer, "render", {"outputs": [{"path": "C:\\old\\clips\\clip_00.mp4"}]})
    assert [r["id"] for r in list_project_jobs([older, newer])] == ["02", "01"]


def test_research_jobs_are_not_projects_and_stage_state_is_exposed(tmp_path):
    waiting = job(tmp_path, "01", status="waiting_for_worker")
    failed = job(tmp_path, "02", status="failed")
    failed.error = "ingest failed"
    research = job(tmp_path, "03", job_mode="research")
    result = list_project_jobs([waiting, failed, research], stage_runs_by_job={
        failed.id: [{"stage": "ingest", "status": "failed"}],
    })
    assert [item["id"] for item in result] == [failed.id, waiting.id]
    assert result[0]["current_stage"] == "ingest"
    assert result[0]["error"] == "ingest failed"
    assert result[1]["current_stage"] == "worker_queued"


def test_legacy_rendered_project_is_completed_without_modern_status_records(tmp_path):
    item = job(tmp_path, "01-legacy")
    rendered(item)
    summary = list_project_jobs([item])[0]
    assert summary["status"] == "done"
    assert summary["completed"] is True
    assert summary["current_stage"] == "complete"
    assert summary["stage_progress"] == 1.0


def test_active_and_failed_states_override_legacy_render_evidence(tmp_path):
    active = job(tmp_path, "01-active", status="running")
    rendered(active)
    failed = job(tmp_path, "02-failed", status="failed")
    rendered(failed)
    failed.error = "render failed"
    summaries = {item["id"]: item for item in list_project_jobs([active, failed], stage_runs_by_job={
        active.id: [{"stage": "render", "status": "running"}],
        failed.id: [{"stage": "render", "status": "failed"}],
    })}
    assert summaries[active.id]["status"] == "running"
    assert summaries[active.id]["current_stage"] == "render"
    assert summaries[failed.id]["status"] == "failed"
    assert summaries[failed.id]["current_stage"] == "render"


def test_duplicates_use_source_identity_not_titles(tmp_path):
    completed = job(tmp_path, "01-completed", source="https://youtu.be/duplicate123", status="done")
    rendered(completed)
    failed = job(tmp_path, "02-failed", source="https://www.youtube.com/watch?v=duplicate123", status="failed")
    same_title_other_video = job(tmp_path, "03-other", title="Same title", source="https://youtu.be/different456", status="done")
    same_title_other_video.title = completed.title
    summaries = {item["id"]: item for item in list_project_jobs([completed, failed, same_title_other_video])}
    groups = duplicate_groups([completed, failed, same_title_other_video], summaries)
    assert groups[completed.id]["preferred_job_id"] == completed.id
    assert groups[failed.id]["job_ids"] == [failed.id, completed.id]
    assert same_title_other_video.id not in groups


def test_worker_provenance_recovers_youtube_thumbnail_after_source_becomes_file(tmp_path):
    item = job(tmp_path, "01-worker", source=str(tmp_path / "media.mkv"))
    item.source_type = "file"
    item.source_provenance_json = json.dumps({
        "original_source_url": "https://youtu.be/thumb12345",
        "external_video_id": "thumb12345",
        "thumbnail_url": "https://example.test/thumb.jpg",
    })
    assert list_project_jobs([item])[0]["thumbnail_url"] == "https://example.test/thumb.jpg"
