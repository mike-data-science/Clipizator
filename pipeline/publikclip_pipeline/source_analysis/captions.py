"""Derived caption roles, transcript links, and conservative emphasis evidence."""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from statistics import mean, median
from typing import Any

from .core import bbox_center, canvas_position


TEXT_ROLES = {
    "title_hook", "caption", "emphasized_caption", "cta", "label", "watermark",
    "username_or_handle", "meme_or_graphic_text", "other_overlay", "uncertain",
}


def _words(value: str) -> list[str]:
    return re.findall(r"[\w$%']+", str(value).casefold(), flags=re.UNICODE)


def _similarity(left: str, right: str) -> float:
    a, b = " ".join(_words(left)), " ".join(_words(right))
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def measure_text_style(frame: Any, bbox: dict[str, float]) -> dict[str, Any]:
    """Return only conservative, frame-supported style measurements.

    OCR geometry is the reliable font-size proxy.  Saturated text pixels are
    reported only when they occupy enough of the OCR crop; white/outlined text
    and background-box details remain explicitly unavailable.
    """
    import cv2
    import numpy as np

    height, width = frame.shape[:2]
    x1, y1 = max(0, int(bbox["x"] * width)), max(0, int(bbox["y"] * height))
    x2 = min(width, max(x1 + 1, int((bbox["x"] + bbox["width"]) * width)))
    y2 = min(height, max(y1 + 1, int((bbox["y"] + bbox["height"]) * height)))
    crop = frame[y1:y2, x1:x2]
    result: dict[str, Any] = {
        "relative_font_size": round(float(bbox["height"]), 6),
        "dominant_text_color": None, "color_confidence": None,
        "background_box": {"status": "unavailable", "reason": "OCR crop cannot reliably separate glyph and background."},
        "outline_or_shadow": {"status": "unavailable", "reason": "Sparse OCR sampling cannot reliably isolate glyph effects."},
    }
    if crop.size == 0:
        return result
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 1] >= 105) & (hsv[:, :, 2] >= 105)
    coverage = float(mask.mean())
    if coverage < 0.045:
        return result
    hue = float(np.median(hsv[:, :, 0][mask]))
    color = "red" if hue < 10 or hue >= 170 else "yellow" if hue < 38 else "green" if hue < 88 else "blue" if hue < 132 else "purple"
    result["dominant_text_color"] = color
    result["color_confidence"] = round(min(0.9, 0.42 + coverage * 1.8), 4)
    return result


def _case_style(text: str) -> str:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return "unavailable"
    if all(char.isupper() for char in letters):
        return "uppercase"
    if all(char.islower() for char in letters):
        return "lowercase"
    return "mixed"


def _transcript_alignment(text: str, start: float, end: float, segments: list[dict[str, Any]]) -> dict[str, Any]:
    nearby = [item for item in segments if float(item.get("end") or item.get("start") or 0) > start - 0.35 and float(item.get("start") or 0) < end + 0.35]
    if not nearby:
        return {"status": "unavailable", "similarity": None, "transcript_reference": None}
    caption_words = _words(text)
    best: tuple[float, dict[str, Any], str] | None = None
    for segment in nearby:
        candidates = [(str(segment.get("text") or ""), None)]
        for word in segment.get("words") or []:
            if isinstance(word, dict) and word.get("word"):
                candidates.append((str(word["word"]), word))
        for candidate, word_ref in candidates:
            candidate_words = _words(candidate)
            overlap = len(set(caption_words) & set(candidate_words)) / max(1, len(caption_words))
            similarity = max(overlap, _similarity(text, candidate))
            if best is None or similarity > best[0]:
                best = (similarity, segment, candidate if word_ref is None else str(word_ref["word"]))
    assert best is not None
    similarity, segment, spoken = best
    if similarity < 0.45:
        return {"status": "unavailable", "similarity": round(similarity, 4), "transcript_reference": None}
    reference = {"start": segment.get("start"), "end": segment.get("end"), "text": spoken}
    return {"status": "aligned" if similarity >= 0.7 else "partial", "similarity": round(similarity, 4), "transcript_reference": reference}


def _role(track: dict[str, Any], title_ids: set[str]) -> str:
    text = str(track.get("text") or "")
    clean = " ".join(_words(text))
    prior = track.get("classification")
    if not clean:
        return "uncertain"
    if track.get("id") in title_ids:
        return "title_hook"
    if re.search(r"\b(follow|subscribe|link in bio|shop now|learn more)\b", clean):
        return "cta"
    if re.search(r"(^|\s)@[\w.]+", text):
        return "username_or_handle"
    if prior == "watermark/username":
        return "watermark"
    if prior == "label":
        return "label"
    if prior == "subtitles/captions":
        return "caption"
    if text.startswith("*") and text.endswith("*"):
        return "meme_or_graphic_text"
    return "other_overlay" if prior == "other" else "uncertain"


def _style_for(track: dict[str, Any], styles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = [styles[item] for item in track.get("raw_detection_ids") or [] if item in styles]
    colors = [item.get("dominant_text_color") for item in values if item.get("dominant_text_color") and (item.get("color_confidence") or 0) >= 0.5]
    return {
        "normalized_bbox": track.get("bbox"), "placement": track.get("canvas_position") or canvas_position(track["bbox"]),
        "line_count": track.get("line_count", 1), "relative_font_size": track.get("height_ratio"),
        "case": _case_style(str(track.get("text") or "")),
        "dominant_text_color": Counter(colors).most_common(1)[0][0] if colors else None,
        "background_box": {"status": "unavailable", "reason": "No reliable glyph/background separation."},
        "outline_or_shadow": {"status": "unavailable", "reason": "No reliable sparse-frame evidence."},
        "style_stability": "unavailable" if not values else "stable" if len(set(colors)) <= 1 else "changing",
    }


def _visual_refs(start_ms: int, end_ms: int, visual_units: list[dict[str, Any]]) -> list[str]:
    return [str(unit.get("id")) for unit in visual_units if int(unit.get("end_ms") or 0) > start_ms and int(unit.get("start_ms") or 0) < end_ms]


def _caption_item(track: dict[str, Any], styles: dict[str, dict[str, Any]], transcript: list[dict[str, Any]], visual_units: list[dict[str, Any]]) -> dict[str, Any]:
    start, end = float(track["start"]), float(track["end"])
    alignment = _transcript_alignment(str(track.get("text") or ""), start, end, transcript)
    return {
        "id": f"caption-{track['id']}", "start_ms": round(start * 1000), "end_ms": round(end * 1000),
        "text": track.get("text") or "", "bbox": track.get("bbox"), "line_count": track.get("line_count", 1),
        "source_ocr_track_ids": [track["id"]], "source_text_block_ids": [],
        "source_ocr_detection_ids": track.get("raw_detection_ids") or [],
        "confidence": track.get("confidence"), "role": "caption", "style": _style_for(track, styles),
        "transcript_alignment": alignment,
        "visual_unit_ids": _visual_refs(round(start * 1000), round(end * 1000), visual_units),
        "evidence": {"sample_hits": track.get("sample_hits"), "track_classification": track.get("classification")},
    }


def _compatible_caption(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if right["start_ms"] - left["end_ms"] > 1050 or _similarity(left["text"], right["text"]) < 0.84:
        return False
    a, b = left["bbox"], right["bbox"]
    ax, ay = bbox_center(a)
    bx, by = bbox_center(b)
    return abs(ax - bx) <= 0.08 and abs(ay - by) <= 0.06 and left["style"].get("dominant_text_color") == right["style"].get("dominant_text_color")


def _consolidate(captions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in sorted(captions, key=lambda value: value["start_ms"]):
        if output and _compatible_caption(output[-1], item):
            prior = output[-1]
            prior["end_ms"] = item["end_ms"]
            prior["source_ocr_track_ids"].extend(item["source_ocr_track_ids"])
            prior["source_ocr_detection_ids"].extend(item["source_ocr_detection_ids"])
            prior["visual_unit_ids"] = list(dict.fromkeys([*prior["visual_unit_ids"], *item["visual_unit_ids"]]))
            prior["confidence"] = round(mean([float(prior["confidence"] or 0), float(item["confidence"] or 0)]), 4)
        else:
            output.append(item)
    for index, item in enumerate(output, 1):
        item["id"] = f"caption-{index:03d}"
    return output


def _emphasis_events(captions: list[dict[str, Any]], raw_ocr: dict[str, dict[str, Any]], styles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for caption in captions:
        ids = caption["source_ocr_detection_ids"]
        measurements = [(raw_ocr[item], styles[item]) for item in ids if item in raw_ocr and item in styles]
        if len(measurements) < 2:
            continue
        heights = [float(style.get("relative_font_size") or 0) for _, style in measurements]
        base_height = median(heights)
        colors = [style.get("dominant_text_color") for _, style in measurements if (style.get("color_confidence") or 0) >= 0.55 and style.get("dominant_text_color")]
        base_color = Counter(colors).most_common(1)[0][0] if colors else None
        for raw, style in measurements:
            word = str(raw.get("text") or "").strip()
            if not word or len(_words(word)) > max(3, len(_words(caption["text"]))):
                continue
            color = style.get("dominant_text_color")
            color_change = base_color and color and color != base_color and (style.get("color_confidence") or 0) >= 0.55
            size_change = base_height > 0 and float(style.get("relative_font_size") or 0) >= base_height * 1.35
            if not color_change and not size_change:
                continue
            emphasis_type = "color_highlight" if color_change else "size_emphasis"
            confidence = 0.72 if color_change else 0.64
            events.append({
                "start_ms": round(float(raw.get("timestamp") or caption["start_ms"] / 1000) * 1000),
                "end_ms": caption["end_ms"], "emphasized_text": word, "emphasis_type": emphasis_type,
                "confidence": confidence, "caption_track_id": caption["id"],
                "transcript_reference": caption["transcript_alignment"].get("transcript_reference"),
                "evidence_frame_timestamps_ms": [round(float(raw.get("timestamp") or 0) * 1000)],
                "style_before": {"dominant_text_color": base_color, "relative_font_size": round(base_height, 6)},
                "style_during": {"dominant_text_color": color, "relative_font_size": style.get("relative_font_size")},
            })
    return events


def build_caption_system(*, tracks: list[dict[str, Any]], title_candidates: list[dict[str, Any]], raw_ocr_detections: list[dict[str, Any]], text_style_observations: list[dict[str, Any]], transcript_segments: list[dict[str, Any]], visual_units: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    """Normalize existing OCR tracks without changing OCR or title-hook derivation."""
    title_ids = {str(track_id) for item in title_candidates for track_id in (item.get("evidence") or {}).get("source_track_ids", [])}
    title_ids.update(str(item.get("track_id")) for item in title_candidates if item.get("track_id"))
    raw_by_id = {str(item.get("id")): item for item in raw_ocr_detections if item.get("id")}
    styles = {str(item.get("source_detection_id")): item for item in text_style_observations if item.get("source_detection_id")}
    roles = []
    caption_inputs = []
    for track in tracks:
        role = _role(track, title_ids)
        record = {"source_ocr_track_id": track.get("id"), "role": role, "text": track.get("text"), "start_ms": round(float(track.get("start") or 0) * 1000), "end_ms": round(float(track.get("end") or 0) * 1000), "confidence": track.get("confidence"), "bbox": track.get("bbox")}
        roles.append(record)
        if role == "caption":
            caption_inputs.append(_caption_item(track, styles, transcript_segments, visual_units))
    captions = _consolidate(caption_inputs)
    emphasis = _emphasis_events(captions, raw_by_id, styles)
    emphasized_ids = {event["caption_track_id"] for event in emphasis}
    for caption in captions:
        if caption["id"] in emphasized_ids:
            caption["role"] = "emphasized_caption"
    covered = sum(item["end_ms"] - item["start_ms"] for item in captions)
    region_counts = Counter(item["style"]["placement"] for item in captions if item["style"].get("placement"))
    word_count = sum(len(_words(item["text"])) for item in captions)
    metrics = {
        "captions_present": bool(captions), "caption_coverage_ratio": round(min(1.0, covered / max(1, duration * 1000)), 4) if captions else 0.0,
        "caption_event_count": len(captions), "caption_changes_per_minute": round(len(captions) / max(duration, 0.001) * 60, 4) if captions else 0.0,
        "emphasis_event_count": len(emphasis), "emphasis_events_per_minute": round(len(emphasis) / max(duration, 0.001) * 60, 4) if emphasis else 0.0,
        "most_common_caption_region": region_counts.most_common(1)[0][0] if region_counts else None,
        "average_words_per_caption": round(word_count / len(captions), 3) if captions else None,
        "highlighted_word_ratio": round(len(emphasis) / word_count, 4) if word_count else None,
    }
    return {
        "schema_version": 1, "status": "available" if captions else "limited" if tracks else "unavailable", "caption_tracks": captions,
        "emphasis_events": emphasis, "overlays": [item for item in roles if item["role"] != "caption"], "caption_metrics": metrics,
        "evidence": {"raw_ocr_detection_count": len(raw_ocr_detections), "text_track_count": len(tracks), "text_style_observation_count": len(text_style_observations), "transcript_segment_count": len(transcript_segments), "visual_unit_ids": [unit.get("id") for unit in visual_units]},
        "provenance": {"method": "ocr-caption-role-and-emphasis-rules-v1", "style_measurement": "opencv-saturated-glyph-color-v1", "ocr_reused": True},
        "limitations": ["Caption text and timing are limited by sparse OCR sampling.", "Color is reported only for sufficiently saturated OCR-crop evidence.", "Background boxes, outlines, shadows, and animation remain unavailable unless directly measurable."],
    }
