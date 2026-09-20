import json
from types import SimpleNamespace

import pytest

from backend.analyzer_views import analyzer_detail, analyzer_summary


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "publikclip-home"))


def checkpoint(job, name, data, created_at=100.0):
    (job.dir / f"{name}.json").write_text(json.dumps({"created_at": created_at, "data": data}))


def analyzed_job(tmp_path):
    directory = tmp_path / "short-01"
    directory.mkdir()
    job = SimpleNamespace(
        id="short-01", dir=directory, status="done", created_at=90.0,
        source_type="file", source=str(directory / "media.mkv"), title="media", error=None,
    )
    (directory / "media.mkv").write_bytes(b"video")
    checkpoint(job, "ingest", {"title": "media", "media_path": "media.mkv", "probe": {"duration_sec": 42.0}})
    checkpoint(job, "asr", {"model": "small", "segments": [{"start": 1, "end": 2, "text": "hello", "words": []}]})
    checkpoint(job, "diarize", {"speakers": 1, "turns": [{"speaker": 0, "start": 1, "end": 2}], "segments": []})
    checkpoint(job, "events", {"timeline": [], "counts": {}, "arousal_source": "ser"})
    checkpoint(job, "curves", {"grid_sec": 0.1, "rms": [0.1, 0.2], "dynamics": [1.0], "arousal": [3.0], "arousal_grid_sec": 0.5})
    checkpoint(job, "scenes", [0.0, 12.0])
    checkpoint(job, "candidates", {"count": 1, "scene_detector_outcome": "success_with_detections"})
    checkpoint(job, "score", {"model": "qwen3:14b", "llm_mode": "ollama", "scored_count": 1, "clips": [{"start": 1, "end": 20, "summary": "Model interpretation"}]}, 120.0)
    return job


def test_summary_only_uses_real_persisted_values(tmp_path):
    job = analyzed_job(tmp_path)
    result = analyzer_summary(job)
    assert result["duration_sec"] == 42.0
    assert result["model"] == "qwen3:14b"
    assert result["scene_count"] == 2
    assert result["source"]["title"] is None
    assert result["source"]["platform"] is None


def test_detail_separates_source_analysis_from_generated_edits(tmp_path):
    job = analyzed_job(tmp_path)
    checkpoint(job, "camera", {"camera_settings": {"punch_in": True}, "trajectories": {}, "stats": [{"punches": 2}]})
    checkpoint(job, "render", {"outputs": [], "caption_preset": "hormozi"})
    result = analyzer_detail(job)
    assert result["audio"]["events"] == []
    assert result["candidate_analysis"]["clips"][0]["summary"] == "Model interpretation"
    assert result["generated_edit"]["camera_stats"][0]["punches"] == 2
    assert result["generated_edit"]["render"]["caption_preset"] == "hormozi"
    assert result["source_analysis"]["available"] is False


def test_detail_normalizes_source_analysis_and_keeps_timeline_timestamps(tmp_path):
    job = analyzed_job(tmp_path)
    checkpoint(job, "source_analysis", {
        "raw_ocr_detections": [{"arbitrary": "not exposed"}],
        "text_tracks": [{"id": "text-001", "text": "Hook", "start": 0.25, "end": 12.25}],
        "text_blocks": [{
            "id": "text-block-001", "text": "Complete Hook", "start": 0.25, "end": 12.25,
            "bbox": {"x": 0.1, "y": 0.1, "width": 0.5, "height": 0.1}, "line_count": 2,
            "source_track_ids": ["text-001", "text-002"],
        }],
        "title_hook_candidates": [{"track_id": "text-001", "text": "Hook", "start": 0.25, "end": 12.25}],
        "source_layout": {"layout_mode": "centered_1:1_in_9:16"},
        "layout_signature": {"version": 1},
        "visual_observations": [{"start": 1.25, "end": 2.25, "type": "face_present"}],
        "source_editing_evidence": {
            "shot_cuts": [{"start": 8.0, "end": 8.0}],
            "layout_changes": [{"start": 10.0, "end": 10.0}],
            "b_roll_candidates": [],
        },
        "runtime": {"ocr_sec": 2.3, "layout_sec": 0.1, "visual_sampling_sec": 0.2, "sample_count": 12},
        "provenance": {"run_job_id": job.id},
    })
    result = analyzer_detail(job)["source_analysis"]
    assert result["available"] is True
    assert result["text_tracks"][0]["start"] == 0.25
    assert result["text_blocks"][0]["text"] == "Complete Hook"
    assert result["text_blocks"][0]["source_track_ids"] == ["text-001", "text-002"]
    assert result["title_hook_candidates"][0]["end"] == 12.25
    assert result["visual_observations"][0]["start"] == 1.25
    assert result["source_editing_evidence"]["layout_changes"][0]["start"] == 10.0
    assert result["runtime"]["artifact_size_bytes"] > 0
    assert "raw_ocr_detections" not in result


def test_jobs_longer_than_short_form_scope_are_excluded(tmp_path):
    job = analyzed_job(tmp_path)
    checkpoint(job, "ingest", {"media_path": "media.mkv", "probe": {"duration_sec": 181.0}})
    assert analyzer_summary(job) is None


def test_research_job_source_uses_persisted_catalog_provenance(tmp_path):
    job = analyzed_job(tmp_path)
    job.source_provenance_json = json.dumps({
        "platform": "youtube", "external_video_id": "yt123456789",
        "canonical_url": "https://www.youtube.com/shorts/yt123456789",
        "creator_source_id": 4, "creator_video_id": 9, "catalog_title": "Catalog title",
    })
    result = analyzer_summary(job)
    assert result["source"]["platform"] == "youtube"
    assert result["source"]["source_url"] == "https://www.youtube.com/shorts/yt123456789"
    assert result["source"]["external_video_id"] == "yt123456789"
    assert result["source"]["creator_source_id"] == 4
    assert result["source"]["creator_video_id"] == 9


def test_video_dna_v2_maps_research_provenance_and_keeps_legacy_api(tmp_path):
    job = analyzed_job(tmp_path)
    job.job_mode = "research"
    job.source_provenance_json = json.dumps({
        "platform": "youtube", "external_video_id": "yt123456789",
        "canonical_url": "https://www.youtube.com/shorts/yt123456789",
        "creator_source_id": 4, "creator_video_id": 9,
        "creator": {"handle": "creator", "display_name": "Creator"},
        "catalog_title": "Catalog title", "origin": "creator_research_queue",
        "catalog_metadata": {"content_type": "short", "tab_origin": "shorts", "views": 1200},
    })
    checkpoint(job, "source_analysis", {"source_layout": {}, "provenance": {"run_job_id": job.id}}, 130.0)
    detail = analyzer_detail(job)
    assert detail["analysis_run"]["status"] == "legacy_read_only"
    assert detail["analyzer_version"] == "legacy"
    assert detail["source_analysis"]["available"] is True  # old API remains intact
    assert detail["video_dna"]["source"]["canonical_url"].endswith("yt123456789")
    assert detail["video_dna"]["source"]["creator"]["handle"] == "creator"
    assert detail["video_dna"]["source"]["content_type"] == "short"
    assert detail["video_dna"]["performance"]["catalog_metrics"]["value"]["views"] == 1200
    assert detail["video_dna"]["uncertainty"]["capabilities"]["object_action_understanding"]["status"] == "unavailable"


def test_api_reads_persisted_video_dna_for_completed_analysis_run(tmp_path):
    from publikclip_pipeline import analysis_runs

    job = analyzed_job(tmp_path)
    run = analysis_runs.create_analysis_run(job)
    generated = analyzer_detail(job)["video_dna"]
    generated["source"]["title"] = "immutable run result"
    analysis_runs.complete_analysis_run(job, run["analysis_run_id"], generated)

    detail = analyzer_detail(job)
    assert detail["analysis_run"]["status"] == "completed"
    assert detail["analysis_run"]["analysis_run_id"] == run["analysis_run_id"]
    assert detail["analyzer_version"] == analysis_runs.ANALYZER_VERSION
    assert detail["video_dna"]["source"]["title"] == "immutable run result"


def test_api_read_only_normalizes_old_persisted_video_dna_with_caption_fields(tmp_path):
    from publikclip_pipeline import analysis_runs

    job = analyzed_job(tmp_path)
    run = analysis_runs.create_analysis_run(job)
    analysis_runs.complete_analysis_run(job, run["analysis_run_id"], {"source": {"title": "old"}, "text_system": {}})
    detail = analyzer_detail(job)
    assert detail["analysis_run"]["status"] == "completed"
    assert "caption_tracks" in detail["video_dna"]["text_system"]



def test_research_full_source_analysis_completes_without_candidates_or_score(tmp_path):
    job = analyzed_job(tmp_path)
    job.job_mode = "research"
    (job.dir / "candidates.json").unlink()
    (job.dir / "score.json").unlink()
    checkpoint(job, "source_analysis", {
        "source_layout": {"layout_mode": "full_canvas"},
        "source_editing_evidence": {"shot_cuts": [], "layout_changes": [], "b_roll_candidates": []},
        "provenance": {"run_job_id": job.id},
    }, 130.0)
    summary = analyzer_summary(job)
    assert summary is not None
    assert summary["job_mode"] == "research"
    assert summary["scoring_status"] == "unavailable"
    assert summary["candidate_count"] is None
    assert summary["scored_count"] is None
    assert summary["analyzed_at"] == 130.0
    detail = analyzer_detail(job)
    assert detail["source_analysis"]["available"] is True
    assert detail["candidate_analysis"]["clips"] == []


def test_research_detail_does_not_expose_generated_edit_artifacts(tmp_path):
    job = analyzed_job(tmp_path)
    job.job_mode = "research"
    checkpoint(job, "source_analysis", {"source_layout": {}, "provenance": {}})
    checkpoint(job, "camera", {"camera_settings": {"punch_in": True}, "stats": [{"punches": 3}]})
    checkpoint(job, "render", {"outputs": [{"path": "generated.mp4"}], "caption_preset": "hormozi"})
    detail = analyzer_detail(job)
    assert detail["job"]["scoring_status"] == "unavailable"
    assert detail["candidate_analysis"]["clips"] == []
    assert detail["generated_edit"]["camera_stats"] == []
    assert detail["generated_edit"]["render"]["outputs"] == []


def test_api_reconstructs_legacy_raw_ocr_checkpoint_derivations(tmp_path):
    job = analyzed_job(tmp_path)
    job.job_mode = "research"
    checkpoint(job, "source_analysis", {
        "sample_interval_sec": 1.0,
        "raw_ocr_detections": [
            {"id": "a", "timestamp": 0.25, "text": "delivery team didn't", "confidence": 0.9,
             "bbox": {"x": 0.2, "y": 0.10, "width": 0.45, "height": 0.03}},
            {"id": "b", "timestamp": 0.25, "text": "believe the $4.5M car is his", "confidence": 0.9,
             "bbox": {"x": 0.15, "y": 0.14, "width": 0.65, "height": 0.03}},
        ],
        "source_layout": {"primary_content_bbox": {"x": 0.0, "y": 0.25, "width": 1.0, "height": 0.65}},
        "provenance": {},
    })
    result = analyzer_detail(job)
    assert result["source_analysis"]["title_hook_candidates"][0]["text"] == "delivery team didn't believe the $4.5M car is his"
    assert result["source_analysis"]["text_blocks"][0]["source_track_ids"] == ["text-001", "text-002"]
