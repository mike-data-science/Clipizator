"""Durable, sequential hand-off from creator catalogs to the laptop worker."""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any

from . import config, creator_sources
from .jobs import queue


ACTIVE_STATES = ("queued", "claimed_by_worker", "downloading", "uploading", "uploaded", "waiting_for_analysis", "analyzing")
ALL_STATES = (*ACTIVE_STATES, "completed", "failed", "cancelled")
WORKER_STATES = {"downloading", "uploading", "failed"}
CLAIM_LEASE_SEC = 60 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_queue_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_video_id INTEGER NOT NULL,
    creator_source_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    external_video_id TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    catalog_title TEXT,
    creator_handle TEXT,
    creator_display_name TEXT,
    source_metadata_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at REAL NOT NULL,
    started_at REAL,
    completed_at REAL,
    updated_at REAL NOT NULL,
    failure_reason TEXT,
    job_id TEXT,
    claim_token TEXT,
    claimed_by TEXT,
    claim_expires_at REAL,
    analysis_token TEXT,
    analysis_pid INTEGER,
    FOREIGN KEY (creator_video_id) REFERENCES creator_videos(id),
    FOREIGN KEY (creator_source_id) REFERENCES creator_sources(id),
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_research_queue_status ON research_queue_items(status, created_at);
CREATE INDEX IF NOT EXISTS idx_research_queue_video ON research_queue_items(creator_video_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_research_queue_active_video
ON research_queue_items(creator_video_id)
WHERE status IN ('queued','claimed_by_worker','downloading','uploading','uploaded','waiting_for_analysis','analyzing');
"""


class ResearchQueueError(ValueError):
    pass


def ensure_schema(conn: sqlite3.Connection) -> None:
    creator_sources.ensure_schema(conn)
    conn.executescript(SCHEMA)
    for column in ("analysis_token TEXT", "analysis_pid INTEGER"):
        try:
            conn.execute(f"ALTER TABLE research_queue_items ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass
    # SQLite cannot alter a partial-index predicate. Recreate only when upgrading
    # an older queue so waiting rows retain the same active-item dedupe guarantee.
    index = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_research_queue_active_video'"
    ).fetchone()
    if index and "waiting_for_analysis" not in str(index["sql"] or ""):
        conn.execute("DROP INDEX idx_research_queue_active_video")
        conn.execute(
            "CREATE UNIQUE INDEX idx_research_queue_active_video ON research_queue_items(creator_video_id) "
            "WHERE status IN ('queued','claimed_by_worker','downloading','uploading','uploaded','waiting_for_analysis','analyzing')"
        )
    # Rows created before pipeline modes existed are unambiguously research jobs
    # because they are linked from this table; do not infer from UI or filenames.
    conn.execute(
        "UPDATE jobs SET job_mode='research' WHERE id IN "
        "(SELECT job_id FROM research_queue_items WHERE job_id IS NOT NULL) "
        "AND COALESCE(job_mode, 'clipping')!='research'"
    )
    # Callers that need an atomic claim begin their transaction after schema
    # migration/backfill; do not leave SQLite in an implicit write transaction.
    conn.commit()


def _provenance(row: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        key: row.get(key)
        for key in (
            "title", "published_at", "duration_sec", "views", "likes", "comments", "thumbnail_url",
            "content_type", "tab_origin", "derived_performance_label", "manual_performance_label", "performance_metric",
        )
    }
    return {
        "platform": row["platform"],
        "external_video_id": row["external_video_id"],
        "canonical_url": row["canonical_url"],
        "creator_source_id": row["creator_source_id"],
        "creator_video_id": row["id"],
        "creator": {"handle": row.get("creator_handle"), "display_name": row.get("creator_display_name")},
        "catalog_title": row.get("title"),
        "catalog_metadata": metadata,
        "origin": "creator_research_queue",
    }


def queue_selected(creator_id: int) -> dict[str, Any]:
    """Queue only selected rows, preserving active/completed dedupe."""
    with queue._connect() as conn:
        ensure_schema(conn)
        creator = conn.execute("SELECT * FROM creator_sources WHERE id=?", (creator_id,)).fetchone()
        if not creator:
            raise ResearchQueueError("Creator source not found.")
        selected = [dict(row) for row in conn.execute(
            "SELECT v.*,c.handle AS creator_handle,c.display_name AS creator_display_name "
            "FROM creator_videos v JOIN creator_sources c ON c.id=v.creator_source_id "
            "WHERE v.creator_source_id=? AND v.selected_for_analysis=1 ORDER BY v.views DESC NULLS LAST,v.id",
            (creator_id,),
        ).fetchall()]

    result: dict[str, Any] = {
        "queued_count": 0,
        "skipped_already_queued": 0,
        "skipped_already_analyzed": 0,
        "errors": [],
        "queue_item_ids": [],
    }
    for video in selected:
        with queue._connect() as conn:
            ensure_schema(conn)
            active = conn.execute(
                f"SELECT id FROM research_queue_items WHERE creator_video_id=? AND status IN ({','.join('?' for _ in ACTIVE_STATES)}) LIMIT 1",
                (video["id"], *ACTIVE_STATES),
            ).fetchone()
            linked_job = conn.execute("SELECT status FROM jobs WHERE id=?", (video["analysis_job_id"],)).fetchone() if video.get("analysis_job_id") else None
            completed = conn.execute(
                "SELECT id FROM research_queue_items WHERE creator_video_id=? AND status='completed' LIMIT 1",
                (video["id"],),
            ).fetchone()
            failed = conn.execute(
                "SELECT id FROM research_queue_items WHERE creator_video_id=? AND status='failed' ORDER BY created_at DESC LIMIT 1",
                (video["id"],),
            ).fetchone()
        if active:
            result["skipped_already_queued"] += 1
            continue
        if completed or (linked_job and linked_job["status"] == "done"):
            result["skipped_already_analyzed"] += 1
            continue
        if failed:
            result["errors"].append({"creator_video_id": video["id"], "error": "A failed queue item already exists; retry it from Research Queue."})
            continue

        provenance = _provenance(video)
        try:
            job = queue.create_job(
                "url", video["canonical_url"], json.dumps(config.Settings().to_json()),
                title=video.get("title"), source_provenance=provenance, job_mode="research",
            )
            now = time.time()
            with queue._connect() as conn:
                ensure_schema(conn)
                cursor = conn.execute(
                    "INSERT INTO research_queue_items(creator_video_id,creator_source_id,platform,external_video_id,canonical_url,catalog_title,creator_handle,creator_display_name,source_metadata_json,status,created_at,updated_at,job_id) "
                    "VALUES (?,?,?,?,?,?,?,?,?,'queued',?,?,?)",
                    (video["id"], creator_id, video["platform"], video["external_video_id"], video["canonical_url"],
                     video.get("title"), video.get("creator_handle"), video.get("creator_display_name"),
                     json.dumps(provenance["catalog_metadata"], ensure_ascii=False), now, now, job.id),
                )
                item_id = int(cursor.lastrowid)
                conn.execute(
                    "UPDATE creator_videos SET research_queue_item_id=?,research_queue_status='queued',analysis_job_id=?,analysis_status='queued' WHERE id=?",
                    (item_id, job.id, video["id"]),
                )
            result["queued_count"] += 1
            result["queue_item_ids"].append(item_id)
        except sqlite3.IntegrityError:
            result["skipped_already_queued"] += 1
        except Exception as err:  # keep one bad row from losing the rest of a small batch
            result["errors"].append({"creator_video_id": video["id"], "error": str(err)})
    return result


def _item_view(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.pop("source_metadata_json", None)
    try:
        row["source_metadata"] = json.loads(metadata or "{}")
    except (TypeError, ValueError):
        row["source_metadata"] = {}
    row.pop("claim_token", None)
    row.pop("analysis_token", None)
    row.pop("analysis_pid", None)
    return row


def list_items(limit: int = 200) -> list[dict[str, Any]]:
    with queue._connect() as conn:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT r.*,j.status AS analysis_status,j.error AS analysis_error,"
            "(SELECT s.stage FROM stage_runs s WHERE s.job_id=r.job_id AND s.status='running' ORDER BY s.started_at DESC LIMIT 1) AS progress_stage "
            "FROM research_queue_items r LEFT JOIN jobs j ON j.id=r.job_id ORDER BY r.created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_item_view(dict(row)) for row in rows]


def claim_next(worker_id: str | None = None) -> dict[str, Any] | None:
    now = time.time()
    token = uuid.uuid4().hex
    with queue._connect() as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE research_queue_items SET status='queued',claim_token=NULL,claimed_by=NULL,claim_expires_at=NULL,updated_at=? "
            "WHERE status IN ('claimed_by_worker','downloading','uploading') AND claim_expires_at IS NOT NULL AND claim_expires_at<?",
            (now, now),
        )
        row = conn.execute("SELECT * FROM research_queue_items WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
        if not row:
            return None
        changed = conn.execute(
            "UPDATE research_queue_items SET status='claimed_by_worker',started_at=COALESCE(started_at,?),updated_at=?,claim_token=?,claimed_by=?,claim_expires_at=? WHERE id=? AND status='queued'",
            (now, now, token, worker_id, now + CLAIM_LEASE_SEC, row["id"]),
        ).rowcount
        if changed != 1:
            return None
        conn.execute(
            "UPDATE creator_videos SET research_queue_status='claimed_by_worker',download_status='queued' WHERE id=?",
            (row["creator_video_id"],),
        )
        claimed = dict(conn.execute("SELECT * FROM research_queue_items WHERE id=?", (row["id"],)).fetchone())
    return {
        "type": "research_queue", "queue_item_id": claimed["id"], "job_id": claimed["job_id"],
        "url": claimed["canonical_url"], "title": claimed["catalog_title"], "platform": claimed["platform"],
        "external_video_id": claimed["external_video_id"], "creator_id": claimed["creator_source_id"],
        "creator_video_id": claimed["creator_video_id"], "claim_token": token,
    }


def _owned_item(conn: sqlite3.Connection, item_id: int, claim_token: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM research_queue_items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise ResearchQueueError("Research queue item not found.")
    if not claim_token or row["claim_token"] != claim_token:
        raise ResearchQueueError("Research queue claim is no longer valid.")
    return row


def claimed_item(item_id: int, claim_token: str) -> dict[str, Any]:
    with queue._connect() as conn:
        ensure_schema(conn)
        return dict(_owned_item(conn, item_id, claim_token))


def report_worker_status(item_id: int, claim_token: str, status: str, error: str | None = None) -> dict[str, Any]:
    if status not in WORKER_STATES:
        raise ResearchQueueError("Worker status must be downloading, uploading, or failed.")
    now = time.time()
    with queue._connect() as conn:
        ensure_schema(conn)
        row = _owned_item(conn, item_id, claim_token)
        allowed_from = {
            "downloading": {"claimed_by_worker", "downloading"},
            "uploading": {"claimed_by_worker", "downloading", "uploading"},
            "failed": {"claimed_by_worker", "downloading", "uploading"},
        }
        if row["status"] not in allowed_from[status]:
            raise ResearchQueueError(f"Cannot move a {row['status']} item to {status}.")
        completed_at = now if status == "failed" else None
        conn.execute(
            "UPDATE research_queue_items SET status=?,updated_at=?,completed_at=?,failure_reason=?,claim_expires_at=? WHERE id=?",
            (status, now, completed_at, error if status == "failed" else None,
             None if status == "failed" else now + CLAIM_LEASE_SEC, item_id),
        )
        download_status = "failed" if status == "failed" else status
        conn.execute(
            "UPDATE creator_videos SET research_queue_status=?,download_status=?,analysis_status=CASE WHEN ?='failed' THEN 'failed' ELSE analysis_status END WHERE id=?",
            (status, download_status, status, row["creator_video_id"]),
        )
        updated = dict(conn.execute("SELECT * FROM research_queue_items WHERE id=?", (item_id,)).fetchone())
    return _item_view(updated)


def mark_uploaded(item_id: int, claim_token: str) -> dict[str, Any]:
    now = time.time()
    with queue._connect() as conn:
        ensure_schema(conn)
        row = _owned_item(conn, item_id, claim_token)
        if row["status"] not in {"claimed_by_worker", "downloading", "uploading"}:
            raise ResearchQueueError(f"Cannot upload a {row['status']} item.")
        conn.execute(
            "UPDATE research_queue_items SET status='waiting_for_analysis',updated_at=?,failure_reason=NULL,claim_token=NULL,claimed_by=NULL,claim_expires_at=NULL WHERE id=?",
            (now, item_id),
        )
        conn.execute(
            "UPDATE creator_videos SET research_queue_status='waiting_for_analysis',download_status='downloaded' WHERE id=?",
            (row["creator_video_id"],),
        )
        updated = dict(conn.execute("SELECT * FROM research_queue_items WHERE id=?", (item_id,)).fetchone())
    return _item_view(updated)


def claim_next_analysis(analysis_pid: int | None = None) -> dict[str, Any] | None:
    """Atomically reserve at most one uploaded research job for heavy analysis."""
    now = time.time()
    token = uuid.uuid4().hex
    pid = analysis_pid if analysis_pid is not None else os.getpid()
    with queue._connect() as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM research_queue_items WHERE status='analyzing' LIMIT 1").fetchone():
            return None
        row = conn.execute(
            "SELECT * FROM research_queue_items WHERE status IN ('uploaded','waiting_for_analysis') "
            "ORDER BY created_at,id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        changed = conn.execute(
            "UPDATE research_queue_items SET status='analyzing',updated_at=?,analysis_token=?,analysis_pid=? "
            "WHERE id=? AND status IN ('uploaded','waiting_for_analysis')",
            (now, token, pid, row["id"]),
        ).rowcount
        if changed != 1:
            return None
        conn.execute(
            "UPDATE creator_videos SET research_queue_status='analyzing',analysis_status='analyzing' WHERE id=?",
            (row["creator_video_id"],),
        )
        claimed = dict(conn.execute("SELECT * FROM research_queue_items WHERE id=?", (row["id"],)).fetchone())
    return {"queue_item_id": int(claimed["id"]), "job_id": claimed["job_id"], "analysis_token": token}


def mark_analyzing(item_id: int) -> None:
    """Compatibility transition for callers that do not use the atomic scheduler."""
    with queue._connect() as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT creator_video_id FROM research_queue_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return
        now = time.time()
        conn.execute("UPDATE research_queue_items SET status='analyzing',updated_at=? WHERE id=?", (now, item_id))
        conn.execute("UPDATE creator_videos SET research_queue_status='analyzing',analysis_status='analyzing' WHERE id=?", (row["creator_video_id"],))


def _finish_analysis(item_id: int, status: str, error: str | None, analysis_token: str | None) -> bool:
    now = time.time()
    with queue._connect() as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT * FROM research_queue_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return False
        if analysis_token is not None and row["analysis_token"] != analysis_token:
            return False
        if analysis_token is not None and row["status"] != "analyzing":
            return False
        completed_at = now
        conn.execute(
            "UPDATE research_queue_items SET status=?,updated_at=?,completed_at=?,failure_reason=?,"
            "claim_token=NULL,claimed_by=NULL,claim_expires_at=NULL,analysis_token=NULL,analysis_pid=NULL WHERE id=?",
            (status, now, completed_at, error, item_id),
        )
        analysis_status = "analyzed" if status == "completed" else "failed"
        conn.execute(
            "UPDATE creator_videos SET research_queue_status=?,analysis_status=? WHERE id=?",
            (status, analysis_status, row["creator_video_id"]),
        )
    return True


def mark_completed(item_id: int, analysis_token: str | None = None) -> bool:
    return _finish_analysis(item_id, "completed", None, analysis_token)


def mark_failed(item_id: int, error: str, analysis_token: str | None = None) -> bool:
    return _finish_analysis(item_id, "failed", error, analysis_token)


def retry(item_id: int) -> dict[str, Any] | None:
    with queue._connect() as conn:
        ensure_schema(conn)
        row = conn.execute("SELECT * FROM research_queue_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        if row["status"] != "failed":
            raise ResearchQueueError("Only failed research queue items can be retried.")
        job_id = row["job_id"]

    # Inspect artifacts outside the queue transaction; this keeps retry safe
    # with SQLite's single-writer locking while preserving existing checkpoints.
    job = queue.get_job(job_id) if job_id else None
    resume_uploaded = bool(job and (job.dir / "media.mkv").exists())
    status = "waiting_for_analysis" if resume_uploaded else "queued"
    now = time.time()
    with queue._connect() as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT * FROM research_queue_items WHERE id=?", (item_id,)).fetchone()
        if not current:
            return None
        if current["status"] != "failed":
            raise ResearchQueueError("Only failed research queue items can be retried.")
        conn.execute(
            "UPDATE research_queue_items SET status=?,started_at=CASE WHEN ? THEN started_at ELSE NULL END,"
            "completed_at=NULL,updated_at=?,failure_reason=NULL,claim_token=NULL,claimed_by=NULL,claim_expires_at=NULL,"
            "analysis_token=NULL,analysis_pid=NULL WHERE id=?",
            (status, int(resume_uploaded), now, item_id),
        )
        conn.execute(
            "UPDATE creator_videos SET research_queue_status=?,download_status=?,analysis_status='queued' WHERE id=?",
            (status, "downloaded" if resume_uploaded else "not_downloaded", current["creator_video_id"]),
        )
        if job_id:
            conn.execute("UPDATE jobs SET status='pending',error=NULL,job_mode='research' WHERE id=?", (job_id,))
        updated = dict(conn.execute("SELECT * FROM research_queue_items WHERE id=?", (item_id,)).fetchone())
    return _item_view(updated)


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True


def recover_interrupted_analyses(pid_is_alive=None) -> int:
    """Return abandoned analyses to the wait queue without touching a live owner."""
    checker = pid_is_alive or _pid_is_alive
    recovered = 0
    with queue._connect() as conn:
        ensure_schema(conn)
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT id,job_id,creator_video_id,analysis_pid FROM research_queue_items WHERE status='analyzing' ORDER BY created_at,id"
        ).fetchall()
        for row in rows:
            pid = row["analysis_pid"]
            if pid is not None and checker(int(pid)):
                continue
            conn.execute(
                "UPDATE research_queue_items SET status='waiting_for_analysis',updated_at=?,analysis_token=NULL,analysis_pid=NULL WHERE id=?",
                (time.time(), row["id"]),
            )
            conn.execute(
                "UPDATE creator_videos SET research_queue_status='waiting_for_analysis',analysis_status='queued' WHERE id=?",
                (row["creator_video_id"],),
            )
            if row["job_id"]:
                conn.execute("UPDATE jobs SET status='pending',error=NULL,job_mode='research' WHERE id=?", (row["job_id"],))
            recovered += 1
    return recovered


def recoverable_analyses() -> list[tuple[int, str]]:
    """Backward-compatible inspection of analyses eligible for a single claim."""
    with queue._connect() as conn:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT r.id,r.job_id FROM research_queue_items r JOIN jobs j ON j.id=r.job_id "
            "WHERE r.status IN ('uploaded','waiting_for_analysis','analyzing') AND j.status!='done' ORDER BY r.created_at"
        ).fetchall()
    return [(int(row["id"]), str(row["job_id"])) for row in rows]
