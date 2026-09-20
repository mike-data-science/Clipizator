"""Conservative source-editing observations derived from existing Analyzer evidence."""

from __future__ import annotations

import hashlib
import re
from statistics import mean, median
from typing import Any


NEAR_EVENT_MS = 400


def _ms(value: Any) -> int:
    return round(float(value or 0) * 1000)


def _event_id(kind: str, timestamp_ms: int, discriminator: str | None = None) -> str:
    """Timestamp-addressed IDs remain stable when unrelated events are added."""
    suffix = ""
    if discriminator:
        clean = re.sub(r"[^a-z0-9]+", "_", discriminator.casefold()).strip("_")
        digest = hashlib.sha1(discriminator.encode("utf-8")).hexdigest()[:8]
        suffix = f"_{clean[:24]}_{digest}" if clean else f"_{digest}"
    return f"edit_{kind}_{max(0, int(timestamp_ms)):09d}{suffix}"


def classify_transition(boundary: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
    """Classify only transitions directly supported by the boundary detector.

    ContentDetector is a fast content-change detector, so a confident boundary
    supports a hard cut. It does not provide enough evidence for fades/dissolves.
    """
    provenance = boundary.get("provenance") if isinstance(boundary.get("provenance"), dict) else {}
    detector = str(provenance.get("detector") or boundary.get("model_or_detector") or "")
    confidence = float(boundary.get("confidence") or 0)
    if "PySceneDetect ContentDetector" in detector and confidence >= 0.7:
        return "hard_cut", min(confidence, 0.9), {"reason": "content_detector_boundary"}
    return "unknown", min(confidence, 0.49), {
        "reason": "boundary evidence does not distinguish hard cut, fade, or dissolve"
    }


def _shot_structure(duration: float, cuts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bounds = [0, *sorted({int(item["timestamp_ms"]) for item in cuts}), _ms(duration)]
    return [
        {
            "id": f"shot-{index:03d}", "type": "source_shot", "start_ms": start, "end_ms": end,
            "duration_ms": end - start, "confidence": 0.8, "source": "derived", "status": "interpreted",
            "evidence": {"bounded_by_cut_ids": [
                item["id"] for item in cuts if item["timestamp_ms"] in {start, end}
            ]},
        }
        for index, (start, end) in enumerate(zip(bounds, bounds[1:]), 1) if end > start
    ]


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _reframe_events(layout_changes: list[dict[str, Any]], cut_times_ms: list[int]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    reframes: list[dict[str, Any]] = []
    zooms: list[dict[str, Any]] = []
    excluded_near_cuts = 0
    for change in layout_changes:
        start_ms = _ms(change.get("start"))
        before = change.get("from_bbox") if isinstance(change.get("from_bbox"), dict) else {}
        after = change.get("to_bbox") if isinstance(change.get("to_bbox"), dict) else {}
        if not all(isinstance(box.get(key), (int, float)) for box in (before, after) for key in ("x", "y", "width", "height")):
            continue
        if any(abs(start_ms - cut) <= 550 for cut in cut_times_ms):
            excluded_near_cuts += 1
            continue
        before_area = float(before["width"]) * float(before["height"])
        after_area = float(after["width"]) * float(after["height"])
        scale_ratio = after_area / max(before_area, 1e-6)
        before_center = (float(before["x"]) + float(before["width"]) / 2, float(before["y"]) + float(before["height"]) / 2)
        after_center = (float(after["x"]) + float(after["width"]) / 2, float(after["y"]) + float(after["height"]) / 2)
        center_delta = max(abs(after_center[0] - before_center[0]), abs(after_center[1] - before_center[1]))
        width_ratio = float(after["width"]) / max(float(before["width"]), 1e-6)
        height_ratio = float(after["height"]) / max(float(before["height"]), 1e-6)
        proportional = abs(width_ratio - height_ratio) <= 0.1
        evidence = {
            "from_bbox": before, "to_bbox": after, "area_scale_ratio": round(scale_ratio, 4),
            "center_delta": round(center_delta, 4), "sample_timestamp_ms": start_ms,
            "cut_proximity_excluded": True,
        }
        magnitude = max(abs(scale_ratio - 1), center_delta * 2)
        if magnitude < 0.16:
            continue
        confidence = round(min(0.82, 0.54 + magnitude * 0.35), 4)
        event = {
            "id": _event_id("reframe", start_ms), "type": "source_reframe", "timestamp_ms": start_ms,
            "start_ms": start_ms, "end_ms": start_ms, "confidence": confidence,
            "source": "derived", "status": "interpreted", "evidence": evidence,
        }
        reframes.append(event)
        # A stable-center, proportional and large content-bounds change is the
        # only sparse evidence considered sufficient for a likely source zoom.
        if proportional and center_delta <= 0.045 and (scale_ratio >= 1.25 or scale_ratio <= 0.8):
            direction = "likely_punch_in" if scale_ratio > 1 else "likely_punch_out"
            zooms.append({
                "id": _event_id("zoom", start_ms), "type": "source_zoom", "subtype": direction,
                "timestamp_ms": start_ms, "start_ms": start_ms, "end_ms": start_ms,
                "confidence": round(min(0.72, confidence), 4), "source": "derived", "status": "interpreted",
                "evidence": {**evidence, "reframe_event_id": event["id"], "classification": "likely_not_confirmed"},
            })
    return reframes, zooms, excluded_near_cuts


def _pattern_interrupts(
    cuts: list[dict[str, Any]], reframes: list[dict[str, Any]], visual_units: list[dict[str, Any]],
    overlays: list[dict[str, Any]], emphasis_events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, str, str, float, dict[str, Any]]] = []
    candidates.extend((item["timestamp_ms"], "shot_change", item["id"], item["confidence"], {}) for item in cuts)
    candidates.extend((item["timestamp_ms"], "strong_framing_change", item["id"], item["confidence"], {}) for item in reframes if item["confidence"] >= 0.6)
    previous_type = None
    for unit in sorted(visual_units, key=lambda item: int(item.get("start_ms") or 0)):
        unit_type = str(unit.get("visual_type") or "")
        if unit_type == "b_roll" and previous_type != "b_roll" and unit.get("id"):
            candidates.append((int(unit.get("start_ms") or 0), "b_roll_transition", str(unit["id"]), float(unit.get("confidence") or 0), {}))
        previous_type = unit_type
    significant_roles = {"title_hook", "cta", "meme_or_graphic_text", "label"}
    for overlay in overlays:
        if overlay.get("role") in significant_roles and overlay.get("source_ocr_track_id"):
            candidates.append((int(overlay.get("start_ms") or 0), "overlay_appearance", str(overlay["source_ocr_track_id"]), float(overlay.get("confidence") or 0), {"role": overlay.get("role")}))
    for emphasis in emphasis_events:
        if emphasis.get("caption_track_id"):
            candidates.append((int(emphasis.get("start_ms") or 0), "caption_emphasis", str(emphasis["caption_track_id"]), float(emphasis.get("confidence") or 0), {}))
    output = []
    seen: set[tuple[int, str, str]] = set()
    for timestamp_ms, subtype, reference_id, confidence, extra in sorted(candidates):
        key = (timestamp_ms, subtype, reference_id)
        if key in seen:
            continue
        seen.add(key)
        output.append({
            "id": _event_id("pattern_interrupt", timestamp_ms, f"{subtype}_{reference_id}"),
            "type": "observable_pattern_interrupt", "subtype": subtype,
            "timestamp_ms": timestamp_ms, "start_ms": timestamp_ms, "end_ms": timestamp_ms,
            "confidence": round(confidence, 4), "source": "derived", "status": "interpreted",
            "evidence": {"source_event_ids": [reference_id], **extra, "interpretation_limit": "observable_change_only"},
        })
    return output


def _relationships(edit_events: list[dict[str, Any]], targets: list[tuple[str, str, int]]) -> list[dict[str, Any]]:
    output = []
    for event in edit_events:
        timestamp = int(event.get("timestamp_ms") or event.get("start_ms") or 0)
        for target_type, target_id, target_start in targets:
            delta = target_start - timestamp
            if abs(delta) > NEAR_EVENT_MS:
                continue
            relation = f"{target_type}_begins_near_edit"
            output.append({
                "id": _event_id("relationship", timestamp, f"{event['id']}_{target_id}"),
                "type": "temporal_proximity", "editing_event_id": event["id"],
                "target_type": target_type, "target_event_id": target_id, "delta_ms": delta,
                "relation": relation, "confidence": round(min(float(event.get("confidence") or 0), 0.85), 4),
                "source": "derived", "status": "interpreted",
                "evidence": {"threshold_ms": NEAR_EVENT_MS, "causality_inferred": False},
            })
    return output


def build_source_editing(
    *, duration: float, scene_times: list[float], scene_detector_outcome: str,
    layout_changes: list[dict[str, Any]], visual_units: list[dict[str, Any]],
    caption_tracks: list[dict[str, Any]], overlays: list[dict[str, Any]],
    emphasis_events: list[dict[str, Any]], audio_events: list[dict[str, Any]],
) -> dict[str, Any]:
    cut_times = sorted({float(value) for value in scene_times if 0.05 < float(value) < duration})
    cuts = []
    transitions = []
    for timestamp in cut_times:
        timestamp_ms = _ms(timestamp)
        cut = {
            "id": _event_id("cut", timestamp_ms), "type": "shot_boundary", "timestamp_ms": timestamp_ms,
            "start_ms": timestamp_ms, "end_ms": timestamp_ms, "confidence": 0.8,
            "source": "detector", "status": "raw",
            "evidence": {"artifact": "scenes.json", "detector": "PySceneDetect ContentDetector", "threshold": 27.0},
        }
        cuts.append(cut)
        transition_type, confidence, reason = classify_transition({"confidence": cut["confidence"], "provenance": {"detector": cut["evidence"]["detector"]}})
        transitions.append({
            "id": _event_id("transition", timestamp_ms), "type": "source_transition",
            "subtype": transition_type, "timestamp_ms": timestamp_ms, "start_ms": timestamp_ms, "end_ms": timestamp_ms,
            "confidence": round(confidence, 4), "source": "derived", "status": "interpreted",
            "evidence": {"cut_event_id": cut["id"], **reason},
        })
    shots = _shot_structure(duration, cuts)
    reframes, zooms, excluded_near_cuts = _reframe_events(layout_changes, [item["timestamp_ms"] for item in cuts])
    patterns = _pattern_interrupts(cuts, reframes, visual_units, overlays, emphasis_events)
    target_refs: list[tuple[str, str, int]] = []
    target_refs.extend(("visual_unit", str(item["id"]), int(item.get("start_ms") or 0)) for item in visual_units if item.get("id"))
    target_refs.extend(("caption", str(item["id"]), int(item.get("start_ms") or 0)) for item in caption_tracks if item.get("id"))
    target_refs.extend(("audio_event", str(item["id"]), int(item.get("start_ms") or 0)) for item in audio_events if item.get("id"))
    relationships = _relationships([*cuts, *reframes, *zooms], target_refs)
    durations = [(item["end_ms"] - item["start_ms"]) / 1000 for item in shots]
    # Transition and zoom records classify a cut/reframe rather than adding a
    # second edit. Pattern events add density only when they introduce another
    # observable source change.
    additional_patterns = [
        item for item in patterns if item.get("subtype") not in {"shot_change", "strong_framing_change"}
    ]
    density_events = [*cuts, *reframes, *additional_patterns]
    metrics = {
        "cut_count": len(cuts), "shot_count": len(shots),
        "cuts_per_minute": round(len(cuts) / max(duration, 0.001) * 60, 4),
        "shot_duration_sec": {
            "min": round(min(durations), 4) if durations else None,
            "p25": round(_percentile(durations, .25), 4) if durations else None,
            "median": round(median(durations), 4) if durations else None,
            "mean": round(mean(durations), 4) if durations else None,
            "p75": round(_percentile(durations, .75), 4) if durations else None,
            "max": round(max(durations), 4) if durations else None,
        },
        "visual_change_cadence_per_minute": round(len(patterns) / max(duration, 0.001) * 60, 4),
        "edit_event_count": len(density_events),
        "edit_event_density_per_minute": round(len(density_events) / max(duration, 0.001) * 60, 4),
        "pattern_interrupt_count": len(patterns),
        "approx_pattern_interrupt_interval_sec": round(duration / len(patterns), 4) if patterns else None,
    }
    available = scene_detector_outcome != "unavailable"
    return {
        "schema_version": 1, "status": "available" if available else "limited",
        "cuts": cuts, "shots": shots, "transitions": transitions,
        "reframes": reframes, "zooms": zooms, "pattern_interrupts": patterns,
        "cross_modal_relationships": relationships, "metrics": metrics,
        "capabilities": {
            "transition_classification": {"status": "limited", "reason": "ContentDetector supports hard-cut evidence; fades and dissolves remain unknown without direct evidence."},
            "source_reframe_detection": {"status": "experimental" if layout_changes else "unavailable", "reason": "Sparse content-bound changes away from cuts are conservative framing evidence." if layout_changes else "No supported content-bound changes were observed."},
            "source_zoom_detection": {"status": "experimental" if zooms else "unavailable", "reason": "Only large proportional, stable-center content-bound changes are reported as likely zooms." if zooms else "Sparse observations do not support a source zoom classification."},
            "speed_change_detection": {"status": "unavailable", "reason": "No timing or playback-rate evidence is available; motion alone is not used."},
        },
        "evidence": {
            "scene_detector_outcome": scene_detector_outcome, "layout_change_count": len(layout_changes),
            "layout_changes_excluded_near_cuts": excluded_near_cuts,
            "visual_unit_ids": [item.get("id") for item in visual_units if item.get("id")],
            "caption_track_ids": [item.get("id") for item in caption_tracks if item.get("id")],
            "audio_event_ids": [item.get("id") for item in audio_events if item.get("id")],
            "generated_camera_data_excluded": True,
        },
        "provenance": {
            "method": "source-editing-rules-v1", "shot_detector": "PySceneDetect ContentDetector",
            "framing_detector": "opencv-row-column-content-bounds", "source_video_only": True,
        },
        "limitations": [
            "Fade and dissolve classification is unavailable without direct transition evidence.",
            "Sparse content bounds cannot always distinguish subject/camera motion from digital reframing.",
            "Likely punch changes are not asserted as confirmed digital zooms.",
            "Pattern interrupts describe observable changes, not intent or retention impact.",
        ],
    }
