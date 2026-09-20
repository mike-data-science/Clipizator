"""Small, metadata-only catalog for creator research sources.

This deliberately uses yt-dlp's flat-playlist mode: it never downloads media
or starts analysis work.  The catalog is a separate concern from campaigns
and pipeline jobs, with optional conservative links to existing jobs.
"""

from __future__ import annotations

import json
import re
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlparse

from .jobs import queue


PLATFORM = "youtube"
LABELS = {"strong", "average", "weak", "unclassified"}
SELECTION_REASONS = {
    "creator_relative_strong", "creator_relative_average", "creator_relative_weak",
    "top_views", "manual", "editing_reference",
}
_AUTO_SELECTION_REASONS = {
    "creator_relative_strong", "creator_relative_average", "creator_relative_weak", "top_views",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS creator_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    external_creator_id TEXT,
    handle TEXT,
    display_name TEXT,
    canonical_channel_url TEXT NOT NULL,
    thumbnail_url TEXT,
    subscriber_count INTEGER,
    first_seen_at REAL NOT NULL,
    last_refreshed_at REAL NOT NULL,
    UNIQUE(platform, external_creator_id),
    UNIQUE(platform, canonical_channel_url)
);
CREATE TABLE IF NOT EXISTS creator_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    external_video_id TEXT NOT NULL,
    creator_source_id INTEGER NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT,
    published_at REAL,
    duration_sec REAL,
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    thumbnail_url TEXT,
    first_seen_at REAL NOT NULL,
    last_metadata_refresh_at REAL NOT NULL,
    download_status TEXT NOT NULL DEFAULT 'not_downloaded',
    analysis_status TEXT NOT NULL DEFAULT 'not_analyzed',
    analysis_job_id TEXT,
    derived_performance_label TEXT NOT NULL DEFAULT 'unclassified',
    performance_metric TEXT,
    manual_performance_label TEXT,
    is_reference INTEGER NOT NULL DEFAULT 0,
    is_editing_reference INTEGER NOT NULL DEFAULT 0,
    tab_origin TEXT,
    content_type TEXT,
    selected_for_analysis INTEGER NOT NULL DEFAULT 0,
    selected_at REAL,
    selection_reason TEXT,
    research_queue_item_id INTEGER,
    research_queue_status TEXT,
    UNIQUE(platform, external_video_id),
    FOREIGN KEY (creator_source_id) REFERENCES creator_sources(id)
);
CREATE INDEX IF NOT EXISTS idx_creator_videos_creator ON creator_videos(creator_source_id);
"""


class CreatorSourceError(ValueError):
    """A creator source could not be parsed or its metadata fetched."""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Small additive migration for databases created by Creator Sources v1.
    for column in (
        "tab_origin TEXT", "content_type TEXT",
        "selected_for_analysis INTEGER NOT NULL DEFAULT 0", "selected_at REAL", "selection_reason TEXT",
        "research_queue_item_id INTEGER", "research_queue_status TEXT",
    ):
        try:
            conn.execute(f"ALTER TABLE creator_videos ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass


def normalize_youtube_creator(value: str) -> dict[str, str | None]:
    """Normalize supported channel forms without pretending video URLs are channels."""
    raw = value.strip()
    if not raw:
        raise CreatorSourceError("Enter a YouTube @handle or channel URL.")
    if raw.startswith("@"):
        handle = raw[1:].strip().lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9._-]{3,}", handle):
            raise CreatorSourceError("That YouTube handle is not valid.")
        return {"handle": handle, "canonical_channel_url": f"https://www.youtube.com/@{handle}", "fetch_url": f"https://www.youtube.com/@{handle}/videos"}
    candidate = raw if re.match(r"https?://", raw, re.I) else f"https://{raw}"
    parsed = urlparse(candidate)
    host = (parsed.hostname or "").lower()
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        raise CreatorSourceError("Only a YouTube @handle or channel URL is supported right now.")
    path = parsed.path.rstrip("/")
    if re.match(r"^/(watch|shorts|embed|playlist)(/|$)", path, re.I):
        raise CreatorSourceError("Enter a creator/channel URL, not an individual video URL.")
    match = re.match(r"^/@([A-Za-z0-9._-]{3,})", path)
    if match:
        handle = match.group(1)
        return {"handle": handle, "canonical_channel_url": f"https://www.youtube.com/@{handle}", "fetch_url": f"https://www.youtube.com/@{handle}/videos"}
    match = re.match(r"^/(channel/(UC[A-Za-z0-9_-]+)|c/[^/]+|user/[^/]+)", path, re.I)
    if not match:
        raise CreatorSourceError("Use a YouTube @handle, /channel/, /c/, or /user/ URL.")
    channel_path = match.group(1)
    return {"handle": None, "canonical_channel_url": f"https://www.youtube.com/{channel_path}", "fetch_url": f"https://www.youtube.com/{channel_path}/videos"}


def _timestamp(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and re.fullmatch(r"\d{8}", value):
        try:
            return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None
    return None


def _integer(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None


def _metadata(url: str, progress: Callable[[float, str], None]) -> dict[str, Any]:
    """Fetch channel and flat playlist metadata only; no media bytes are requested."""
    from .ingest.ytdlp import _run, _with_self_update_retry, ensure_ytdlp

    binary = ensure_ytdlp(progress)

    def run() -> str:
        return _run(binary, ["-J", "--flat-playlist", "--no-warnings", url])

    try:
        return json.loads(_with_self_update_retry(binary, progress, run))
    except Exception as err:  # ytdlp has its own user-facing errors; retain their message.
        raise CreatorSourceError(str(err)) from err


def _tab_urls(parsed: dict[str, str | None]) -> dict[str, str]:
    """Use independent YouTube tabs; some Shorts creators have no /videos tab."""
    base = str(parsed["canonical_channel_url"]).rstrip("/")
    return {"videos": f"{base}/videos", "shorts": f"{base}/shorts"}


def _is_missing_tab_error(error: CreatorSourceError, tab: str) -> bool:
    message = str(error).casefold()
    return bool(re.search(rf"(?:does not have|no|missing).{{0,24}}{tab}.{{0,12}}tab|{tab}.{{0,12}}tab.{{0,24}}(?:not available|unavailable)", message))


def _fetch_tabs(
    parsed: dict[str, str | None],
    fetcher: Callable[[str, Callable[[float, str], None]], dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """Fetch every available catalog tab, treating an absent tab as normal."""
    available: list[tuple[str, dict[str, Any]]] = []
    failures: list[CreatorSourceError] = []
    for tab, url in _tab_urls(parsed).items():
        try:
            raw = fetcher(url, lambda *_: None)
        except CreatorSourceError as err:
            if _is_missing_tab_error(err, tab):
                continue
            failures.append(err)
            continue
        available.append((tab, raw))
    if available:
        return available
    if failures:
        raise failures[0]
    raise CreatorSourceError("This channel has neither an available Videos tab nor an available Shorts tab.")


def _creator_payload(parsed: dict[str, str | None], raw: dict[str, Any]) -> dict[str, Any]:
    external_id = raw.get("channel_id") or raw.get("uploader_id")
    if not isinstance(external_id, str) or not external_id:
        external_id = None
    handle = raw.get("uploader_id") or raw.get("channel_handle") or parsed["handle"]
    if isinstance(handle, str):
        handle = handle.lstrip("@") or None
    canonical = raw.get("channel_url") or raw.get("uploader_url") or parsed["canonical_channel_url"]
    if not isinstance(canonical, str) or "youtube" not in canonical:
        canonical = parsed["canonical_channel_url"]
    canonical = canonical.rstrip("/")
    return {
        "platform": PLATFORM, "external_creator_id": external_id, "handle": handle,
        "display_name": raw.get("channel") or raw.get("uploader") or raw.get("title"),
        "canonical_channel_url": canonical, "thumbnail_url": raw.get("thumbnail"),
        "subscriber_count": _integer(raw.get("channel_follower_count") or raw.get("channel_subscriber_count")),
    }


def _video_payload(entry: dict[str, Any], tab_origin: str) -> dict[str, Any] | None:
    external_id = entry.get("id")
    if not isinstance(external_id, str) or not external_id:
        return None
    return {
        "external_video_id": external_id,
        "canonical_url": entry.get("webpage_url") or entry.get("url") or f"https://www.youtube.com/watch?v={external_id}",
        "title": entry.get("title"), "published_at": _timestamp(entry.get("timestamp") or entry.get("release_timestamp") or entry.get("upload_date")),
        "duration_sec": float(entry["duration"]) if isinstance(entry.get("duration"), (int, float)) else None,
        "views": _integer(entry.get("view_count")), "likes": _integer(entry.get("like_count")),
        "comments": _integer(entry.get("comment_count")), "thumbnail_url": entry.get("thumbnail"),
        "tab_origins": {tab_origin}, "content_type": "short" if tab_origin == "shorts" else "video",
    }


def _merge_tab_entries(tabs: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Merge tabs by stable video ID, retaining the richest metadata and origin."""
    merged: dict[str, dict[str, Any]] = {}
    for tab, raw in tabs:
        for entry in raw.get("entries") or []:
            if not isinstance(entry, dict):
                continue
            item = _video_payload(entry, tab)
            if not item:
                continue
            current = merged.get(item["external_video_id"])
            if current is None:
                merged[item["external_video_id"]] = item
                continue
            current["tab_origins"].update(item["tab_origins"])
            if sum(value is not None for key, value in item.items() if key not in {"tab_origins", "content_type"}) > sum(value is not None for key, value in current.items() if key not in {"tab_origins", "content_type"}):
                for key, value in item.items():
                    if key not in {"tab_origins", "content_type"}:
                        current[key] = value
    output = []
    for item in merged.values():
        origins = item.pop("tab_origins")
        item["tab_origin"] = ",".join(tab for tab in ("videos", "shorts") if tab in origins)
        # A Shorts-only discovery is reliable. A duplicate across tabs is not.
        item["content_type"] = "short" if origins == {"shorts"} else "video" if origins == {"videos"} else None
        output.append(item)
    return output


def _classification(rows: list[dict[str, Any]], now: float) -> dict[int, tuple[str, str | None]]:
    """Creator-relative labels, never a cross-creator quality score."""
    candidates: list[tuple[int, float, str]] = []
    for row in rows:
        views, published = row.get("views"), row.get("published_at")
        if not isinstance(views, int) or views < 0:
            continue
        if isinstance(published, (int, float)):
            age_days = max(0.0, (now - published) / 86400)
            if age_days < 7:
                continue  # Fresh uploads are too volatile for this v1 label.
            candidates.append((row["id"], views / max(1.0, age_days), "views_per_day"))
        else:
            candidates.append((row["id"], float(views), "views"))
    if len(candidates) < 5:
        return {row["id"]: ("unclassified", None) for row in rows}
    baseline = statistics.median(value for _, value, _ in candidates)
    result = {row["id"]: ("unclassified", None) for row in rows}
    for video_id, value, metric in candidates:
        label = "strong" if value >= baseline * 1.75 else "weak" if value <= baseline * 0.55 else "average"
        result[video_id] = (label, metric)
    return result


def _existing_job_for_video(conn: sqlite3.Connection, video_id: str) -> tuple[str | None, str | None]:
    """Link only URLs that yield an exact YouTube video id; do not guess."""
    pattern = re.compile(r"(?:youtu\.be/|[?&]v=|/shorts/|/embed/)([A-Za-z0-9_-]{6,})", re.I)
    for row in conn.execute("SELECT id, source, status FROM jobs WHERE source_type='url'").fetchall():
        match = pattern.search(str(row["source"]))
        if match and match.group(1) == video_id:
            return row["id"], str(row["status"])
    return None, None


def _upsert_creator(conn: sqlite3.Connection, item: dict[str, Any], now: float) -> int:
    existing = None
    if item["external_creator_id"]:
        existing = conn.execute("SELECT id FROM creator_sources WHERE platform=? AND external_creator_id=?", (PLATFORM, item["external_creator_id"])).fetchone()
    if not existing:
        existing = conn.execute("SELECT id FROM creator_sources WHERE platform=? AND canonical_channel_url=?", (PLATFORM, item["canonical_channel_url"])).fetchone()
    if not existing and item["handle"]:
        existing = conn.execute("SELECT id FROM creator_sources WHERE platform=? AND lower(handle)=lower(?)", (PLATFORM, item["handle"])).fetchone()
    if existing:
        creator_id = int(existing["id"])
        conn.execute(
            "UPDATE creator_sources SET external_creator_id=COALESCE(?,external_creator_id),handle=?,display_name=?,canonical_channel_url=?,thumbnail_url=?,subscriber_count=?,last_refreshed_at=? WHERE id=?",
            (item["external_creator_id"], item["handle"], item["display_name"], item["canonical_channel_url"], item["thumbnail_url"], item["subscriber_count"], now, creator_id),
        )
        return creator_id
    cursor = conn.execute(
        "INSERT INTO creator_sources(platform,external_creator_id,handle,display_name,canonical_channel_url,thumbnail_url,subscriber_count,first_seen_at,last_refreshed_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (PLATFORM, item["external_creator_id"], item["handle"], item["display_name"], item["canonical_channel_url"], item["thumbnail_url"], item["subscriber_count"], now, now),
    )
    return int(cursor.lastrowid)


def refresh_creator(source: str, fetcher: Callable[[str, Callable[[float, str], None]], dict[str, Any]] = _metadata) -> dict[str, Any]:
    parsed = normalize_youtube_creator(source)
    tabs = _fetch_tabs(parsed, fetcher)
    raw = tabs[0][1]
    now = time.time()
    creator_data = _creator_payload(parsed, raw)
    entries = _merge_tab_entries(tabs)
    with queue._connect() as conn:
        ensure_schema(conn)
        creator_id = _upsert_creator(conn, creator_data, now)
        for item in entries:
            job_id, job_status = _existing_job_for_video(conn, item["external_video_id"])
            conn.execute(
                "INSERT INTO creator_videos(platform,external_video_id,creator_source_id,canonical_url,title,published_at,duration_sec,views,likes,comments,thumbnail_url,first_seen_at,last_metadata_refresh_at,analysis_job_id,analysis_status,tab_origin,content_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(platform,external_video_id) DO UPDATE SET creator_source_id=excluded.creator_source_id,canonical_url=excluded.canonical_url,title=excluded.title,published_at=excluded.published_at,duration_sec=excluded.duration_sec,views=excluded.views,likes=excluded.likes,comments=excluded.comments,thumbnail_url=excluded.thumbnail_url,last_metadata_refresh_at=excluded.last_metadata_refresh_at,tab_origin=excluded.tab_origin,content_type=excluded.content_type,analysis_job_id=COALESCE(creator_videos.analysis_job_id,excluded.analysis_job_id),analysis_status=CASE WHEN creator_videos.analysis_job_id IS NOT NULL THEN creator_videos.analysis_status ELSE excluded.analysis_status END",
                (PLATFORM, item["external_video_id"], creator_id, item["canonical_url"], item["title"], item["published_at"], item["duration_sec"], item["views"], item["likes"], item["comments"], item["thumbnail_url"], now, now, job_id, "analyzed" if job_status == "done" else "not_analyzed", item["tab_origin"], item["content_type"]),
            )
        rows = [dict(row) for row in conn.execute("SELECT * FROM creator_videos WHERE creator_source_id=?", (creator_id,)).fetchall()]
        for video_id, (label, metric) in _classification(rows, now).items():
            conn.execute("UPDATE creator_videos SET derived_performance_label=?,performance_metric=? WHERE id=?", (label, metric, video_id))
    return creator_detail(creator_id) or {}


def list_creators() -> list[dict[str, Any]]:
    with queue._connect() as conn:
        ensure_schema(conn)
        rows = conn.execute("SELECT c.*,COUNT(v.id) AS video_count FROM creator_sources c LEFT JOIN creator_videos v ON v.creator_source_id=c.id GROUP BY c.id ORDER BY c.last_refreshed_at DESC").fetchall()
    return [_creator_view(dict(row), include_videos=False) for row in rows]


def _video_view(row: dict[str, Any]) -> dict[str, Any]:
    derived = row.get("derived_performance_label") or "unclassified"
    manual = row.get("manual_performance_label")
    return {**row, "performance_label": manual or derived, "manual_performance_label": manual, "derived_performance_label": derived, "is_reference": bool(row.get("is_reference")), "is_editing_reference": bool(row.get("is_editing_reference")), "selected_for_analysis": bool(row.get("selected_for_analysis"))}


def _creator_view(row: dict[str, Any], include_videos: bool) -> dict[str, Any]:
    result = {key: row.get(key) for key in ("id", "platform", "external_creator_id", "handle", "display_name", "canonical_channel_url", "thumbnail_url", "subscriber_count", "first_seen_at", "last_refreshed_at", "video_count")}
    if include_videos:
        result["videos"] = [_video_view(video) for video in row["videos"]]
        result["selection_summary"] = _selection_summary(row["videos"])
    return result


def creator_detail(creator_id: int) -> dict[str, Any] | None:
    with queue._connect() as conn:
        ensure_schema(conn)
        creator = conn.execute("SELECT * FROM creator_sources WHERE id=?", (creator_id,)).fetchone()
        if not creator:
            return None
        videos = [dict(row) for row in conn.execute("SELECT * FROM creator_videos WHERE creator_source_id=? ORDER BY views DESC NULLS LAST, published_at DESC", (creator_id,)).fetchall()]
    item = dict(creator)
    item["videos"] = videos
    return _creator_view(item, include_videos=True)


def _selection_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"selected": 0, "strong": 0, "average": 0, "weak": 0, "manual_reference": 0}
    for row in rows:
        if not row.get("selected_for_analysis"):
            continue
        summary["selected"] += 1
        reason = row.get("selection_reason")
        if reason == "creator_relative_strong":
            summary["strong"] += 1
        elif reason == "creator_relative_average":
            summary["average"] += 1
        elif reason == "creator_relative_weak":
            summary["weak"] += 1
        else:
            summary["manual_reference"] += 1
    return summary


def set_selection(creator_id: int, video_ids: list[int], selected: bool, reason: str | None = None) -> dict[str, Any] | None:
    """Persist a manual/bulk selection only; this never schedules work."""
    if selected and reason not in SELECTION_REASONS:
        raise CreatorSourceError("A valid selection reason is required.")
    with queue._connect() as conn:
        ensure_schema(conn)
        if not conn.execute("SELECT 1 FROM creator_sources WHERE id=?", (creator_id,)).fetchone():
            return None
        ids = sorted({int(video_id) for video_id in video_ids})
        if ids:
            placeholders = ",".join("?" for _ in ids)
            if selected:
                conn.execute(
                    f"UPDATE creator_videos SET selected_for_analysis=1,selected_at=?,selection_reason=? WHERE creator_source_id=? AND id IN ({placeholders})",
                    (time.time(), reason, creator_id, *ids),
                )
            else:
                conn.execute(
                    f"UPDATE creator_videos SET selected_for_analysis=0,selected_at=NULL,selection_reason=NULL WHERE creator_source_id=? AND id IN ({placeholders})",
                    (creator_id, *ids),
                )
    return creator_detail(creator_id)


def clear_selection(creator_id: int) -> dict[str, Any] | None:
    with queue._connect() as conn:
        ensure_schema(conn)
        if not conn.execute("SELECT 1 FROM creator_sources WHERE id=?", (creator_id,)).fetchone():
            return None
        conn.execute("UPDATE creator_videos SET selected_for_analysis=0,selected_at=NULL,selection_reason=NULL WHERE creator_source_id=?", (creator_id,))
    return creator_detail(creator_id)


def auto_select_sample(creator_id: int) -> dict[str, Any] | None:
    """Fill a small creator-relative sample, preserving manual selections."""
    targets = (("strong", 5), ("average", 3), ("weak", 3))
    with queue._connect() as conn:
        ensure_schema(conn)
        if not conn.execute("SELECT 1 FROM creator_sources WHERE id=?", (creator_id,)).fetchone():
            return None
        # A repeatable auto-select replaces its own choices but never manual or
        # editing-reference selections, and never changes the reference flags.
        reasons = ",".join("?" for _ in _AUTO_SELECTION_REASONS)
        conn.execute(
            f"UPDATE creator_videos SET selected_for_analysis=0,selected_at=NULL,selection_reason=NULL WHERE creator_source_id=? AND selection_reason IN ({reasons})",
            (creator_id, *_AUTO_SELECTION_REASONS),
        )
        rows = [dict(row) for row in conn.execute("SELECT * FROM creator_videos WHERE creator_source_id=?", (creator_id,)).fetchall()]
        selected_ids = {row["id"] for row in rows if row.get("selected_for_analysis")}
        for label, target in targets:
            group = [row for row in rows if (row.get("manual_performance_label") or row.get("derived_performance_label") or "unclassified") == label]
            already_selected = sum(row["id"] in selected_ids for row in group)
            needed = max(0, target - already_selected)
            ranked = sorted((row for row in group if row["id"] not in selected_ids), key=lambda row: row.get("views") or 0, reverse=True)
            picked = ranked[:needed]
            if picked:
                now = time.time()
                conn.executemany(
                    "UPDATE creator_videos SET selected_for_analysis=1,selected_at=?,selection_reason=? WHERE id=?",
                    [(now, f"creator_relative_{label}", row["id"]) for row in picked],
                )
                selected_ids.update(row["id"] for row in picked)
    return creator_detail(creator_id)


def set_manual_label(video_id: int, label: str | None) -> dict[str, Any] | None:
    normalized = label if label in LABELS and label != "unclassified" else None
    with queue._connect() as conn:
        ensure_schema(conn)
        conn.execute("UPDATE creator_videos SET manual_performance_label=? WHERE id=?", (normalized, video_id))
        row = conn.execute("SELECT * FROM creator_videos WHERE id=?", (video_id,)).fetchone()
    return _video_view(dict(row)) if row else None


def set_references(video_id: int, reference: bool | None = None, editing_reference: bool | None = None) -> dict[str, Any] | None:
    with queue._connect() as conn:
        ensure_schema(conn)
        if reference is not None:
            conn.execute("UPDATE creator_videos SET is_reference=? WHERE id=?", (int(reference), video_id))
        if editing_reference is not None:
            conn.execute("UPDATE creator_videos SET is_editing_reference=? WHERE id=?", (int(editing_reference), video_id))
        row = conn.execute("SELECT * FROM creator_videos WHERE id=?", (video_id,)).fetchone()
    return _video_view(dict(row)) if row else None
