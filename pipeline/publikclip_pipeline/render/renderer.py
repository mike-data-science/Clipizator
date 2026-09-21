"""Clip renderer: one ffmpeg filter_complex per clip.

The sendcmd architecture (vendored from mutonby/openshorts punch_in.py +
reframe_v2.py, MIT): the director's per-frame trajectory array becomes a
deduped sendcmd command file driving a labeled crop filter — hard cuts are
just discontinuities in the same array, pans are smooth regions, punch-ins
already live in the w/h values. One decode, one encode:

    sendcmd → crop@c → scale 1080x1920 → subtitles burn → loudnorm

Deduping to change-points matters: a 45 s clip at 25 fps is 1125 frames and
writing every parameter every frame slows the filter measurably (openshorts'
own comment). Even dimensions everywhere — x264/NVENC reject odd ones.

Encoder tiers follow openshorts ffmpeg_utils.py: try hardware
(h264_videotoolbox on macOS), fall back to libx264, mapping quality between
CRF and the hardware encoder's bitrate model.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from . import ffmpeg_bin

OUT_W = 2160
OUT_H = 3840
X264_CRF = 19
VT_BITRATE = "10M"

_vt_checked: bool | None = None


def videotoolbox_available() -> bool:
    """Probe once: encode 0.2 s of black through h264_videotoolbox."""
    global _vt_checked
    if _vt_checked is None:
        proc = subprocess.run(
            [
                ffmpeg_bin.ffmpeg(), "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=black:s=320x240:d=0.2",
                "-c:v", "h264_videotoolbox", "-f", "null", "-",
            ],
            capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
        )
        _vt_checked = proc.returncode == 0
    return _vt_checked


_nvenc_checked: bool | None = None

def nvenc_available() -> bool:
    """Probe once: encode 0.2 s of black through h264_nvenc."""
    global _nvenc_checked
    if _nvenc_checked is None:
        proc = subprocess.run(
            [
                ffmpeg_bin.ffmpeg(), "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=black:s=320x240:d=0.2",
                "-c:v", "h264_nvenc", "-f", "null", "-",
            ],
            capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
        )
        _nvenc_checked = proc.returncode == 0
    return _nvenc_checked


_cuda_checked: bool | None = None

def _cuda_decode_available() -> bool:
    """Compatibility alias for callers of the old, ineffective decode probe."""
    return cuda_scale_available()


def cuda_scale_available() -> bool:
    """Exercise the upload/scale/download path, not a lavfi 'decode'."""
    global _cuda_checked
    if _cuda_checked is None:
        proc = subprocess.run(
            [
                ffmpeg_bin.ffmpeg(), "-nostdin", "-v", "error",
                "-f", "lavfi", "-i", "color=black:s=320x240:d=0.2",
                "-vf", "format=yuv420p,hwupload_cuda,scale_cuda=160:120,hwdownload,format=yuv420p",
                "-f", "null", "-",
            ],
            capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
        )
        _cuda_checked = proc.returncode == 0
    return _cuda_checked


def scale_filter() -> str:
    # CUDA also avoids the FFmpeg 6.1 software scaler stall when crop@c
    # changes dimensions during a punch-in. Captions still require CPU frames.
    if cuda_scale_available():
        return f"format=yuv420p,hwupload_cuda,scale_cuda={OUT_W}:{OUT_H},hwdownload,format=yuv420p"
    return f"scale={OUT_W}:{OUT_H},format=yuv420p"


def _run_ffmpeg(
    args: list[str], duration: float, timeout: float,
    progress: Callable[[float], None] | None,
    stall_timeout: float = 120.0,
) -> None:
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        stdin=subprocess.DEVNULL,
    )
    stderr_lines: deque[str] = deque(maxlen=200)
    last_advance = time.monotonic()
    last_values = {"frame": -1.0, "out_time_ms": -1.0}

    def read_stdout() -> None:
        nonlocal last_advance
        if proc.stdout is None:
            return
        for line in proc.stdout:
            key, _, value = line.partition("=")
            if key in last_values:
                try:
                    number = float(value)
                    if number > last_values[key]:
                        last_values[key] = number
                        last_advance = time.monotonic()
                except ValueError:
                    pass
            if key == "out_time_ms" and progress:
                try:
                    progress(min(1.0, max(0.0, float(value) / 1_000_000 / duration)))
                except ValueError:
                    pass

    def read_stderr() -> None:
        if proc.stderr is not None:
            stderr_lines.extend(proc.stderr)

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    started = time.monotonic()
    try:
        while proc.poll() is None:
            now = time.monotonic()
            if now - started > timeout:
                raise RuntimeError(f"Render timed out after {timeout:.0f}s.")
            if now - last_advance > stall_timeout:
                raise RuntimeError(
                    f"Render stalled: FFmpeg made no frame/time progress for {stall_timeout:.0f}s. "
                    f"Last output time: {max(0, last_values['out_time_ms']) / 1_000_000:.1f}s."
                )
            try:
                proc.wait(timeout=min(0.5, stall_timeout, timeout))
            except subprocess.TimeoutExpired:
                pass
        returncode = proc.returncode
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    finally:
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
    if returncode != 0:
        raise RuntimeError(f"Render failed: {''.join(stderr_lines)[-800:]}")


def crop_boxes(frames: list[list[float]], src_w: int, src_h: int) -> list[tuple[int, int, int, int]]:
    """Director frames [x, y, w, h] → even-int (w, h, x, y) crop boxes,
    clamped in-bounds (openshorts crop_boxes rounding rules)."""
    boxes: list[tuple[int, int, int, int]] = []
    for x, y, w, h in frames:
        wi = max(2, min(int(w) - int(w) % 2, src_w))
        hi = max(2, min(int(h) - int(h) % 2, src_h))
        xi = max(0, min(int(round(x)), src_w - wi))
        yi = max(0, min(int(round(y)), src_h - hi))
        boxes.append((wi, hi, xi - xi % 2, yi - yi % 2))
    return boxes


def sendcmd_lines(boxes: list[tuple[int, int, int, int]], fps: float, target: str = "crop@c") -> list[str]:
    """Per-frame w/h/x/y commands, deduped to change-points (openshorts)."""
    lines: list[str] = []
    prev: tuple[int, int, int, int] | None = None
    for i, box in enumerate(boxes):
        if box == prev:
            continue
        t = i / fps
        w, h, x, y = box
        pw, ph, px, py = prev if prev else (None, None, None, None)
        if w != pw:
            lines.append(f"{t:.4f} {target} w {w};")
        if h != ph:
            lines.append(f"{t:.4f} {target} h {h};")
        if x != px:
            lines.append(f"{t:.4f} {target} x {x};")
        if y != py:
            lines.append(f"{t:.4f} {target} y {y};")
        prev = box
    return lines


def _q(path: str) -> str:
    """ffmpeg filter-option quoting: single quotes make the value literal;
    an embedded quote closes, escapes, reopens ('\\'').

    Windows adds two wrinkles the mac path never sees: backslash is
    ffmpeg's escape character even inside quotes (av_get_token), and the
    drive-letter colon reads as an option separator on some parse levels.
    Forward slashes (fine for libass and every filter) plus an escaped
    colon is the canonical portable form: 'C\\:/Users/…/clip.ass'."""
    text = str(path)
    if os.name == "nt":
        text = text.replace("\\", "/").replace(":", "\\:")
    return "'" + text.replace("'", "'\\''") + "'"


def render_clip(
    media_path: str,
    out_path: Path,
    clip_start: float,
    clip_end: float,
    trajectory: dict,
    ass_path: Path | None,
    fonts_dir: Path | None,
    lufs: float = -14.0,
    true_peak: float = -1.0,
    src_w: int = 1920,
    src_h: int = 1080,
    timeout: float = 1800.0,
    progress: Callable[[float], None] | None = None,
    retained_ranges: list[tuple[float, float]] | None = None,
    crossfades_ms: list[int] | None = None,
) -> None:
    ranges = retained_ranges or [(clip_start, clip_end)]
    if not ranges or any(b <= a for a, b in ranges) or any(a2 < b1 for (_, b1), (a2, _) in zip(ranges, ranges[1:])):
        raise ValueError("retained ranges must be ordered, non-overlapping, and positive")
    if ranges[0][0] < clip_start or ranges[-1][1] > clip_end:
        raise ValueError("retained ranges must stay inside the clip")
    duration = sum(b - a for a, b in ranges)
    boxes = crop_boxes(trajectory["frames"], src_w, src_h)
    if not boxes:
        boxes = [(src_h * 9 // 16 // 2 * 2, src_h - src_h % 2, 0, 0)]
    fps = float(trajectory.get("fps", 25))

    cmd_path = out_path.with_suffix(".cmd")
    cmd_path.write_text("\n".join(sendcmd_lines(boxes, fps)) + "\n")

    w0, h0, x0, y0 = boxes[0]

    use_cuda = cuda_scale_available() and nvenc_available()

    if use_cuda:
        # Dynamic crop on CPU, scale on CUDA, CPU subtitle burn, NVENC encode.
        vf_parts = [
            f"sendcmd=f={_q(cmd_path)}",
            f"crop@c=w={w0}:h={h0}:x={x0}:y={y0}",
            scale_filter(),
            "setsar=1",
        ]
        if ass_path is not None:
            sub = f"subtitles=filename={_q(ass_path)}"
            if fonts_dir is not None:
                sub += f":fontsdir={_q(fonts_dir)}"
            vf_parts.append(sub)
        vcodec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(X264_CRF)]
        hwaccel_args = []
    else:
        vf_parts = [
            f"sendcmd=f={_q(cmd_path)}",
            f"crop@c=w={w0}:h={h0}:x={x0}:y={y0}",
            f"scale={OUT_W}:{OUT_H},format=yuv420p",
            "setsar=1",
        ]
        if ass_path is not None:
            sub = f"subtitles=filename={_q(ass_path)}"
            if fonts_dir is not None:
                sub += f":fontsdir={_q(fonts_dir)}"
            vf_parts.append(sub)
        hwaccel_args = []

        if nvenc_available():
            vcodec = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(X264_CRF)]
        elif videotoolbox_available():
            vcodec = ["-c:v", "h264_videotoolbox", "-b:v", VT_BITRATE, "-allow_sw", "1"]
        else:
            vcodec = ["-c:v", "libx264", "-preset", "medium", "-crf", str(X264_CRF)]

    if ranges == [(clip_start, clip_end)]:
        args = [
            ffmpeg_bin.ffmpeg(), "-nostdin", "-y", "-v", "error",
            *hwaccel_args,
            "-ss", f"{clip_start:.3f}", "-t", f"{duration:.3f}",
            "-i", media_path,
            "-vf", ",".join(vf_parts),
            "-af", f"loudnorm=I={lufs}:TP={true_peak}:LRA=11",
            *vcodec,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart", "-map_metadata", "-1",
            "-progress", "pipe:1", "-nostats", str(out_path),
        ]
    else:
        span_a, span_b = ranges[0][0], ranges[-1][1]
        graph: list[str] = []
        for i, (a, b) in enumerate(ranges):
            ra, rb = a - span_a, b - span_a
            graph.append(f"[0:v]trim=start={ra:.3f}:end={rb:.3f},setpts=PTS-STARTPTS[v{i}]")
            graph.append(f"[0:a]atrim=start={ra:.3f}:end={rb:.3f},asetpts=PTS-STARTPTS[a{i}]")
        graph.append("".join(f"[v{i}]" for i in range(len(ranges))) + f"concat=n={len(ranges)}:v=1:a=0[vc]")
        audio_label = "a0"
        fades = crossfades_ms or []
        for i in range(1, len(ranges)):
            output_label = f"aj{i}"
            fade_ms = max(0, min(80, int(fades[i - 1] if i - 1 < len(fades) else 0)))
            if fade_ms:
                # No overlap: adjacent short fades suppress discontinuities
                # without smearing separate spoken words or shortening audio.
                graph.append(f"[{audio_label}][a{i}]acrossfade=d={fade_ms / 1000:.3f}:o=0:c1=tri:c2=tri[{output_label}]")
            else:
                graph.append(f"[{audio_label}][a{i}]concat=n=2:v=0:a=1[{output_label}]")
            audio_label = output_label
        graph.append(f"[vc]{','.join(vf_parts)}[vo]")
        graph.append(f"[{audio_label}]loudnorm=I={lufs}:TP={true_peak}:LRA=11[ao]")
        args = [
            ffmpeg_bin.ffmpeg(), "-nostdin", "-y", "-v", "error", *hwaccel_args,
            "-ss", f"{span_a:.3f}", "-t", f"{span_b - span_a:.3f}", "-i", media_path,
            "-filter_complex", ";".join(graph), "-map", "[vo]", "-map", "[ao]",
            *vcodec, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-shortest", "-movflags", "+faststart", "-map_metadata", "-1",
            "-progress", "pipe:1", "-nostats", str(out_path),
        ]
    _run_ffmpeg(args, duration, timeout, progress)
    cmd_path.unlink(missing_ok=True)


def verify_output(out_path: Path, expected_duration: float) -> dict:
    """Post-render sanity: exists, has both streams, duration within 1.5 s."""
    proc = subprocess.run(
        [
            ffmpeg_bin.ffprobe(), "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(out_path),
        ],
        capture_output=True, text=True, timeout=120,
    )
    import json

    info = json.loads(proc.stdout or "{}")
    streams = info.get("streams", [])
    has_v = any(s.get("codec_type") == "video" for s in streams)
    has_a = any(s.get("codec_type") == "audio" for s in streams)
    duration = float(info.get("format", {}).get("duration", 0.0))
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
    video_duration = float(video.get("duration", duration) or duration)
    audio_duration = float(audio.get("duration", duration) or duration)
    av_sync_delta = abs(video_duration - audio_duration)
    return {
        "ok": has_v and has_a and abs(duration - expected_duration) < 1.5 and av_sync_delta < .12,
        "duration": duration,
        "video_duration": video_duration, "audio_duration": audio_duration,
        "av_sync_delta": av_sync_delta,
        "width": video.get("width"),
        "height": video.get("height"),
    }
