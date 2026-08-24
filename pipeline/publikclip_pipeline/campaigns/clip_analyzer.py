"""Clip Analyzer — extracts visual hook text, audio hook, transcript,
metadata, and thumbnail from individual short-form clips.

Pipeline per clip:
    1. yt-dlp  → download video + pull metadata (title, views, likes, channel)
    2. ffmpeg  → capture frame at t=1.5s
    3. Tesseract OCR → extract visual hook text from top 50% of frame
    4. WhisperX → word-level transcription
    5. First 3-5s of transcript → audio hook
    6. Store everything in campaign_clips table
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .. import config

ProgressFn = Callable[[float, str], None]

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


class ClipAnalysisError(Exception):
    """User-facing error from clip analysis."""


# ---- Metadata via yt-dlp ----------------------------------------------------

def _fetch_clip_meta(url: str, progress: ProgressFn) -> dict:
    """Fetch metadata for a short-form clip. Returns raw yt-dlp JSON dict."""
    from ..ingest.ytdlp import ensure_ytdlp, _run, _with_self_update_retry

    bin_path = ensure_ytdlp(progress)

    def _go() -> str:
        args = ["-J", "--no-playlist", "--no-warnings"]
        cookies_path = Path("cookies.txt").resolve()
        if cookies_path.exists():
            args.extend(["--cookies", str(cookies_path)])
        args.append(url)
        return _run(bin_path, args)

    out = _with_self_update_retry(bin_path, progress, _go)
    data = json.loads(out)

    # Handle playlist-type responses
    if data.get("_type") == "playlist":
        entries = data.get("entries") or []
        if entries:
            data = entries[0]

    return data


def _download_clip(url: str, out_path: Path, progress: ProgressFn) -> None:
    """Download the clip video file."""
    from ..ingest.ytdlp import download
    download(url, out_path, progress)


# ---- Frame capture via ffmpeg -----------------------------------------------

def _capture_frame(video_path: Path, time_sec: float, out_path: Path) -> bool:
    """Capture a single frame at the given timestamp using ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        from ..render.ffmpeg_bin import ffmpeg as get_ffmpeg
        ffmpeg = get_ffmpeg()

    try:
        subprocess.run(
            [
                ffmpeg, "-y", "-v", "error",
                "-ss", f"{time_sec:.2f}",
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(out_path),
            ],
            capture_output=True, timeout=30,
            check=True,
        )
        return out_path.exists()
    except Exception:
        return False


# ---- OCR via Tesseract ------------------------------------------------------

def _ocr_top_half(image_path: Path) -> str:
    """Run Tesseract OCR on the top 50% of the image to extract the visual
    hook text overlay. Returns cleaned text or empty string."""
    try:
        from PIL import Image
    except ImportError:
        # Pillow not installed — try raw Tesseract on full image
        return _ocr_full(image_path)

    try:
        img = Image.open(image_path)
        w, h = img.size
        # Crop to top 50% of the frame
        top_half = img.crop((0, 0, w, h // 2))
        cropped_path = image_path.with_name("_top_half.png")
        top_half.save(cropped_path)
        text = _ocr_full(cropped_path)
        cropped_path.unlink(missing_ok=True)
        return text
    except Exception:
        return _ocr_full(image_path)


def _ocr_full(image_path: Path) -> str:
    """Run Tesseract on the full image."""
    tesseract = TESSERACT_PATH
    if not Path(tesseract).exists():
        tesseract = shutil.which("tesseract") or tesseract

    try:
        result = subprocess.run(
            [tesseract, str(image_path), "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            # Clean up OCR noise — remove very short lines and junk characters
            lines = []
            for line in text.splitlines():
                line = line.strip()
                # Filter out noise: too short, only symbols, etc.
                if len(line) >= 3 and re.search(r"[a-zA-Z]", line):
                    lines.append(line)
            return " ".join(lines)
    except Exception:
        pass
    return ""


# ---- Audio transcript via WhisperX ------------------------------------------

def _transcribe_clip(video_path: Path, progress: ProgressFn) -> list[dict]:
    """Run WhisperX on the clip to get word-level transcription.
    Returns list of word dicts: [{word, start, end}, ...]"""
    try:
        import whisperx
        import torch
    except ImportError:
        progress(-1, "WhisperX not available — skipping audio transcript")
        return []

    device = "cpu"
    compute_type = "int8"
    if torch.cuda.is_available():
        device = "cuda"
        compute_type = "float16"

    progress(0.4, "Transcribing audio…")
    model = whisperx.load_model("large-v3-turbo", device, compute_type=compute_type)
    audio = whisperx.load_audio(str(video_path))
    result = model.transcribe(audio)

    progress(0.6, "Aligning words…")
    align_model, metadata = whisperx.load_align_model(
        language_code=result.get("language", "en"), device=device
    )
    aligned = whisperx.align(
        result["segments"], align_model, metadata, audio, device
    )

    del model
    del align_model
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # Flatten to word list
    words = []
    for seg in aligned.get("segments", []):
        for w in seg.get("words", []):
            if "start" in w and "end" in w and "word" in w:
                words.append({
                    "word": w["word"],
                    "start": round(w["start"], 3),
                    "end": round(w["end"], 3),
                })
    return words


def _extract_audio_hook(words: list[dict], max_sec: float = 5.0) -> str:
    """Extract the audio hook = first 3-5 seconds of spoken words."""
    hook_words = []
    for w in words:
        if w["start"] <= max_sec:
            hook_words.append(w["word"])
        else:
            break
    return " ".join(hook_words).strip()


# ---- Main analysis pipeline -------------------------------------------------

def analyze_clip(
    campaign_id: str,
    clip_url: str,
    role: str = "competitor",
    progress: ProgressFn | None = None,
) -> dict:
    """Full extraction pipeline for a single short-form clip.

    Returns a dict with all extracted data, ready for store.add_clip().
    """
    emit = progress or (lambda f, m: None)
    config.ensure_home()

    work_dir = config.jobs_dir() / campaign_id / "clip_analysis"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch metadata
    emit(0.05, "Fetching clip metadata…")
    meta = _fetch_clip_meta(clip_url, emit)

    title = meta.get("title", "")
    channel = meta.get("channel") or meta.get("uploader") or ""
    views = meta.get("view_count")
    likes = meta.get("like_count")
    duration_sec = meta.get("duration")
    channel_subs = meta.get("channel_follower_count")
    thumbnail_url = meta.get("thumbnail") or ""

    # 2. Download video
    emit(0.1, "Downloading clip…")
    video_file = work_dir / f"clip_{meta.get('id', 'video')}.mp4"
    if not video_file.exists():
        _download_clip(clip_url, video_file, emit)

    # 3. Capture frame at t=1.5s for OCR
    emit(0.3, "Capturing frame for hook text detection…")
    frame_path = work_dir / f"frame_{meta.get('id', 'video')}.jpg"
    _capture_frame(video_file, 1.5, frame_path)

    # 4. OCR on top half of frame
    visual_hook = ""
    if frame_path.exists():
        emit(0.35, "Running OCR for visual hook text…")
        visual_hook = _ocr_top_half(frame_path)

    # 5. Transcribe audio
    emit(0.4, "Transcribing audio…")
    words = _transcribe_clip(video_file, emit)

    # 6. Extract audio hook (first 5s)
    audio_hook = _extract_audio_hook(words, max_sec=5.0)

    # Full transcript text
    full_transcript = " ".join(w["word"] for w in words)

    # 7. Save thumbnail
    thumbnail_path = None
    if frame_path.exists():
        thumb_dest = config.home_dir() / "campaigns" / campaign_id / "thumbs"
        thumb_dest.mkdir(parents=True, exist_ok=True)
        final_thumb = thumb_dest / f"{meta.get('id', 'thumb')}.jpg"
        shutil.copy2(frame_path, final_thumb)
        thumbnail_path = str(final_thumb)

    # Cleanup work files
    video_file.unlink(missing_ok=True)
    frame_path.unlink(missing_ok=True)

    emit(0.95, "Storing results…")

    result = {
        "campaign_id": campaign_id,
        "role": role,
        "clip_url": clip_url,
        "title": title,
        "channel": channel,
        "views": views,
        "likes": likes,
        "duration_sec": duration_sec,
        "channel_subscribers": channel_subs,
        "thumbnail_path": thumbnail_path,
        "hook_text_overlay": visual_hook,
        "audio_hook": audio_hook,
        "audio_transcript_json": json.dumps(words),
        "transcript_excerpt": full_transcript[:500] if full_transcript else None,
        "hook_text": audio_hook,  # Primary hook for the learning system
        "source_video_url": clip_url,
    }

    emit(1.0, "Clip analysis complete!")
    return result
