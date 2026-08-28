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
