import json

import pytest

from publikclip_pipeline import analysis_runs, config
from publikclip_pipeline.jobs import queue
from publikclip_pipeline.video_dna import TOP_LEVEL_SECTIONS, normalize_video_dna


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "home"))


def _job():
    provenance = {
        "platform": "youtube", "external_video_id": "video-1", "creator_video_id": 17,
        "canonical_url": "https://www.youtube.com/shorts/video-1",
    }
    return queue.create_job(
        "url", provenance["canonical_url"], json.dumps(config.Settings().to_json()),
        source_provenance=provenance, job_mode="research",
    )


def _dna(run):
    return normalize_video_dna(
        source={"platform": "youtube", "external_video_id": "video-1", "duration_sec": 30.0},
        transcript={"model": "small", "word_count": 2, "segments": [{"start": 0.0, "end": 1.0}]},
        speakers={"count": 1, "turns": []}, scenes={"timestamps": [], "detector_outcome": "success_no_detections"},
        source_analysis={}, audio={"events": [], "curves": []}, performance={}, provenance={},
        corrections=[], analysis_run=run,
    )


def test_creates_and_persists_analysis_run_artifact():
    job = _job()
    run = analysis_runs.create_analysis_run(job)
    completed = analysis_runs.complete_analysis_run(job, run["analysis_run_id"], _dna(run))
    assert completed["status"] == "completed"
    assert completed["creator_video_id"] == 17
    assert completed["analyzer_version"] == "2.3.0"
    assert completed["schema_version"] == 2
    assert completed["config_fingerprint"]
    assert (job.dir / completed["artifact_path"]).exists()


def test_multiple_runs_for_same_source_do_not_overwrite_old_result():
    job = _job()
    first = analysis_runs.create_analysis_run(job)
    first_dna = _dna(first)
    first_dna["source"]["title"] = "first"
    analysis_runs.complete_analysis_run(job, first["analysis_run_id"], first_dna)
    first_path = job.dir / analysis_runs.get_analysis_run(first["analysis_run_id"])["artifact_path"]
    original = first_path.read_text()

    second = analysis_runs.create_analysis_run(job)
    second_dna = _dna(second)
    second_dna["source"]["title"] = "second"
    analysis_runs.complete_analysis_run(job, second["analysis_run_id"], second_dna)

    assert first["analysis_run_id"] != second["analysis_run_id"]
    assert first_path.read_text() == original
    assert len(analysis_runs.list_analysis_runs(job.id)) == 2
    assert analysis_runs.latest_analysis_run(job.id)["analysis_run_id"] == second["analysis_run_id"]


def test_video_dna_has_canonical_sections_and_explicit_missing_capabilities():
    run = {"analysis_run_id": "ar-test", "job_id": "job-test", "analyzer_version": "2.0.0"}
    dna = _dna(run)
    assert tuple(dna) == TOP_LEVEL_SECTIONS
    capabilities = dna["uncertainty"]["capabilities"]
    assert capabilities["b_roll_detection"]["status"] == "unavailable"
    assert capabilities["caption_style_analysis"]["status"] == "unavailable"
    assert capabilities["music_segmentation"]["status"] == "unavailable"
    assert dna["speech_story"]["transcript"]["source"] == "detector"
    assert dna["speech_story"]["transcript"]["status"] == "raw"


def test_video_dna_maps_visual_understanding_with_provenance_and_evidence():
    run = {"analysis_run_id": "ar-visual", "job_id": "job-visual", "analyzer_version": "2.0.0"}
    visual_understanding = {
        "status": "available",
        "visual_units": [{"id": "visual-unit-001", "visual_type": "b_roll", "source_shot_ids": ["shot-001"]}],
        "b_roll_segments": [{"start_ms": 0, "end_ms": 2000, "source_shot_ids": ["shot-001"]}],
        "objects_entities_summary": [{"label": "car", "unit_count": 1}],
        "scene_environment_summary": [], "actions_summary": [],
        "metrics": {"b_roll_ratio": 1.0, "talking_head_ratio": 0.0},
        "evidence": {"source_shot_ids": ["shot-001"], "raw_semantic_observation_count": 2, "generated_camera_data_excluded": True},
        "provenance": {"method": "sparse-shot-visual-rules-v1", "semantic_model": "openai/clip-vit-base-patch32"},
        "limitations": ["zero-shot labels"],
    }
    dna = normalize_video_dna(
        source={}, transcript={}, speakers={}, scenes={},
        source_analysis={"available": True, "visual_understanding": visual_understanding},
        audio={}, performance={}, provenance={}, corrections=[], analysis_run=run,
    )
    assert dna["visual"]["status"] == "available"
    assert dna["visual"]["visual_units"]["value"][0]["visual_type"] == "b_roll"
    assert dna["visual"]["b_roll_segments"]["evidence"]["visual_unit_ids"] == ["visual-unit-001"]
    assert dna["visual"]["evidence"]["generated_camera_data_excluded"] is True
    assert dna["visual"]["provenance"]["semantic_model"] == "openai/clip-vit-base-patch32"
    assert dna["uncertainty"]["capabilities"]["b_roll_detection"]["status"] == "experimental"
    assert dna["uncertainty"]["capabilities"]["object_action_understanding"]["status"] == "limited"


def test_video_dna_maps_caption_system_and_experimental_capability():
    run = {"analysis_run_id": "ar-caption", "job_id": "job-caption", "analyzer_version": "2.0.0"}
    caption_system = {
        "caption_tracks": [{"id": "caption-001", "text": "you might actually"}],
        "emphasis_events": [{"caption_track_id": "caption-001", "emphasized_text": "might"}],
        "overlays": [{"role": "title_hook"}], "caption_metrics": {"caption_coverage_ratio": 0.5},
        "evidence": {"raw_ocr_detection_count": 4}, "provenance": {"method": "ocr-caption-role-and-emphasis-rules-v1"},
        "limitations": ["sparse OCR"],
    }
    dna = normalize_video_dna(
        source={}, transcript={}, speakers={}, scenes={},
        source_analysis={"available": True, "caption_system": caption_system},
        audio={}, performance={}, provenance={}, corrections=[], analysis_run=run,
    )
    assert dna["text_system"]["caption_tracks"]["value"][0]["id"] == "caption-001"
    assert dna["text_system"]["emphasis_events"]["value"][0]["emphasized_text"] == "might"
    assert dna["text_system"]["caption_style"]["status"] == "experimental"


def test_video_dna_maps_audio_intelligence_and_capabilities():
    run = {"analysis_run_id": "ar-audio", "job_id": "job-audio", "analyzer_version": "2.0.0"}
    intelligence = {
        "status": "available", "audio_segments": [{"id": "audio-segment-001", "type": "mixed"}],
        "music_segments": [{"id": "music-001"}], "sfx_events": [{"id": "sfx-001"}],
        "dynamics": {"status": "available", "median_rms": .1}, "ducking_events": [],
        "cross_modal_relationships": [{"audio_event_id": "sfx-001", "relation_type": "aligned_with_cut"}],
        "metrics": {"music_coverage_ratio": .5},
        "evidence": {"panns_intelligence_available": True, "raw_audio_observation_count": 2, "rms_sample_count": 20},
        "provenance": {"method": "source-audio-intelligence-rules-v1", "event_model": "PANNs"}, "limitations": [],
    }
    dna = normalize_video_dna(
        source={}, transcript={}, speakers={}, scenes={},
        source_analysis={"available": True, "visual_understanding": {"visual_units": [{"id": "v1"}]}},
        audio={"audio_intelligence": intelligence}, performance={}, provenance={}, corrections=[], analysis_run=run,
    )
    assert dna["audio"]["audio_segments"]["value"][0]["type"] == "mixed"
    assert dna["audio"]["music_segmentation"]["status"] == "experimental"
    assert dna["audio"]["sound_effect_detection"]["status"] == "limited"
    assert dna["audio"]["audio_dynamics"]["status"] == "available"


def test_video_dna_serializes_source_editing_without_generated_camera_data():
    run = {"analysis_run_id": "ar-editing", "job_id": "job-editing", "analyzer_version": "2.0.0"}
    source_editing = {
        "schema_version": 1, "status": "available",
        "cuts": [{
            "id": "edit_cut_000002000", "type": "shot_boundary", "timestamp_ms": 2000,
            "start_ms": 2000, "end_ms": 2000, "confidence": .8, "source": "detector",
            "status": "raw", "evidence": {"artifact": "scenes.json"},
        }],
        "shots": [{"id": "shot-001", "start_ms": 0, "end_ms": 2000}],
        "transitions": [{"id": "edit_transition_000002000", "subtype": "hard_cut"}],
        "reframes": [], "zooms": [],
        "pattern_interrupts": [{"id": "edit_pattern_interrupt_000002000_shot_change"}],
        "cross_modal_relationships": [], "metrics": {"cut_count": 1},
        "capabilities": {"speed_change_detection": {"status": "unavailable", "reason": "no timing evidence"}},
        "evidence": {"generated_camera_data_excluded": True},
        "provenance": {"method": "source-editing-rules-v1"}, "limitations": [],
        # This simulates an accidental foreign field at the normalization boundary.
        "camera_trajectory": {"punches": [{"start": 2.0}]},
    }
    dna = normalize_video_dna(
        source={}, transcript={}, speakers={}, scenes={},
        source_analysis={"available": True, "source_editing": source_editing},
        audio={}, performance={}, provenance={}, corrections=[], analysis_run=run,
    )
    editing = dna["source_editing"]
    assert editing["cuts"]["value"][0]["id"] == "edit_cut_000002000"
    assert editing["cuts"]["status"] == "raw"
    assert editing["transitions"]["status"] == "interpreted"
    assert editing["metrics"]["cut_count"] == 1
    assert editing["evidence"]["generated_camera_data_excluded"] is True
    assert "camera_trajectory" not in editing
    assert "punches" not in json.dumps(editing)


def test_video_dna_serializes_story_semantics_and_closure():
    run = {"analysis_run_id": "ar-story", "job_id": "job-story", "analyzer_version": "2.2.0"}
    story = {
        "schema_version": 1, "status": "available",
        "semantic_units": [{"semantic_unit_id": "semantic_unit_000001000_abcd", "start_ms": 1000, "end_ms": 3000}],
        "story_segments": [{
            "story_id": "story_000001000_abcd", "start_ms": 1000, "end_ms": 3000,
            "semantic_unit_ids": ["semantic_unit_000001000_abcd"],
            "completeness": {"next_topic_started": True, "likely_semantic_end_ms": 3000},
        }],
        "hooks": [{"id": "hook_000001000_abcd"}],
        "speech_signals": [{"id": "speech_signal_question_000001000_abcd", "type": "question"}],
        "payoff_relationships": [], "structural_metrics": {"story_segment_count": 1},
        "evidence": {"source_editing_ids_reused": ["edit_cut_000003100"]},
        "provenance": {"method": "semantic-story-hybrid-v1", "llm_used": True, "llm_call_count": 1, "llm_failure_count": 0},
        "limitations": [],
    }
    dna = normalize_video_dna(
        source={}, transcript={}, speakers={}, scenes={},
        source_analysis={"available": True, "story_semantics": story},
        audio={}, performance={}, provenance={}, corrections=[], analysis_run=run,
    )
    speech_story = dna["speech_story"]
    assert speech_story["schema_version"] == 1
    assert speech_story["semantic_units"]["value"][0]["semantic_unit_id"].startswith("semantic_unit_")
    assert speech_story["semantic_units"]["source"] == "llm"
    assert speech_story["story_segments"]["value"][0]["completeness"]["likely_semantic_end_ms"] == 3000
    assert speech_story["story_beats"]["evidence"]["alias_of"] == "story_segments"
    assert speech_story["evidence"]["source_editing_ids_reused"] == ["edit_cut_000003100"]
