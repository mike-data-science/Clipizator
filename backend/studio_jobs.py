"""Fast, local-only lifecycle summaries for normal Studio projects."""

import json
import re
import hashlib
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


# This is the normal clipping plan in backend.server._stages().  Keep the
# progress representation next to the lifecycle derivation so every UI gets
# the same complete, ordered pipeline rather than maintaining its own subset.
PIPELINE_STAGES = (
    ("ingest", "Ingest"),
    ("asr", "ASR / Transcription"),
    ("diarize", "Diarization"),
    ("events", "Audio / Events"),
    ("source_analysis", "Source analysis"),
    ("candidates", "Finding moments"),
    ("semantic_compression", "Refining moments"),
    ("safe_edit_execution", "Preparing edits"),
    ("score", "Scoring"),
    ("camera", "Camera / Editing"),
    ("render", "Rendering"),
)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _title(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or value.lower() in {"media", "video", "clip", "watch", "playlist"}:
        return None
    if re.search(r"https?://|(?:youtube(?:-nocookie)?\.com|youtu\.be)|watch\?|[?&]v=", value, re.I):
        return None
    return value


def _stage_data(path: Path) -> dict:
    data = _read_json(path).get("data")
    return data if isinstance(data, dict) else {}


def _has_clip(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _provenance(job) -> dict:
    try:
        value = json.loads(getattr(job, "source_provenance_json", None) or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _info_metadata(job) -> dict:
    for path in [job.dir / "media.info.json", *job.dir.glob("media*.info.json"), job.dir / "media.json"]:
        data = _read_json(path)
        if data:
            return data.get("data", data) if isinstance(data.get("data", data), dict) else {}
    return {}


def _youtube_id(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(?:youtu\.be/|youtube(?:-nocookie)?\.com/(?:watch\?v=|shorts/|embed/))([A-Za-z0-9_-]{6,})", value)
    return match.group(1) if match else None


def _canonical_url(value: str | None) -> str | None:
    if not value or not value.startswith(("http://", "https://")):
        return None
    if video_id := _youtube_id(value):
        return f"https://www.youtube.com/watch?v={video_id}"
    parts = urlsplit(value)
    query = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True) if not key.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def _source_identity(job) -> tuple[str, str] | None:
    provenance = _provenance(job)
    metadata = _info_metadata(job)
    external_id = provenance.get("external_video_id") or metadata.get("id") or _youtube_id(provenance.get("canonical_url"))
    if isinstance(external_id, str) and external_id:
        original = provenance.get("canonical_url") or provenance.get("original_source_url") or metadata.get("webpage_url")
        platform = provenance.get("platform") or ("youtube" if _youtube_id(original if isinstance(original, str) else None) else "unknown")
        return "external_video_id", f"{platform}:{external_id}"
    original = provenance.get("canonical_url") or provenance.get("original_source_url") or provenance.get("source_url") or metadata.get("webpage_url") or metadata.get("original_url") or job.source
    if canonical := _canonical_url(original if isinstance(original, str) else None):
        return "canonical_url", canonical
    source_hash = provenance.get("source_hash")
    if not isinstance(source_hash, str) or not source_hash:
        source_hash = hashlib.sha256(str(original).encode("utf-8")).hexdigest() if original else None
    return ("source_hash", source_hash) if source_hash else None


def _thumbnail(job, provenance: dict, metadata: dict, source: str) -> str | None:
    catalog = provenance.get("catalog_metadata") if isinstance(provenance.get("catalog_metadata"), dict) else {}
    for value in (provenance.get("thumbnail_url"), provenance.get("thumbnail"), catalog.get("thumbnail_url"), catalog.get("thumbnail")):
        if isinstance(value, str) and value:
            return value
    if video_id := provenance.get("external_video_id") or _youtube_id(source):
        if isinstance(video_id, str) and video_id:
            return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    for value in (metadata.get("thumbnail_url"), metadata.get("thumbnail")):
        if isinstance(value, str) and value:
            return value
    thumbnails = metadata.get("thumbnails")
    if isinstance(thumbnails, list):
        for value in reversed(thumbnails):
            if isinstance(value, dict) and isinstance(value.get("url"), str):
                return value["url"]
    return None


def _local_title(job, campaign_titles: dict[str, str]) -> str:
    ingest = _stage_data(job.dir / "ingest.json")
    for candidate in (job.title, ingest.get("title"), campaign_titles.get(job.id)):
        if title := _title(candidate):
            return title
    for path in sorted(job.dir.glob("*.info.json")):
        metadata = _read_json(path)
        for key in ("title", "fulltitle"):
            if title := _title(metadata.get(key)):
                return title
    # Never turn a URL into a filename such as "watch?v=...".
    if job.source_type == "file":
        if title := _title(Path(job.source.replace("\\", "/")).stem):
            return title
    return f"Clipped video · {job.id}"


def _effective_status(job, stage_runs: list[dict], clip_count: int) -> str:
    """Infer terminal status for legacy renders without overriding live work."""
    active_statuses = {"waiting_for_worker", "downloading", "uploading", "running"}
    if job.status in active_statuses or job.status == "failed":
        return job.status
    if any(row.get("status") == "failed" for row in stage_runs):
        return "failed"
    if any(row.get("status") == "running" for row in stage_runs):
        return "running"
    return "done" if clip_count else job.status


def _lifecycle(job, status: str, stage_runs: list[dict]) -> tuple[str | None, list[str]]:
    pipeline_stages = tuple(stage_id for stage_id, _ in PIPELINE_STAGES)
    completed = {row["stage"] for row in stage_runs if row.get("status") == "done"}
    completed.update(stage for stage in pipeline_stages if (job.dir / f"{stage}.json").is_file())
    if status in {"waiting_for_worker", "downloading", "uploading"}:
        return ({
            "waiting_for_worker": "worker_queued",
            "downloading": "downloading",
            "uploading": "uploading",
        }[status], sorted(completed))
    failed = next((row["stage"] for row in stage_runs if row.get("status") == "failed"), None)
    if status == "failed":
        return failed, sorted(completed)
    active = next((row["stage"] for row in stage_runs if row.get("status") == "running"), None)
    if active:
        return active, sorted(completed)
    if failed:
        return failed, sorted(completed)
    return ("complete" if status == "done" else None, sorted(completed))


def list_project_jobs(
    jobs,
    campaign_titles: dict[str, str] | None = None,
    stage_runs_by_job: dict[str, list[dict]] | None = None,
) -> list[dict]:
    summaries = []
    for job in jobs:
        if getattr(job, "job_mode", "clipping") == "research":
            continue
        provenance = _provenance(job)
        metadata = _info_metadata(job)
        render = _stage_data(job.dir / "render.json")
        ingest = _stage_data(job.dir / "ingest.json")
        outputs = render.get("outputs") or []
        if not isinstance(outputs, list):
            outputs = []
        clip_count = 0
        for output in outputs:
            if not isinstance(output, dict) or not isinstance(output.get("path"), str):
                continue
            path = Path(output["path"].replace("\\", "/"))
            candidates = [path if path.is_absolute() else job.dir / path, job.dir / "clips" / path.name]
            if any(_has_clip(p) for p in candidates):
                clip_count += 1
        source = provenance.get("canonical_url") or provenance.get("original_source_url") or provenance.get("source_url") or job.source or ""
        duration_sec = ((ingest.get("probe") or {}).get("duration_sec") if isinstance(ingest.get("probe"), dict) else None)
        stage_runs = (stage_runs_by_job or {}).get(job.id, [])
        status = _effective_status(job, stage_runs, clip_count)
        current_stage, completed_stages = _lifecycle(job, status, stage_runs)
        thumbnail_url = _thumbnail(job, provenance, metadata, source)
        summaries.append({
            "id": job.id,
            "title": _local_title(job, campaign_titles or {}),
            "ingested": (job.dir / "ingest.json").is_file(),
            "rendered": bool(clip_count),
            "completed": status == "done",
            "clip_count": clip_count,
            "duration_sec": duration_sec,
            "thumbnail_url": thumbnail_url,
            "source": source,
            "status": status,
            "current_stage": current_stage,
            "stage_progress": 1.0 if status == "done" else None,
            "completed_stages": completed_stages,
            "pipeline_stages": [{"id": stage_id, "label": label} for stage_id, label in PIPELINE_STAGES],
            "error": job.error,
            "created_at": job.created_at,
        })
    return sorted(summaries, key=lambda item: item["id"], reverse=True)


def duplicate_groups(jobs, summaries: dict[str, dict]) -> dict[str, dict]:
    """Review-only duplicate grouping; titles are deliberately never identities."""
    groups: dict[tuple[str, str], list] = {}
    for job in jobs:
        if getattr(job, "job_mode", "clipping") == "research":
            continue
        if identity := _source_identity(job):
            groups.setdefault(identity, []).append(job)
    result: dict[str, dict] = {}
    for identity, members in groups.items():
        if len(members) < 2:
            continue
        def rank(job):
            summary = summaries.get(job.id, {})
            artifacts = sum((job.dir / f"{stage}.json").is_file() for stage, _ in PIPELINE_STAGES)
            return (bool(summary.get("completed")), bool(summary.get("rendered")), artifacts, job.created_at)
        preferred = max(members, key=rank)
        member_ids = sorted((job.id for job in members), reverse=True)
        for job in members:
            result[job.id] = {"identity_type": identity[0], "preferred_job_id": preferred.id, "job_ids": member_ids}
    return result


# Compatibility for callers that used the old helper name. It now returns all
# normal project lifecycles rather than filtering to rendered clips.
list_rendered_jobs = list_project_jobs
