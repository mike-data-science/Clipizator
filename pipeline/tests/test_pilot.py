import json

import pytest

from publikclip_pipeline import config, pilot
from publikclip_pipeline.jobs import queue


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "home"))


def _settings_json() -> str:
    return json.dumps(config.Settings().to_json())


def _noop_progress(stage, fraction, message):
    pass


class ArtifactStage(queue.Stage):
    name = "counting"

    def run(self, ctx):
        return {"count": 1}


class FailingStage(queue.Stage):
    name = "failing"

    def run(self, ctx):
        raise queue.StageError("pilot failure")


def test_manifest_records_runtime_outcome_and_artifact():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    queue.run_stages(job, [ArtifactStage()], _noop_progress)

    manifest = json.loads((job.dir / "pilot_manifest.json").read_text())
    stage = manifest["stages"][0]
    assert manifest["manifest_version"] == 1
    assert manifest["code_revision"]
    assert stage["stage"] == "counting"
    assert stage["outcome"] == "success_with_detections"
    assert stage["runtime_sec"] >= 0
    assert stage["artifacts"][0]["path"].endswith("counting.json")


def test_manifest_records_failed_stage():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    with pytest.raises(queue.StageError):
        queue.run_stages(job, [FailingStage()], _noop_progress)

    manifest = json.loads((job.dir / "pilot_manifest.json").read_text())
    assert manifest["job_status"] == "failed"
    assert manifest["stages"][0]["outcome"] == "failed"
    assert "pilot failure" in manifest["stages"][0]["error"]


def test_scene_outcomes_distinguish_empty_unavailable_and_legacy():
    outcome, details = pilot.infer_outcome(
        "candidates", {"count": 2, "scene_count": 0, "scene_detector_outcome": "success_no_detections"}
    )
    assert outcome == "success_with_detections"
    assert details["scenes"]["outcome"] == "success_no_detections"

    _, unavailable = pilot.infer_outcome(
        "candidates", {"count": 2, "scene_count": 0, "scene_detector_outcome": "unavailable", "scene_detector_error": "decoder failed"}
    )
    assert unavailable["scenes"]["outcome"] == "unavailable"
    assert unavailable["scenes"]["error"] == "decoder failed"

    _, legacy = pilot.infer_outcome("candidates", {"count": 2, "scene_count": 0})
    assert legacy["scenes"]["outcome"] == "unknown"


def test_fallback_outcome_and_qa_label_storage():
    outcome, details = pilot.infer_outcome(
        "events", {"timeline": [], "counts": {}, "arousal_source": "dsp-proxy"}
    )
    assert outcome == "fallback_used"
    assert details["audio_events"]["outcome"] == "success_no_detections"

    job = queue.create_job("file", "/tmp/video.mp4", _settings_json())
    with queue._connect() as conn:
        label_id = pilot.add_qa_label(
            conn, job_id=job.id, media_ref=job.source, start_sec=1.0, end_sec=2.0,
            target_type="audio_event/laugh", original={"confidence": 0.2},
            corrected={"present": False}, note="false positive",
        )
        row = conn.execute("SELECT * FROM pilot_qa_labels WHERE id=?", (label_id,)).fetchone()
    assert row["job_id"] == job.id
    assert json.loads(row["corrected_json"]) == {"present": False}


def test_qa_label_rejects_invalid_interval():
    with queue._connect() as conn, pytest.raises(ValueError):
        pilot.add_qa_label(
            conn, job_id="job", media_ref=None, start_sec=2.0, end_sec=1.0,
            target_type="speaker", original=None, corrected="S1",
        )


def test_summary_backfills_legacy_stage_rows():
    job = queue.create_job("file", "/tmp/video.mp4", _settings_json())
    queue.write_checkpoint(job, "asr", 1, {"word_count": 3, "model": "small", "compute_type": "float16"})
    with queue._connect() as conn:
        conn.execute("DELETE FROM pilot_stage_observations WHERE job_id=?", (job.id,))
        summary = pilot.summarize(conn, [job])
    stage = summary["jobs"][0]["stages"][0]
    assert stage["stage"] == "asr"
    assert stage["outcome"] == "success_with_detections"
    assert stage["runtime_sec"] is not None
