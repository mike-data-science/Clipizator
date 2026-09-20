"""Compact, evidence-backed source-audio interpretation for Video DNA."""

from __future__ import annotations

import math
from statistics import mean, median
from typing import Any


SFX_SUBTYPES = {
    "impact/hit", "whoosh", "riser", "click/shutter", "beep/notification",
    "clap/applause", "engine/mechanical", "crowd", "other_sfx",
}


def _overlap(start: float, end: float, other_start: float, other_end: float) -> float:
    return max(0.0, min(end, other_end) - max(start, other_start))


def _curve_slice(values: list[float], grid: float, start: float, end: float) -> list[float]:
    first = max(0, int(math.floor(start / grid + 1e-9)))
    last = min(len(values), max(first + 1, int(math.ceil(end / grid - 1e-9))))
    return [float(value) for value in values[first:last]]


def _energy_summary(rms: list[float], grid: float, start: float, end: float) -> dict[str, Any]:
    values = _curve_slice(rms, grid, start, end)
    if not values:
        return {"mean_rms": None, "median_rms": None, "peak_rms": None}
    return {
        "mean_rms": round(mean(values), 6), "median_rms": round(median(values), 6),
        "peak_rms": round(max(values), 6),
    }


def _merge_observations(items: list[dict[str, Any]], gap: float = 0.32) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda value: (float(value.get("start") or 0), str(value.get("subtype") or ""))):
        current = dict(item)
        if merged and merged[-1].get("type") == current.get("type") and merged[-1].get("subtype") == current.get("subtype") and float(current["start"]) - float(merged[-1]["end"]) <= gap:
            prior = merged[-1]
            prior["end"] = max(float(prior["end"]), float(current["end"]))
            prior["confidence"] = max(float(prior.get("confidence") or 0), float(current.get("confidence") or 0))
            prior["source_detector_labels"] = sorted(set(prior.get("source_detector_labels") or []) | set(current.get("source_detector_labels") or []))
            prior.setdefault("source_observation_ids", []).extend(current.get("source_observation_ids") or [current.get("id")])
        else:
            current["source_observation_ids"] = current.get("source_observation_ids") or [current.get("id")]
            merged.append(current)
    return merged


def _speech_intervals(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for index, segment in enumerate(segments):
        start = segment.get("start")
        end = segment.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end > start:
            output.append({"id": f"transcript-{index + 1:03d}", "start": float(start), "end": float(end), "text": segment.get("text")})
    return output


def _normalize_audio_observations(raw: list[dict[str, Any]], legacy: list[dict[str, Any]], rms: list[float], grid: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    music = [item for item in raw if item.get("type") == "music" and float(item.get("confidence") or 0) >= 0.4]
    sfx = [item for item in raw if item.get("type") == "sfx" and item.get("subtype") in SFX_SUBTYPES and float(item.get("confidence") or 0) >= 0.45]
    for index, item in enumerate(legacy):
        subtype = "clap/applause" if item.get("type") == "applause" else "crowd" if item.get("type") == "cheer" else None
        if subtype and float(item.get("confidence") or 0) >= 0.45:
            sfx.append({
                "id": f"legacy-event-{index + 1:03d}", "type": "sfx", "subtype": subtype,
                "start": item.get("start"), "end": item.get("end"), "confidence": item.get("confidence"),
                "source_detector_labels": [str(item.get("type"))], "model_or_detector": "+".join(item.get("sources") or ["PANNs"]),
            })
    music = _merge_observations(music, gap=0.4)
    sfx = _merge_observations(sfx, gap=0.32)
    for index, item in enumerate(music, 1):
        item["id"] = f"music-{index:03d}"
        item["energy"] = _energy_summary(rms, grid, float(item["start"]), float(item["end"]))
    for index, item in enumerate(sfx, 1):
        item["id"] = f"sfx-{index:03d}"
        energy = _energy_summary(rms, grid, float(item["start"]), float(item["end"]))
        item["energy_peak"] = energy["peak_rms"]
        item["evidence"] = {"source_observation_ids": [value for value in item.get("source_observation_ids") or [] if value], "source_detector_labels": item.get("source_detector_labels") or []}
    return music, sfx


def _energy_trend(values: list[float]) -> str:
    if len(values) < 4:
        return "uncertain"
    width = max(1, len(values) // 3)
    before, after = mean(values[:width]), mean(values[-width:])
    scale = max(mean(values), 1e-6)
    delta = (after - before) / scale
    return "rising" if delta >= 0.18 else "falling" if delta <= -0.18 else "stable"


def _music_segments(music: list[dict[str, Any]], speech: list[dict[str, Any]], rms: list[float], grid: float) -> list[dict[str, Any]]:
    output = []
    for item in music:
        start, end = float(item["start"]), float(item["end"])
        overlap = sum(_overlap(start, end, segment["start"], segment["end"]) for segment in speech)
        values = _curve_slice(rms, grid, start, end)
        overlap_ratio = min(1.0, overlap / max(end - start, .001))
        output.append({
            "id": item["id"], "start_ms": round(start * 1000), "end_ms": round(end * 1000),
            "confidence": item.get("confidence"), "relative_energy": item.get("energy"),
            "presence": "background" if overlap_ratio >= 0.35 else "dominant",
            "dominance_is_approximate": True, "speech_overlap_ratio": round(overlap_ratio, 4),
            "energy_trend": _energy_trend(values),
            "evidence": {"source_observation_ids": item.get("source_observation_ids") or [], "source_detector_labels": item.get("source_detector_labels") or []},
        })
    return output


def _mask(intervals: list[dict[str, Any]], count: int, grid: float) -> list[bool]:
    output = [False] * count
    for item in intervals:
        start = float(item.get("start", item.get("start_ms", 0) / 1000))
        end = float(item.get("end", item.get("end_ms", 0) / 1000))
        for index in range(max(0, int(math.floor(start / grid + 1e-9))), min(count, int(math.ceil(end / grid - 1e-9)))):
            output[index] = True
    return output


def _audio_segments(duration: float, rms: list[float], grid: float, speech: list[dict[str, Any]], music: list[dict[str, Any]], sfx: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], float]:
    count = max(1, min(len(rms) if rms else math.ceil(duration / grid), math.ceil(duration / grid)))
    speech_mask, music_mask, sfx_mask = _mask(speech, count, grid), _mask(music, count, grid), _mask(sfx, count, grid)
    median_rms = median(rms[:count]) if rms else 0.0
    silence_threshold = max(0.001, median_rms * 0.12)
    labels = []
    for index in range(count):
        quiet = bool(rms) and float(rms[index]) <= silence_threshold
        active = int(speech_mask[index]) + int(music_mask[index]) + int(sfx_mask[index])
        labels.append("silence" if quiet and active == 0 else "mixed" if active >= 2 else "speech" if speech_mask[index] else "music" if music_mask[index] else "sfx" if sfx_mask[index] else "uncertain")
    output = []
    start = 0
    for index in range(1, count + 1):
        if index < count and labels[index] == labels[start]:
            continue
        seg_start, seg_end = start * grid, min(duration, index * grid)
        kind = labels[start]
        output.append({
            "id": f"audio-segment-{len(output) + 1:03d}", "start_ms": round(seg_start * 1000), "end_ms": round(seg_end * 1000),
            "type": kind, "subtype": None, "confidence": 0.95 if kind == "speech" else 0.85 if kind == "silence" else 0.7 if kind in {"music", "sfx", "mixed"} else 0.3,
            "energy": _energy_summary(rms, grid, seg_start, seg_end),
            "source_detector_model": "ASR timestamps + PANNs AudioSet + librosa RMS",
            "evidence": {"speech": any(speech_mask[start:index]), "music": any(music_mask[start:index]), "sfx": any(sfx_mask[start:index])},
        })
        start = index
    # ASR segment boundaries commonly leave one or two empty 100 ms windows.
    # Bridge only short uncertain gaps surrounded by the same supported type.
    index = 1
    while index < len(output) - 1:
        prior, gap, following = output[index - 1:index + 2]
        if gap["type"] == "uncertain" and gap["end_ms"] - gap["start_ms"] <= 350 and prior["type"] == following["type"] and prior["type"] != "silence":
            prior["end_ms"] = following["end_ms"]
            prior["energy"] = _energy_summary(rms, grid, prior["start_ms"] / 1000, prior["end_ms"] / 1000)
            prior["evidence"]["bridged_sparse_timing_gap_ms"] = gap["end_ms"] - gap["start_ms"]
            del output[index:index + 2]
            continue
        index += 1
    for index, item in enumerate(output, 1):
        item["id"] = f"audio-segment-{index:03d}"
    return output, silence_threshold


def _dynamics(rms: list[float], flux: list[float], grid: float, speech: list[dict[str, Any]]) -> dict[str, Any]:
    if not rms:
        return {"status": "unavailable", "transient_peaks": [], "strong_energy_changes": [], "speech_pauses": []}
    ordered = sorted(float(value) for value in rms)
    p10 = ordered[int((len(ordered) - 1) * .1)]
    p90 = ordered[int((len(ordered) - 1) * .9)]
    positive_p10 = max(p10, 1e-6)
    flux_values = [float(value) for value in flux[:len(rms)]]
    flux_med = median(flux_values) if flux_values else 0.0
    flux_mad = median([abs(value - flux_med) for value in flux_values]) if flux_values else 0.0
    positive_flux = [value for value in flux_values if value > 0]
    threshold = max(flux_med + max(3 * flux_mad, flux_med * 1.5), median(positive_flux) * .5 if positive_flux else 0.0)
    transient = []
    for index, value in enumerate(flux_values):
        if threshold <= 0 or value <= threshold or (transient and index * grid - transient[-1]["timestamp_ms"] / 1000 < .3):
            continue
        transient.append({"timestamp_ms": round(index * grid * 1000), "flux": round(value, 6), "rms": round(float(rms[index]), 6)})
    diffs = [abs(float(right) - float(left)) for left, right in zip(rms, rms[1:])]
    diff_med = median(diffs) if diffs else 0.0
    diff_mad = median([abs(value - diff_med) for value in diffs]) if diffs else 0.0
    change_threshold = diff_med + max(3 * diff_mad, diff_med * 1.5)
    changes = [{"timestamp_ms": round((index + 1) * grid * 1000), "delta_rms": round(float(rms[index + 1]) - float(rms[index]), 6)} for index, value in enumerate(diffs) if change_threshold > 0 and value > change_threshold]
    pauses = []
    for left, right in zip(speech, speech[1:]):
        if right["start"] - left["end"] >= .35:
            pauses.append({"start_ms": round(left["end"] * 1000), "end_ms": round(right["start"] * 1000), "duration_ms": round((right["start"] - left["end"]) * 1000)})
    return {
        "status": "available", "average_rms": round(mean(rms), 6), "median_rms": round(median(rms), 6),
        "p10_rms": round(p10, 6), "p90_rms": round(p90, 6),
        "dynamic_range_rms": round(p90 - p10, 6), "dynamic_range_db_approx": round(20 * math.log10(max(p90, 1e-6) / positive_p10), 3),
        "transient_peaks": transient, "strong_energy_changes": changes, "speech_pauses": pauses,
    }


def _ducking(music: list[dict[str, Any]], speech: list[dict[str, Any]], rms: list[float], grid: float) -> list[dict[str, Any]]:
    output = []
    for segment in speech:
        onset = segment["start"]
        if not any(float(item["start"]) < onset < float(item["end"]) for item in music):
            continue
        before = _curve_slice(rms, grid, max(0, onset - .6), onset)
        during = _curve_slice(rms, grid, onset, min(segment["end"], onset + .8))
        if len(before) < 2 or len(during) < 2:
            continue
        before_energy, during_energy = mean(before), mean(during)
        reduction = (before_energy - during_energy) / max(before_energy, 1e-6)
        if reduction < .22:
            continue
        output.append({
            "id": f"ducking-{len(output) + 1:03d}", "start_ms": round(onset * 1000), "end_ms": round(min(segment["end"], onset + .8) * 1000),
            "type": "probable_ducking", "description": "level_reduction_during_speech", "confidence": round(min(.78, .5 + reduction * .45), 4),
            "before_energy": round(before_energy, 6), "during_energy": round(during_energy, 6), "evidence": {"speech_reference": segment["id"], "music_present": True},
        })
    return output


def _relationships(sfx: list[dict[str, Any]], cuts: list[float], visual_units: list[dict[str, Any]], emphasis: list[dict[str, Any]], text_changes: list[dict[str, Any]], speech: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets = [(float(value), "shot_cut", f"cut@{float(value):.3f}s") for value in cuts if float(value) > .05]
    targets.extend((float(unit.get("start_ms") or 0) / 1000, "visual_unit", str(unit.get("id"))) for unit in visual_units if int(unit.get("start_ms") or 0) > 0)
    output = []
    seen = set()
    for event in sfx:
        start, end = float(event["start"]), float(event["end"])
        anchor = (start + end) / 2
        if targets:
            target_time, target_type, target_id = min(targets, key=lambda target: abs(target[0] - anchor))
            delta = round((target_time - anchor) * 1000)
            relation = "aligned_with_cut" if abs(delta) <= 250 else "precedes_cut" if 0 < delta <= 600 else None
            if relation:
                key = (event["id"], relation, target_id)
                if key not in seen:
                    output.append({"relation_type": relation, "audio_event_id": event["id"], "target_type": target_type, "target_id_reference": target_id, "delta_ms": delta, "confidence": round(min(.9, float(event.get("confidence") or 0) * (.9 if relation == "aligned_with_cut" else .72)), 4)})
                    seen.add(key)
        for item in emphasis:
            target = float(item.get("start_ms") or 0) / 1000
            delta = round((target - anchor) * 1000)
            if abs(delta) <= 300 or _overlap(start, end, target, float(item.get("end_ms") or item.get("start_ms") or 0) / 1000) > 0:
                output.append({"relation_type": "aligned_with_caption_emphasis", "audio_event_id": event["id"], "target_type": "caption_emphasis", "target_id_reference": item.get("caption_track_id"), "delta_ms": delta, "confidence": round(min(.88, float(event.get("confidence") or 0) * .82), 4)})
        for item in text_changes:
            target = float(item.get("start") or 0)
            delta = round((target - anchor) * 1000)
            if abs(delta) <= 250:
                output.append({"relation_type": "aligned_with_text_change", "audio_event_id": event["id"], "target_type": "text_track", "target_id_reference": item.get("id"), "delta_ms": delta, "confidence": round(min(.8, float(event.get("confidence") or 0) * .7), 4)})
        for segment in speech:
            if _overlap(start, end, segment["start"], segment["end"]) > 0:
                output.append({"relation_type": "overlaps_spoken_phrase", "audio_event_id": event["id"], "target_type": "transcript", "target_id_reference": segment["id"], "delta_ms": round((segment["start"] - anchor) * 1000), "confidence": round(min(.85, float(event.get("confidence") or 0) * .75), 4)})
                break
    return output


def _coverage(intervals: list[tuple[float, float]], duration: float) -> float:
    if duration <= 0:
        return 0.0
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return round(min(1.0, sum(end - start for start, end in merged) / duration), 4)


def build_audio_intelligence(*, duration: float, transcript_segments: list[dict[str, Any]], legacy_events: list[dict[str, Any]], raw_audio_observations: list[dict[str, Any]], curves: dict[str, Any], visual_units: list[dict[str, Any]], shot_cuts: list[float], caption_emphasis_events: list[dict[str, Any]], text_tracks: list[dict[str, Any]], panns_intelligence_available: bool = False) -> dict[str, Any]:
    grid = float(curves.get("grid_sec") or .1)
    rms = [float(value) for value in curves.get("rms") or []]
    flux = [float(value) for value in curves.get("flux") or []]
    speech = _speech_intervals(transcript_segments)
    raw_music, sfx = _normalize_audio_observations(raw_audio_observations, legacy_events, rms, grid)
    music = _music_segments(raw_music, speech, rms, grid)
    segments, silence_threshold = _audio_segments(duration, rms, grid, speech, raw_music, sfx)
    dynamics = _dynamics(rms, flux, grid, speech)
    ducking = _ducking(raw_music, speech, rms, grid)
    relationships = _relationships(sfx, shot_cuts, visual_units, caption_emphasis_events, text_tracks, speech)
    speech_coverage = _coverage([(item["start"], item["end"]) for item in speech], duration)
    music_coverage = _coverage([(float(item["start"]), float(item["end"])) for item in raw_music], duration)
    overlap_coverage = _coverage([(max(segment["start"], float(item["start"])), min(segment["end"], float(item["end"]))) for segment in speech for item in raw_music if _overlap(segment["start"], segment["end"], float(item["start"]), float(item["end"])) > 0], duration)
    silence_coverage = _coverage([(item["start_ms"] / 1000, item["end_ms"] / 1000) for item in segments if item["type"] == "silence"], duration)
    metrics = {
        "speech_coverage_ratio": speech_coverage, "music_coverage_ratio": music_coverage,
        "silence_ratio": silence_coverage, "sfx_event_count": len(sfx),
        "sfx_events_per_minute": round(len(sfx) / max(duration, .001) * 60, 4),
        "music_speech_overlap_ratio": overlap_coverage, "probable_ducking_event_count": len(ducking),
        "impact_transient_count": len(dynamics.get("transient_peaks") or []),
        "average_rms": dynamics.get("average_rms"), "median_rms": dynamics.get("median_rms"),
        "dynamic_range_rms": dynamics.get("dynamic_range_rms"), "dynamic_range_db_approx": dynamics.get("dynamic_range_db_approx"),
    }
    return {
        "schema_version": 1, "status": "available" if rms or speech or raw_audio_observations else "unavailable",
        "audio_segments": segments, "music_segments": music,
        "sfx_events": [{
            "id": item["id"], "start_ms": round(float(item["start"]) * 1000), "end_ms": round(float(item["end"]) * 1000),
            "type": "sfx", "subtype": item.get("subtype"), "confidence": item.get("confidence"),
            "energy_peak": item.get("energy_peak"), "source_detector_labels": item.get("source_detector_labels") or [],
            "model_or_detector": item.get("model_or_detector"), "evidence": item.get("evidence") or {},
        } for item in sfx],
        "dynamics": dynamics, "ducking_events": ducking, "cross_modal_relationships": relationships, "metrics": metrics,
        "evidence": {"raw_audio_observation_count": len(raw_audio_observations), "panns_intelligence_available": panns_intelligence_available, "legacy_event_count": len(legacy_events), "rms_sample_count": len(rms), "flux_sample_count": len(flux), "transcript_segment_count": len(speech), "silence_threshold_rms": round(silence_threshold, 6), "generated_render_audio_excluded": True},
        "provenance": {"method": "source-audio-intelligence-rules-v1", "event_model": "PANNs Cnn14_DecisionLevelMax/AudioSet", "signal_features": "librosa RMS + spectral flux", "speech_timing": "ASR/diarization", "source_audio_only": True},
        "limitations": ["Music and SFX labels are limited to a conservative AudioSet subset.", "Speech/music dominance and ducking are approximate without source separation.", "Temporal alignment indicates proximity, not causality.", "Ambience remains uncertain without supported semantic evidence."],
    }
