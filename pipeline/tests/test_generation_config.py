"""Focused tests for the versioned creative generation contract."""

import json

import pytest

from publikclip_pipeline import config, generation_config
from publikclip_pipeline.jobs import queue


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIKCLIP_HOME", str(tmp_path / "home"))


def make_job(*, settings: config.Settings | None = None):
    value = settings or config.Settings()
    return queue.create_job("file", "/tmp/source.mp4", json.dumps(value.to_json()))


def test_default_profile_and_config_are_created():
    job = make_job()
    profile = generation_config.get_profile(generation_config.DEFAULT_PROFILE_ID)
    saved = generation_config.get_project_config(job.id)

    assert profile is not None
    assert profile["name"] == "Publikclip Default"
    assert profile["scope"] == "global"
    assert saved["resolved_config"] == generation_config.system_default_config()


def test_profile_creation_loading_and_inheritance():
    profile = generation_config.save_profile({
        "name": "Creator captions",
        "scope": "creator",
        "config": {"captions": {"preset_id": "classic"}},
    })
    loaded = generation_config.get_profile(profile["id"])
    resolved = generation_config.resolve_config({"style_profile_id": profile["id"]})

    assert loaded["config"]["captions"]["preset_id"] == "classic"
    assert resolved["captions"]["preset_id"] == "classic"
    assert resolved["captions"]["fill"] == "white"


def test_project_override_wins_and_inputs_are_not_mutated():
    profile = generation_config.save_profile({
        "name": "Yellow", "scope": "custom",
        "config": {"captions": {"preset_id": "classic", "fill": "yellow"}},
    })
    raw = {"style_profile_id": profile["id"], "captions": {"fill": "cyan"}}
    before = json.loads(json.dumps(raw))
    resolved = generation_config.resolve_config(raw)

    assert resolved["captions"]["preset_id"] == "classic"
    assert resolved["captions"]["fill"] == "cyan"
    assert raw == before


def test_run_snapshot_is_unchanged_after_profile_update():
    job = make_job()
    profile = generation_config.save_profile({
        "id": "mutable-profile", "name": "Mutable", "scope": "custom",
        "config": {"captions": {"fill": "yellow"}},
    })
    generation_config.save_project_config(job.id, {"style_profile_id": profile["id"]})
    snapshot = generation_config.snapshot_run(job.id)

    generation_config.save_profile({
        "name": "Mutable", "scope": "custom",
        "config": {"captions": {"fill": "cyan"}},
    }, profile_id=profile["id"])

    assert generation_config.get_run_snapshot(snapshot["run_id"])["resolved_config"]["captions"]["fill"] == "yellow"
    assert generation_config.get_project_config(job.id)["resolved_config"]["captions"]["fill"] == "cyan"


def test_legacy_job_fallback_preserves_existing_settings():
    settings = config.Settings(caption_preset="classic", caption_color="yellow")
    job = make_job(settings=settings)
    with queue._connect() as conn:
        conn.execute("DELETE FROM generation_configs WHERE job_id=?", (job.id,))

    fallback = generation_config.get_project_config(job.id)
    assert fallback["legacy_fallback"] is True
    assert fallback["resolved_config"]["captions"]["preset_id"] == "classic"
    assert fallback["resolved_config"]["captions"]["fill"] == "yellow"


@pytest.mark.parametrize("payload", [
    {"broll": {"mode": "constant"}},
    {"sfx": {"mode": "loud"}},
    {"music": {"mode": "high"}},
    {"transitions": {"mode": "automatic"}},
    {"title_hook": {"mode": "surprise"}},
    {"sfx": {"allowed_event_families": ["explosion"]}},
])
def test_validation_rejects_unsupported_enums(payload):
    with pytest.raises(ValueError):
        generation_config.validate_config(payload)


def test_future_persistence_only_fields_round_trip_without_execution():
    job = make_job()
    payload = {
        "broll": {"mode": "balanced", "presentation": "overlay", "future_hint": "stock-only"},
        "music": {"mode": "low", "track_ref": "asset:bed-1"},
        "user_overrides": {"future_renderer": {"grain": 0.2}},
    }
    saved = generation_config.save_project_config(job.id, payload)
    settings = generation_config.apply_to_settings(config.Settings(), saved["resolved_config"])

    assert saved["config"]["broll"]["future_hint"] == "stock-only"
    assert saved["config"]["user_overrides"]["future_renderer"]["grain"] == 0.2
    assert not hasattr(settings, "broll")


def test_clip_length_contract_persists_in_the_run_snapshot():
    job = make_job()
    generation_config.save_project_config(job.id, {"clip_length": {"min_seconds": 30, "max_seconds": 60}})
    snapshot = generation_config.snapshot_run(job.id)
    assert snapshot["resolved_config"]["clip_length"] == {"min_seconds": 30, "max_seconds": 60}
