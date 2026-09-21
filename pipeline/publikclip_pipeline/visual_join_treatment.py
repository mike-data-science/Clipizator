"""Visual continuity repair for cuts already approved by Safe Edit Execution.

The planner is deliberately independent of semantic approval.  It may expand
an existing removal inside its approved window when no retained word is
touched, or attach a subtle crop treatment after the join.  It never restores
removed media, invents a transition, or changes the Safe Edit artifact.
"""
from __future__ import annotations

import copy
import math
import statistics
import time
from dataclasses import dataclass
from typing import Any, Callable

VERSION = "visual-join-treatment-v1"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class VisualJoinPolicy:
    max_shift_ms: int = 80
    acceptable_score: float = .035
    boundary_improvement: float = .008
    treatment_improvement: float = .003
    treated_max_score: float = .09
    treatment_duration_ms: int = 1500
    return_duration_ms: int = 300
    frame_width: int = 96
    frame_height: int = 54


def _pixels(observation: Any, policy: VisualJoinPolicy) -> list[float]:
    values = observation.get("pixels") if isinstance(observation, dict) else observation
    if values is None:
        raise ValueError("missing_visual_join_frame")
    raw = values if isinstance(values, bytes) else bytes(values)
    expected = policy.frame_width * policy.frame_height
    if len(raw) != expected:
        raise ValueError(f"visual_join_frame_size:{len(raw)}:{expected}")
    return [value / 255 for value in raw]


def _content_bounds(values: list[float], policy: VisualJoinPolicy) -> tuple[float, float, float, float]:
    width, height = policy.frame_width, policy.frame_height
    rows, cols = [], []
    for y in range(height):
        row = values[y * width:(y + 1) * width]
        mean = sum(row) / width
        spread = (sum((value - mean) ** 2 for value in row) / width) ** .5
        if mean > .06 or spread > .035:
            rows.append(y)
    for x in range(width):
        col = values[x::width]
        mean = sum(col) / height
        spread = (sum((value - mean) ** 2 for value in col) / height) ** .5
        if mean > .06 or spread > .035:
            cols.append(x)
    if not rows or not cols:
        return (0.0, 0.0, 1.0, 1.0)
    return (cols[0] / width, rows[0] / height, (cols[-1] + 1) / width, (rows[-1] + 1) / height)


def _face(observation: Any) -> dict[str, float] | None:
    if not isinstance(observation, dict):
        return None
    face = observation.get("face")
    if face:
        return face.get("bbox") or face
    faces = observation.get("faces") or []
    if not faces:
        return None
    item = max(faces, key=lambda value: float((value.get("bbox") or value).get("width", 0)) * float((value.get("bbox") or value).get("height", 0)))
    return item.get("bbox") or item


def _face_delta(left: Any, right: Any) -> float:
    a, b = _face(left), _face(right)
    if not a and not b:
        return 0.0
    if not a or not b:
        return .75
    ac = (float(a["x"]) + float(a["width"]) / 2, float(a["y"]) + float(a["height"]) / 2)
    bc = (float(b["x"]) + float(b["width"]) / 2, float(b["y"]) + float(b["height"]) / 2)
    aa = max(1e-6, float(a["width"]) * float(a["height"]))
    ba = max(1e-6, float(b["width"]) * float(b["height"]))
    return min(1.0, math.dist(ac, bc) + .3 * abs(math.log(aa / ba)))


def discontinuity(left: Any, right: Any, *, source_cut: bool = False,
                  policy: VisualJoinPolicy | None = None) -> dict[str, Any]:
    """Compact deterministic 0..1 discontinuity score; lower is better."""
    policy = policy or VisualJoinPolicy()
    a, b = _pixels(left, policy), _pixels(right, policy)
    count = len(a)
    frame = sum(abs(x - y) for x, y in zip(a, b)) / count
    luminance = abs(sum(a) / count - sum(b) / count)
    width, height = policy.frame_width, policy.frame_height
    structure_total = 0.0
    structure_count = 0
    for y in range(height - 1):
        for x in range(width - 1):
            i = y * width + x
            ag = abs(a[i + 1] - a[i]) + abs(a[i + width] - a[i])
            bg = abs(b[i + 1] - b[i]) + abs(b[i + width] - b[i])
            structure_total += abs(ag - bg)
            structure_count += 1
    structure = structure_total / max(1, structure_count * 2)
    ab, bb = _content_bounds(a, policy), _content_bounds(b, policy)
    composition = sum(abs(x - y) for x, y in zip(ab, bb)) / 4
    face = _face_delta(left, right)
    raw = .45 * frame + .18 * luminance + .20 * structure + .07 * composition + .10 * face
    score = raw * (.90 if source_cut else 1.0)
    return {
        "score": round(min(1.0, score), 6),
        "components": {
            "frame": round(frame, 6), "luminance": round(luminance, 6),
            "structure": round(structure, 6), "composition": round(composition, 6),
            "face_position_size": round(face, 6),
        },
        "source_scene_cut": source_cut,
    }


def _transform(observation: Any, scale: float, dx: float, dy: float,
               policy: VisualJoinPolicy) -> dict[str, Any]:
    source = _pixels(observation, policy)
    width, height = policy.frame_width, policy.frame_height
    output = bytearray(width * height)
    cx, cy = (width - 1) / 2, (height - 1) / 2
    for y in range(height):
        sy = round((y - cy - dy * height) / scale + cy)
        sy = max(0, min(height - 1, sy))
        for x in range(width):
            sx = round((x - cx - dx * width) / scale + cx)
            sx = max(0, min(width - 1, sx))
            output[y * width + x] = round(source[sy * width + sx] * 255)
    result: dict[str, Any] = {"pixels": bytes(output)}
    face = _face(observation)
    if face:
        fw, fh = min(1.0, float(face["width"]) * scale), min(1.0, float(face["height"]) * scale)
        fcx = .5 + (float(face["x"]) + float(face["width"]) / 2 - .5) * scale + dx
        fcy = .5 + (float(face["y"]) + float(face["height"]) / 2 - .5) * scale + dy
        result["face"] = {"x": max(0.0, min(1.0 - fw, fcx - fw / 2)),
                          "y": max(0.0, min(1.0 - fh, fcy - fh / 2)),
                          "width": fw, "height": fh}
    return result


def _word_spans(segments: list[dict[str, Any]]) -> list[tuple[int, int]]:
    spans = []
    for segment in segments:
        for word in segment.get("words") or []:
            start = round(float(word.get("start_ms", (word.get("start") or 0) * 1000)))
            end = round(float(word.get("end_ms", (word.get("end") or word.get("start") or 0) * 1000)))
            spans.append((start, max(start, end)))
    return spans


def _clear(a: int, b: int, spans: list[tuple[int, int]]) -> bool:
    return not any(a < end and b > start for start, end in spans)


def _frame_points(lo: int, hi: int, fps: float) -> list[int]:
    if hi < lo:
        return []
    frame_ms = 1000 / max(fps, 1)
    first, last = math.ceil(lo / frame_ms), math.floor(hi / frame_ms)
    return sorted({lo, hi, *(round(index * frame_ms) for index in range(first, last + 1))})


def _decision(candidate: dict[str, Any], decision_id: Any) -> dict[str, Any]:
    return next((item for item in candidate.get("planned_decisions") or [] if item.get("decision_id") == decision_id), {})


def _treatment(left: Any, right: Any, baseline: float,
               policy: VisualJoinPolicy) -> dict[str, Any] | None:
    options: list[tuple[float, float, float, float, str, Any]] = []
    for scale in (1.04, 1.08, 1.12):
        moved = _transform(right, scale, 0, 0, policy)
        metric = discontinuity(left, moved, policy=policy)
        options.append((metric["score"], scale, 0.0, 0.0, "subtle_punch_in", moved))
    left_face, right_face = _face(left), _face(right)
    if left_face and right_face:
        left_area = float(left_face["width"]) * float(left_face["height"])
        right_area = float(right_face["width"]) * float(right_face["height"])
        if right_area > left_area * 1.12:
            for scale in (.96, .92):
                moved = _transform(right, scale, 0, 0, policy)
                metric = discontinuity(left, moved, policy=policy)
                options.append((metric["score"], scale, 0.0, 0.0, "subtle_punch_out", moved))
    for dx, dy in ((-.05, 0), (.05, 0), (0, -.04), (0, .04), (-.03, -.03), (.03, .03)):
        moved = _transform(right, 1.0, dx, dy, policy)
        metric = discontinuity(left, moved, policy=policy)
        options.append((metric["score"], 1.0, dx, dy, "reframe", moved))
    score, scale, dx, dy, treatment, moved = min(options, key=lambda item: (item[0], abs(item[1] - 1), abs(item[2]) + abs(item[3]), item[4]))
    if baseline - score < policy.treatment_improvement or score > policy.treated_max_score:
        return None
    return {
        "treatment": treatment, "scale_after": scale, "reframe_dx": dx, "reframe_dy": dy,
        "score": score, "face_delta": round(_face_delta(left, moved), 6),
    }


def build_visual_join_plan(*, safe_execution: dict[str, Any], segments: list[dict[str, Any]],
                           frame_loader: Callable[[str, int], Any],
                           source_cuts_ms: list[int] | None = None, fps: float = 25.0,
                           policy: VisualJoinPolicy | None = None) -> dict[str, Any]:
    started = time.monotonic()
    policy = policy or VisualJoinPolicy()
    spans = _word_spans(segments)
    source_cuts_ms = sorted(source_cuts_ms or [])
    output_candidates = []
    for source_candidate in safe_execution.get("candidates") or []:
        candidate_id = str(source_candidate.get("candidate_id") or "")
        semantic_ranges = copy.deepcopy(source_candidate.get("final_retained_ranges") or [])
        render_ranges = copy.deepcopy(semantic_ranges)
        joins = []
        for index, cut in enumerate(source_candidate.get("executed_removals") or []):
            original_left = int(cut["refined_left_boundary_ms"])
            original_right = int(cut["refined_right_boundary_ms"])
            planned = _decision(source_candidate, cut.get("decision_id"))
            window = planned.get("recommended_cut_window_ms") or [original_left, original_right]
            left_lo = max(int(window[0]), original_left - policy.max_shift_ms)
            right_hi = min(int(window[1]), original_right + policy.max_shift_ms)
            # Outward-only search cannot restore removed speech. Expanded
            # intervals are rejected if they touch any ASR word.
            left_points = [point for point in _frame_points(left_lo, original_left, fps)
                           if _clear(point, original_left, spans)] or [original_left]
            right_points = [point for point in _frame_points(original_right, right_hi, fps)
                            if _clear(original_right, point, spans)] or [original_right]
            frame_gap = round(1000 / max(fps, 1))

            def assess(left_ms: int, right_ms: int) -> tuple[dict[str, Any], Any, Any]:
                before = frame_loader(candidate_id, max(0, left_ms - frame_gap))
                after = frame_loader(candidate_id, right_ms)
                scene_cut = any(abs(point - left_ms) <= frame_gap or abs(point - right_ms) <= frame_gap for point in source_cuts_ms)
                return discontinuity(before, after, source_cut=scene_cut, policy=policy), before, after

            original_metric, original_before, original_after = assess(original_left, original_right)
            best = (original_metric["score"], 0, original_left, original_right, original_metric)
            for left_ms in left_points:
                for right_ms in right_points:
                    metric, _, _ = assess(left_ms, right_ms)
                    item = (metric["score"], abs(left_ms - original_left) + abs(right_ms - original_right), left_ms, right_ms, metric)
                    if item[:2] < best[:2]:
                        best = item
            best_score, _, selected_left, selected_right, selected_metric = best
            boundary_gain = original_metric["score"] - best_score
            treatment = "none"
            scale_after, dx, dy = 1.0, 0.0, 0.0
            after_score = original_metric["score"]
            face_after = _face_delta(original_before, original_after)
            reason = "visual_continuity_already_acceptable"
            requires_cover = False
            if original_metric["score"] > policy.acceptable_score:
                boundary_solves = boundary_gain >= policy.boundary_improvement and best_score <= policy.acceptable_score
                if boundary_solves:
                    treatment = "boundary_shift"
                    after_score = best_score
                    _, best_before, best_after = assess(selected_left, selected_right)
                    face_after = _face_delta(best_before, best_after)
                    reason = "nearby_approved_frame_boundary_reduced_visual_discontinuity"
                    if index < len(render_ranges) - 1:
                        render_ranges[index]["end_ms"] = selected_left
                        render_ranges[index + 1]["start_ms"] = selected_right
                else:
                    selected_left, selected_right = original_left, original_right
                    proposed = _treatment(original_before, original_after, original_metric["score"], policy)
                    if proposed:
                        treatment = proposed["treatment"]
                        scale_after, dx, dy = proposed["scale_after"], proposed["reframe_dx"], proposed["reframe_dy"]
                        after_score, face_after = proposed["score"], proposed["face_delta"]
                        reason = "subtle_post_cut_crop_improves_alignment"
                    else:
                        treatment = "visual_cover_required"
                        requires_cover = True
                        reason = "no_safe_boundary_or_subtle_crop_met_visual_threshold"
            output_join_ms = sum(int(item["end_ms"]) - int(item["start_ms"]) for item in render_ranges[:index + 1])
            improvement = original_metric["score"] - after_score
            confidence = min(.98, .58 + max(0.0, improvement) * 4 + (.12 if treatment == "none" else 0))
            joins.append({
                "cut_id": cut.get("cut_id"), "candidate_id": candidate_id,
                "original_boundary_ms": {"left": original_left, "right": original_right},
                "selected_boundary_ms": {"left": selected_left, "right": selected_right},
                "boundary_shift_ms": {"left": selected_left - original_left, "right": selected_right - original_right},
                "visual_discontinuity_before": original_metric["score"],
                "visual_discontinuity_after": round(after_score, 6),
                "visual_components_before": original_metric["components"],
                "face_evidence_available": bool(_face(original_before) and _face(original_after)),
                "face_position_delta_before": original_metric["components"]["face_position_size"],
                "face_position_delta_after": round(face_after, 6),
                "treatment": treatment, "scale_before": 1.0, "scale_after": scale_after,
                "reframe_dx": dx, "reframe_dy": dy,
                "requires_visual_cover": requires_cover,
                "suggested_cover_start_ms": max(0, output_join_ms - 250) if requires_cover else None,
                "suggested_cover_end_ms": output_join_ms + 750 if requires_cover else None,
                "confidence": round(confidence, 4), "reason": reason,
                "output_join_ms": output_join_ms,
                "treatment_duration_ms": policy.treatment_duration_ms,
                "return_duration_ms": policy.return_duration_ms,
                "camera_trajectory_conflict": False,
            })
        output_candidates.append({
            "candidate_id": candidate_id,
            "semantic_retained_ranges": semantic_ranges,
            "render_retained_ranges": render_ranges,
            "joins": joins,
            "requires_visual_cover_count": sum(item["requires_visual_cover"] for item in joins),
        })
    return {
        "visual_join_treatment_version": VERSION, "schema_version": SCHEMA_VERSION,
        "status": "available", "candidates": output_candidates,
        "metrics": {
            "join_count": sum(len(item["joins"]) for item in output_candidates),
            "treated_count": sum(join["treatment"] not in {"none", "visual_cover_required"} for item in output_candidates for join in item["joins"]),
            "visual_cover_required_count": sum(join["requires_visual_cover"] for item in output_candidates for join in item["joins"]),
            "runtime_ms": round((time.monotonic() - started) * 1000, 3),
        },
        "policy": policy.__dict__,
        "provenance": {"method": "deterministic-small-frame-visual-continuity-v1", "new_model_used": False},
    }


def _bounded_box(box: list[float], scale: float, dx: float, dy: float,
                 src_w: int, src_h: int) -> list[float]:
    x, y, width, height = map(float, box)
    new_width = min(float(src_w), max(2.0, width / scale))
    new_height = min(float(src_h), max(2.0, height / scale))
    cx = x + width / 2 + dx * width
    cy = y + height / 2 + dy * height
    return [max(0.0, min(src_w - new_width, cx - new_width / 2)),
            max(0.0, min(src_h - new_height, cy - new_height / 2)),
            new_width, new_height]


def apply_treatments(trajectory: dict[str, Any], joins: list[dict[str, Any]],
                     src_w: int, src_h: int) -> tuple[dict[str, Any], list[str]]:
    """Locally replace camera motion with the selected join treatment."""
    output = copy.deepcopy(trajectory)
    frames = [list(map(float, frame)) for frame in output.get("frames") or []]
    fps = float(output.get("fps") or 25)
    conflicts: list[str] = []
    for join in joins:
        if join.get("treatment") not in {"subtle_punch_in", "subtle_punch_out", "reframe"}:
            continue
        start = max(0, round(float(join.get("output_join_ms", 0)) * fps / 1000))
        hold = max(1, round(float(join.get("treatment_duration_ms", 1500)) * fps / 1000))
        return_frames = max(1, round(float(join.get("return_duration_ms", 300)) * fps / 1000))
        end = min(len(frames), start + hold)
        if start >= len(frames) or end <= start:
            continue
        anchor = frames[start][:]
        moving = any(max(abs(a - b) for a, b in zip(anchor, frame)) > 2 for frame in frames[start:end])
        camera_cut = any(start <= int(value) < end for value in output.get("cuts") or [])
        join_sec = float(join.get("output_join_ms", 0)) / 1000
        camera_punch = any(float(item.get("start", -99)) <= join_sec <= float(item.get("start", -99)) + 2.1 for item in output.get("punches") or [])
        if moving or camera_cut or camera_punch:
            conflicts.append(str(join.get("cut_id")))
        treated = _bounded_box(anchor, float(join.get("scale_after", 1)),
                               float(join.get("reframe_dx", 0)), float(join.get("reframe_dy", 0)),
                               src_w, src_h)
        for index in range(start, end):
            frames[index] = treated[:]
        return_end = min(len(frames), end + return_frames)
        for index in range(end, return_end):
            progress = (index - end + 1) / max(1, return_end - end)
            base = frames[index]
            frames[index] = [a + (b - a) * progress for a, b in zip(treated, base)]
    output["frames"] = frames
    return output, conflicts
