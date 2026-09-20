"""Sparse whole-Short OCR, layout, and source-visual evidence stage."""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import tempfile
import time
from pathlib import Path
from statistics import median
from typing import Any

from ..jobs.queue import Stage, StageContext, StageError
from .captions import build_caption_system, measure_text_style
from .core import classify_text_tracks, merge_ocr_detections, normalize_bbox, normalize_layout_signature


SAMPLE_INTERVAL_SEC = 1.0
MAX_SAMPLES = 64
OCR_MIN_CONFIDENCE = 0.45


def _media_path(job_dir: Path, ingest: dict[str, Any]) -> Path:
    raw = Path(str(ingest.get("media_path") or "media.mkv").replace("\\", "/"))
    return raw if raw.exists() else job_dir / raw.name


def _timestamps(duration: float, scenes: list[float]) -> list[float]:
    regular = [0.25 + index * SAMPLE_INTERVAL_SEC for index in range(max(1, int(duration // SAMPLE_INTERVAL_SEC) + 1))]
    # Scene boundaries are consumed directly as source-edit evidence. OCR and
    # face observations stay on a bounded regular cadence to avoid frame-wise
    # inference and make runtime predictable for larger batches.
    values = sorted({round(max(0.0, min(duration - 0.01, value)), 3) for value in regular if 0 <= value < duration})
    if len(values) <= MAX_SAMPLES:
        return values
    return [values[round(i * (len(values) - 1) / (MAX_SAMPLES - 1))] for i in range(MAX_SAMPLES)]


def _largest_run(mask: Any) -> tuple[int, int]:
    best = (0, 0)
    start = None
    for index, active in enumerate([*mask, False]):
        if active and start is None:
            start = index
        elif not active and start is not None:
            if index - start > best[1] - best[0]:
                best = (start, index)
            start = None
    return best


def estimate_content_bbox(frame: Any) -> dict[str, float]:
    """Find the largest non-flat row/column region, excluding title glyph islands."""
    import cv2
    import numpy as np

    small = cv2.resize(frame, (180, 320), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
    row_active = (gray.mean(axis=1) > 17.0) | (gray.std(axis=1) > 19.0)
    y1, y2 = _largest_run(row_active)
    region = gray[y1:y2] if y2 > y1 else gray
    col_active = (region.mean(axis=0) > 12.0) | (region.std(axis=0) > 16.0)
    x1, x2 = _largest_run(col_active)
    if (y2 - y1) < gray.shape[0] * 0.25:
        y1, y2 = 0, gray.shape[0]
    if (x2 - x1) < gray.shape[1] * 0.25:
        x1, x2 = 0, gray.shape[1]
    return {
        "x": round(x1 / gray.shape[1], 6), "y": round(y1 / gray.shape[0], 6),
        "width": round((x2 - x1) / gray.shape[1], 6), "height": round((y2 - y1) / gray.shape[0], 6),
    }


def _median_layout(boxes: list[dict[str, float]], width: int, height: int) -> dict[str, Any]:
    box = {key: round(median(item[key] for item in boxes), 6) for key in ("x", "y", "width", "height")}
    canvas_ratio = width / max(height, 1)
    content_ratio = width * box["width"] / max(1.0, height * box["height"])
    nearly_full = box["width"] >= 0.94 and box["height"] >= 0.92
    horizontal_bars = box["height"] < 0.88 and box["width"] >= 0.9
    if nearly_full:
        mode, background = "full_canvas", "none"
    elif horizontal_bars:
        label = "1:1" if abs(content_ratio - 1.0) < 0.1 else "3:4" if abs(content_ratio - 0.75) < 0.1 else "embedded"
        mode, background = f"centered_{label}_in_9:16", "letterbox_bars"
    elif box["width"] < 0.88:
        mode, background = "pillarboxed_content", "pillarbox_bars"
    else:
        mode, background = "foreground_over_background", "canvas_background"
    return {
        "canvas_aspect_ratio": round(canvas_ratio, 6), "primary_content_bbox": box,
        "primary_content_aspect_ratio": round(content_ratio, 6), "layout_mode": mode,
        "approximate_shape": "rectangle", "rounded_corners": False, "split_screen": False,
        "background_relationship": background, "confidence": 0.88 if nearly_full or horizontal_bars else 0.68,
        "provenance": {"detector": "opencv-row-column-content-bounds", "version": 1},
    }


def _layout_changes(samples: list[tuple[float, dict[str, float]]]) -> list[dict[str, Any]]:
    changes = []
    for (timestamp, current), (_, previous) in zip(samples[1:], samples):
        delta = max(abs(current[key] - previous[key]) for key in ("x", "y", "width", "height"))
        if delta >= 0.08:
            changes.append({"start": timestamp, "end": timestamp, "confidence": round(min(0.95, 0.55 + delta), 4), "from_bbox": previous, "to_bbox": current})
    return changes


class SourceAnalysisStage(Stage):
    name = "source_analysis"
    schema_version = 9

    def run(self, ctx: StageContext) -> dict:
        import cv2
        from rapidocr_onnxruntime import RapidOCR

        from ..camera.detect import FaceDetector, MODEL_H, MODEL_W
        from ..models import registry, specs

        prior = ctx.prior or {}
        ingest = prior.get("ingest")
        asr = prior.get("asr") or {}
        if not ingest:
            raise StageError("Source analysis needs the ingest stage output.")
        media = _media_path(ctx.job_dir, ingest)
        if not media.exists():
            raise StageError("Source media missing — re-run ingest.")
        probe = ingest.get("probe") or {}
        duration = float(probe.get("duration_sec") or 0)
        width, height = int(probe.get("width") or 0), int(probe.get("height") or 0)
        if duration <= 0 or width <= 0 or height <= 0:
            raise StageError("Source analysis needs valid video duration and dimensions.")

        scenes_path = ctx.job_dir / "scenes.json"
        scenes: list[float] = []
        scene_detector_outcome = "success_no_detections"
        scene_detector_error = None
        if scenes_path.exists():
            try:
                loaded_scenes = json.loads(scenes_path.read_text())
                scenes = [float(value) for value in loaded_scenes if isinstance(value, (int, float))]
                if scenes:
                    scene_detector_outcome = "success_with_detections"
            except (OSError, ValueError, TypeError):
                scenes = []
        else:
            # Normal clipping gets this artifact from CandidatesStage. Research
            # intentionally skips candidates, so reuse the same source detector
            # here without turning its lack of detections into a job failure.
            try:
                from ..candidates.stage import detect_scenes

                scenes = detect_scenes(str(media))
                scene_detector_outcome = "success_with_detections" if scenes else "success_no_detections"
            except Exception as err:  # noqa: BLE001 - source scene evidence may degrade
                scene_detector_outcome = "unavailable"
                scene_detector_error = f"{type(err).__name__}: {err}"
                scenes = []
            try:
                scenes_path.write_text(json.dumps(scenes))
            except OSError:
                pass
        sample_times = _timestamps(duration, scenes)
        ctx.emit(-1, f"Loading source OCR and sparse vision models ({len(sample_times)} samples)…")
        ocr = RapidOCR()
        face_model = registry.ensure(specs.ULTRAFACE, lambda f, m: ctx.emit(-1, m))
        face_detector = FaceDetector(str(face_model))
        face_providers = face_detector.session.get_providers()
        execution_device = "mixed: OCR CPU + vision CUDA" if "CUDAExecutionProvider" in face_providers else "CPU"
        detector_version = importlib.metadata.version("rapidocr-onnxruntime")

        raw_ocr: list[dict[str, Any]] = []
        raw_text_styles: list[dict[str, Any]] = []
        raw_visual: list[dict[str, Any]] = []
        raw_visual_semantics: list[dict[str, Any]] = []
        semantic_runtime: dict[str, Any] = {}
        semantic_error = None
        layout_samples: list[tuple[float, dict[str, float]]] = []
        ocr_runtime = layout_runtime = visual_runtime = 0.0
        # OpenCV's bundled decoder can fail on AV1 even when the project's
        # ffmpeg supports it. Decode one sparse pass with ffmpeg into a scoped
        # temporary directory, then run all detectors over those same frames.
        with tempfile.TemporaryDirectory(prefix="publikclip-source-analysis-") as temp_dir:
            pattern = str(Path(temp_dir) / "sample-%05d.jpg")
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", "0.25", "-i", str(media),
                "-vf", f"fps=1/{SAMPLE_INTERVAL_SEC},scale=720:-2", "-frames:v", str(len(sample_times)),
                "-q:v", "3", pattern,
            ]
            try:
                subprocess.run(command, capture_output=True, text=True, timeout=max(60, int(duration * 3)), check=True)
            except (OSError, subprocess.SubprocessError) as err:
                detail = getattr(err, "stderr", "") or str(err)
                raise StageError(f"Could not decode sparse source samples: {detail[-300:]}") from err
            frame_paths = sorted(Path(temp_dir).glob("sample-*.jpg"))
            if not frame_paths:
                raise StageError("Could not decode source video for visual analysis.")
            for sample_index, (timestamp, frame_path) in enumerate(zip(sample_times, frame_paths)):
                frame = cv2.imread(str(frame_path))
                if frame is None:
                    continue
                actual_h, actual_w = frame.shape[:2]
                begin = time.monotonic()
                content_box = estimate_content_bbox(frame)
                layout_runtime += time.monotonic() - begin
                layout_samples.append((timestamp, content_box))

                # 720 px retains the title/subtitle geometry while bounding OCR cost.
                scale = min(1.0, 720.0 / actual_w)
                ocr_frame = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
                begin = time.monotonic()
                result, _ = ocr(ocr_frame)
                ocr_runtime += time.monotonic() - begin
                for row in result or []:
                    if not isinstance(row, (list, tuple)) or len(row) < 3:
                        continue
                    polygon, text, confidence = row[0], str(row[1]).strip(), float(row[2])
                    if not text or confidence < OCR_MIN_CONFIDENCE:
                        continue
                    detection = {
                        "id": f"ocr-{sample_index:03d}-{len(raw_ocr):04d}", "timestamp": timestamp,
                        "text": text, "confidence": round(confidence, 4),
                        "bbox": normalize_bbox(polygon, ocr_frame.shape[1], ocr_frame.shape[0]),
                        "provenance": {"detector": "RapidOCR/PP-OCRv3", "version": detector_version},
                    }
                    raw_ocr.append(detection)
                    raw_text_styles.append({
                        "source_detection_id": detection["id"], "timestamp": timestamp,
                        **measure_text_style(ocr_frame, detection["bbox"]),
                        "provenance": {"detector": "opencv-ocr-crop-style", "version": 1},
                    })

                begin = time.monotonic()
                rgb = cv2.cvtColor(cv2.resize(frame, (MODEL_W, MODEL_H)), cv2.COLOR_BGR2RGB)
                faces = face_detector.detect(rgb)
                visual_runtime += time.monotonic() - begin
                raw_visual.append({
                    "timestamp": timestamp, "face_count": len(faces),
                    "faces": [{"bbox": {"x": round(face.x1, 6), "y": round(face.y1, 6), "width": round(face.x2 - face.x1, 6), "height": round(face.y2 - face.y1, 6)}, "confidence": round(face.score, 4)} for face in faces],
                    "provenance": {"detector": "UltraFace-RFB-320", "version": "clip-forge-export"},
                })
                ctx.emit((sample_index + 1) / len(sample_times), f"Analyzing source sample {sample_index + 1}/{len(sample_times)}…")

            if (getattr(ctx.job, "job_mode", "clipping") or "clipping") == "research":
                detector = None
                try:
                    from .visual import ClipSemanticDetector, representative_sample_times, shot_intervals

                    selected_times = representative_sample_times(shot_intervals(duration, scenes), sample_times)
                    path_by_time = {timestamp: path for timestamp, path in zip(sample_times, frame_paths)}
                    selected = [(timestamp, path_by_time[timestamp]) for timestamp in selected_times if timestamp in path_by_time]
                    if selected:
                        ctx.emit(-1, f"Loading sparse visual semantics ({len(selected)} representative frames)…")
                        detector = ClipSemanticDetector()
                        raw_visual_semantics, semantic_runtime = detector.analyze(
                            [path for _, path in selected], [timestamp for timestamp, _ in selected]
                        )
                except Exception as err:  # noqa: BLE001 - semantics degrade to conservative visual units
                    semantic_error = f"{type(err).__name__}: {err}"
                finally:
                    if detector is not None:
                        detector.unload()

        if not layout_samples:
            raise StageError("Sparse source frames could not be analyzed.")

        source_layout = _median_layout([item[1] for item in layout_samples], width, height)
        tracks = merge_ocr_detections(
            raw_ocr, sample_interval=SAMPLE_INTERVAL_SEC, video_duration=duration,
            detector="RapidOCR/PP-OCRv3", detector_version=detector_version,
        )
        transcript = " ".join(str(segment.get("text") or "") for segment in asr.get("segments") or [])
        tracks, title_candidates, text_blocks = classify_text_tracks(
            tracks, source_layout["primary_content_bbox"], duration, transcript, include_blocks=True,
        )
        signature = normalize_layout_signature(source_layout, title_candidates)

        observations = []
        for item in raw_visual:
            largest = max((face["bbox"]["width"] * face["bbox"]["height"] for face in item["faces"]), default=0.0)
            if item["face_count"]:
                observations.append({
                    "start": item["timestamp"], "end": min(duration, item["timestamp"] + SAMPLE_INTERVAL_SEC),
                    "type": "talking_head_likely" if largest >= 0.08 else "face_present",
                    "face_count": item["face_count"], "confidence": max(face["confidence"] for face in item["faces"]),
                    "evidence": {"largest_face_area_ratio": round(largest, 6)},
                    "provenance": {"detector": "UltraFace-RFB-320", "interpretation": "face-size-rules-v1"},
                })
        layout_changes = _layout_changes(layout_samples)
        # PySceneDetect returns the first scene's 0.0 start; that is not a cut.
        cut_times = [value for value in scenes if value > 0.05]
        from .visual import build_visual_understanding

        diarize = prior.get("diarize") or {}
        transcript_segments = diarize.get("segments") or asr.get("segments") or []
        visual_understanding = build_visual_understanding(
            duration=duration, scene_times=scenes, raw_faces=raw_visual,
            semantic_observations=raw_visual_semantics, raw_ocr=raw_ocr,
            transcript_segments=transcript_segments, layout=source_layout,
            semantic_runtime=semantic_runtime, semantic_error=semantic_error,
        )
        caption_system = build_caption_system(
            tracks=tracks, title_candidates=title_candidates, raw_ocr_detections=raw_ocr,
            text_style_observations=raw_text_styles, transcript_segments=transcript_segments,
            visual_units=visual_understanding.get("visual_units") or [], duration=duration,
        )
        from ..events.intelligence import build_audio_intelligence

        events = prior.get("events") or {}
        try:
            curves = json.loads((ctx.job_dir / "curves.json").read_text())
            curves = curves.get("data", curves) if isinstance(curves, dict) else {}
        except (OSError, ValueError, TypeError):
            curves = {}
        audio_started = time.monotonic()
        audio_intelligence = build_audio_intelligence(
            duration=duration, transcript_segments=transcript_segments,
            legacy_events=events.get("timeline") or [],
            raw_audio_observations=events.get("raw_audio_observations") or [], curves=curves,
            visual_units=visual_understanding.get("visual_units") or [], shot_cuts=cut_times,
            caption_emphasis_events=caption_system.get("emphasis_events") or [],
            text_tracks=tracks,
            panns_intelligence_available="raw_audio_observations" in events,
        )
        audio_intelligence_sec = time.monotonic() - audio_started
        from .editing import build_source_editing

        source_editing = build_source_editing(
            duration=duration, scene_times=scenes, scene_detector_outcome=scene_detector_outcome,
            layout_changes=layout_changes,
            visual_units=visual_understanding.get("visual_units") or [],
            caption_tracks=caption_system.get("caption_tracks") or [],
            overlays=caption_system.get("overlays") or [],
            emphasis_events=caption_system.get("emphasis_events") or [],
            audio_events=[
                *(audio_intelligence.get("sfx_events") or []),
                *(audio_intelligence.get("music_segments") or []),
                *(audio_intelligence.get("audio_segments") or []),
            ],
        )
        from .story import build_story_semantics

        story_client = None
        story_llm_error = None
        story_started = time.monotonic()
        if ctx.settings.llm_mode != "manual":
            try:
                from ..scoring.llm import make_client

                story_client = make_client(
                    ctx.settings.llm_mode,
                    gemini_model=ctx.settings.gemini_model,
                    ollama_model=ctx.settings.ollama_model,
                    ollama_base_url=ctx.settings.ollama_base_url,
                    # Story annotations can cover up to 28 transcript units;
                    # retain the user's larger cap but avoid truncating the
                    # bounded structured response at the scoring default.
                    ollama_num_predict=max(2048, ctx.settings.ollama_num_predict),
                )
            except Exception as err:  # noqa: BLE001 - story semantics has a deterministic fallback
                story_llm_error = f"{type(err).__name__}: {err}"
        try:
            ctx.emit(-1, "Building semantic and story timeline…")
            story_semantics = build_story_semantics(
                duration=duration, transcript_segments=transcript_segments,
                source_editing=source_editing,
                visual_units=visual_understanding.get("visual_units") or [],
                caption_tracks=caption_system.get("caption_tracks") or [],
                emphasis_events=caption_system.get("emphasis_events") or [],
                title_hooks=title_candidates,
                audio_events=[
                    *(audio_intelligence.get("sfx_events") or []),
                    *(audio_intelligence.get("music_segments") or []),
                    *(audio_intelligence.get("audio_segments") or []),
                ],
                llm_client=story_client,
            )
        finally:
            if story_client is not None:
                story_client.unload()
        if story_llm_error:
            story_semantics["provenance"]["llm_error"] = story_llm_error
            story_semantics["limitations"].append("Configured semantic LLM was unavailable; deterministic transcript rules were used.")
        story_semantics_sec = time.monotonic() - story_started
        # Keep the legacy source-analysis view while making every cut addressable.
        editing = {
            "shot_cuts": [
                {
                    "id": item["id"], "start": item["start_ms"] / 1000, "end": item["end_ms"] / 1000,
                    "confidence": item["confidence"], "source": item["source"], "status": item["status"],
                    "evidence": item["evidence"],
                }
                for item in source_editing["cuts"]
            ],
            "visual_change_density_per_minute": source_editing["metrics"]["visual_change_cadence_per_minute"],
            "layout_changes": layout_changes, "b_roll_candidates": [],
            "provenance": {"source_artifact": "scenes.json", "note": "Generated camera trajectories are excluded."},
        }
        return {
            "schema_version": 9, "sample_interval_sec": SAMPLE_INTERVAL_SEC, "sample_timestamps": sample_times,
            "raw_ocr_detections": raw_ocr, "text_tracks": tracks, "text_blocks": text_blocks,
            "title_hook_candidates": title_candidates,
            "source_layout": source_layout, "layout_signature": signature,
            "raw_visual_observations": raw_visual, "raw_visual_semantic_observations": raw_visual_semantics,
            "raw_text_style_observations": raw_text_styles,
            "visual_observations": observations, "visual_understanding": visual_understanding,
            "caption_system": caption_system, "audio_intelligence": audio_intelligence,
            "source_editing": source_editing, "story_semantics": story_semantics,
            "source_editing_evidence": editing,
            "runtime": {
                "ocr_sec": round(ocr_runtime, 4), "layout_sec": round(layout_runtime, 4),
                "visual_sampling_sec": round(visual_runtime, 4), "sample_count": len(sample_times),
                "visual_semantic_sec": semantic_runtime.get("runtime_sec"),
                "visual_semantic_sample_count": semantic_runtime.get("sampled_frames", 0),
                "visual_semantic_inference_batches": semantic_runtime.get("inference_batches", 0),
                "visual_semantic_peak_gpu_memory_bytes": semantic_runtime.get("peak_gpu_memory_bytes"),
                "audio_intelligence_sec": round(audio_intelligence_sec, 4),
                "story_semantics_sec": round(story_semantics_sec, 4),
                "device": execution_device, "onnx_providers": face_providers, "ocr_max_input_width": 720,
            },
            "device": execution_device, "onnx_providers": face_providers,
            "provenance": {
                "source_artifact": str(media.name), "run_job_id": ctx.job.id,
                "scene_detector_outcome": scene_detector_outcome,
                "scene_detector_error": scene_detector_error,
                "config": {"sample_interval_sec": SAMPLE_INTERVAL_SEC, "max_samples": MAX_SAMPLES, "ocr_min_confidence": OCR_MIN_CONFIDENCE, "semantic_max_frames": 24},
            },
        }
