"""Lightweight observability for the Analyzer pilot.

Stores references and small provenance records, not copies of analyzer
payloads. Existing checkpoints remain the source of truth.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from . import config

OUTCOMES = {"success_with_detections", "success_no_detections", "unavailable", "fallback_used", "failed"}

PILOT_SCHEMA = """
CREATE TABLE IF NOT EXISTS pilot_stage_observations (
    job_id TEXT NOT NULL, stage TEXT NOT NULL, stage_status TEXT NOT NULL,
    outcome TEXT, runtime_sec REAL, error TEXT,
    config_json TEXT NOT NULL DEFAULT '{}', provenance_json TEXT NOT NULL DEFAULT '{}',
    artifacts_json TEXT NOT NULL DEFAULT '[]', created_at REAL NOT NULL, updated_at REAL NOT NULL,
    PRIMARY KEY (job_id, stage)
);
CREATE TABLE IF NOT EXISTS pilot_qa_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, media_ref TEXT,
    start_sec REAL NOT NULL, end_sec REAL NOT NULL, target_type TEXT NOT NULL,
    original_json TEXT, corrected_json TEXT NOT NULL, note TEXT, created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pilot_qa_job_time ON pilot_qa_labels(job_id, start_sec, end_sec);
"""

_STAGE_PATTERNS = {
    "ingest": ("ingest.json", "settings.json", "media.mkv", "media_cfr.mp4", "audio16k.wav"),
    "asr": ("asr.json",),
    "diarize": ("diarize.json", "diar_embeddings.npy"),
    "events": ("events.json", "curves.json"),
    "candidates": ("candidates.json", "scenes.json", "interest_curve.json"),
    "score": ("score.json", "manual_prompts.json", "manual_scores.json"),
    "camera": ("camera.json", "trajectory_*.json"),
    "render": ("render.json", "clips/*"),
}


def ensure_schema(conn) -> None:
    conn.executescript(PILOT_SCHEMA)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def code_revision() -> str | None:
    if override := os.environ.get("PUBLIKCLIP_CODE_REVISION"):
        return override
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def code_dirty() -> bool | None:
    try:
        output = subprocess.run(
            ["git", "status", "--porcelain"], cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout
        return bool(output.strip())
    except (OSError, subprocess.SubprocessError):
        return None


def _file_identity(path: Path, include_sample_hash: bool = False) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "exists": False, "size_bytes": None}
    item: dict[str, Any] = {"path": str(path), "exists": True, "size_bytes": stat.st_size, "mtime": stat.st_mtime}
    if include_sample_hash and path.is_file():
        digest = hashlib.sha256()
        digest.update(str(stat.st_size).encode())
        try:
            with path.open("rb") as handle:
                digest.update(handle.read(1024 * 1024))
                if stat.st_size > 1024 * 1024:
                    handle.seek(max(0, stat.st_size - 1024 * 1024))
                    digest.update(handle.read(1024 * 1024))
            item["fingerprint"] = f"sha256-size-first-last-1m:{digest.hexdigest()}"
        except OSError:
            item["fingerprint"] = None
    return item


def _checkpoint_data(job_dir: Path, stage: str) -> dict[str, Any]:
    try:
        payload = json.loads((job_dir / f"{stage}.json").read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload.get("data") if isinstance(payload.get("data"), dict) else {}


def stage_artifacts(job_dir: Path, stage: str) -> list[dict[str, Any]]:
    seen: set[Path] = set()
    paths: list[Path] = []
    for pattern in _STAGE_PATTERNS.get(stage, (f"{stage}.json",)):
        for path in sorted(job_dir.glob(pattern)):
            if path.is_file() and path not in seen:
                seen.add(path)
                paths.append(path)
    return [_file_identity(path) for path in paths]


def relevant_config(settings: Any, stage: str) -> dict[str, Any]:
    values = settings.to_json() if hasattr(settings, "to_json") else dict(settings or {})
    keys = {
        "asr": ("asr_model",), "events": ("laughter_specialist",),
        "score": ("llm_mode", "gemini_model", "ollama_model", "ollama_base_url"),
        "camera": ("camera",),
        "render": ("camera", "lufs_target", "true_peak_db", "caption_preset", "caption_color"),
    }.get(stage, ())
    return {key: values.get(key) for key in keys}


def infer_outcome(stage: str, data: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    detectors: dict[str, Any] = {}
    count = 1
    if stage == "asr":
        count = int(data.get("word_count") or 0)
    elif stage == "diarize":
        count = len(data.get("turns") or [])
    elif stage == "events":
        event_count = sum(int(v) for k, v in (data.get("counts") or {}).items() if k != "pause")
        detectors["audio_events"] = {"outcome": "success_with_detections" if event_count else "success_no_detections", "count": event_count}
        source = data.get("arousal_source")
        detectors["arousal"] = {"outcome": "fallback_used" if source == "dsp-proxy" else "success_with_detections", "source": source}
        count = len(data.get("timeline") or [])
        if source == "dsp-proxy":
            return "fallback_used", detectors
    elif stage == "candidates":
        count = int(data.get("count") or 0)
        detectors["scenes"] = {
            "outcome": data.get("scene_detector_outcome", "unknown"),
            "count": int(data.get("scene_count") or 0), "error": data.get("scene_detector_error"),
        }
    elif stage == "score":
        count = len(data.get("clips") or [])
        if not data.get("t2_ran", False):
            detectors["visual_scoring"] = {"outcome": "unavailable", "reason": "backend_has_no_vision"}
    elif stage == "camera":
        count = len(data.get("trajectories") or {})
    elif stage == "render":
        count = len(data.get("outputs") or [])
    return ("success_with_detections" if count else "success_no_detections"), detectors


def _model_identity(directory: str, filename: str) -> dict[str, Any]:
    identity = _file_identity(config.models_dir() / directory / filename)
    identity.update({"id": directory, "filename": filename, "weight_sha256": None})
    return identity


def _device_info(stage: str, data: dict[str, Any]) -> dict[str, Any]:
    explicit = str(data.get("device") or "").lower()
    providers = data.get("onnx_providers")
    gpu_name = None
    if "cuda" in explicit or "gpu" in explicit:
        mode = "gpu"
    elif "cpu" in explicit:
        mode = "cpu"
    elif stage == "score" and data.get("llm_mode") == "gemini":
        mode = "remote"
    elif stage == "render":
        acceleration = data.get("acceleration") or {}
        mode = "gpu" if acceleration.get("scaling") == "CUDA" or acceleration.get("encoding") == "NVENC" else "cpu"
    else:
        mode = "unknown"
    if mode == "gpu":
        try:
            import torch
            gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
        except Exception:  # noqa: BLE001 - provenance must never break a run
            pass
    return {"mode": mode, "reported_device": data.get("device"), "gpu_name": gpu_name, "onnx_providers": providers}


def stage_provenance(stage: str, data: dict[str, Any]) -> dict[str, Any]:
    libraries = {
        "ingest": ("yt-dlp",), "asr": ("whisperx", "faster-whisper", "torch"),
        "diarize": ("torch", "scikit-learn", "librosa"),
        "events": ("torch", "librosa", "scipy"), "candidates": ("scenedetect", "numpy"),
        "score": ("httpx",), "camera": ("onnxruntime", "opencv-python-headless"), "render": (),
    }.get(stage, ())
    models: list[dict[str, Any]] = []
    if stage == "asr":
        models.append({"id": data.get("model"), "compute_type": data.get("compute_type")})
    elif stage == "diarize":
        models.append(_model_identity("campplus", "campplus_cn_common.bin"))
    elif stage == "events":
        models.append(_model_identity("panns-cnn14-decisionlevelmax", "Cnn14_DecisionLevelMax.pth"))
        if data.get("benchmark", {}).get("laughter_sec") is not None:
            models.append(_model_identity("laughter-jrgillick", "best.pth.tar"))
    elif stage == "score":
        models.append({"id": data.get("model"), "backend": data.get("llm_mode")})
    elif stage == "camera":
        models.extend([_model_identity("ultraface", "ultraface-rfb-320.onnx"), _model_identity("lr-asd", "frontend.onnx"), _model_identity("lr-asd", "backend.onnx")])
    return {
        "code_revision": code_revision(), "code_dirty": code_dirty(), "python": platform.python_version(), "platform": platform.platform(),
        "device": _device_info(stage, data), "libraries": {name: _package_version(name) for name in libraries}, "models": models,
    }


def record_stage(conn, job: Any, stage: str, stage_status: str, *, outcome: str | None = None,
                 runtime_sec: float | None = None, error: str | None = None,
                 settings: Any = None, data: dict[str, Any] | None = None,
                 legacy_backfill: bool = False, created_at: float | None = None) -> None:
    ensure_schema(conn)
    now, data = time.time(), data or {}
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError(f"invalid pilot outcome {outcome!r}")
    provenance = stage_provenance(stage, data) if stage_status != "running" else {}
    _, detectors = infer_outcome(stage, data) if data else ("success_no_detections", {})
    provenance["detectors"] = detectors
    provenance["capture_mode"] = "legacy_inferred" if legacy_backfill else "runtime"
    if legacy_backfill:
        provenance["code_revision"] = None
        provenance["code_dirty"] = None
        provenance["device"] = {"mode": "unknown", "gpu_name": None, "onnx_providers": None}
        provenance["libraries"] = {name: None for name in provenance.get("libraries", {})}
    conn.execute(
        "INSERT INTO pilot_stage_observations (job_id,stage,stage_status,outcome,runtime_sec,error,config_json,provenance_json,artifacts_json,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(job_id,stage) DO UPDATE SET"
        " stage_status=excluded.stage_status,outcome=excluded.outcome,runtime_sec=excluded.runtime_sec,error=excluded.error,"
        " config_json=excluded.config_json,provenance_json=excluded.provenance_json,artifacts_json=excluded.artifacts_json,updated_at=excluded.updated_at",
        (job.id, stage, stage_status, outcome, runtime_sec, error, _json(relevant_config(settings, stage)),
         _json(provenance), _json(stage_artifacts(job.dir, stage)), created_at or now, now),
    )


def add_qa_label(conn, *, job_id: str, media_ref: str | None, start_sec: float, end_sec: float,
                 target_type: str, original: Any, corrected: Any, note: str | None = None) -> int:
    if start_sec < 0 or end_sec < start_sec:
        raise ValueError("QA timestamps must satisfy 0 <= start_sec <= end_sec")
    ensure_schema(conn)
    cursor = conn.execute(
        "INSERT INTO pilot_qa_labels (job_id,media_ref,start_sec,end_sec,target_type,original_json,corrected_json,note,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (job_id, media_ref, start_sec, end_sec, target_type, _json(original) if original is not None else None,
         _json(corrected), note, time.time()),
    )
    return int(cursor.lastrowid)


def _backfill_legacy_observations(conn, job: Any) -> None:
    """Populate the pilot catalog from existing stage rows/checkpoints once."""
    settings = config.Settings.from_json(json.loads(job.settings_json))
    rows = conn.execute(
        "SELECT sr.* FROM stage_runs sr LEFT JOIN pilot_stage_observations po"
        " ON po.job_id=sr.job_id AND po.stage=sr.stage"
        " WHERE sr.job_id=? AND po.job_id IS NULL ORDER BY sr.started_at",
        (job.id,),
    ).fetchall()
    for row in rows:
        data = _checkpoint_data(job.dir, row["stage"])
        runtime = None
        if row["finished_at"] is not None:
            runtime = max(0.0, float(row["finished_at"]) - float(row["started_at"]))
        if row["status"] == "failed":
            outcome = "failed"
        elif row["status"] == "done" and data:
            outcome, _ = infer_outcome(row["stage"], data)
        elif row["status"] == "done":
            outcome = "unavailable"
        else:
            outcome = None
        error = row["error"]
        if row["status"] == "done" and not data:
            error = error or "checkpoint missing or unreadable"
        record_stage(
            conn, job, row["stage"], row["status"], outcome=outcome,
            runtime_sec=runtime, error=error, settings=settings, data=data,
            legacy_backfill=True, created_at=float(row["started_at"]),
        )


def build_manifest(conn, job: Any) -> dict[str, Any]:
    ensure_schema(conn)
    _backfill_legacy_observations(conn, job)
    rows = conn.execute("SELECT * FROM pilot_stage_observations WHERE job_id=? ORDER BY created_at,stage", (job.id,)).fetchall()
    ingest = _checkpoint_data(job.dir, "ingest")
    media_path = ingest.get("media_path")
    media = Path(media_path) if media_path else None
    if media is not None and not media.is_absolute():
        media = job.dir / media
    fingerprint = ingest.get("source_hash")
    if not fingerprint and media and media.exists():
        fingerprint = _file_identity(media, include_sample_hash=True).get("fingerprint")
    stages = [{
        "stage": row["stage"], "stage_status": row["stage_status"], "outcome": row["outcome"],
        "runtime_sec": row["runtime_sec"], "error": row["error"], "config": json.loads(row["config_json"]),
        "provenance": json.loads(row["provenance_json"]), "artifacts": json.loads(row["artifacts_json"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    } for row in rows]
    return {
        "manifest_version": 1, "job_id": job.id, "source": job.source, "source_type": job.source_type,
        "source_fingerprint": fingerprint, "duration_sec": (ingest.get("probe") or {}).get("duration_sec"),
        "code_revision": code_revision(), "code_dirty": code_dirty(), "job_status": job.status, "job_error": job.error,
        "created_at": job.created_at, "stages": stages,
    }


def write_manifest(conn, job: Any) -> dict[str, Any]:
    manifest = build_manifest(conn, job)
    path = job.dir / "pilot_manifest.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    tmp.replace(path)
    return manifest


def _category(path: Path) -> str:
    if path.name.startswith("media") and path.suffix.lower() in {".mp4", ".mkv", ".mov", ".webm"}:
        return "source_media"
    if path.parent.name == "clips" and path.suffix.lower() == ".mp4":
        return "rendered_video"
    if path.suffix.lower() == ".wav": return "analysis_audio"
    if path.suffix.lower() == ".npy": return "embeddings"
    if path.suffix.lower() in {".json", ".ass"}: return "structured_data"
    return "other"


def summarize(conn, jobs: list[Any]) -> dict[str, Any]:
    manifests = [write_manifest(conn, job) for job in jobs]
    category_bytes: dict[str, int] = {}
    seen: set[str] = set()
    missing: list[dict[str, Any]] = []
    modes: dict[str, int] = {}
    for manifest in manifests:
        for stage in manifest["stages"]:
            for artifact in stage["artifacts"]:
                path = artifact.get("path")
                if path and path not in seen:
                    seen.add(path)
                    category = _category(Path(path))
                    category_bytes[category] = category_bytes.get(category, 0) + int(artifact.get("size_bytes") or 0)
            for detector, detail in (stage["provenance"].get("detectors") or {}).items():
                if detail.get("outcome") in {"unavailable", "fallback_used", "unknown"}:
                    missing.append({"job_id": manifest["job_id"], "stage": stage["stage"], "detector": detector, **detail})
            mode = (stage["provenance"].get("device") or {}).get("mode")
            if mode:
                modes[mode] = modes.get(mode, 0) + 1
    return {
        "summary_version": 1, "created_at": time.time(), "job_count": len(manifests), "jobs": manifests,
        "totals": {
            "runtime_sec": sum(float(s.get("runtime_sec") or 0) for m in manifests for s in m["stages"]),
            "artifact_bytes_by_category": category_bytes, "device_stage_counts": modes,
            "missing_unavailable_or_fallback_detectors": missing,
        },
    }


def human_summary(summary: dict[str, Any]) -> str:
    lines = [f"Pilot summary: {summary['job_count']} job(s), {summary['totals']['runtime_sec']:.1f}s recorded stage runtime"]
    for job in summary["jobs"]:
        stages = ", ".join(f"{s['stage']}={s['outcome'] or s['stage_status']}" + (f"/{s['runtime_sec']:.1f}s" if s.get("runtime_sec") is not None else "") for s in job["stages"]) or "no recorded stages"
        lines.append(f"{job['job_id']} [{job['job_status']}]: {stages}")
    sizes = ", ".join(f"{k}={v / (1024 * 1024):.1f} MiB" for k, v in sorted(summary["totals"]["artifact_bytes_by_category"].items()))
    lines.append(f"Disk: {sizes or 'no artifacts recorded'}")
    devices = ", ".join(f"{k}={v}" for k, v in sorted(summary["totals"]["device_stage_counts"].items()))
    lines.append(f"Device stages: {devices or 'unknown'}")
    lines.append(f"Detector issues/fallbacks: {len(summary['totals']['missing_unavailable_or_fallback_detectors'])}")
    return "\n".join(lines)
