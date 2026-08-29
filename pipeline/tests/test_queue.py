"""Job queue + checkpoint/resume contract tests.

The resume guarantee is the whole point of M0: kill anywhere, re-run, and
only missing/stale work repeats. These tests exercise that contract without
any media."""

import json

import pytest
import backend.server
from publikclip_pipeline import config
from publikclip_pipeline.campaigns import store
from publikclip_pipeline.jobs import queue


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "home"))
    yield


def _settings_json() -> str:
    return json.dumps(config.Settings().to_json())


class CountingStage(queue.Stage):
    name = "counting"
    schema_version = 1

    def __init__(self):
        self.runs = 0

    def run(self, ctx):
        self.runs += 1
        return {"runs": self.runs}


class FailingStage(queue.Stage):
    name = "failing"
    schema_version = 1

    def run(self, ctx):
        raise queue.StageError("boom, but politely")


class ArtifactStage(queue.Stage):
    name = "artifact"
    schema_version = 1

    def __init__(self):
        self.runs = 0

    def run(self, ctx):
        self.runs += 1
        out = ctx.job_dir / "artifact.bin"
        out.write_bytes(b"data")
        return {"path": str(out)}

    def artifacts_ok(self, ctx, data):
        from pathlib import Path

        return Path(data["path"]).exists()


def _noop_progress(stage, fraction, message):
    pass


def test_create_and_get_job():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    fetched = queue.get_job(job.id)
    assert fetched is not None
    assert fetched.source == "/tmp/x.mp4"
    assert job.dir.exists()
    assert (job.dir / "settings.json").exists()


def test_stage_runs_once_then_caches():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    stage = CountingStage()
    queue.run_stages(job, [stage], _noop_progress)
    queue.run_stages(job, [stage], _noop_progress)
    assert stage.runs == 1  # second run served from checkpoint


def test_schema_version_bump_invalidates():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    stage = CountingStage()
    queue.run_stages(job, [stage], _noop_progress)
    stage.schema_version = 2
    queue.run_stages(job, [stage], _noop_progress)
    assert stage.runs == 2


def test_missing_artifact_invalidates_checkpoint():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    stage = ArtifactStage()
    queue.run_stages(job, [stage], _noop_progress)
    (job.dir / "artifact.bin").unlink()
    queue.run_stages(job, [stage], _noop_progress)
    assert stage.runs == 2


def test_corrupt_checkpoint_reruns():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    stage = CountingStage()
    queue.run_stages(job, [stage], _noop_progress)
    queue.checkpoint_path(job, stage.name).write_text("{not json")
    queue.run_stages(job, [stage], _noop_progress)
    assert stage.runs == 2


def test_legacy_cp1252_checkpoint_is_readable():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    path = queue.checkpoint_path(job, "legacy")
    path.write_bytes(b'{"stage":"legacy","schema_version":1,"data":{"text":"caf\x96"}}')

    assert queue.read_checkpoint(job, "legacy", 1) == {"text": "caf\u2013"}


def test_stage_error_marks_job_failed():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    with pytest.raises(queue.StageError):
        queue.run_stages(job, [FailingStage()], _noop_progress)
    fetched = queue.get_job(job.id)
    assert fetched.status == "failed"
    assert "politely" in (fetched.error or "")


def test_failure_then_resume_skips_completed_stages():
    job = queue.create_job("file", "/tmp/x.mp4", _settings_json())
    counting = CountingStage()
    with pytest.raises(queue.StageError):
        queue.run_stages(job, [counting, FailingStage()], _noop_progress)
    assert counting.runs == 1

    class FixedStage(queue.Stage):
        name = "failing"  # same name — simulates the bug being fixed
        schema_version = 1

        def run(self, ctx):
            return {"ok": True}

    results = queue.run_stages(job, [counting, FixedStage()], _noop_progress)
    assert counting.runs == 1  # not re-run
    assert results["failing"] == {"ok": True}
    assert queue.get_job(job.id).status == "done"


def test_campaign_video_uses_transcript_title_when_available():
    campaign = store.create_campaign("Demo")
    video_url = "https://example.com/watch?v=test-video"

    store.add_video(campaign["id"], video_url)
    store.store_transcript(
        video_url,
        campaign["id"],
        "Actual Video Title",
        "Demo Channel",
        123.0,
        [{"text": "hello world", "start": 0.0, "end": 1.0}],
        2,
    )

    rows = store.campaign_videos(campaign["id"])
    assert rows[0]["title"] == "Actual Video Title"


def test_job_title_uses_original_info_json_when_ingest_is_generic():
    job = queue.create_job("url", "https://example.com/watch?v=abc123", _settings_json())
    (job.dir / "media.info.json").write_text(json.dumps({"title": "Original Video Title"}))
    assert backend.server._resolve_job_title(job) == "Original Video Title"
