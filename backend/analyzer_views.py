"""Read-only presentation helpers for persisted Analyzer artifacts.

The checkpoint files remain the source of truth.  This module only selects
and normalizes fields that the creator-facing UI can safely display.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse


SHORT_FORM_MAX_SECONDS = 180.0


def _read_envelope(job_dir: Path, name: str) -> tuple[dict[str, Any] | list[Any] | None, float | None]:
    path = job_dir / f"{name}.json"
    try:
        payload = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError, TypeError):
        return None, None
    if isinstance(payload, dict) and "data" in payload:
        created_at = payload.get("created_at")
        return payload.get("data"), float(created_at) if isinstance(created_at, (int, float)) else None
    return payload, None


def _media_url(job_id: str, relative: str) -> str:
    return f"/media/jobs/{job_id}/{relative.lstrip('/')}"


def _metadata(job_dir: Path) -> dict[str, Any]:
    candidates = [job_dir / "media.info.json", *job_dir.glob("media*.info.json"), job_dir / "media.json"]
    for path in candidates:
        if not path.exists():
            continue
        try:
            value = json.loads(path.read_text(errors="replace"))
            value = value.get("data", value) if isinstance(value, dict) else {}
            if isinstance(value, dict):
                return value
        except (OSError, ValueError, TypeError):
            continue
    return {}


def _source_platform(source: str | None, metadata: dict[str, Any]) -> str | None:
    extractor = str(metadata.get("extractor_key") or metadata.get("extractor") or "").lower()
    if "youtube" in extractor:
        return "YouTube"
    if "tiktok" in extractor:
        return "TikTok"
    if "instagram" in extractor:
        return "Instagram"
    if source and source.startswith(("http://", "https://")):
        host = (urlparse(source).hostname or "").lower()
        if "youtu" in host:
            return "YouTube"
        if "tiktok" in host:
            return "TikTok"
        if "instagram" in host:
            return "Instagram"
    return None


def _title(job: Any, ingest: dict[str, Any], metadata: dict[str, Any]) -> str | None:
    values = [metadata.get("fulltitle"), metadata.get("title"), getattr(job, "title", None), ingest.get("title")]
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() not in {"media", "video", "watch"} and not text.lower().startswith("watch?v="):
            return text
    return None


def _thumbnail(job_id: str, job_dir: Path, metadata: dict[str, Any]) -> str | None:
    local_names = ["thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png", "media.jpg", "media.webp"]
    for name in local_names:
        if (job_dir / name).exists():
            return _media_url(job_id, name)
    thumbnail = metadata.get("thumbnail") or metadata.get("thumbnail_url")
    if isinstance(thumbnail, str) and thumbnail.startswith(("http://", "https://")):
        return thumbnail
    thumbnails = metadata.get("thumbnails")
    if isinstance(thumbnails, list):
        for item in reversed(thumbnails):
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                return item["url"]
    return None


def _job_source_provenance(job: Any) -> dict[str, Any]:
    try:
        provenance = json.loads(getattr(job, "source_provenance_json", None) or "{}")
    except (TypeError, ValueError):
        provenance = {}
    return provenance if isinstance(provenance, dict) else {}


def _source(job: Any, ingest: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    provenance = _job_source_provenance(job)
    catalog = provenance.get("catalog_metadata") if isinstance(provenance.get("catalog_metadata"), dict) else {}
    media_name = str(ingest.get("media_path") or "media.mkv").replace("\\", "/").split("/")[-1]
    source_value = getattr(job, "source", None)
    source_url = source_value if isinstance(source_value, str) and source_value.startswith(("http://", "https://")) else None
    return {
        "title": _title(job, ingest, metadata) or provenance.get("catalog_title"),
        "type": getattr(job, "source_type", None),
        "platform": provenance.get("platform") or _source_platform(source_url, metadata),
        "source_url": metadata.get("webpage_url") or metadata.get("original_url") or provenance.get("canonical_url") or source_url,
        "canonical_url": provenance.get("canonical_url") or metadata.get("webpage_url") or metadata.get("original_url") or source_url,
        "external_video_id": provenance.get("external_video_id"),
        "creator_source_id": provenance.get("creator_source_id"),
        "creator_video_id": provenance.get("creator_video_id"),
        "creator": provenance.get("creator") if isinstance(provenance.get("creator"), dict) else None,
        "content_type": catalog.get("content_type"),
        "tab_origin": catalog.get("tab_origin"),
        "catalog_metadata": catalog,
        "video_url": _media_url(job.id, media_name) if (job.dir / media_name).exists() else None,
        "thumbnail_url": _thumbnail(job.id, job.dir, metadata),
    }


def _downsample(values: Any, limit: int = 160) -> list[float]:
    if not isinstance(values, list):
        return []
    clean = [float(value) for value in values if isinstance(value, (int, float))]
    if len(clean) <= limit:
        return clean
    step = len(clean) / limit
    return [clean[min(len(clean) - 1, int(index * step))] for index in range(limit)]


def _curve(name: str, values: Any, grid_sec: float | None) -> dict[str, Any]:
    clean = [float(value) for value in values] if isinstance(values, list) else []
    return {
        "name": name,
        "values": _downsample(clean),
        "sample_count": len(clean),
        "grid_sec": grid_sec,
        "min": min(clean) if clean else None,
        "max": max(clean) if clean else None,
        "mean": sum(clean) / len(clean) if clean else None,
    }


def _trajectory(job: Any, index: str, path_value: Any) -> dict[str, Any] | None:
    path = Path(str(path_value)) if path_value else job.dir / f"trajectory_{int(index):02d}.json"
    if not path.exists():
        path = job.dir / path.name
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (OSError, ValueError, TypeError):
        return None
    fps = float(data.get("fps") or 0)
    clip_start = float(data.get("clip_start") or 0)
    frames = data.get("frames") if isinstance(data.get("frames"), list) else []
    widths = [float(frame[2]) for frame in frames if isinstance(frame, list) and len(frame) >= 4 and isinstance(frame[2], (int, float))]
    cuts = [clip_start + float(frame) / fps for frame in data.get("cuts", []) if fps and isinstance(frame, (int, float))]
    punches = []
    for punch in data.get("punches", []):
        if not isinstance(punch, dict):
            continue
        start = float(punch.get("start") or 0)
        end = float(punch.get("end") or start)
        punches.append({**punch, "source_start": clip_start + start, "source_end": clip_start + end})
    return {
        "clip": int(index),
        "clip_start": clip_start,
        "clip_end": data.get("clip_end"),
        "fps": fps or None,
        "frame_count": len(frames),
        "cuts": cuts,
        "punches": punches,
        "meta": data.get("meta") or {},
        "crop_summary": {
            "min_width": min(widths) if widths else None,
            "max_width": max(widths) if widths else None,
        },
    }


def _qa_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = dict(row)
        for source_name, target_name in (("original_json", "original"), ("corrected_json", "corrected")):
            raw = item.pop(source_name, None)
            try:
                item[target_name] = json.loads(raw) if raw is not None else None
            except (TypeError, ValueError):
                item[target_name] = None
        result.append(item)
    return result


def _analysis_run(job: Any, analyzed_at: float | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    from publikclip_pipeline import analysis_runs

    run = analysis_runs.latest_analysis_run(job.id)
    if run is not None:
        return analysis_runs.public_run(run), analysis_runs.read_video_dna(job, run)
    legacy = {
        "analysis_run_id": f"legacy-{job.id}", "job_id": job.id,
        "creator_video_id": _job_source_provenance(job).get("creator_video_id"),
        "source_identity": None, "analyzer_version": "legacy",
        "schema_version": analysis_runs.VIDEO_DNA_SCHEMA_VERSION, "pipeline_version": None,
        "config_fingerprint": None, "status": "legacy_read_only", "artifact_path": None,
        "started_at": None, "completed_at": analyzed_at, "created_at": getattr(job, "created_at", None),
        "error": None,
    }
    return legacy, None


def _performance(job: Any) -> dict[str, Any]:
    provenance = _job_source_provenance(job)
    catalog = provenance.get("catalog_metadata") if isinstance(provenance.get("catalog_metadata"), dict) else {}
    metrics = {key: catalog.get(key) for key in ("views", "likes", "comments") if catalog.get(key) is not None}
    manual = catalog.get("manual_performance_label")
    derived = catalog.get("derived_performance_label")
    return {
        "metrics": metrics, "classification": manual or derived,
        "manual": bool(manual), "metric": catalog.get("performance_metric"),
        "origin": provenance.get("origin"),
    }


def _source_analysis_view(data: Any, ingest: dict[str, Any] | None = None, asr: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the stable Analyzer contract, never arbitrary checkpoint fields."""
    value = data if isinstance(data, dict) else {}
    # Rebuild only derived OCR interpretations for older checkpoints. This
    # makes the spacing/block fix visible immediately while retaining the raw
    # detector output and avoiding a forced media re-analysis.
    raw = value.get("raw_ocr_detections")
    layout_for_text = value.get("source_layout") if isinstance(value.get("source_layout"), dict) else None
    primary_bbox = layout_for_text.get("primary_content_bbox") if layout_for_text else None
    duration = ((ingest or {}).get("probe") or {}).get("duration_sec")
    if isinstance(raw, list) and raw and isinstance(primary_bbox, dict) and isinstance(duration, (int, float)):
        try:
            from publikclip_pipeline.source_analysis.core import classify_text_tracks, merge_ocr_detections

            tracks = merge_ocr_detections(
                raw, sample_interval=float(value.get("sample_interval_sec") or 1.0),
                video_duration=float(duration), detector="RapidOCR/PP-OCRv3", detector_version=None,
            )
            transcript = " ".join(str(segment.get("text") or "") for segment in (asr or {}).get("segments") or [])
            tracks, candidates, blocks = classify_text_tracks(
                tracks, primary_bbox, float(duration), transcript, include_blocks=True,
            )
            value = {**value, "text_tracks": tracks, "text_blocks": blocks, "title_hook_candidates": candidates}
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
    if not isinstance(value.get("caption_system"), dict) and isinstance(value.get("text_tracks"), list) and isinstance(duration, (int, float)):
        try:
            from publikclip_pipeline.source_analysis.captions import build_caption_system

            value = {
                **value,
                "caption_system": build_caption_system(
                    tracks=value["text_tracks"], title_candidates=value.get("title_hook_candidates") or [],
                    raw_ocr_detections=raw if isinstance(raw, list) else [],
                    text_style_observations=value.get("raw_text_style_observations") or [],
                    transcript_segments=(asr or {}).get("segments") or [],
                    visual_units=((value.get("visual_understanding") or {}).get("visual_units") or []),
                    duration=float(duration),
                ),
            }
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
    layout = value.get("source_layout") if isinstance(value.get("source_layout"), dict) else None
    signature = value.get("layout_signature") if isinstance(value.get("layout_signature"), dict) else None
    editing = value.get("source_editing_evidence") if isinstance(value.get("source_editing_evidence"), dict) else {}
    source_editing = value.get("source_editing") if isinstance(value.get("source_editing"), dict) else None
    runtime = value.get("runtime") if isinstance(value.get("runtime"), dict) else {}
    provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
    return {
        "text_tracks": value.get("text_tracks") if isinstance(value.get("text_tracks"), list) else [],
        "text_blocks": value.get("text_blocks") if isinstance(value.get("text_blocks"), list) else [],
        "title_hook_candidates": value.get("title_hook_candidates") if isinstance(value.get("title_hook_candidates"), list) else [],
        "source_layout": layout,
        "layout_signature": signature,
        "visual_observations": value.get("visual_observations") if isinstance(value.get("visual_observations"), list) else [],
        "visual_understanding": value.get("visual_understanding") if isinstance(value.get("visual_understanding"), dict) else None,
        "caption_system": value.get("caption_system") if isinstance(value.get("caption_system"), dict) else None,
        "audio_intelligence": value.get("audio_intelligence") if isinstance(value.get("audio_intelligence"), dict) else None,
        "source_editing": source_editing,
        "story_semantics": value.get("story_semantics") if isinstance(value.get("story_semantics"), dict) else None,
        "source_editing_evidence": {
            "shot_cuts": editing.get("shot_cuts") if isinstance(editing.get("shot_cuts"), list) else [],
            "visual_change_density_per_minute": editing.get("visual_change_density_per_minute"),
            "layout_changes": editing.get("layout_changes") if isinstance(editing.get("layout_changes"), list) else [],
            "b_roll_candidates": editing.get("b_roll_candidates") if isinstance(editing.get("b_roll_candidates"), list) else [],
            "provenance": editing.get("provenance") if isinstance(editing.get("provenance"), dict) else {},
        },
        "runtime": {
            "ocr_sec": runtime.get("ocr_sec"), "layout_sec": runtime.get("layout_sec"),
            "visual_sampling_sec": runtime.get("visual_sampling_sec"), "sample_count": runtime.get("sample_count"),
            "visual_semantic_sec": runtime.get("visual_semantic_sec"),
            "visual_semantic_sample_count": runtime.get("visual_semantic_sample_count"),
            "visual_semantic_inference_batches": runtime.get("visual_semantic_inference_batches"),
            "visual_semantic_peak_gpu_memory_bytes": runtime.get("visual_semantic_peak_gpu_memory_bytes"),
            "audio_intelligence_sec": runtime.get("audio_intelligence_sec"),
            "story_semantics_sec": runtime.get("story_semantics_sec"),
            "device": runtime.get("device"), "onnx_providers": runtime.get("onnx_providers") or [],
            "artifact_size_bytes": runtime.get("artifact_size_bytes"),
        },
        "provenance": provenance,
        "available": bool(value),
    }


def analyzer_summary(job: Any) -> dict[str, Any] | None:
    ingest, _ = _read_envelope(job.dir, "ingest")
    score, score_at = _read_envelope(job.dir, "score")
    source_analysis, source_analysis_at = _read_envelope(job.dir, "source_analysis")
    job_mode = getattr(job, "job_mode", "clipping") or "clipping"
    completion_artifact = source_analysis if job_mode == "research" else score
    if not isinstance(ingest, dict) or not isinstance(completion_artifact, dict) or getattr(job, "status", None) != "done":
        return None
    score = score if isinstance(score, dict) and job_mode != "research" else {}
    duration = (ingest.get("probe") or {}).get("duration_sec")
    if not isinstance(duration, (int, float)) or duration > SHORT_FORM_MAX_SECONDS:
        return None
    diarize, _ = _read_envelope(job.dir, "diarize")
    events, _ = _read_envelope(job.dir, "events")
    candidates, _ = _read_envelope(job.dir, "candidates")
    semantic_compression, _ = _read_envelope(job.dir, "semantic_compression")
    if job_mode == "research":
        candidates = None
    scenes, _ = _read_envelope(job.dir, "scenes")
    metadata = _metadata(job.dir)
    source = _source(job, ingest, metadata)
    counts = events.get("counts", {}) if isinstance(events, dict) else {}
    return {
        "job_id": job.id,
        "status": job.status,
        "created_at": job.created_at,
        "analyzed_at": source_analysis_at if job_mode == "research" else score_at,
        "duration_sec": float(duration),
        "job_mode": job_mode,
        "scoring_status": "available" if score else "unavailable",
        "source": source,
        "model": score.get("model"),
        "scene_count": len(scenes) if isinstance(scenes, list) else None,
        "speaker_count": diarize.get("speakers") if isinstance(diarize, dict) else None,
        "audio_event_count": sum(value for value in counts.values() if isinstance(value, int)),
        "candidate_count": candidates.get("count") if isinstance(candidates, dict) else None,
        "scored_count": score.get("scored_count"),
    }


def analyzer_detail(job: Any, qa_rows: Iterable[Any] = ()) -> dict[str, Any] | None:
    summary = analyzer_summary(job)
    if summary is None:
        return None
    ingest, _ = _read_envelope(job.dir, "ingest")
    asr, _ = _read_envelope(job.dir, "asr")
    diarize, _ = _read_envelope(job.dir, "diarize")
    events, _ = _read_envelope(job.dir, "events")
    curves, _ = _read_envelope(job.dir, "curves")
    scenes, _ = _read_envelope(job.dir, "scenes")
    candidates, _ = _read_envelope(job.dir, "candidates")
    score, _ = _read_envelope(job.dir, "score")
    camera, _ = _read_envelope(job.dir, "camera")
    render, _ = _read_envelope(job.dir, "render")
    source_analysis, _ = _read_envelope(job.dir, "source_analysis")

    ingest = ingest if isinstance(ingest, dict) else {}
    asr = asr if isinstance(asr, dict) else {}
    diarize = diarize if isinstance(diarize, dict) else {}
    events = events if isinstance(events, dict) else {}
    curves = curves if isinstance(curves, dict) else {}
    score = score if isinstance(score, dict) else {}
    camera = camera if isinstance(camera, dict) else {}
    render = render if isinstance(render, dict) else {}
    is_research = (getattr(job, "job_mode", "clipping") or "clipping") == "research"
    if is_research:
        # Old research runs may have candidate/edit artifacts on disk. They are
        # not whole-source evidence and are intentionally hidden from Video DNA.
        candidates = {}
        score = {}
        camera = {}
        render = {}

    transcript = diarize.get("segments") or asr.get("segments") or []
    curve_grid = curves.get("grid_sec")
    trajectory_items = []
    for index, path in (camera.get("trajectories") or {}).items():
        item = _trajectory(job, str(index), path)
        if item:
            trajectory_items.append(item)
    outputs = []
    for output in render.get("outputs") or []:
        if not isinstance(output, dict):
            continue
        output_path = Path(str(output.get("path") or ""))
        outputs.append({**output, "url": _media_url(job.id, f"clips/{output_path.name}") if output_path.name else None})

    source_analysis_view = _source_analysis_view(source_analysis, ingest, asr)
    try:
        source_analysis_view["runtime"]["artifact_size_bytes"] = (job.dir / "source_analysis.json").stat().st_size
    except OSError:
        pass

    if not isinstance(source_analysis_view.get("audio_intelligence"), dict):
        from publikclip_pipeline.events.intelligence import build_audio_intelligence

        visual_units = ((source_analysis_view.get("visual_understanding") or {}).get("visual_units") or [])
        caption_emphasis = ((source_analysis_view.get("caption_system") or {}).get("emphasis_events") or [])
        cut_times = [float(item.get("start")) for item in source_analysis_view["source_editing_evidence"]["shot_cuts"] if isinstance(item, dict) and isinstance(item.get("start"), (int, float))]
        if not cut_times and isinstance(scenes, list):
            cut_times = [float(value) for value in scenes if isinstance(value, (int, float)) and value > .05]
        source_analysis_view["audio_intelligence"] = build_audio_intelligence(
            duration=float(summary["duration_sec"]), transcript_segments=transcript,
            legacy_events=events.get("timeline") or [],
            raw_audio_observations=events.get("raw_audio_observations") or [], curves=curves,
            visual_units=visual_units, shot_cuts=cut_times,
            caption_emphasis_events=caption_emphasis,
            text_tracks=source_analysis_view.get("text_tracks") or [],
            panns_intelligence_available="raw_audio_observations" in events,
        )

    qa = _qa_rows(qa_rows)
    detail = {
        "job": {**summary, "error": getattr(job, "error", None)},
        "source": {**summary["source"], "probe": ingest.get("probe") or {}, "heatmap_available": bool(ingest.get("heatmap"))},
        "transcript": {
            "language": asr.get("language"),
            "model": asr.get("model"),
            "word_count": asr.get("word_count"),
            "segments": transcript,
        },
        "speakers": {"count": diarize.get("speakers"), "turns": diarize.get("turns") or []},
        "scenes": {
            "timestamps": scenes if isinstance(scenes, list) else [],
            "count": len(scenes) if isinstance(scenes, list) else None,
            "detector_outcome": (candidates.get("scene_detector_outcome") if isinstance(candidates, dict) else None) or source_analysis_view["provenance"].get("scene_detector_outcome"),
            "detector_error": (candidates.get("scene_detector_error") if isinstance(candidates, dict) else None) or source_analysis_view["provenance"].get("scene_detector_error"),
        },
        "audio": {
            "events": events.get("timeline") or [],
            "counts": events.get("counts") or {},
            "arousal_source": events.get("arousal_source"),
            "curves": [
                _curve("RMS", curves.get("rms"), curve_grid),
                _curve("Dynamics", curves.get("dynamics"), curve_grid),
                _curve("Arousal", curves.get("arousal"), curves.get("arousal_grid_sec")),
            ],
            "audio_intelligence": source_analysis_view.get("audio_intelligence"),
            "detector_benchmark": events.get("benchmark") or {},
        },
        "source_analysis": source_analysis_view,
        "candidate_analysis": {
            "candidate_count": candidates.get("count") if isinstance(candidates, dict) else None,
            "scored_count": score.get("scored_count"),
            "clips": score.get("clips") or [],
            "semantic_compression": semantic_compression if isinstance(semantic_compression, dict) else None,
        },
        "generated_edit": {
            "camera_settings": camera.get("camera_settings") or {},
            "camera_stats": camera.get("stats") or [],
            "device": camera.get("device"),
            "trajectories": trajectory_items,
            "render": {
                "outputs": outputs,
                "caption_preset": render.get("caption_preset"),
                "caption_color": render.get("caption_color"),
                "captions_burned": render.get("captions_burned"),
                "acceleration": render.get("acceleration") or {},
            },
        },
        "provenance": {
            "llm_mode": score.get("llm_mode"),
            "model": score.get("model"),
            "llm_generation": score.get("llm_generation") or {},
            "scoring_config_version": score.get("scoring_config_version"),
            "asr_model": asr.get("model"),
            "asr_device": asr.get("device"),
            "diarization_device": diarize.get("device"),
            "event_device": events.get("device"),
        },
        "qa": qa,
    }
    run, persisted_video_dna = _analysis_run(job, summary.get("analyzed_at"))
    persisted_text = persisted_video_dna.get("text_system") if isinstance(persisted_video_dna, dict) else None
    persisted_audio = persisted_video_dna.get("audio") if isinstance(persisted_video_dna, dict) else None
    persisted_editing = persisted_video_dna.get("source_editing") if isinstance(persisted_video_dna, dict) else None
    persisted_story = persisted_video_dna.get("speech_story") if isinstance(persisted_video_dna, dict) else None
    if persisted_video_dna is None or not isinstance(persisted_text, dict) or "caption_tracks" not in persisted_text or not isinstance(persisted_audio, dict) or "audio_segments" not in persisted_audio or not isinstance(persisted_editing, dict) or "cuts" not in persisted_editing or not isinstance(persisted_story, dict) or "semantic_units" not in persisted_story:
        from publikclip_pipeline.video_dna import normalize_video_dna

        persisted_video_dna = normalize_video_dna(
            source=detail["source"], transcript=detail["transcript"], speakers=detail["speakers"],
            scenes=detail["scenes"], source_analysis=detail["source_analysis"], audio=detail["audio"],
            performance=_performance(job), provenance=detail["provenance"], corrections=qa,
            analysis_run=run,
        )
    detail["analysis_run"] = run
    detail["analyzer_version"] = run["analyzer_version"]
    detail["video_dna"] = persisted_video_dna
    return detail
