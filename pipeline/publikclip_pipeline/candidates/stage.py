"""Candidate discovery stage.

Clip Selection v2 constructs and ranks candidates from the persisted story
timeline. Older jobs without that evidence retain the interest-curve/window
fallback, so existing artifacts remain resumable.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..jobs.queue import Stage, StageContext, StageError


def detect_scenes(media_path: str, progress=None) -> list[float]:
    """Scene-change timestamps via PySceneDetect ContentDetector (BSD-3) on
    a downscaled decode. On a static podcast this returns camera cuts; on
    gaming/vlog footage it captures visual pacing."""
    from scenedetect import ContentDetector, open_video
    from scenedetect.scene_manager import SceneManager

    video = open_video(media_path)
    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=27.0))
    manager.auto_downscale = True
    manager.detect_scenes(video, show_progress=False)
    return [start.get_seconds() for start, _ in manager.get_scene_list()]


class CandidatesStage(Stage):
    name = "candidates"
    schema_version = 3

    def run(self, ctx: StageContext) -> dict:
        import numpy as np

        from . import curve as curve_mod
        from . import windows as windows_mod

        prior = ctx.prior or {}
        ingest = prior.get("ingest")
        diarize = prior.get("diarize")
        events = prior.get("events")
        source_analysis = prior.get("source_analysis") or {}
        if not (ingest and diarize and events):
            raise StageError("Candidates need ingest + diarize + events outputs.")

        segments = diarize["segments"]
        duration = float(ingest["probe"]["duration_sec"])
        n = int(np.ceil(duration))

        curves_path = Path(events["curves_path"])
        if not curves_path.exists():
            raise StageError("curves.json missing — re-run events.")
        curves = json.loads(curves_path.read_text())

        ctx.emit(-1, "Detecting scene changes…")
        
        media_str = ingest.get("media_path", "").replace("\\", "/")
        media = Path(media_str)
        if not media.exists():
            media = ctx.job_dir / Path(media_str).name
            
        scene_detector_outcome = "success_no_detections"
        scene_detector_error = None
        scenes_path = ctx.job_dir / "scenes.json"
        if scenes_path.exists():
            try:
                scene_times = [float(item) for item in json.loads(scenes_path.read_text())]
                scene_detector_outcome = "success_with_detections" if scene_times else "success_no_detections"
            except (OSError, TypeError, ValueError):
                scene_times = []
        else:
            try:
                scene_times = detect_scenes(str(media))
                if scene_times:
                    scene_detector_outcome = "success_with_detections"
            except Exception as err:  # noqa: BLE001 — scenes are a minor channel; degrade
                scene_times = []
                scene_detector_outcome = "unavailable"
                scene_detector_error = f"{type(err).__name__}: {err}"
            scenes_path.write_text(json.dumps(scene_times))

        ctx.emit(0.6, "Building interest curve…")
        channels = {
            "heatmap": curve_mod.heatmap_channel(ingest.get("heatmap"), n),
            "dynamics": curve_mod.dynamics_channel(curves["dynamics"], curves["grid_sec"], n),
            "events": curve_mod.events_channel(events["timeline"], n),
            "turns": curve_mod.turns_channel(diarize["turns"], n),
            "arousal": curve_mod.arousal_channel(
                curves.get("arousal", []), curves.get("arousal_grid_sec", 0.5), n
            ),
            "scenes": curve_mod.scenes_channel(scene_times, n),
            "lexical": curve_mod.lexical_channel(segments, n),
        }
        curve, effective_weights = curve_mod.interest_curve(channels)

        story_semantics = source_analysis.get("story_semantics") if isinstance(source_analysis, dict) else None
        source_editing = source_analysis.get("source_editing") if isinstance(source_analysis, dict) else None
        if isinstance(story_semantics, dict) and isinstance(source_editing, dict):
            from .selection import build_selection, debug_artifact

            ctx.emit(0.8, "Constructing story-aware candidate portfolio…")
            selection = build_selection(
                story_semantics=story_semantics, source_editing=source_editing,
                rms=[float(item) for item in curves.get("rms") or []],
                grid_sec=float(curves.get("grid_sec") or .1),
                clip_length=(ctx.generation_config or {}).get("clip_length"),
            )
            if selection is not None:
                compact_debug = debug_artifact(selection)
                (ctx.job_dir / "clip_selection_v2.json").write_text(json.dumps(compact_debug, ensure_ascii=False, indent=1))
                (ctx.job_dir / "interest_curve.json").write_text(
                    json.dumps({"per_sec": np.round(curve, 4).tolist()})
                )
                return {
                    "selection_version": "clip-selection-v2", "candidates": selection["portfolio"],
                    "portfolio": selection["portfolio"], "selection_debug": compact_debug,
                    "count": selection["post_dedupe_count"],
                    "broad_candidate_count": selection["broad_candidate_count"],
                    "post_dedupe_count": selection["post_dedupe_count"],
                    "final_count": selection["final_count"],
                    "duration_contract": selection["duration_contract"],
                    "quality_bucket_counts": selection["quality_bucket_counts"],
                    "effective_weights": effective_weights, "scene_count": len(scene_times),
                    "scene_detector_outcome": scene_detector_outcome,
                    "scene_detector_error": scene_detector_error,
                    "heatmap_present": bool(ingest.get("heatmap")),
                }

        ctx.emit(0.8, "Extracting candidate windows…")
        candidates = windows_mod.extract(curve, channels, segments, duration)
        if not candidates:
            raise StageError(
                "No candidate moments found — the video may be too short or too quiet."
            )

        # Persist the curve for the review UI's timeline visualization.
        (ctx.job_dir / "interest_curve.json").write_text(
            json.dumps({"per_sec": np.round(curve, 4).tolist()})
        )

        return {
            "candidates": [c.to_json() for c in candidates],
            "count": len(candidates),
            "effective_weights": effective_weights,
            "scene_count": len(scene_times),
            "scene_detector_outcome": scene_detector_outcome,
            "scene_detector_error": scene_detector_error,
            "heatmap_present": bool(ingest.get("heatmap")),
        }
