"""Versioned edit-style profiles and per-job generation configuration.

The contract is intentionally broader than today's renderer.  Resolution is
pure and deterministic; only ``apply_to_settings`` bridges fields already
supported by the pipeline.
"""

from __future__ import annotations

import copy
import json
import sqlite3
import time
import uuid
from typing import Any

from . import config


CONFIG_VERSION = 1
DEFAULT_PROFILE_ID = "publikclip-default"

PROFILE_SCOPES = {"global", "creator", "page/account", "client", "custom"}
TITLE_MODES = {"none", "generated", "manual", "profile_default"}
BROLL_MODES = {"off", "conservative", "balanced", "aggressive"}
BROLL_PRESENTATIONS = {"replace", "overlay", "mixed"}
SFX_MODES = {"off", "minimal", "balanced", "punchy"}
SFX_FAMILIES = {"riser", "impact", "hit", "whoosh", "click", "shutter"}
MUSIC_MODES = {"off", "low", "medium"}
TRANSITION_MODES = {"none", "minimal", "profile_default", "custom"}
CAPITALIZATION_MODES = {"preserve", "uppercase", "lowercase", "title"}
CAPTION_FILLS = {"white", "yellow", "cyan"}
CAMERA_SPEAKER_CHANGE_MODES = {"cut", "pan", "locked"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS edit_style_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    scope TEXT NOT NULL,
    description TEXT,
    config_version INTEGER NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    is_active INTEGER NOT NULL DEFAULT 1,
    is_default INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS generation_configs (
    job_id TEXT PRIMARY KEY,
    style_profile_id TEXT,
    config_version INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    resolved_config_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id),
    FOREIGN KEY (style_profile_id) REFERENCES edit_style_profiles(id)
);
CREATE TABLE IF NOT EXISTS generation_config_runs (
    run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    style_profile_id TEXT,
    config_version INTEGER NOT NULL,
    config_json TEXT NOT NULL,
    resolved_config_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_generation_config_runs_job
ON generation_config_runs(job_id, created_at DESC);
"""


def system_default_config() -> dict[str, Any]:
    """Defaults matching the pre-contract renderer and camera behavior."""
    return {
        "config_version": CONFIG_VERSION,
        "style_profile_id": DEFAULT_PROFILE_ID,
        "layout": {
            "preset_id": "vertical_9_16",
            "target_aspect_ratio": "9:16",
            "content_aspect_ratio": None,
            "content_bbox": None,
            "background_mode": None,
            "title_placement_relation": None,
            "custom_overrides": {},
        },
        "captions": {
            "preset_id": "hormozi",
            "enabled": True,
            "font_style_ref": None,
            "relative_size": None,
            "placement": None,
            "max_lines": None,
            "words_per_phrase": 1,
            "fill": "white",
            "outline": None,
            "shadow": None,
            "highlight_color": None,
            "emphasis_mode": "existing",
            "capitalization": None,
        },
        "title_hook": {
            "mode": "none", "manual_text": None, "preset_id": None,
            "placement": None, "enabled": False,
        },
        "broll": {
            "mode": "off", "presentation": "replace",
            "still_vs_video": None, "source_preference": None,
        },
        "sfx": {"mode": "off", "allowed_event_families": [], "intensity": None, "density": None},
        "music": {
            "mode": "off", "track_ref": None, "energy": None,
            "speech_safe_level": None, "ducking": None,
        },
        "camera": {
            "enabled": True,
            "speaker_tracking": True,
            "reframing_behavior": "existing",
            "speaker_change": "cut",
            "pan_duration_s": 0.6,
            "deadzone_frac": 0.05,
            "punch": {"enabled": True, "frequency": None, "intensity": 1.0},
            "zoom_lock_per_scene": True,
            "profile_defaults": {},
        },
        "transitions": {"mode": "none", "preset_id": None},
        "clip_length": {"min_seconds": None, "max_seconds": None},
        "user_overrides": {},
    }


def config_from_settings(settings: config.Settings) -> dict[str, Any]:
    """Represent legacy, already-supported settings as explicit overrides."""
    return {
        "config_version": CONFIG_VERSION,
        "style_profile_id": DEFAULT_PROFILE_ID,
        "captions": {
            "preset_id": settings.caption_preset,
            "fill": settings.caption_color,
        },
        "camera": {
            "speaker_change": settings.camera.speaker_change,
            "pan_duration_s": settings.camera.pan_duration_s,
            "deadzone_frac": settings.camera.deadzone_frac,
            "punch": {
                "enabled": settings.camera.punch_in,
                "intensity": settings.camera.punch_in_sensitivity,
            },
            "zoom_lock_per_scene": settings.camera.zoom_lock_per_scene,
        },
    }


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    existing = conn.execute(
        "SELECT 1 FROM edit_style_profiles WHERE id=?", (DEFAULT_PROFILE_ID,)
    ).fetchone()
    if existing is not None:
        return
    now = time.time()
    conn.execute(
        "INSERT OR IGNORE INTO edit_style_profiles"
        "(id,name,scope,description,config_version,config_json,is_active,is_default,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?,1,1,?,?)",
        (
            DEFAULT_PROFILE_ID, "Publikclip Default", "global",
            "System profile preserving the existing Publikclip output behavior.",
            CONFIG_VERSION, "{}", now, now,
        ),
    )


def _connect() -> sqlite3.Connection:
    config.ensure_home()
    conn = sqlite3.connect(config.db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return copy.deepcopy(value)


def _enum(section: dict[str, Any], key: str, allowed: set[str], label: str) -> None:
    value = section.get(key)
    if value is not None and value not in allowed:
        raise ValueError(f"{label}.{key} must be one of: {', '.join(sorted(allowed))}")


def validate_config(value: Any, *, partial: bool = True) -> dict[str, Any]:
    data = _json_object(value, "generation config")
    version = data.get("config_version", CONFIG_VERSION)
    if version != CONFIG_VERSION:
        raise ValueError(f"unsupported config_version {version!r}")
    data["config_version"] = version
    for key in ("layout", "captions", "title_hook", "broll", "sfx", "music", "camera", "transitions", "clip_length", "user_overrides"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError(f"{key} must be an object")
    _enum(data.get("title_hook", {}), "mode", TITLE_MODES, "title_hook")
    _enum(data.get("broll", {}), "mode", BROLL_MODES, "broll")
    _enum(data.get("broll", {}), "presentation", BROLL_PRESENTATIONS, "broll")
    _enum(data.get("sfx", {}), "mode", SFX_MODES, "sfx")
    _enum(data.get("music", {}), "mode", MUSIC_MODES, "music")
    _enum(data.get("transitions", {}), "mode", TRANSITION_MODES, "transitions")
    _enum(data.get("captions", {}), "capitalization", CAPITALIZATION_MODES, "captions")
    _enum(data.get("captions", {}), "fill", CAPTION_FILLS, "captions")
    _enum(data.get("camera", {}), "speaker_change", CAMERA_SPEAKER_CHANGE_MODES, "camera")
    families = data.get("sfx", {}).get("allowed_event_families")
    if families is not None:
        if not isinstance(families, list) or any(item not in SFX_FAMILIES for item in families):
            raise ValueError("sfx.allowed_event_families contains an unsupported family")
    for section, key in (("captions", "enabled"), ("title_hook", "enabled"), ("camera", "enabled"), ("camera", "speaker_tracking")):
        item = data.get(section, {}).get(key)
        if item is not None and not isinstance(item, bool):
            raise ValueError(f"{section}.{key} must be a boolean")
    clip_length = data.get("clip_length", {})
    for key in ("min_seconds", "max_seconds"):
        value = clip_length.get(key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0):
            raise ValueError(f"clip_length.{key} must be a positive number or null")
    minimum, maximum = clip_length.get("min_seconds"), clip_length.get("max_seconds")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("clip_length.min_seconds cannot exceed clip_length.max_seconds")
    if not partial:
        missing = set(system_default_config()) - set(data)
        if missing:
            raise ValueError(f"generation config is missing sections: {', '.join(sorted(missing))}")
    return data


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def merge_config_overrides(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Return validated nested overrides without mutating either input."""
    return validate_config(_merge(validate_config(base), validate_config(override)))


def _profile_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    result["config"] = json.loads(result.pop("config_json") or "{}")
    result["is_active"] = bool(result["is_active"])
    result["is_default"] = bool(result["is_default"])
    return result


def list_profiles(*, active_only: bool = False) -> list[dict[str, Any]]:
    with _connect() as conn:
        sql = "SELECT * FROM edit_style_profiles"
        if active_only:
            sql += " WHERE is_active=1"
        rows = conn.execute(sql + " ORDER BY is_default DESC,name,id").fetchall()
    return [_profile_row(row) for row in rows]  # type: ignore[misc]


def get_profile(profile_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM edit_style_profiles WHERE id=?", (profile_id,)).fetchone()
    return _profile_row(row)


def save_profile(payload: dict[str, Any], *, profile_id: str | None = None) -> dict[str, Any]:
    data = _json_object(payload, "style profile")
    existing = get_profile(profile_id) if profile_id else None
    requested_version = data.get("config_version", CONFIG_VERSION)
    if requested_version != CONFIG_VERSION:
        raise ValueError(f"unsupported config_version {requested_version!r}")
    resolved_id = profile_id or data.get("id") or f"profile-{uuid.uuid4().hex}"
    scope = data.get("scope", existing["scope"] if existing else "custom")
    if scope not in PROFILE_SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(sorted(PROFILE_SCOPES))}")
    name = data.get("name", existing["name"] if existing else None)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required")
    profile_config = validate_config(data.get("config", existing["config"] if existing else {}))
    now = time.time()
    created_at = existing["created_at"] if existing else now
    with _connect() as conn:
        conn.execute(
            "INSERT INTO edit_style_profiles"
            "(id,name,scope,description,config_version,config_json,is_active,is_default,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name,scope=excluded.scope,description=excluded.description,"
            "config_version=excluded.config_version,config_json=excluded.config_json,"
            "is_active=excluded.is_active,updated_at=excluded.updated_at",
            (
                resolved_id, name.strip(), scope, data.get("description", existing.get("description") if existing else None),
                CONFIG_VERSION, json.dumps(profile_config, sort_keys=True),
                int(bool(data.get("is_active", existing["is_active"] if existing else True))),
                int(bool(existing["is_default"])) if existing else 0, created_at, now,
            ),
        )
    result = get_profile(resolved_id)
    assert result is not None
    return result


def resolve_config(raw_config: dict[str, Any] | None = None, *, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = validate_config(raw_config or {})
    profile_id = raw.get("style_profile_id") or (profile or {}).get("id") or DEFAULT_PROFILE_ID
    selected_profile = profile if profile is not None else get_profile(profile_id)
    if selected_profile is None:
        raise ValueError(f"style profile not found: {profile_id}")
    result = _merge(system_default_config(), validate_config(selected_profile.get("config") or {}))
    result = _merge(result, raw)
    result["config_version"] = CONFIG_VERSION
    result["style_profile_id"] = profile_id
    return validate_config(result, partial=False)


def save_project_config(job_id: str, raw_config: dict[str, Any] | None, *, conn: sqlite3.Connection | None = None) -> dict[str, Any]:
    raw = validate_config(raw_config or {})
    raw.setdefault("style_profile_id", DEFAULT_PROFILE_ID)
    now = time.time()
    owns_connection = conn is None
    database = conn or _connect()
    try:
        ensure_schema(database)
        profile_row = database.execute(
            "SELECT * FROM edit_style_profiles WHERE id=?", (raw["style_profile_id"],)
        ).fetchone()
        if profile_row is None:
            raise ValueError(f"style profile not found: {raw['style_profile_id']}")
        resolved = resolve_config(raw, profile=_profile_row(profile_row))
        exists = database.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not exists:
            raise KeyError(job_id)
        database.execute(
            "INSERT INTO generation_configs"
            "(job_id,style_profile_id,config_version,config_json,resolved_config_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(job_id) DO UPDATE SET "
            "style_profile_id=excluded.style_profile_id,config_version=excluded.config_version,"
            "config_json=excluded.config_json,resolved_config_json=excluded.resolved_config_json,updated_at=excluded.updated_at",
            (
                job_id, raw["style_profile_id"], CONFIG_VERSION,
                json.dumps(raw, sort_keys=True), json.dumps(resolved, sort_keys=True), now, now,
            ),
        )
        if owns_connection:
            database.commit()
        else:
            return {
                "job_id": job_id, "config": raw, "resolved_config": resolved,
                "saved_resolved_config": copy.deepcopy(resolved),
                "legacy_fallback": False, "created_at": now, "updated_at": now,
            }
    finally:
        if owns_connection:
            database.close()
    return get_project_config(job_id)


def get_project_config(job_id: str) -> dict[str, Any]:
    with _connect() as conn:
        job = conn.execute("SELECT settings_json FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise KeyError(job_id)
        row = conn.execute("SELECT * FROM generation_configs WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        try:
            settings = config.Settings.from_json(json.loads(job["settings_json"]))
        except (TypeError, ValueError):
            settings = config.Settings()
        raw = config_from_settings(settings)
        return {"job_id": job_id, "config": raw, "resolved_config": resolve_config(raw), "legacy_fallback": True}
    raw = json.loads(row["config_json"])
    return {
        "job_id": job_id,
        "config": raw,
        "resolved_config": resolve_config(raw),
        "saved_resolved_config": json.loads(row["resolved_config_json"]),
        "legacy_fallback": False,
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def preview_project_config(job_id: str, raw_config: dict[str, Any] | None = None) -> dict[str, Any]:
    current = get_project_config(job_id)
    raw = current["config"] if raw_config is None else validate_config(raw_config)
    return {"job_id": job_id, "config": raw, "resolved_config": resolve_config(raw)}


def update_supported_settings(job_id: str, settings: config.Settings) -> dict[str, Any]:
    """Keep legacy caption/camera inputs authoritative for supported fields."""
    current = get_project_config(job_id)["config"]
    supported = config_from_settings(settings)
    supported.pop("style_profile_id", None)
    return save_project_config(job_id, merge_config_overrides(current, supported))


def snapshot_run(job_id: str) -> dict[str, Any]:
    current = get_project_config(job_id)
    run_id = f"gcr-{uuid.uuid4().hex}"
    resolved = current["resolved_config"]
    raw = current["config"]
    with _connect() as conn:
        conn.execute(
            "INSERT INTO generation_config_runs"
            "(run_id,job_id,style_profile_id,config_version,config_json,resolved_config_json,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                run_id, job_id, resolved.get("style_profile_id"), CONFIG_VERSION,
                json.dumps(raw, sort_keys=True), json.dumps(resolved, sort_keys=True), time.time(),
            ),
        )
    return get_run_snapshot(run_id)


def get_run_snapshot(run_id: str) -> dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM generation_config_runs WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    result = dict(row)
    result["config"] = json.loads(result.pop("config_json"))
    result["resolved_config"] = json.loads(result.pop("resolved_config_json"))
    return result


def list_run_snapshots(job_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT run_id FROM generation_config_runs WHERE job_id=? ORDER BY created_at,run_id", (job_id,)
        ).fetchall()
    return [get_run_snapshot(row["run_id"]) for row in rows]


def apply_to_settings(settings: config.Settings, resolved: dict[str, Any]) -> config.Settings:
    """Apply only controls the current pipeline already implements."""
    result = config.Settings.from_json(settings.to_json())
    captions = resolved.get("captions") or {}
    if captions.get("preset_id") is not None:
        result.caption_preset = captions["preset_id"]
    if captions.get("fill") is not None:
        result.caption_color = captions["fill"]
    camera = resolved.get("camera") or {}
    for contract_key, settings_key in (
        ("speaker_change", "speaker_change"), ("pan_duration_s", "pan_duration_s"),
        ("deadzone_frac", "deadzone_frac"), ("zoom_lock_per_scene", "zoom_lock_per_scene"),
    ):
        if camera.get(contract_key) is not None:
            setattr(result.camera, settings_key, camera[contract_key])
    punch = camera.get("punch") or {}
    if punch.get("enabled") is not None:
        result.camera.punch_in = punch["enabled"]
    if punch.get("intensity") is not None:
        result.camera.punch_in_sensitivity = punch["intensity"]
    return result
