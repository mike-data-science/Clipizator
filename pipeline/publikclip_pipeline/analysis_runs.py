"""Versioned Analyzer run metadata with immutable Video DNA artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from . import config


ANALYZER_VERSION = "2.3.0"
VIDEO_DNA_SCHEMA_VERSION = 2
PIPELINE_VERSION = "0.1.0"

SCHEMA = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    analysis_run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    creator_video_id INTEGER,
    source_identity TEXT,
    analyzer_version TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    pipeline_version TEXT,
    config_fingerprint TEXT,
    component_provenance_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    artifact_path TEXT,
    started_at REAL,
    completed_at REAL,
    created_at REAL NOT NULL,
    error TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_job
ON analysis_runs(job_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_creator_video
ON analysis_runs(creator_video_id, created_at DESC);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _connect() -> sqlite3.Connection:
    config.ensure_home()
    conn = sqlite3.connect(config.db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    ensure_schema(conn)
    return conn


def _source_provenance(job: Any) -> dict[str, Any]:
    try:
        value = json.loads(getattr(job, "source_provenance_json", None) or "{}")
    except (TypeError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _source_identity(job: Any, provenance: dict[str, Any]) -> str | None:
    platform = provenance.get("platform")
    external_id = provenance.get("external_video_id")
    if platform and external_id:
        return f"{platform}:{external_id}"
    return provenance.get("canonical_url") or getattr(job, "source", None)


def config_fingerprint(settings_json: str | None) -> str | None:
    if not settings_json:
        return None
    try:
        canonical = json.dumps(json.loads(settings_json), sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        canonical = str(settings_json)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    try:
        result["component_provenance"] = json.loads(result.pop("component_provenance_json") or "{}")
    except (TypeError, ValueError):
        result["component_provenance"] = {}
    return result


def create_analysis_run(job: Any, *, started_at: float | None = None) -> dict[str, Any]:
    """Create a new run even when this job/source has older completed runs."""
    now = time.time()
    provenance = _source_provenance(job)
    run_id = f"ar-{uuid.uuid4().hex}"
    creator_video_id = provenance.get("creator_video_id")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO analysis_runs(analysis_run_id,job_id,creator_video_id,source_identity,"
            "analyzer_version,schema_version,pipeline_version,config_fingerprint,status,started_at,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, job.id, int(creator_video_id) if isinstance(creator_video_id, int) else None,
                _source_identity(job, provenance), ANALYZER_VERSION, VIDEO_DNA_SCHEMA_VERSION,
                PIPELINE_VERSION, config_fingerprint(getattr(job, "settings_json", None)),
                "running", started_at if started_at is not None else now, now,
            ),
        )
    result = get_analysis_run(run_id)
    assert result is not None
    return result


def get_analysis_run(analysis_run_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM analysis_runs WHERE analysis_run_id=?", (analysis_run_id,)
        ).fetchone()
    return _row(row)


def list_analysis_runs(job_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM analysis_runs WHERE job_id=? ORDER BY created_at DESC,analysis_run_id DESC",
            (job_id,),
        ).fetchall()
    return [_row(row) for row in rows if row is not None]  # type: ignore[misc]


def latest_analysis_run(job_id: str) -> dict[str, Any] | None:
    runs = list_analysis_runs(job_id)
    return runs[0] if runs else None


def complete_analysis_run(job: Any, analysis_run_id: str, video_dna: dict[str, Any]) -> dict[str, Any]:
    """Persist one immutable DNA artifact, then point the run row at it."""
    run_dir = Path(job.dir) / "analysis_runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    relative = f"analysis_runs/{analysis_run_id}.video_dna.json"
    path = Path(job.dir) / relative
    if path.exists():
        raise FileExistsError(f"Analysis run artifact already exists: {analysis_run_id}")
    envelope = {
        "analysis_run_id": analysis_run_id,
        "analyzer_version": ANALYZER_VERSION,
        "schema_version": VIDEO_DNA_SCHEMA_VERSION,
        "created_at": time.time(),
        "video_dna": video_dna,
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(envelope, ensure_ascii=False, indent=1))
    temp.replace(path)
    completed_at = time.time()
    components = ((video_dna.get("provenance") or {}).get("components") or {})
    with _connect() as conn:
        changed = conn.execute(
            "UPDATE analysis_runs SET status='completed',artifact_path=?,completed_at=?,error=NULL,"
            "component_provenance_json=? WHERE analysis_run_id=? AND job_id=? AND status='running'",
            (relative, completed_at, json.dumps(components, ensure_ascii=False), analysis_run_id, job.id),
        ).rowcount
    if changed != 1:
        path.unlink(missing_ok=True)
        raise ValueError(f"Analysis run is not active: {analysis_run_id}")
    result = get_analysis_run(analysis_run_id)
    assert result is not None
    return result


def fail_analysis_run(analysis_run_id: str, error: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE analysis_runs SET status='failed',completed_at=?,error=? "
            "WHERE analysis_run_id=? AND status='running'",
            (time.time(), error, analysis_run_id),
        )


def mark_analysis_run_unavailable(analysis_run_id: str, reason: str) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE analysis_runs SET status='unavailable',completed_at=?,error=? "
            "WHERE analysis_run_id=? AND status='running'",
            (time.time(), reason, analysis_run_id),
        )


def read_video_dna(job: Any, run: dict[str, Any]) -> dict[str, Any] | None:
    relative = run.get("artifact_path")
    if not isinstance(relative, str) or not relative:
        return None
    path = Path(job.dir) / relative
    try:
        payload = json.loads(path.read_text(errors="replace"))
    except (OSError, TypeError, ValueError):
        return None
    value = payload.get("video_dna") if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else None


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    return {
        key: run.get(key)
        for key in (
            "analysis_run_id", "job_id", "creator_video_id", "source_identity",
            "analyzer_version", "schema_version", "pipeline_version", "config_fingerprint",
            "status", "artifact_path", "started_at", "completed_at", "created_at", "error",
        )
    }
