"""Campaign data store — SQLite schema, CRUD, and queries.

A campaign groups source videos (with their YouTube transcripts),
tracked clips (yours + competitor), and analyzed moments into one
project. Everything is local; nothing is shared.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path

from .. import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    rules_json TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    video_url TEXT NOT NULL,
    job_id TEXT,
    title TEXT,
    channel TEXT,
    duration_sec REAL,
    channel_subscribers INTEGER,
    added_at REAL NOT NULL,
    UNIQUE(campaign_id, video_url),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS yt_transcripts (
    video_url TEXT PRIMARY KEY,
    campaign_id TEXT,
    title TEXT,
    channel TEXT,
    duration_sec REAL,
    transcript_json TEXT NOT NULL,
    word_count INTEGER,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'mine',
    -- Source linkage
    job_id TEXT,
    clip_index INTEGER,
    source_video_url TEXT,
    -- Posted clip info
    clip_url TEXT,
    title TEXT,
    channel TEXT,
    platform TEXT DEFAULT 'youtube',
    posted_at REAL,
    -- Clip text
    hook_text TEXT,
    hook_type TEXT,
    hook_template TEXT,
    transcript_excerpt TEXT,
    start_sec REAL,
    end_sec REAL,
    duration_sec REAL,
    -- Analytics (mine: full YouTube Studio; competitor: public view count)
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    watch_time_pct REAL,
    avg_view_duration_sec REAL,
    ctr REAL,
    impressions INTEGER,
    retention_3s REAL,
    retention_5s REAL,
    swipe_away_pct REAL,
    -- Normalized metric
    channel_subscribers INTEGER,
    views_per_subscriber REAL,
    -- Pipeline scores (if processed)
    predicted_score REAL,
    hook_score REAL,
    funniness_score REAL,
    shock_score REAL,
    curiosity_score REAL,
    value_score REAL,
    -- Meta
    notes TEXT,
    raw_metrics_json TEXT,
    updated_at REAL,
    UNIQUE(campaign_id, clip_url),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE TABLE IF NOT EXISTS moment_analysis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id TEXT NOT NULL,
    video_url TEXT NOT NULL,
    start_sec REAL NOT NULL,
    end_sec REAL NOT NULL,
    -- Extracted text
    transcript_text TEXT,
    word_count INTEGER,
    -- Text features (instant, no LLM)
    sentence_count INTEGER,
    avg_sentence_length REAL,
    question_density REAL,
    specificity_score REAL,
    controversy_score REAL,
    emotional_arc_type TEXT,
    first_person_ratio REAL,
    imperative_density REAL,
    dialogue_ratio REAL,
    incomplete_thought INTEGER DEFAULT 0,
    -- Hook features (instant)
    hook_text TEXT,
    hook_type TEXT,
    hook_template TEXT,
    hook_density_score REAL,
    first_word_quality REAL,
    time_to_curiosity REAL,
    -- Retention features (instant)
    payoff_density REAL,
    middle_energy REAL,
    drop_off_risk REAL,
    energy_shape TEXT,
    -- LLM scores (API, top candidates only)
    llm_hook_score INTEGER,
    llm_funniness INTEGER,
    llm_shock INTEGER,
    llm_curiosity_gap INTEGER,
    llm_value_score INTEGER,
    llm_summary TEXT,
    llm_self_contained INTEGER,
    llm_hook_type TEXT,
    -- Similarity
    sim_to_top_clips REAL,
    -- Composite
    predicted_virality REAL,
    recommendation_score REAL,
    uncertainty REAL,
    -- Performance linkage
    has_clip INTEGER DEFAULT 0,
    clip_views INTEGER,
    clip_role TEXT,
    -- Meta
    analyzed_at REAL,
    UNIQUE(campaign_id, video_url, start_sec, end_sec),
    FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
);

CREATE INDEX IF NOT EXISTS idx_moments_campaign ON moment_analysis(campaign_id);
CREATE INDEX IF NOT EXISTS idx_moments_video ON moment_analysis(video_url);
CREATE INDEX IF NOT EXISTS idx_clips_campaign ON campaign_clips(campaign_id);
CREATE INDEX IF NOT EXISTS idx_videos_campaign ON campaign_videos(campaign_id);
"""

# New columns added after initial schema — SQLite ALTER TABLE.
_MIGRATIONS = [
    "ALTER TABLE campaign_clips ADD COLUMN thumbnail_path TEXT",
    "ALTER TABLE campaign_clips ADD COLUMN hook_text_overlay TEXT",
    "ALTER TABLE campaign_clips ADD COLUMN audio_hook TEXT",
    "ALTER TABLE campaign_clips ADD COLUMN audio_transcript_json TEXT",
    "ALTER TABLE campaign_clips ADD COLUMN traffic_source TEXT",
    "ALTER TABLE campaign_videos ADD COLUMN views INTEGER",
    "ALTER TABLE campaign_videos ADD COLUMN likes INTEGER",
]


def _connect() -> sqlite3.Connection:
    config.ensure_home()
    conn = sqlite3.connect(config.db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    
    # Auto-migrations for schema changes
    try:
        conn.execute("ALTER TABLE campaign_clips ADD COLUMN channel TEXT;")
    except sqlite3.OperationalError:
        pass  # Column already exists
        
    # Run migrations (ignore if column already exists)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn


# ---- Campaigns CRUD --------------------------------------------------------


def create_campaign(
    name: str,
    description: str = "",
    rules: str = "",
) -> dict:
    """Create a new campaign. Returns the campaign dict."""
    campaign_id = str(uuid.uuid4())[:8]
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO campaigns (id, name, description, rules_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (campaign_id, name, description, rules, now),
        )
    return {
        "id": campaign_id,
        "name": name,
        "description": description,
        "rules": rules,
        "created_at": now,
    }


def list_campaigns() -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT c.*, "
            " (SELECT COUNT(*) FROM campaign_videos cv WHERE cv.campaign_id = c.id) AS video_count,"
            " (SELECT COUNT(*) FROM campaign_clips cc WHERE cc.campaign_id = c.id) AS clip_count,"
            " (SELECT COUNT(*) FROM moment_analysis ma WHERE ma.campaign_id = c.id) AS moment_count"
            " FROM campaigns c ORDER BY c.created_at DESC"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "description": r["description"],
            "rules": r["rules_json"],
            "created_at": r["created_at"],
            "video_count": r["video_count"],
            "clip_count": r["clip_count"],
            "moment_count": r["moment_count"],
        }
        for r in rows
    ]


def get_campaign(campaign_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
        ).fetchone()
        if not row:
            return None
        videos = conn.execute(
            "SELECT cv.*, "
            " (CASE WHEN yt.video_url IS NOT NULL THEN 1 ELSE 0 END) AS has_transcript"
            " FROM campaign_videos cv"
            " LEFT JOIN yt_transcripts yt ON yt.video_url = cv.video_url"
            " WHERE cv.campaign_id = ? ORDER BY cv.added_at DESC",
            (campaign_id,),
        ).fetchall()
        clips = conn.execute(
            "SELECT * FROM campaign_clips WHERE campaign_id = ? ORDER BY views DESC NULLS LAST",
            (campaign_id,),
        ).fetchall()
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "rules": row["rules_json"],
        "created_at": row["created_at"],
        "videos": [dict(v) for v in videos],
        "clips": [dict(c) for c in clips],
    }


def update_campaign(
    campaign_id: str,
    name: str | None = None,
    description: str | None = None,
    rules: str | None = None,
) -> bool:
    sets = []
    vals = []
    if name is not None:
        sets.append("name = ?")
        vals.append(name)
    if description is not None:
        sets.append("description = ?")
        vals.append(description)
    if rules is not None:
        sets.append("rules_json = ?")
        vals.append(rules)
    if not sets:
        return False
    vals.append(campaign_id)
    with _connect() as conn:
        conn.execute(
            f"UPDATE campaigns SET {', '.join(sets)} WHERE id = ?", vals
        )
    return True


def delete_campaign(campaign_id: str) -> bool:
    with _connect() as conn:
        conn.execute("DELETE FROM moment_analysis WHERE campaign_id = ?", (campaign_id,))
        conn.execute("DELETE FROM campaign_clips WHERE campaign_id = ?", (campaign_id,))
        conn.execute("DELETE FROM campaign_videos WHERE campaign_id = ?", (campaign_id,))
        cur = conn.execute("DELETE FROM campaigns WHERE id = ?", (campaign_id,))
    return cur.rowcount > 0


# ---- Videos -----------------------------------------------------------------


def add_video(
    campaign_id: str,
    video_url: str,
    *,
    job_id: str | None = None,
    title: str | None = None,
    channel: str | None = None,
    duration_sec: float | None = None,
    channel_subscribers: int | None = None,
) -> dict:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO campaign_videos"
            " (campaign_id, video_url, job_id, title, channel, duration_sec,"
            "  channel_subscribers, added_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (campaign_id, video_url, job_id, title, channel, duration_sec,
             channel_subscribers, now),
        )
    return {
        "campaign_id": campaign_id,
        "video_url": video_url,
        "job_id": job_id,
        "title": title,
        "channel": channel,
        "duration_sec": duration_sec,
        "added_at": now,
    }


def remove_video(campaign_id: str, video_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM campaign_videos WHERE id = ? AND campaign_id = ?",
            (video_id, campaign_id),
        )
    return cur.rowcount > 0


def campaign_videos(campaign_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT cv.*, "
            " (CASE WHEN yt.video_url IS NOT NULL THEN 1 ELSE 0 END) AS has_transcript"
            " FROM campaign_videos cv"
            " LEFT JOIN yt_transcripts yt ON yt.video_url = cv.video_url"
            " WHERE cv.campaign_id = ? ORDER BY cv.added_at DESC",
            (campaign_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---- Clips ------------------------------------------------------------------


CLIP_FIELDS = [
    "job_id", "clip_index", "source_video_url", "clip_url", "title", "channel",
    "platform", "posted_at",
    "hook_text", "hook_type", "hook_template", "transcript_excerpt",
    "start_sec", "end_sec", "duration_sec",
    "views", "likes", "comments", "shares",
    "watch_time_pct", "avg_view_duration_sec", "ctr", "impressions",
    "retention_3s", "retention_5s", "swipe_away_pct",
    "channel_subscribers", "views_per_subscriber",
    "predicted_score", "hook_score", "funniness_score",
    "shock_score", "curiosity_score", "value_score",
    "notes", "raw_metrics_json", "updated_at",
    "thumbnail_path", "hook_text_overlay", "audio_hook",
    "audio_transcript_json", "traffic_source",
]


def add_clip(campaign_id: str, role: str = "mine", **kwargs) -> dict:
    """Add a tracked clip (mine or competitor)."""
    now = time.time()
    # Compute views_per_subscriber if both values present
    views = kwargs.get("views")
    subs = kwargs.get("channel_subscribers")
    vps = None
    if views is not None and subs and subs > 0:
        vps = round(views / subs, 6)

    vals = {
        "campaign_id": campaign_id,
        "role": role,
        "views_per_subscriber": vps,
        "updated_at": now,
    }
    for f in CLIP_FIELDS:
        if f not in vals and f in kwargs:
            vals[f] = kwargs[f]

    present_fields = [f for f in CLIP_FIELDS + ["campaign_id", "role"] if f in vals]
    placeholders = ", ".join("?" for _ in present_fields)
    col_list = ", ".join(present_fields)
    values = [vals[f] for f in present_fields]

    with _connect() as conn:
        cur = conn.execute(
            f"INSERT INTO campaign_clips ({col_list}) VALUES ({placeholders})",
            values,
        )
    result = dict(vals)
    result["id"] = cur.lastrowid
    return result


def add_clip_from_analysis(campaign_id: str, data: dict) -> dict:
    """Add a clip from the clip_analyzer extraction pipeline.
    Accepts the dict returned by clip_analyzer.analyze_clip()."""
    role = data.get("role", "competitor")
    return add_clip(campaign_id, role, **{
        k: v for k, v in data.items()
        if k not in ("campaign_id", "role") and v is not None
    })


def update_clip(clip_id: int, **kwargs) -> bool:
    """Update analytics for a clip."""
    # Recompute views_per_subscriber
    if "views" in kwargs or "channel_subscribers" in kwargs:
        with _connect() as conn:
            row = conn.execute(
                "SELECT views, channel_subscribers FROM campaign_clips WHERE id = ?",
                (clip_id,),
            ).fetchone()
        if row:
            views = kwargs.get("views", row["views"])
            subs = kwargs.get("channel_subscribers", row["channel_subscribers"])
            if views is not None and subs and subs > 0:
                kwargs["views_per_subscriber"] = round(views / subs, 6)

    kwargs["updated_at"] = time.time()
    
    # Filter kwargs to only valid fields
    valid_kwargs = {k: v for k, v in kwargs.items() if k in CLIP_FIELDS}
    if not valid_kwargs:
        return False
        
    sets = ", ".join(f"{k} = ?" for k in valid_kwargs)
    vals = list(valid_kwargs.values()) + [clip_id]
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE campaign_clips SET {sets} WHERE id = ?", vals
        )
    return cur.rowcount > 0


def delete_clip(clip_id: int) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM campaign_clips WHERE id = ?", (clip_id,))
    return cur.rowcount > 0


def campaign_clips(campaign_id: str, role: str | None = None) -> list[dict]:
    with _connect() as conn:
        if role:
            rows = conn.execute(
                "SELECT * FROM campaign_clips WHERE campaign_id = ? AND role = ?"
                " ORDER BY views DESC NULLS LAST",
                (campaign_id, role),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM campaign_clips WHERE campaign_id = ?"
                " ORDER BY views DESC NULLS LAST",
                (campaign_id,),
            ).fetchall()
    return [dict(r) for r in rows]


# ---- Transcripts ------------------------------------------------------------


def store_transcript(
    video_url: str,
    campaign_id: str | None,
    title: str | None,
    channel: str | None,
    duration_sec: float | None,
    transcript: list[dict],
    word_count: int,
) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO yt_transcripts"
            " (video_url, campaign_id, title, channel, duration_sec,"
            "  transcript_json, word_count, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (video_url, campaign_id, title, channel, duration_sec,
             json.dumps(transcript), word_count, time.time()),
        )


def get_transcript(video_url: str) -> list[dict] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT transcript_json FROM yt_transcripts WHERE video_url = ?",
            (video_url,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row["transcript_json"])


def campaign_transcripts(campaign_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT yt.* FROM yt_transcripts yt "
            "JOIN campaign_videos cv ON yt.video_url = cv.video_url "
            "WHERE cv.campaign_id = ? "
            "ORDER BY yt.fetched_at DESC",
            (campaign_id,),
        ).fetchall()
    res = []
    for r in rows:
        transcript = json.loads(r["transcript_json"])
        for seg in transcript:
            seg.pop("words", None)
        res.append({
            "video_url": r["video_url"],
            "title": r["title"],
            "channel": r["channel"],
            "duration_sec": r["duration_sec"],
            "word_count": r["word_count"],
            "fetched_at": r["fetched_at"],
            "transcript": transcript,
        })
    return res


def search_transcripts(campaign_id: str, query: str) -> list[dict]:
    """Full-text search across all transcripts in a campaign."""
    query_lower = query.lower()
    results = []
    for entry in campaign_transcripts(campaign_id):
        for seg in entry["transcript"]:
            text = seg.get("text", "")
            if query_lower in text.lower():
                results.append({
                    "video_url": entry["video_url"],
                    "title": entry["title"],
                    "start": seg.get("start"),
                    "end": seg.get("end"),
                    "text": text,
                })
    return results


# ---- Moments ----------------------------------------------------------------


def store_moments(campaign_id: str, moments: list[dict]) -> int:
    """Bulk insert analyzed moments. Returns count inserted."""
    if not moments:
        return 0
    now = time.time()
    with _connect() as conn:
        count = 0
        for m in moments:
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO moment_analysis"
                    " (campaign_id, video_url, start_sec, end_sec,"
                    "  transcript_text, word_count,"
                    "  sentence_count, avg_sentence_length, question_density,"
                    "  specificity_score, controversy_score, emotional_arc_type,"
                    "  first_person_ratio, imperative_density, dialogue_ratio,"
                    "  incomplete_thought,"
                    "  hook_text, hook_type, hook_template, hook_density_score,"
                    "  first_word_quality, time_to_curiosity,"
                    "  payoff_density, middle_energy, drop_off_risk, energy_shape,"
                    "  llm_hook_score, llm_funniness, llm_shock, llm_curiosity_gap,"
                    "  llm_value_score, llm_summary, llm_self_contained, llm_hook_type,"
                    "  sim_to_top_clips,"
                    "  predicted_virality, recommendation_score, uncertainty,"
                    "  has_clip, clip_views, clip_role,"
                    "  analyzed_at)"
                    " VALUES ("
                    "  ?, ?, ?, ?,"
                    "  ?, ?,"
                    "  ?, ?, ?,"
                    "  ?, ?, ?,"
                    "  ?, ?, ?,"
                    "  ?,"
                    "  ?, ?, ?, ?,"
                    "  ?, ?,"
                    "  ?, ?, ?, ?,"
                    "  ?, ?, ?, ?,"
                    "  ?, ?, ?, ?,"
                    "  ?,"
                    "  ?, ?, ?,"
                    "  ?, ?, ?,"
                    "  ?)",
                    (
                        campaign_id, m.get("video_url"), m.get("start_sec"), m.get("end_sec"),
                        m.get("transcript_text"), m.get("word_count"),
                        m.get("sentence_count"), m.get("avg_sentence_length"), m.get("question_density"),
                        m.get("specificity_score"), m.get("controversy_score"), m.get("emotional_arc_type"),
                        m.get("first_person_ratio"), m.get("imperative_density"), m.get("dialogue_ratio"),
                        m.get("incomplete_thought", 0),
                        m.get("hook_text"), m.get("hook_type"), m.get("hook_template"), m.get("hook_density_score"),
                        m.get("first_word_quality"), m.get("time_to_curiosity"),
                        m.get("payoff_density"), m.get("middle_energy"), m.get("drop_off_risk"), m.get("energy_shape"),
                        m.get("llm_hook_score"), m.get("llm_funniness"), m.get("llm_shock"), m.get("llm_curiosity_gap"),
                        m.get("llm_value_score"), m.get("llm_summary"), m.get("llm_self_contained"), m.get("llm_hook_type"),
                        m.get("sim_to_top_clips"),
                        m.get("predicted_virality"), m.get("recommendation_score"), m.get("uncertainty"),
                        m.get("has_clip", 0), m.get("clip_views"), m.get("clip_role"),
                        now,
                    ),
                )
                count += 1
            except sqlite3.IntegrityError:
                pass
    return count


def campaign_moments(
    campaign_id: str,
    *,
    limit: int = 50,
    unclipped_only: bool = False,
    order_by: str = "recommendation_score",
) -> list[dict]:
    where = "campaign_id = ?"
    params: list = [campaign_id]
    if unclipped_only:
        where += " AND has_clip = 0"
    allowed_orders = {
        "recommendation_score", "predicted_virality", "llm_hook_score",
        "hook_density_score", "sim_to_top_clips", "analyzed_at",
    }
    if order_by not in allowed_orders:
        order_by = "recommendation_score"
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM moment_analysis WHERE {where}"
            f" ORDER BY {order_by} DESC NULLS LAST LIMIT ?",
            params + [limit],
        ).fetchall()
    return [dict(r) for r in rows]


def update_moment_clips(campaign_id: str) -> int:
    """Cross-reference moments with actual clips. Returns count updated."""
    clips = campaign_clips(campaign_id)
    if not clips:
        return 0
    updated = 0
    with _connect() as conn:
        for clip in clips:
            if clip.get("source_video_url") and clip.get("start_sec") is not None:
                cur = conn.execute(
                    "UPDATE moment_analysis SET has_clip = 1, clip_views = ?,"
                    " clip_role = ? WHERE campaign_id = ? AND video_url = ?"
                    " AND start_sec <= ? AND end_sec >= ?",
                    (
                        clip.get("views"), clip.get("role"),
                        campaign_id, clip["source_video_url"],
                        clip["start_sec"], clip["end_sec"],
                    ),
                )
                updated += cur.rowcount
    return updated
