"""Conservative execution plans for Semantic Compression v1.1.

This module approves and refines cuts; it does not render media.  OPTIONAL_KEEP
is always retained, protected or high-risk removals are skipped, and every
result is deterministic and inspectable.
"""
from __future__ import annotations

import hashlib
import statistics
import time
from dataclasses import dataclass
from typing import Any

EXECUTION_VERSION = "safe-edit-execution-v1"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ExecutionPolicy:
    allow_reviewed_false_starts: bool = True
    max_boundary_shift_ms: int = 80
    min_removal_ms: int = 80
    min_retained_range_ms: int = 80
    false_start_crossfade_ms: int = 20
    silence_crossfade_ms: int = 40
    max_crossfade_ms: int = 80


def _stable_id(candidate_id: str, decision_id: str, left: int, right: int) -> str:
    raw = f"{candidate_id}:{decision_id}:{left}:{right}"
    return f"cut_{hashlib.sha1(raw.encode()).hexdigest()[:12]}"


def _word_boundaries(segments: list[dict[str, Any]], lo: int, hi: int) -> list[int]:
    points: set[int] = set()
    for segment in segments:
        for word in segment.get("words") or []:
            start = round(float(word.get("start_ms", (word.get("start") or 0) * 1000)))
            end = round(float(word.get("end_ms", (word.get("end") or word.get("start") or 0) * 1000)))
            if lo <= start <= hi:
                points.add(start)
            if lo <= end <= hi:
                points.add(end)
    return sorted(points)


def _energy_at(timestamp_ms: int, rms: list[float], grid_sec: float) -> float | None:
    if not rms or grid_sec <= 0:
        return None
    index = min(len(rms) - 1, max(0, round(timestamp_ms / (grid_sec * 1000))))
    return float(rms[index])


def _semantic_boundary_points(segments: list[dict[str, Any]], lo: int, hi: int) -> tuple[set[int], set[int]]:
    phrase: set[int] = set()
    speaker: set[int] = set()
    ordered = sorted(segments, key=lambda item: float(item.get("start", item.get("start_ms", 0))))
    for index, segment in enumerate(ordered):
        start = round(float(segment.get("start_ms", (segment.get("start") or 0) * 1000)))
        end = round(float(segment.get("end_ms", (segment.get("end") or 0) * 1000)))
        if lo <= start <= hi:
            phrase.add(start)
        if lo <= end <= hi:
            phrase.add(end)
        if index and segment.get("speaker") != ordered[index - 1].get("speaker") and lo <= start <= hi:
            speaker.add(start)
        for word in segment.get("words") or []:
            if str(word.get("word") or word.get("text") or "").rstrip().endswith((".", "?", "!", ";", ":")):
                point = round(float(word.get("end_ms", (word.get("end") or 0) * 1000)))
                if lo <= point <= hi:
                    phrase.add(point)
    return phrase, speaker


def _refine_edge(
    desired_ms: int, allowed: tuple[int, int], *, segments: list[dict[str, Any]],
    source_cuts_ms: list[int], rms: list[float], grid_sec: float, fps: float,
    policy: ExecutionPolicy,
) -> tuple[int, dict[str, Any]]:
    lo = max(allowed[0], desired_ms - policy.max_boundary_shift_ms)
    hi = min(allowed[1], desired_ms + policy.max_boundary_shift_ms)
    if lo > hi:
        return desired_ms, {"method": "desired_boundary", "energy": _energy_at(desired_ms, rms, grid_sec)}
    word_points = _word_boundaries(segments, lo, hi)
    phrase_points, speaker_points = _semantic_boundary_points(segments, lo, hi)
    scene_points = [point for point in source_cuts_ms if lo <= point <= hi]
    frame_ms = 1000 / max(fps, 1)
    frame_points = [
        round(index * frame_ms)
        for index in range(max(0, int(lo / frame_ms) - 1), int(hi / frame_ms) + 2)
        if lo <= round(index * frame_ms) <= hi
    ]
    points = sorted({desired_ms, *word_points, *phrase_points, *speaker_points, *scene_points, *frame_points})
    median_energy = statistics.median(rms) if rms else None

    def score(point: int) -> tuple[float, int]:
        energy = _energy_at(point, rms, grid_sec)
        value = 0.0
        if point in scene_points:
            value += 1.5
        if point in word_points:
            value += 2.0
        if point in phrase_points:
            value += 1.0
        if point in speaker_points:
            value += .75
        if point in frame_points:
            value += .5
        if energy is not None and median_energy is not None:
            value += max(0.0, 4.0 * (1.0 - energy / max(median_energy, 1e-6)))
        value -= abs(point - desired_ms) / max(1, policy.max_boundary_shift_ms)
        return value, -abs(point - desired_ms)

    chosen = max(points, key=score)
    chosen_energy = _energy_at(chosen, rms, grid_sec)
    low_energy = chosen_energy is not None and median_energy is not None and chosen_energy <= median_energy * .6
    method = ("low_energy" if low_energy else "word_boundary" if chosen in word_points
              else "phrase_boundary" if chosen in phrase_points else "speaker_boundary" if chosen in speaker_points
              else "source_cut" if chosen in scene_points else "frame_boundary" if chosen in frame_points else "desired_boundary")
    return chosen, {
        "method": method, "energy": chosen_energy,
        "low_energy": low_energy, "word_boundary": chosen in word_points,
        "phrase_boundary": chosen in phrase_points, "speaker_boundary": chosen in speaker_points,
        "source_cut_aligned": chosen in scene_points,
        "frame_aligned": chosen in frame_points, "nearest_frame_ms": round(round(chosen / frame_ms) * frame_ms),
    }


def _overlaps(a: int, b: int, span: dict[str, Any]) -> bool:
    return a < int(span.get("end_ms", 0)) and b > int(span.get("start_ms", 0))


def _skip(decision: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "decision_id": decision.get("decision_id"), "action": decision.get("action"),
        "reason": decision.get("reason"), "start_ms": decision.get("start_ms"),
        "end_ms": decision.get("end_ms"), "skip_reason": reason,
        "potential_time_saving_ms": max(0, int(decision.get("end_ms", 0)) - int(decision.get("start_ms", 0))),
        "cut_risk": decision.get("cut_risk"), "join_risk": decision.get("join_risk") or {},
    }


def _retained_ranges(start: int, end: int, removals: list[dict[str, Any]], minimum: int) -> list[dict[str, int]]:
    ranges: list[dict[str, int]] = []
    cursor = start
    for removal in sorted(removals, key=lambda item: item["refined_left_boundary_ms"]):
        left, right = removal["refined_left_boundary_ms"], removal["refined_right_boundary_ms"]
        if left < cursor or right <= left or left < start or right > end:
            raise ValueError("invalid_or_overlapping_refined_removal")
        if left - cursor < minimum and cursor != start:
            raise ValueError("retained_range_too_short")
        if cursor < left:
            ranges.append({"start_ms": cursor, "end_ms": left})
        cursor = right
    if cursor < end:
        ranges.append({"start_ms": cursor, "end_ms": end})
    if not ranges or any(item["end_ms"] <= item["start_ms"] for item in ranges):
        raise ValueError("no_valid_retained_ranges")
    return ranges


def _crossfade_ms(reason: str, join: dict[str, Any], policy: ExecutionPolicy) -> int:
    if join.get("audio_join_risk") != "low":
        return 0
    value = policy.silence_crossfade_ms if reason == "dead_air" else policy.false_start_crossfade_ms if reason in {"false_start", "repeated_phrase", "self_correction"} else 0
    return max(0, min(policy.max_crossfade_ms, value))


def build_execution_plan(
    *, semantic_compression: dict[str, Any], segments: list[dict[str, Any]],
    source_editing: dict[str, Any] | None = None, rms: list[float] | None = None,
    rms_grid_sec: float = .1, fps: float = 25.0, policy: ExecutionPolicy | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    policy = policy or ExecutionPolicy()
    source_editing = source_editing or {}
    source_cuts = sorted({int(item.get("timestamp_ms", item.get("start_ms", 0)) or 0) for item in source_editing.get("cuts") or []})
    candidates = []
    for plan in semantic_compression.get("candidates") or []:
        candidate_id = str(plan.get("candidate_id") or "")
        start, end = int(plan["original_start_ms"]), int(plan["original_end_ms"])
        executed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        pending = sorted(plan.get("decisions") or [], key=lambda item: (int(item.get("start_ms", 0)), int(item.get("end_ms", 0))))
        proposed_removals = [item for item in pending if item.get("action") == "remove"]
        overlapping_ids: set[str] = set()
        for left_item, right_item in zip(proposed_removals, proposed_removals[1:]):
            if int(right_item.get("start_ms", 0)) < int(left_item.get("end_ms", 0)):
                overlapping_ids.update({str(left_item.get("decision_id")), str(right_item.get("decision_id"))})
        for decision in pending:
            action = decision.get("action")
            if action != "remove":
                if action == "optional_keep":
                    skipped.append(_skip(decision, "optional_keep_retained"))
                continue
            if decision.get("micro_cut_suppressed"):
                skipped.append(_skip(decision, "micro_cut_suppressed")); continue
            a, b = int(decision.get("start_ms", 0)), int(decision.get("end_ms", 0))
            join = decision.get("join_risk") or {}
            reason = str(decision.get("reason") or "unknown")
            if a < start or b > end or b <= a or b - a < policy.min_removal_ms:
                skipped.append(_skip(decision, "invalid_or_too_short_interval")); continue
            if str(decision.get("decision_id")) in overlapping_ids:
                skipped.append(_skip(decision, "overlapping_removal")); continue
            if any(_overlaps(a, b, span) for span in plan.get("protected_ranges") or []):
                skipped.append(_skip(decision, "protected_content")); continue
            if decision.get("cut_value") is not None and decision.get("cut_cost") is not None and float(decision["cut_value"]) <= float(decision["cut_cost"]):
                skipped.append(_skip(decision, "non_positive_cut_utility")); continue
            if decision.get("cut_risk") == "high" or join.get("audio_join_risk") == "high":
                skipped.append(_skip(decision, "high_risk_join")); continue
            if join.get("visual_jump_risk") == "high":
                item = _skip(decision, "visual_cover_required")
                item["requires_visual_cover"] = True
                skipped.append(item); continue
            reviewed_exception = policy.allow_reviewed_false_starts and reason in {"false_start", "repeated_phrase", "self_correction"} and decision.get("cut_risk") in {"low", "medium"} and join.get("audio_join_risk", "low") == "low"
            integrity = plan.get("semantic_integrity_status")
            if integrity == "needs_review" and not reviewed_exception:
                skipped.append(_skip(decision, "candidate_needs_review")); continue
            if integrity not in {"preserved", "safe", "acceptable", "needs_review"}:
                skipped.append(_skip(decision, "semantic_integrity_not_safe")); continue
            window = decision.get("recommended_cut_window_ms") or [a, b]
            allowed = (max(start, int(window[0])), min(end, int(window[1])))
            left, left_meta = _refine_edge(a, allowed, segments=segments, source_cuts_ms=source_cuts, rms=rms or [], grid_sec=rms_grid_sec, fps=fps, policy=policy)
            right, right_meta = _refine_edge(b, allowed, segments=segments, source_cuts_ms=source_cuts, rms=rms or [], grid_sec=rms_grid_sec, fps=fps, policy=policy)
            if right - left < policy.min_removal_ms:
                skipped.append(_skip(decision, "refinement_collapsed_interval")); continue
            visual_risk = join.get("visual_jump_risk", "low")
            aligned = bool(left_meta.get("source_cut_aligned") or right_meta.get("source_cut_aligned"))
            requires_cover = visual_risk == "high" or (visual_risk == "medium" and not aligned)
            if requires_cover:
                item = _skip(decision, "visual_cover_required")
                item["requires_visual_cover"] = True
                skipped.append(item); continue
            fade = _crossfade_ms(reason, join, policy)
            executed.append({
                "cut_id": _stable_id(candidate_id, str(decision.get("decision_id")), left, right),
                "decision_id": decision.get("decision_id"), "desired_start_ms": a, "desired_end_ms": b,
                "refined_left_boundary_ms": left, "refined_right_boundary_ms": right,
                "boundary_shift_ms": {"left": left - a, "right": right - b}, "reason": reason,
                "audio_crossfade_ms": fade, "visual_jump_risk": visual_risk,
                "requires_visual_cover": False, "source_cut_alignment": aligned,
                "boundary_evidence": {"left": left_meta, "right": right_meta},
                "confidence": round(min(float(decision.get("confidence") or .5), .94 if left_meta["method"] != "desired_boundary" or right_meta["method"] != "desired_boundary" else .82), 4),
            })
        # Validate all approved removals together; a malformed set degrades to unchanged.
        try:
            retained = _retained_ranges(start, end, executed, policy.min_retained_range_ms)
        except ValueError as error:
            skipped.extend({**_skip(d, str(error)), "decision_id": d.get("decision_id")} for d in pending if d.get("action") == "remove")
            executed = []
            retained = [{"start_ms": start, "end_ms": end}]
        planned_remove_count = sum(d.get("action") == "remove" for d in pending)
        if not executed:
            status = "review_required" if planned_remove_count else "unchanged"
        elif len(executed) < planned_remove_count:
            status = "partial_safe"
        else:
            status = "auto_safe"
        final_duration = sum(item["end_ms"] - item["start_ms"] for item in retained)
        candidates.append({
            "candidate_id": candidate_id, "source_range": {"start_ms": start, "end_ms": end},
            "semantic_compression_version": semantic_compression.get("semantic_compression_version"),
            "execution_version": EXECUTION_VERSION, "execution_status": status,
            "planned_decisions": pending, "executed_removals": executed, "skipped_removals": skipped,
            "final_retained_ranges": retained, "final_duration_ms": final_duration,
            "time_saved_ms": end - start - final_duration, "internal_cut_count": len(executed),
            "crossfade_count": sum(item["audio_crossfade_ms"] > 0 for item in executed),
            "visual_cover_required_count": sum(bool(item.get("requires_visual_cover")) for item in skipped),
            "review_required_count": sum(item["skip_reason"] not in {"optional_keep_retained"} for item in skipped),
            "warnings": sorted({item["skip_reason"] for item in skipped if item["skip_reason"] != "optional_keep_retained"}),
            "fps": fps,
        })
    return {
        "execution_version": EXECUTION_VERSION, "schema_version": SCHEMA_VERSION,
        "semantic_compression_version": semantic_compression.get("semantic_compression_version"),
        "status": "available", "candidate_count": len(candidates), "candidates": candidates,
        "metrics": {
            "executed_cut_count": sum(item["internal_cut_count"] for item in candidates),
            "skipped_removal_count": sum(len(item["skipped_removals"]) for item in candidates),
            "time_saved_ms": sum(item["time_saved_ms"] for item in candidates),
            "runtime_ms": round((time.monotonic() - started) * 1000, 3),
        },
        "policy": policy.__dict__,
        "provenance": {"method": "deterministic-safe-boundary-rules-v1", "llm_used": False, "media_decode_used": False},
    }
