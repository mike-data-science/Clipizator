"""Small, cached playback copies; full-resolution exports are never modified."""

import hashlib
import os
import tempfile
import threading
from pathlib import Path

from . import ffmpeg_bin, renderer

# Bound on-demand transcoding even when several browser tabs request previews.
_encode_lock = threading.Lock()
PROFILE = "720x1280-30fps-1600k-v1"


def preview_path(source: Path) -> Path:
    stat = source.stat()
    fingerprint = hashlib.sha256(
        f"{PROFILE}:{stat.st_size}:{stat.st_mtime_ns}".encode()
    ).hexdigest()[:20]
    return source.parent / ".previews" / f"{source.stem}-{fingerprint}.mp4"


def ensure_preview(source: Path, duration: float) -> Path:
    """Publish a complete MP4 atomically and invalidate it after a re-render."""
    source = source.resolve(strict=True)
    target = preview_path(source)
    if target.is_file():
        return target
    with _encode_lock:
        target = preview_path(source)
        if target.is_file():
            return target
        target.parent.mkdir(exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="preview-", suffix=".mp4", dir=target.parent)
        os.close(fd)
        temporary = Path(name)
        try:
            gpu = renderer.nvenc_available() and renderer.cuda_scale_available()
            scale = (
                "scale_cuda=720:1280:format=yuv420p"
                if gpu else "scale=720:1280,format=yuv420p"
            )
            codec = ["-c:v", "h264_nvenc", "-preset", "p4"] if gpu else [
                "-c:v", "libx264", "-preset", "veryfast",
            ]
            args = [
                ffmpeg_bin.ffmpeg(), "-nostdin", "-y", "-v", "error",
                *(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"] if gpu else []),
                "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                "-vf", scale, "-r", "30", *codec,
                "-b:v", "1600k", "-maxrate", "2000k", "-bufsize", "4000k",
                "-g", "60", "-c:a", "aac", "-b:a", "96k", "-ar", "48000",
                "-movflags", "+faststart", "-map_metadata", "-1",
                "-progress", "pipe:1", "-nostats", str(temporary),
            ]
            try:
                renderer._run_ffmpeg(args, max(duration, 0.1), max(120, duration * 3), None)
            except RuntimeError:
                if not gpu:
                    raise
                # Legacy clips may use a codec the GPU cannot decode. Keep
                # CUDA scaling/NVENC but decode those particular files on CPU.
                start = args.index("-hwaccel")
                del args[start:start + 4]
                args[args.index("-vf") + 1] = "format=yuv420p,hwupload_cuda,scale_cuda=720:1280"
                renderer._run_ffmpeg(args, max(duration, 0.1), max(120, duration * 3), None)
            if preview_path(source) != target:
                raise RuntimeError("The clip changed while preparing its preview. Try again.")
            check = renderer.verify_output(temporary, duration)
            if not check["ok"] or (check["width"], check["height"]) != (720, 1280):
                raise RuntimeError("Playback preview failed verification.")
            temporary.replace(target)
            return target
        finally:
            temporary.unlink(missing_ok=True)
