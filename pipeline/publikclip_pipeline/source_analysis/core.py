"""Pure normalization and interpretation helpers for source analysis.

The OCR engine and video decoder live in :mod:`stage`; this module keeps the
geometry, tracking, and interpretation rules deterministic and unit-testable.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from statistics import median
from typing import Any, Iterable


CANVAS_BANDS = (0.20, 0.40, 0.60, 0.80)


def clamp01(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 6)


def normalize_bbox(points: Iterable[Iterable[float]], width: int, height: int) -> dict[str, float]:
    """Convert a polygon in pixels to a clamped normalized axis-aligned box."""
    pairs = [(float(p[0]), float(p[1])) for p in points]
    if not pairs or width <= 0 or height <= 0:
        raise ValueError("bbox needs points and positive frame dimensions")
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    x1, x2 = clamp01(min(xs) / width), clamp01(max(xs) / width)
    y1, y2 = clamp01(min(ys) / height), clamp01(max(ys) / height)
    return {"x": x1, "y": y1, "width": round(max(0.0, x2 - x1), 6), "height": round(max(0.0, y2 - y1), 6)}


def bbox_center(box: dict[str, float]) -> tuple[float, float]:
    return clamp01(box["x"] + box["width"] / 2), clamp01(box["y"] + box["height"] / 2)


def bbox_iou(a: dict[str, float], b: dict[str, float]) -> float:
    ix = max(0.0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"]))
    iy = max(0.0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))
    inter = ix * iy
    union = a["width"] * a["height"] + b["width"] * b["height"] - inter
    return inter / union if union > 0 else 0.0


def canvas_position(box: dict[str, float]) -> str:
    """Five-band semantic placement relative to the full source canvas."""
    _, cy = bbox_center(box)
    names = ("top", "upper_middle", "center", "lower_middle", "bottom")
    for boundary, name in zip(CANVAS_BANDS, names):
        if cy < boundary:
            return name
    return names[-1]


def relation_to_primary_content(box: dict[str, float], content: dict[str, float]) -> str:
    """Classify text against primary content while retaining exact geometry."""
    bx1, by1 = box["x"], box["y"]
    bx2, by2 = bx1 + box["width"], by1 + box["height"]
    cx1, cy1 = content["x"], content["y"]
    cx2, cy2 = cx1 + content["width"], cy1 + content["height"]
    tolerance = 0.012
    if by2 <= cy1 + tolerance:
        return "above_content"
    if by1 >= cy2 - tolerance:
        return "below_content"
    ix = max(0.0, min(bx2, cx2) - max(bx1, cx1))
    iy = max(0.0, min(by2, cy2) - max(by1, cy1))
    overlap = ix * iy
    area = max(1e-9, box["width"] * box["height"])
    if overlap / area < 0.5:
        return "outside_content"
    _, center_y = bbox_center(box)
    relative_y = (center_y - cy1) / max(content["height"], 1e-9)
    if relative_y < 1 / 3:
        return "overlay_top"
    if relative_y < 2 / 3:
        return "overlay_center"
    return "overlay_bottom"


def _clean_text(value: str) -> str:
    return re.sub(r"[^\w$%]+", " ", value.casefold(), flags=re.UNICODE).strip()


def _similar_text(a: str, b: str) -> float:
    left, right = _clean_text(a), _clean_text(b)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _median_bbox(boxes: list[dict[str, float]]) -> dict[str, float]:
    return {key: round(median(box[key] for box in boxes), 6) for key in ("x", "y", "width", "height")}


def _union_bbox(boxes: list[dict[str, float]]) -> dict[str, float]:
    x1 = min(box["x"] for box in boxes)
    y1 = min(box["y"] for box in boxes)
    x2 = max(box["x"] + box["width"] for box in boxes)
    y2 = max(box["y"] + box["height"] for box in boxes)
    return {
        "x": round(x1, 6), "y": round(y1, 6),
        "width": round(x2 - x1, 6), "height": round(y2 - y1, 6),
    }


def _vertical_overlap(a: dict[str, float], b: dict[str, float]) -> float:
    overlap = max(0.0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))
    return overlap / max(1e-9, min(a["height"], b["height"]))


def _join_ocr_fragments(parts: list[str]) -> str:
    """Join OCR word boxes without inventing segmentation inside one box."""
    text = ""
    for part in (value.strip() for value in parts):
        if not part:
            continue
        if not text or part[0] in ",.;:!?)]}%" or text[-1] in "([${":
            text += part
        else:
            text += " " + part
    return text


def reconstruct_ocr_lines(detections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive same-frame OCR lines from adjacent word/token boxes.

    RapidOCR normally returns a whole line, but some frames split a title into
    word boxes.  Geometry is required before inserting a separator, so an
    ambiguous single OCR box such as ``TheCarRentalFinalBoss`` remains intact.
    """
    by_time: dict[float, list[dict[str, Any]]] = {}
    for detection in detections:
        by_time.setdefault(float(detection["timestamp"]), []).append(detection)

    lines: list[dict[str, Any]] = []
    for timestamp, sample in by_time.items():
        pending = sorted(sample, key=lambda item: (bbox_center(item["bbox"])[1], item["bbox"]["x"]))
        horizontal_lines: list[list[dict[str, Any]]] = []
        for detection in pending:
            for line in horizontal_lines:
                reference = _union_bbox([item["bbox"] for item in line])
                center_delta = abs(bbox_center(detection["bbox"])[1] - bbox_center(reference)[1])
                height = max(detection["bbox"]["height"], reference["height"])
                if _vertical_overlap(detection["bbox"], reference) >= 0.5 and center_delta <= height * 0.65:
                    line.append(detection)
                    break
            else:
                horizontal_lines.append([detection])

        for line_index, line in enumerate(horizontal_lines):
            words = sorted(line, key=lambda item: item["bbox"]["x"])
            chunk: list[dict[str, Any]] = []
            for word in words:
                if chunk:
                    previous = chunk[-1]["bbox"]
                    gap = word["bbox"]["x"] - (previous["x"] + previous["width"])
                    height = max(word["bbox"]["height"], previous["height"])
                    # A large gap is a separate label in the same horizontal band.
                    if gap > max(0.018, height * 1.5):
                        lines.append(_line_detection(timestamp, len(lines), chunk))
                        chunk = []
                chunk.append(word)
            if chunk:
                lines.append(_line_detection(timestamp, len(lines), chunk))
    return sorted(lines, key=lambda item: (item["timestamp"], item["bbox"]["y"], item["bbox"]["x"]))


def _line_detection(timestamp: float, index: int, words: list[dict[str, Any]]) -> dict[str, Any]:
    raw_ids = [str(item["id"]) for item in words]
    return {
        "id": f"ocr-line-{timestamp:.3f}-{index:03d}", "timestamp": timestamp,
        "text": _join_ocr_fragments([str(item["text"]) for item in words]),
        "confidence": round(sum(float(item["confidence"]) for item in words) / len(words), 4),
        "bbox": _union_bbox([item["bbox"] for item in words]),
        "source_detection_ids": raw_ids,
    }


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", _clean_text(value))


def _representative_track_text(track: dict[str, Any]) -> str:
    """Prefer an observed spaced reading when it agrees with the same OCR text."""
    groups: dict[str, list[tuple[float, str]]] = {}
    for confidence, text in zip(track["confidences"], track["texts"]):
        key = _compact_text(text)
        if key:
            groups.setdefault(key, []).append((float(confidence), str(text).strip()))
    if not groups:
        return ""
    dominant = max(groups.values(), key=lambda values: sum(confidence for confidence, _ in values))
    variants: dict[str, list[float]] = {}
    for confidence, text in dominant:
        variants.setdefault(text, []).append(confidence)
    # Whitespace is selected only from an OCR observation with an identical
    # compact token sequence; never inferred from an ambiguous singleton.
    representative = max(
        variants,
        key=lambda text: (
            len(_clean_text(text).split()) > 1,
            len(_clean_text(text).split()),
            sum(variants[text]),
            max(variants[text]),
        ),
    )
    # RapidOCR can render a persistent emoji as a standalone question mark.
    # Do not expose that detector placeholder in the normalized title text.
    return re.sub(r"\s+\?$", "", representative).strip()


def merge_ocr_detections(
    detections: list[dict[str, Any]], *, sample_interval: float, video_duration: float,
    detector: str, detector_version: str | None,
) -> list[dict[str, Any]]:
    """Merge repeated spatially stable OCR lines into persistent tracks."""
    tracks: list[dict[str, Any]] = []
    max_gap = sample_interval * 1.65 + 1e-6
    for detection in reconstruct_ocr_lines(detections):
        best: tuple[float, dict[str, Any]] | None = None
        for track in tracks:
            if detection["timestamp"] - track["last_seen"] > max_gap:
                continue
            text_score = _similar_text(detection["text"], track["texts"][-1])
            cx1, cy1 = bbox_center(detection["bbox"])
            cx2, cy2 = bbox_center(track["boxes"][-1])
            center_distance = ((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2) ** 0.5
            geometry = max(bbox_iou(detection["bbox"], track["boxes"][-1]), 1.0 - center_distance / 0.18)
            score = 0.72 * text_score + 0.28 * geometry
            if text_score >= 0.78 and geometry >= 0.40 and (best is None or score > best[0]):
                best = (score, track)
        if best is None:
            tracks.append({
                "first_seen": detection["timestamp"], "last_seen": detection["timestamp"],
                "texts": [detection["text"]], "boxes": [detection["bbox"]],
                "confidences": [detection["confidence"]],
                "sample_timestamps": [detection["timestamp"]],
                "detection_ids": list(detection.get("source_detection_ids") or [detection["id"]]),
            })
        else:
            track = best[1]
            track["last_seen"] = detection["timestamp"]
            track["texts"].append(detection["text"])
            track["boxes"].append(detection["bbox"])
            track["confidences"].append(detection["confidence"])
            track["sample_timestamps"].append(detection["timestamp"])
            track["detection_ids"].extend(detection.get("source_detection_ids") or [detection["id"]])

    output = []
    for index, track in enumerate(tracks):
        box = _median_bbox(track["boxes"])
        center_x, center_y = bbox_center(box)
        representative = _representative_track_text(track)
        end = min(video_duration, track["last_seen"] + sample_interval)
        line_count = max(1, representative.count("\n") + 1)
        output.append({
            "id": f"text-{index + 1:03d}", "start": round(track["first_seen"], 3), "end": round(end, 3),
            "text": representative, "confidence": round(sum(track["confidences"]) / len(track["confidences"]), 4),
            "bbox": box, "center_x": center_x, "center_y": center_y,
            "relative_size": round(box["width"] * box["height"], 6), "height_ratio": box["height"],
            "line_count": line_count, "duration": round(max(0.0, end - track["first_seen"]), 3),
            "sample_hits": len(track["sample_timestamps"]), "raw_detection_ids": track["detection_ids"],
            "provenance": {"detector": detector, "version": detector_version},
        })
    return sorted(output, key=lambda item: (item["start"], item["bbox"]["y"]))


def transcript_overlap(text: str, transcript: str) -> float:
    words = set(_clean_text(text).split())
    spoken = set(_clean_text(transcript).split())
    return len(words & spoken) / len(words) if words else 0.0


def _title_score(track: dict[str, Any], video_duration: float) -> float:
    persistence = track["duration"] / max(video_duration, 0.001)
    return (
        (0.22 if track["start"] <= 2.0 else 0.0)
        + min(0.36, persistence * 0.48)
        + (0.24 if track["content_relation"] == "above_content" else 0.10 if track["canvas_position"] in {"top", "upper_middle"} else 0.0)
        + (0.10 if track["sample_hits"] >= 2 else 0.0)
        + (0.08 if track["bbox"]["width"] >= 0.18 else 0.0)
    )


def _title_lines_compatible(a: dict[str, Any], b: dict[str, Any]) -> bool:
    overlap = min(a["end"], b["end"]) - max(a["start"], b["start"])
    shorter = min(a["duration"], b["duration"])
    # Sparse OCR timestamps describe sample intervals, not exact glyph
    # lifetimes. A single missing sample may shift either inferred edge.
    effective_overlap = min(shorter, overlap + 1.05)
    if overlap < -1.05 or (shorter >= 2.0 and effective_overlap < shorter * 0.5):
        return False
    a_box, b_box = a["bbox"], b["bbox"]
    vertical_gap = max(a_box["y"], b_box["y"]) - min(a_box["y"] + a_box["height"], b_box["y"] + b_box["height"])
    if vertical_gap > max(0.04, max(a_box["height"], b_box["height"]) * 1.5):
        return False
    if abs(a["center_x"] - b["center_x"]) > 0.20:
        return False
    left_delta = abs(a_box["x"] - b_box["x"])
    right_delta = abs((a_box["x"] + a_box["width"]) - (b_box["x"] + b_box["width"]))
    return min(left_delta, right_delta) <= 0.18


def derive_title_text_blocks(
    tracks: list[dict[str, Any]], primary_content_bbox: dict[str, float], video_duration: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Group compatible persistent title lines into derived, source-backed blocks."""
    eligible = [
        track for track in tracks
        if track.get("classification") not in {"subtitles/captions", "CTA", "watermark/username"}
        and float(track.get("title_score", 0.0)) >= 0.46
    ]
    groups: list[list[dict[str, Any]]] = []
    for track in eligible:
        matches = [group for group in groups if any(_title_lines_compatible(track, member) for member in group)]
        if not matches:
            groups.append([track])
            continue
        group = matches[0]
        group.append(track)
        for other in matches[1:]:
            group.extend(other)
            groups.remove(other)

    blocks: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        lines = sorted(group, key=lambda item: (item["bbox"]["y"], item["bbox"]["x"]))
        bbox = _union_bbox([line["bbox"] for line in lines])
        start, end = min(line["start"] for line in lines), max(line["end"] for line in lines)
        source_track_ids = [line["id"] for line in lines]
        confidence = sum(float(line["confidence"]) for line in lines) / len(lines)
        score = sum(float(line["title_score"]) for line in lines) / len(lines)
        placement = canvas_position(bbox)
        relation = relation_to_primary_content(bbox, primary_content_bbox)
        block = {
            "id": f"text-block-{index:03d}", "text": " ".join(line["text"] for line in lines),
            "lines": [{
                "track_id": line["id"], "text": line["text"], "start": line["start"], "end": line["end"],
                "bbox": line["bbox"], "confidence": line["confidence"],
            } for line in lines],
            "start": round(start, 3), "end": round(end, 3), "bbox": bbox,
            "line_count": len(lines), "confidence": round(confidence, 4),
            "canvas_position": placement, "content_relation": relation,
            "source_track_ids": source_track_ids,
        }
        blocks.append(block)
        candidates.append({
            "track_id": source_track_ids[0] if len(source_track_ids) == 1 else block["id"],
            "text": block["text"], "start": block["start"], "end": block["end"],
            "confidence": round(min(0.99, score * confidence), 4), "classification": "title_hook",
            "bbox": bbox, "canvas_position": placement, "content_relation": relation,
            "evidence": {
                "near_start": start <= 2.0,
                "persistence_ratio": round((end - start) / max(video_duration, 0.001), 4),
                "sample_hits": sum(line["sample_hits"] for line in lines),
                "stable_position": all(line["sample_hits"] >= 2 for line in lines),
                "source_track_ids": source_track_ids,
                "line_count": len(lines),
            },
            "provenance": {"method": "title-hook-text-block-rules", "version": 2, "source_track_ids": source_track_ids},
        })
    return blocks, sorted(candidates, key=lambda item: item["confidence"], reverse=True)


def classify_text_tracks(
    tracks: list[dict[str, Any]], primary_content_bbox: dict[str, float],
    video_duration: float, transcript: str, *, include_blocks: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach evidence-backed labels and derive title hooks from coherent blocks."""
    for track in tracks:
        track["canvas_position"] = canvas_position(track["bbox"])
        track["content_relation"] = relation_to_primary_content(track["bbox"], primary_content_bbox)
        persistence = track["duration"] / max(video_duration, 0.001)
        overlap = transcript_overlap(track["text"], transcript)
        clean = _clean_text(track["text"])
        edge = track["center_x"] < 0.18 or track["center_x"] > 0.82 or track["center_y"] > 0.86
        if re.search(r"\b(follow|subscribe|link in bio|comment|shop now|learn more)\b", clean):
            classification = "CTA"
        elif persistence >= 0.65 and edge and track["relative_size"] < 0.02:
            classification = "watermark/username"
        elif track["duration"] <= max(3.0, video_duration * 0.2) and track["content_relation"].startswith("overlay") and (
            overlap >= 0.45
            or (0.20 <= track["center_x"] <= 0.80 and 0.014 <= track["bbox"]["height"] <= 0.08 and len(clean) <= 30)
        ):
            classification = "subtitles/captions"
        else:
            title_score = _title_score(track, video_duration)
            classification = "title_hook" if title_score >= 0.58 else ("label" if track["duration"] >= 2.0 else "other")
            track["title_score"] = round(title_score, 4)
        track["classification"] = classification
        track["classification_confidence"] = round(min(0.99, 0.55 + min(0.4, persistence)), 4)
    blocks, candidates = derive_title_text_blocks(tracks, primary_content_bbox, video_duration)
    for track in tracks:
        track.pop("title_score", None)
    if include_blocks:
        return tracks, candidates, blocks
    return tracks, candidates


def normalize_layout_signature(layout: dict[str, Any], title_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Stable, descriptive signature; deliberately not a cluster/template id."""
    box = layout["primary_content_bbox"]
    title_relation = title_candidates[0]["content_relation"] if title_candidates else "none"
    return {
        "version": 1,
        "canvas_aspect_ratio": round(float(layout["canvas_aspect_ratio"]), 6),
        "primary_content_aspect_ratio": round(float(layout["primary_content_aspect_ratio"]), 6),
        "primary_content_bbox": {key: round(float(box[key]), 6) for key in ("x", "y", "width", "height")},
        "content_center": {"x": round(box["x"] + box["width"] / 2, 6), "y": round(box["y"] + box["height"] / 2, 6)},
        "content_area_ratio": round(box["width"] * box["height"], 6),
        "layout_mode": layout["layout_mode"], "approximate_shape": layout["approximate_shape"],
        "rounded_corners": layout["rounded_corners"], "split_screen": layout.get("split_screen", False),
        "background_relationship": layout["background_relationship"], "title_relationship": title_relation,
    }
