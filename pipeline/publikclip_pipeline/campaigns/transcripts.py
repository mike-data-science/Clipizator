"""YouTube transcript fetching via yt-dlp captions.

Uses YouTube's auto-generated captions (json3 format) instead of local STT.
Takes seconds per video instead of hours. Works for any YouTube video with
auto-generated captions (virtually all of them).

Also fetches video metadata (title, channel, duration, view_count,
like_count, channel_follower_count) for competitor intelligence.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from ..ingest import ytdlp
from . import store

ProgressFn = Callable[[float, str], None]


def _parse_json3_captions(json3_path: Path) -> tuple[list[dict], int]:
    """Parse YouTube json3 subtitle format into word-timed segments.

    json3 format has events with segments (segs) containing words with
    timing offsets. We group them into sentence-like segments matching
    the ASR stage output format: [{start, end, text, words: [{word, start, end}]}]
    """
    data = json.loads(json3_path.read_text(encoding="utf-8"))
    events = data.get("events", [])
    words: list[dict] = []
    for event in events:
        # Skip non-text events (window styling, etc.)
        segs = event.get("segs")
        if not segs:
            continue
        base_ms = event.get("tStartMs", 0)
        for seg in segs:
            text = seg.get("utf8", "").strip()
            if not text or text == "\n":
                continue
            offset_ms = seg.get("tOffsetMs", 0)
            start_ms = base_ms + offset_ms
            # Approximate word duration: use next seg offset or 500ms
            words.append({
                "word": text,
                "start": round(start_ms / 1000.0, 3),
                "end": round((start_ms + 500) / 1000.0, 3),
            })

    if not words:
        return [], 0

    # Fix end times: each word ends when the next one starts
    for i in range(len(words) - 1):
        words[i]["end"] = words[i + 1]["start"]

    # Group into segments (~sentence-level) by detecting pauses > 1s
    segments: list[dict] = []
    current_words: list[dict] = []
    for w in words:
        if current_words and w["start"] - current_words[-1]["end"] > 1.0:
            seg_text = " ".join(cw["word"] for cw in current_words)
            segments.append({
                "start": current_words[0]["start"],
                "end": current_words[-1]["end"],
                "text": seg_text,
                "words": list(current_words),
            })
            current_words = []
        current_words.append(w)
    if current_words:
        seg_text = " ".join(cw["word"] for cw in current_words)
        segments.append({
            "start": current_words[0]["start"],
            "end": current_words[-1]["end"],
            "text": seg_text,
            "words": list(current_words),
        })

    word_count = len(words)
    return segments, word_count


def _parse_vtt_captions(vtt_path: Path) -> tuple[list[dict], int]:
    """Parse WebVTT subtitle format as fallback.

    VTT gives us sentence-level timing but not word-level. We approximate
    word timing by splitting text and distributing evenly across the segment.
    """
    text = vtt_path.read_text(encoding="utf-8")
    segments: list[dict] = []
    word_count = 0

    lines = text.strip().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Look for timestamp lines: 00:00:01.234 --> 00:00:05.678
        if "-->" in line:
            parts = line.split("-->")
            start = _parse_vtt_time(parts[0].strip())
            end = _parse_vtt_time(parts[1].strip().split(" ")[0])
            # Collect text lines until blank line
            text_lines = []
            i += 1
            while i < len(lines) and lines[i].strip():
                # Strip VTT tags like <c>, </c>, etc.
                clean = lines[i].strip()
                import re
                clean = re.sub(r"<[^>]+>", "", clean)
                if clean:
                    text_lines.append(clean)
                i += 1
            seg_text = " ".join(text_lines)
            if seg_text:
                # Approximate word-level timing
                seg_words = seg_text.split()
                if seg_words:
                    duration = end - start
                    per_word = duration / len(seg_words)
                    words = [
                        {
                            "word": w,
                            "start": round(start + j * per_word, 3),
                            "end": round(start + (j + 1) * per_word, 3),
                        }
                        for j, w in enumerate(seg_words)
                    ]
                    segments.append({
                        "start": round(start, 3),
                        "end": round(end, 3),
                        "text": seg_text,
                        "words": words,
                    })
                    word_count += len(seg_words)
        i += 1

    return segments, word_count


def _parse_vtt_time(ts: str) -> float:
    """Parse VTT timestamp like '00:01:23.456' or '01:23.456' to seconds."""
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return float(h) * 3600 + float(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return float(m) * 60 + float(s)
    return float(parts[0])


def fetch_transcript(
    video_url: str,
    campaign_id: str | None = None,
    progress: ProgressFn | None = None,
) -> dict:
    """Fetch YouTube transcript for a video via yt-dlp captions.

    Returns dict with: segments, word_count, title, channel, duration_sec,
    view_count, like_count, channel_followers.
    """
    emit = progress or (lambda f, m: None)
    bin_path = ytdlp.ensure_ytdlp(emit)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        out_template = str(tmp_path / "subs")

        # Fetch metadata + subtitles in one pass
        emit(-1, "Fetching video metadata and captions…")
        args = [
            str(bin_path),
            "--skip-download",
            "--write-auto-sub",
            "--sub-lang", "en",
            "--sub-format", "json3",
            "--write-info-json",
            "-J",  # also dump full JSON to stdout for metadata
            "--no-playlist",
            "--no-warnings",
            "-o", out_template,
            video_url,
        ]
        cookies_path = Path("cookies.txt").resolve()
        if cookies_path.exists():
            args.extend(["--cookies", str(cookies_path)])

        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Timed out fetching captions")

        # Parse metadata from stdout
        meta = {}
        if result.stdout.strip():
            try:
                meta = json.loads(result.stdout)
            except json.JSONDecodeError:
                pass

        title = meta.get("title", "")
        channel = meta.get("channel", "") or meta.get("uploader", "")
        duration = meta.get("duration")
        view_count = meta.get("view_count")
        like_count = meta.get("like_count")
        comment_count = meta.get("comment_count")
        channel_followers = meta.get("channel_follower_count")

        # Find subtitle file
        emit(0.5, "Parsing captions…")
        segments = []
        word_count = 0

        # Try json3 first
        json3_files = list(tmp_path.glob("*.json3"))
        if json3_files:
            segments, word_count = _parse_json3_captions(json3_files[0])

        # Fallback to VTT
        if not segments:
            vtt_files = list(tmp_path.glob("*.vtt"))
            if vtt_files:
                segments, word_count = _parse_vtt_captions(vtt_files[0])

        if not segments:
            # Last resort: re-try with --write-auto-sub --sub-format vtt
            emit(0.6, "Retrying with VTT format…")
            args2 = [
                str(bin_path),
                "--skip-download",
                "--write-auto-sub",
                "--sub-lang", "en",
                "--sub-format", "vtt",
                "--no-playlist",
                "--no-warnings",
                "-o", str(tmp_path / "subs2"),
                video_url,
            ]
            if cookies_path.exists():
                args2.extend(["--cookies", str(cookies_path)])
            subprocess.run(args2, capture_output=True, timeout=120)
            vtt_files = list(tmp_path.glob("subs2*.vtt"))
            if vtt_files:
                segments, word_count = _parse_vtt_captions(vtt_files[0])

        if not segments:
            raise RuntimeError(
                f"No captions available for {video_url}. "
                "The video may not have auto-generated subtitles."
            )

    # Store in DB
    store.store_transcript(
        video_url=video_url,
        campaign_id=campaign_id,
        title=title,
        channel=channel,
        duration_sec=duration,
        transcript=segments,
        word_count=word_count,
    )

    emit(1.0, f"Done — {word_count} words")
    return {
        "video_url": video_url,
        "title": title,
        "channel": channel,
        "duration_sec": duration,
        "word_count": word_count,
        "segments": segments,
        "view_count": view_count,
        "like_count": like_count,
        "comment_count": comment_count,
        "channel_followers": channel_followers,
    }


def fetch_all_for_campaign(
    campaign_id: str,
    progress: ProgressFn | None = None,
) -> dict:
    """Fetch transcripts for all videos in a campaign that don't have one yet."""
    emit = progress or (lambda f, m: None)
    videos = store.campaign_videos(campaign_id)
    pending = [v for v in videos if not v.get("has_transcript")]

    if not pending:
        emit(1.0, "All transcripts already fetched")
        return {"fetched": 0, "total": len(videos), "errors": []}

    fetched = 0
    errors = []
    for i, video in enumerate(pending):
        frac = i / len(pending)
        emit(frac, f"Fetching transcript {i + 1}/{len(pending)}: {video.get('title') or video['video_url']}")
        try:
            result = fetch_transcript(video["video_url"], campaign_id)
            # Update video metadata from fetched data
            with store._connect() as conn:
                conn.execute(
                    "UPDATE campaign_videos SET title = COALESCE(title, ?),"
                    " channel = COALESCE(channel, ?), duration_sec = COALESCE(duration_sec, ?)"
                    " WHERE campaign_id = ? AND video_url = ?",
                    (result.get("title"), result.get("channel"),
                     result.get("duration_sec"), campaign_id, video["video_url"]),
                )
            fetched += 1
        except Exception as err:
            errors.append({"video_url": video["video_url"], "error": str(err)})

    emit(1.0, f"Fetched {fetched}/{len(pending)} transcripts")
    return {"fetched": fetched, "total": len(videos), "errors": errors}


def get_moment_text(
    video_url: str,
    start: float,
    end: float,
) -> str:
    """Extract plain transcript text for a time range."""
    segments = store.get_transcript(video_url)
    if not segments:
        return ""
    words = []
    for seg in segments:
        for w in seg.get("words", []):
            if w["start"] >= start and w["end"] <= end:
                words.append(w["word"])
    return " ".join(words)
