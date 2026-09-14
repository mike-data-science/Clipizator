"""Fast, local-only summaries of videos with rendered clips for Studio."""

import json
import re
from pathlib import Path


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


def list_rendered_jobs(jobs, campaign_titles: dict[str, str] | None = None) -> list[dict]:
    summaries = []
    for job in jobs:
        render = _stage_data(job.dir / "render.json")
        ingest = _stage_data(job.dir / "ingest.json")
        outputs = render.get("outputs") or []
        if not isinstance(outputs, list):
            continue
        clip_count = 0
        for output in outputs:
            if not isinstance(output, dict) or not isinstance(output.get("path"), str):
                continue
            path = Path(output["path"].replace("\\", "/"))
            candidates = [path if path.is_absolute() else job.dir / path, job.dir / "clips" / path.name]
            if any(_has_clip(p) for p in candidates):
                clip_count += 1
        if not clip_count:
            continue
        source = job.source or ""
        duration_sec = ((ingest.get("probe") or {}).get("duration_sec") if isinstance(ingest.get("probe"), dict) else None)
        thumbnail_url = None
        match = re.search(r"(?:youtu\.be/|youtube(?:-nocookie)?\.com/(?:watch\?v=|shorts/|embed/))([A-Za-z0-9_-]{6,})", source)
        if match:
            thumbnail_url = f"https://i.ytimg.com/vi/{match.group(1)}/hqdefault.jpg"
        summaries.append({
            "id": job.id,
            "title": _local_title(job, campaign_titles or {}),
            "ingested": (job.dir / "ingest.json").is_file(),
            "rendered": True,
            "clip_count": clip_count,
            "duration_sec": duration_sec,
            "thumbnail_url": thumbnail_url,
            "source": source,
        })
    return sorted(summaries, key=lambda item: item["id"], reverse=True)
