"""Sparse, evidence-first visual understanding over source shot units."""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from pathlib import Path
from statistics import mean, median
from typing import Any

from .. import config


CLIP_MODEL_ID = "openai/clip-vit-base-patch32"
MAX_SEMANTIC_FRAMES = 24
SEMANTIC_BATCH_SIZE = 12
VISUAL_TYPES = {
    "talking_head", "b_roll", "screenshot", "screen_recording",
    "meme_or_graphic", "environment", "mixed", "uncertain",
}

CONCEPTS = {
    "objects": (
        "car", "phone", "laptop", "computer monitor", "chart or graph", "document",
        "social media post", "web page or app interface", "building", "street", "food",
        "product", "microphone", "television", "person",
    ),
    "environments": (
        "office", "home interior", "studio", "street outdoors", "store",
        "vehicle interior", "nature outdoors", "computer screen or interface", "unclear scene",
    ),
    "actions": (
        "person speaking to camera", "person driving", "person pointing",
        "person using a phone", "person using a computer", "hands demonstrating an object",
        "no clear action",
    ),
    "visual_style": (
        "natural camera footage", "inserted illustrative footage", "static screenshot",
        "screen recording", "meme or designed graphic", "unclear visual style",
    ),
}

_SYNONYMS = {
    "car": {"car", "cars", "vehicle", "vehicles", "automobile", "koenigsegg", "ferrari", "lamborghini"},
    "phone": {"phone", "phones", "smartphone", "iphone", "android"},
    "laptop": {"laptop", "computer", "macbook"},
    "computer monitor": {"computer", "monitor", "screen", "desktop"},
    "chart or graph": {"chart", "graph", "data", "analytics", "numbers"},
    "document": {"document", "paper", "letter", "receipt"},
    "social media post": {"post", "tweet", "instagram", "tiktok", "social", "comment"},
    "web page or app interface": {"website", "page", "app", "interface", "screen", "account"},
    "street": {"street", "road", "city", "outside"},
    "food": {"food", "eat", "eating", "meal"},
    "product": {"product", "item", "gift", "bought", "buy"},
    "office": {"office", "work", "business"},
    "vehicle interior": {"car", "drive", "driving", "vehicle"},
}


def shot_intervals(duration: float, scene_times: list[float]) -> list[dict[str, Any]]:
    cuts = sorted({round(float(value), 3) for value in scene_times if 0.05 < float(value) < duration})
    bounds = [0.0, *cuts, float(duration)]
    return [
        {"id": f"shot-{index + 1:03d}", "start": start, "end": end}
        for index, (start, end) in enumerate(zip(bounds, bounds[1:])) if end - start > 0.02
    ]


def representative_sample_times(
    shots: list[dict[str, Any]], sample_times: list[float], limit: int = MAX_SEMANTIC_FRAMES,
) -> list[float]:
    """Choose one midpoint-nearest sample per shot, then a second where capacity allows."""
    choices: list[list[float]] = []
    for shot in shots:
        inside = [value for value in sample_times if shot["start"] <= value < shot["end"]]
        if not inside:
            continue
        midpoint = (shot["start"] + shot["end"]) / 2
        ordered = sorted(inside, key=lambda value: (abs(value - midpoint), value))
        choices.append(ordered)
    selected = [values[0] for values in choices]
    if len(selected) > limit:
        step = len(selected) / limit
        return [selected[min(len(selected) - 1, int(index * step))] for index in range(limit)]
    for rank in (1, 2):
        for values in choices:
            if len(selected) >= limit:
                break
            if len(values) > rank:
                selected.append(values[rank])
    return sorted(set(selected))


def _frame_change_scores(frame_paths: list[Path]) -> list[float | None]:
    import cv2

    prior = None
    scores: list[float | None] = []
    for path in frame_paths:
        frame = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            scores.append(None)
            continue
        small = cv2.resize(frame, (64, 64), interpolation=cv2.INTER_AREA).astype("float32") / 255.0
        scores.append(None if prior is None else round(float(abs(small - prior).mean()), 6))
        prior = small
    return scores


class ClipSemanticDetector:
    """One local CLIP model load and sparse batched zero-shot inference."""

    model_id = CLIP_MODEL_ID

    def __init__(self) -> None:
        import torch
        from transformers import CLIPModel, CLIPProcessor

        cache_dir = config.models_dir() / "hf"
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.processor = CLIPProcessor.from_pretrained(self.model_id, cache_dir=cache_dir)
        self.model = CLIPModel.from_pretrained(self.model_id, cache_dir=cache_dir).to(self.device).eval()
        self._torch = torch
        self.prompts = [f"a photo of {label}" for labels in CONCEPTS.values() for label in labels]
        self.group_ranges: dict[str, tuple[int, int]] = {}
        offset = 0
        for group, labels in CONCEPTS.items():
            self.group_ranges[group] = (offset, offset + len(labels))
            offset += len(labels)
        text = self.processor(text=self.prompts, return_tensors="pt", padding=True)
        with torch.inference_mode():
            features = self.model.get_text_features(**{key: value.to(self.device) for key, value in text.items()})
            self.text_features = features / features.norm(dim=-1, keepdim=True)

    def analyze(self, frame_paths: list[Path], timestamps: list[float]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        from PIL import Image

        started = time.monotonic()
        changes = _frame_change_scores(frame_paths)
        observations: list[dict[str, Any]] = []
        peak_memory = 0
        for begin in range(0, len(frame_paths), SEMANTIC_BATCH_SIZE):
            paths = frame_paths[begin:begin + SEMANTIC_BATCH_SIZE]
            images = [Image.open(path).convert("RGB") for path in paths]
            inputs = self.processor(images=images, return_tensors="pt")
            with self._torch.inference_mode():
                image_features = self.model.get_image_features(pixel_values=inputs["pixel_values"].to(self.device))
                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                similarities = (image_features @ self.text_features.T * 100.0).cpu()
            if self.device == "cuda":
                peak_memory = max(peak_memory, int(self._torch.cuda.max_memory_allocated()))
            for local_index, row in enumerate(similarities):
                observation: dict[str, Any] = {
                    "timestamp": timestamps[begin + local_index],
                    "frame_ref": f"source@{timestamps[begin + local_index]:.3f}s",
                    "frame_change_from_previous": changes[begin + local_index],
                    "model_or_detector": self.model_id,
                }
                for group, labels in CONCEPTS.items():
                    start, end = self.group_ranges[group]
                    probabilities = row[start:end].softmax(dim=0)
                    count = 3 if group == "objects" else 1
                    values, indices = probabilities.topk(min(count, len(labels)))
                    threshold = 0.16 if group == "objects" else 0.30
                    found = [
                        {"label": labels[int(index)], "confidence": round(float(value), 4)}
                        for value, index in zip(values, indices) if float(value) >= threshold
                    ]
                    observation[group] = found
                observations.append(observation)
            for image in images:
                image.close()
        runtime = {
            "model": self.model_id, "device": self.device, "sampled_frames": len(frame_paths),
            "inference_batches": math.ceil(len(frame_paths) / SEMANTIC_BATCH_SIZE),
            "runtime_sec": round(time.monotonic() - started, 4),
            "peak_gpu_memory_bytes": peak_memory or None,
        }
        return observations, runtime

    def unload(self) -> None:
        if self.device == "cuda":
            self.model.to("cpu")
            self._torch.cuda.empty_cache()


def _in_interval(timestamp: float, shot: dict[str, Any]) -> bool:
    return shot["start"] <= timestamp < shot["end"] or (
        timestamp == shot["end"] and timestamp == shot["start"]
    )


def _dominant(items: list[dict[str, Any]], group: str) -> tuple[str | None, float | None]:
    scores: dict[str, list[float]] = {}
    for item in items:
        for concept in item.get(group) or []:
            scores.setdefault(str(concept["label"]), []).append(float(concept["confidence"]))
    if not scores:
        return None, None
    label = max(scores, key=lambda key: (len(scores[key]), mean(scores[key])))
    return label, round(mean(scores[label]), 4)


def _transcript_for(segments: list[dict[str, Any]], start: float, end: float) -> tuple[str, list[dict[str, Any]]]:
    overlapping = [
        item for item in segments
        if isinstance(item, dict) and float(item.get("end") or item.get("start") or 0) > start
        and float(item.get("start") or 0) < end
    ]
    return " ".join(str(item.get("text") or "") for item in overlapping).strip(), [
        {"start": item.get("start"), "end": item.get("end"), "text": item.get("text")}
        for item in overlapping
    ]


def _semantic_speech_overlap(labels: list[str], transcript: str) -> tuple[float, list[str]]:
    words = set(re.findall(r"[\w$]+", transcript.casefold()))
    matched = []
    for label in labels:
        terms = _SYNONYMS.get(label, set(re.findall(r"\w+", label.casefold())))
        if words & terms:
            matched.append(label)
    return (len(matched) / max(1, len(labels))), matched


def _ocr_summary(raw_ocr: list[dict[str, Any]], shot: dict[str, Any]) -> dict[str, float]:
    sample_counts: Counter[float] = Counter()
    areas: list[float] = []
    for item in raw_ocr:
        timestamp = float(item.get("timestamp") or 0)
        if not _in_interval(timestamp, shot):
            continue
        sample_counts[timestamp] += 1
        box = item.get("bbox") or {}
        areas.append(float(box.get("width") or 0) * float(box.get("height") or 0))
    return {
        "detections_per_sample": round(mean(sample_counts.values()), 3) if sample_counts else 0.0,
        "mean_text_area": round(mean(areas), 6) if areas else 0.0,
    }


def _classify_unit(
    shot: dict[str, Any], faces: list[dict[str, Any]], semantics: list[dict[str, Any]],
    raw_ocr: list[dict[str, Any]], transcript_segments: list[dict[str, Any]], layout: dict[str, Any],
) -> dict[str, Any]:
    duration = shot["end"] - shot["start"]
    face_hits = sum(1 for item in faces if int(item.get("face_count") or 0) > 0)
    face_persistence = face_hits / len(faces) if faces else 0.0
    largest_areas = [
        max((float(face["bbox"]["width"]) * float(face["bbox"]["height"]) for face in item.get("faces") or []), default=0.0)
        for item in faces
    ]
    median_face_area = median(largest_areas) if largest_areas else 0.0
    obj, obj_conf = _dominant(semantics, "objects")
    environment, environment_conf = _dominant(semantics, "environments")
    action, action_conf = _dominant(semantics, "actions")
    style, style_conf = _dominant(semantics, "visual_style")
    labels = [value for value in (obj, environment) if value and "unclear" not in value]
    transcript, transcript_refs = _transcript_for(transcript_segments, shot["start"], shot["end"])
    overlap, matched = _semantic_speech_overlap(labels, transcript)
    # The first selected frame may follow a different shot; only compare
    # subsequent representative frames within this temporal unit.
    changes = [
        float(item["frame_change_from_previous"])
        for item in semantics[1:] if item.get("frame_change_from_previous") is not None
    ]
    median_change = median(changes) if changes else None
    static = len(semantics) >= 2 and median_change is not None and median_change <= 0.045
    ocr = _ocr_summary(raw_ocr, shot)
    interface_semantic = environment == "computer screen or interface" or obj in {
        "social media post", "web page or app interface", "chart or graph", "document",
    }
    low_face_persistence = face_persistence <= 0.34
    screenshot_support = (
        low_face_persistence
        and interface_semantic
        and style == "static screenshot"
        and (style_conf or 0) >= 0.38
        and static
        and ocr["detections_per_sample"] >= 2
    )
    graphic_support = (
        low_face_persistence
        and style == "meme or designed graphic"
        and static
        and ocr["detections_per_sample"] >= 1
    )
    screen_recording_support = (
        low_face_persistence
        and interface_semantic
        and style == "screen recording"
        and (style_conf or 0) >= 0.38
        and len(semantics) >= 2
        and median_change is not None
        and median_change > 0.045
        and ocr["detections_per_sample"] >= 2
    )
    interface_overlay_support = (
        not low_face_persistence
        and interface_semantic
        and style in {"static screenshot", "screen recording"}
        and (style_conf or 0) >= 0.5
        and ocr["detections_per_sample"] >= 2
    )
    speaking_semantic = action == "person speaking to camera" and (action_conf or 0) >= 0.34
    talking_support = face_persistence >= 0.65 and median_face_area >= 0.012 and (
        len(faces) >= 2 or duration >= 1.5
    )
    demonstrates = action in {"person pointing", "hands demonstrating an object", "person using a phone", "person using a computer"}
    illustrative_style = style == "inserted illustrative footage" and (style_conf or 0) >= 0.45

    visual_type = "uncertain"
    confidence = 0.35
    reasons: list[str] = []
    if screenshot_support:
        visual_type, confidence = "screenshot", min(0.92, 0.55 + (style_conf or obj_conf or 0) * 0.35)
        reasons.extend(["interface_semantics", "static_across_representative_frames", "ocr_density_support"])
    elif screen_recording_support:
        visual_type, confidence = "screen_recording", min(0.88, 0.5 + (environment_conf or obj_conf or 0) * 0.35)
        reasons.extend(["interface_semantics", "visual_change_across_representative_frames"])
    elif graphic_support:
        visual_type, confidence = "meme_or_graphic", min(0.88, 0.5 + (style_conf or 0) * 0.4)
        reasons.extend(["graphic_semantics", "static_across_representative_frames", "ocr_support"])
    elif talking_support and interface_overlay_support:
        visual_type, confidence = "mixed", min(0.9, 0.56 + face_persistence * 0.15 + (style_conf or 0) * 0.1)
        reasons.extend(["persistent_face", "interface_overlay"])
    elif talking_support and overlap > 0 and demonstrates:
        visual_type, confidence = "mixed", min(0.9, 0.55 + face_persistence * 0.2 + overlap * 0.15)
        reasons.extend(["persistent_face", "visual_demonstration_matches_speech"])
    elif talking_support:
        visual_type, confidence = "talking_head", min(0.95, 0.5 + face_persistence * 0.3 + min(0.12, median_face_area))
        reasons.extend(["persistent_face", "face_size", "shot_continuity"])
        if speaking_semantic:
            reasons.append("speaking_to_camera_semantics")
            confidence = min(0.97, confidence + 0.06)
    elif face_persistence <= 0.34 and labels and overlap > 0 and (obj_conf or environment_conf or 0) >= 0.24:
        visual_type, confidence = "b_roll", min(0.94, 0.5 + overlap * 0.22 + (obj_conf or environment_conf or 0) * 0.25)
        reasons.extend(["semantic_subject", "subject_matches_overlapping_speech", "low_face_persistence"])
    elif face_persistence <= 0.34 and labels and illustrative_style and transcript:
        visual_type, confidence = "b_roll", min(0.78, 0.45 + (style_conf or 0) * 0.25)
        reasons.extend(["illustrative_footage_semantics", "speech_overlap_in_time", "low_face_persistence"])
    elif face_persistence <= 0.2 and environment and environment != "unclear scene" and (environment_conf or 0) >= 0.34:
        visual_type, confidence = "environment", min(0.82, 0.48 + (environment_conf or 0) * 0.3)
        reasons.extend(["environment_semantics", "low_face_persistence"])
    elif 0.25 < face_persistence < 0.75 and labels:
        visual_type, confidence = "mixed", 0.55
        reasons.extend(["intermittent_face", "additional_visual_subject"])
    else:
        reasons.append("insufficient_combined_evidence")

    if not transcript:
        relation, relation_confidence = "no_speech", 1.0
    elif visual_type == "talking_head":
        relation, relation_confidence = "speaker_visible", round(min(0.95, 0.55 + face_persistence * 0.35), 4)
    elif visual_type == "b_roll" and overlap > 0:
        relation = "demonstrates_speech" if demonstrates else "illustrates_speech"
        relation_confidence = round(min(0.92, 0.52 + overlap * 0.3), 4)
    elif visual_type == "b_roll":
        relation, relation_confidence = "contextual_cutaway", round(min(0.72, confidence), 4)
    elif visual_type in {"screenshot", "screen_recording", "meme_or_graphic"} and overlap > 0:
        relation, relation_confidence = "illustrates_speech", round(min(0.82, 0.5 + overlap * 0.25), 4)
    elif visual_type == "mixed" and demonstrates and overlap > 0:
        relation, relation_confidence = "demonstrates_speech", round(min(0.85, 0.5 + overlap * 0.25), 4)
    else:
        relation, relation_confidence = "unrelated_or_unclear", 0.35

    frame_refs = [item.get("frame_ref") for item in semantics if item.get("frame_ref")]
    return {
        "id": shot["id"], "start_ms": round(shot["start"] * 1000), "end_ms": round(shot["end"] * 1000),
        "representative_frame_timestamps_ms": [round(float(item["timestamp"]) * 1000) for item in semantics],
        "representative_frame_refs": frame_refs, "source_shot_ids": [shot["id"]],
        "visual_type": visual_type, "confidence": round(confidence, 4),
        "visual_subject": obj or environment,
        "people_faces": {
            "sample_count": len(faces), "face_present_ratio": round(face_persistence, 4),
            "median_largest_face_area_ratio": round(median_face_area, 6),
        },
        "objects_entities": ([{"label": obj, "confidence": obj_conf}] if obj else []),
        "actions_activity": ([{"label": action, "confidence": action_conf}] if action and action != "no clear action" else []),
        "scene_environment": ({"label": environment, "confidence": environment_conf} if environment and environment != "unclear scene" else None),
        "relation_to_speech": {"type": relation, "confidence": relation_confidence},
        "related_transcript_span": transcript_refs,
        "evidence": {
            "classification_reasons": reasons, "matched_semantic_labels": matched,
            "ocr": ocr, "median_frame_change": round(median_change, 6) if median_change is not None else None,
            "layout_mode": layout.get("layout_mode"), "semantic_observation_count": len(semantics),
        },
        "uncertainty": {
            "status": "uncertain" if visual_type == "uncertain" or confidence < 0.6 else "supported",
            "limitations": [] if semantics else ["No semantic representative frame was available."],
        },
    }


def _merge_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for unit in units:
        if not merged:
            merged.append(unit)
            continue
        prior = merged[-1]
        compatible_subject = prior.get("visual_subject") == unit.get("visual_subject") or not prior.get("visual_subject") or not unit.get("visual_subject")
        if (
            prior["visual_type"] == unit["visual_type"]
            and prior["relation_to_speech"]["type"] == unit["relation_to_speech"]["type"]
            and compatible_subject and unit["start_ms"] - prior["end_ms"] <= 100
        ):
            prior["end_ms"] = unit["end_ms"]
            prior["source_shot_ids"].extend(unit["source_shot_ids"])
            prior["representative_frame_timestamps_ms"].extend(unit["representative_frame_timestamps_ms"])
            prior["representative_frame_refs"].extend(unit["representative_frame_refs"])
            prior["related_transcript_span"].extend(unit["related_transcript_span"])
            prior["confidence"] = round((prior["confidence"] + unit["confidence"]) / 2, 4)
            total_samples = prior["people_faces"]["sample_count"] + unit["people_faces"]["sample_count"]
            if total_samples:
                prior_ratio = prior["people_faces"]["face_present_ratio"]
                unit_ratio = unit["people_faces"]["face_present_ratio"]
                prior["people_faces"]["face_present_ratio"] = round(
                    (prior_ratio * prior["people_faces"]["sample_count"] + unit_ratio * unit["people_faces"]["sample_count"]) / total_samples, 4
                )
                prior["people_faces"]["sample_count"] = total_samples
        else:
            merged.append(unit)
    for index, unit in enumerate(merged, start=1):
        unit["id"] = f"visual-unit-{index:03d}"
    return merged


def _summary(units: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    scores: dict[str, list[float]] = {}
    for unit in units:
        values = unit.get(key) or []
        if isinstance(values, dict):
            values = [values]
        for item in values:
            if item and item.get("label"):
                scores.setdefault(item["label"], []).append(float(item.get("confidence") or 0))
    return [
        {"label": label, "confidence": round(mean(values), 4), "unit_count": len(values)}
        for label, values in sorted(scores.items(), key=lambda item: (-len(item[1]), -mean(item[1]), item[0]))
    ]


def build_visual_understanding(
    *, duration: float, scene_times: list[float], raw_faces: list[dict[str, Any]],
    semantic_observations: list[dict[str, Any]], raw_ocr: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]], layout: dict[str, Any],
    semantic_runtime: dict[str, Any] | None = None, semantic_error: str | None = None,
) -> dict[str, Any]:
    shots = shot_intervals(duration, scene_times)
    units = []
    for shot in shots:
        faces = [item for item in raw_faces if _in_interval(float(item.get("timestamp") or 0), shot)]
        semantics = [item for item in semantic_observations if _in_interval(float(item.get("timestamp") or 0), shot)]
        units.append(_classify_unit(shot, faces, semantics, raw_ocr, transcript_segments, layout))
    units = _merge_units(units)
    b_roll = []
    for unit in units:
        if unit["visual_type"] != "b_roll":
            continue
        confidence = float(unit["confidence"])
        b_roll.append({
            "start_ms": unit["start_ms"], "end_ms": unit["end_ms"], "confidence": confidence,
            "certainty": "confirmed" if confidence >= 0.8 else "probable" if confidence >= 0.6 else "uncertain",
            "visual_subject": unit.get("visual_subject"),
            "related_transcript_span": unit["related_transcript_span"],
            "relation_to_speech": unit["relation_to_speech"],
            "source_shot_ids": unit["source_shot_ids"],
            "representative_frame_refs": unit["representative_frame_refs"],
        })
    total_ms = max(1, round(duration * 1000))
    shot_durations = [shot["end"] - shot["start"] for shot in shots]
    ratio = lambda kinds: round(sum(unit["end_ms"] - unit["start_ms"] for unit in units if unit["visual_type"] in kinds) / total_ms, 4)
    metrics = {
        "talking_head_ratio": ratio({"talking_head"}),
        "b_roll_ratio": ratio({"b_roll"}),
        "screenshot_or_graphic_ratio": ratio({"screenshot", "screen_recording", "meme_or_graphic"}),
        "visual_change_rate_per_minute": round(max(0, len(shots) - 1) / max(duration, 0.001) * 60, 4),
        "shot_count": len(shots),
        "median_shot_duration_sec": round(median(shot_durations), 4) if shot_durations else None,
        "average_shot_duration_sec": round(mean(shot_durations), 4) if shot_durations else None,
    }
    semantic_available = bool(semantic_observations)
    return {
        "schema_version": 1,
        "status": "available" if semantic_available else "limited",
        "visual_units": units,
        "b_roll_segments": b_roll,
        "objects_entities_summary": _summary(units, "objects_entities"),
        "scene_environment_summary": _summary(units, "scene_environment"),
        "actions_summary": _summary(units, "actions_activity"),
        "metrics": metrics,
        "evidence": {
            "source_shot_ids": [shot["id"] for shot in shots],
            "raw_face_observation_count": len(raw_faces),
            "raw_semantic_observation_count": len(semantic_observations),
            "raw_ocr_detection_count": len(raw_ocr),
            "generated_camera_data_excluded": True,
        },
        "provenance": {
            "method": "sparse-shot-visual-rules-v1", "semantic_model": CLIP_MODEL_ID if semantic_available else None,
            "face_detector": "UltraFace-RFB-320", "shot_detector": "PySceneDetect ContentDetector",
            "semantic_runtime": semantic_runtime or {},
        },
        "limitations": [
            "CLIP zero-shot labels are relative, not calibrated object detections.",
            "Fine-grained identities and brands are not inferred.",
            "B-roll requires semantic or illustrative support; no-face alone is insufficient.",
            *([f"Semantic inference unavailable: {semantic_error}"] if semantic_error else []),
        ],
    }
