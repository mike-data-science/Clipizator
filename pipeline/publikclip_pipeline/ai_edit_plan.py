"""Deterministic B-roll opportunity planning from existing source evidence.

This module describes possible coverage only.  It performs no retrieval,
generation, media decode, or render mutation.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any


VERSION = "ai-edit-plan-v1"
SCHEMA_VERSION = 1
POLICIES = {"off", "conservative", "balanced", "aggressive"}
PRESENTATIONS = {"replace", "overlay", "mixed"}
MEANINGFUL_VISUAL_TYPES = {"b_roll", "screenshot", "screen_recording", "meme_or_graphic"}
PROTECTED_ROLES = {"payoff", "reveal", "reaction"}
MONEY_NUMBER_RE = re.compile(
    r"(?:[$£€]\s?\d|\b\d[\d,.]*\s?(?:percent|%|dollars?|pounds?|million|billion|thousand)\b)",
    re.IGNORECASE,
)
EXAMPLE_RE = re.compile(r"\b(?:for example|for instance|proof|evidence|because|here(?:'s| is) how)\b", re.IGNORECASE)


def _ms(clip: dict[str, Any], key: str) -> int:
    explicit = clip.get(f"{key}_ms")
    return int(explicit) if explicit is not None else round(float(clip.get(key) or 0) * 1000)


def _overlap(a: int, b: int, c: int, d: int) -> int:
    return max(0, min(b, d) - max(a, c))


def _refs(unit: dict[str, Any]) -> list[str]:
    references = unit.get("references") or {}
    output: list[str] = []
    for value in references.values():
        if isinstance(value, list):
            output.extend(str(item) for item in value if item)
    for item in unit.get("transcript_refs") or []:
        if isinstance(item, dict) and item.get("id"):
            output.append(str(item["id"]))
    return list(dict.fromkeys(output))


def _stable_id(candidate_id: str, start: int, end: int, role: str, reason: str,
               semantic_ids: list[str]) -> str:
    identity = json.dumps(
        [candidate_id, start, end, role, reason, sorted(semantic_ids)],
        ensure_ascii=True, separators=(",", ":"),
    )
    return f"broll_opportunity_{hashlib.sha1(identity.encode()).hexdigest()[:12]}"


def _entities(unit: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[Any] = []
    for owner in (unit, unit.get("evidence") or {}):
        for key in ("named_entities", "entities"):
            raw = owner.get(key)
            values.extend(raw if isinstance(raw, list) else ([raw] if raw else []))
    output = []
    for value in values:
        if isinstance(value, str):
            output.append({"label": value, "confidence": float(unit.get("confidence") or 0.7)})
        elif isinstance(value, dict) and value.get("label"):
            output.append({"label": str(value["label"]), "confidence": float(value.get("confidence") or 0.7)})
    return [item for item in output if item["confidence"] >= 0.7]


def _visuals_for(visual_units: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    return [
        item for item in visual_units
        if _overlap(start, end, int(item.get("start_ms") or 0), int(item.get("end_ms") or 0)) > 0
    ]


def _window(start: int, end: int, clip_start: int, clip_end: int) -> tuple[int, int] | None:
    start, end = max(start, clip_start), min(end, clip_end)
    if end - start < 800:
        return None
    return start, min(end, start + 4000)


def _clipped_range(start: int, end: int, clip_start: int, clip_end: int) -> tuple[int, int] | None:
    start, end = max(start, clip_start), min(end, clip_end)
    return (start, end) if end > start else None


def _visual_cover_requirements(
    candidate_id: str, clip_start: int, clip_end: int,
    safe_execution: dict[str, Any], visual_join: dict[str, Any],
) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    sources = (
        ("visual_join_treatment", visual_join.get("candidates") or [], "joins"),
        ("safe_edit_execution", safe_execution.get("candidates") or [], "executed_removals"),
    )
    for source_name, candidates, key in sources:
        candidate = next((item for item in candidates if str(item.get("candidate_id")) == candidate_id), None)
        for cut in (candidate or {}).get(key) or []:
            if not cut.get("requires_visual_cover"):
                continue
            cut_id = str(cut.get("cut_id") or "unknown_cut")
            selected = cut.get("selected_boundary_ms") or {}
            original = cut.get("original_boundary_ms") or cut.get("original_desired_cut_interval") or {}
            boundary = int(
                cut.get("refined_left_boundary_ms")
                or selected.get("left")
                or original.get("left")
                or original.get("start_ms")
                or clip_start
            )
            start = int(cut.get("suggested_cover_start_ms") or max(clip_start, boundary - 500))
            end = int(cut.get("suggested_cover_end_ms") or min(clip_end, boundary + 1000))
            record = found.setdefault(cut_id, {
                "cut_id": cut_id, "start_ms": start, "end_ms": max(start + 1, end),
                "reason": str(cut.get("reason") or "executed cut requires visual cover"),
                "source_evidence_refs": [],
            })
            record["source_evidence_refs"] = list(dict.fromkeys([
                *record["source_evidence_refs"], f"{source_name}:{cut_id}",
            ]))
    return sorted(found.values(), key=lambda item: (item["start_ms"], item["cut_id"]))


def _protected_ranges(
    units: list[dict[str, Any]], visual_units: list[dict[str, Any]],
    clip_start: int, clip_end: int,
) -> list[dict[str, Any]]:
    protected: list[dict[str, Any]] = []
    for unit in units:
        start, end = int(unit.get("start_ms") or 0), int(unit.get("end_ms") or 0)
        window = _clipped_range(start, end, clip_start, clip_end)
        if not window:
            continue
        roles = {str(unit.get("primary_story_role") or ""), *(str(item) for item in unit.get("secondary_roles") or [])}
        reason = next((f"protected_{role}" for role in sorted(PROTECTED_ROLES) if role in roles), None)
        visuals = _visuals_for(visual_units, *window)
        important_visual = any(
            item.get("visual_type") in MEANINGFUL_VISUAL_TYPES and float(item.get("confidence") or 0) >= 0.6
            for item in visuals
        )
        if "hook" in roles and important_visual:
            reason = "protected_hook_with_important_source_visual"
        if reason:
            protected.append({
                "start_ms": window[0], "end_ms": window[1], "reason": reason,
                "semantic_unit_ids": [str(unit.get("semantic_unit_id"))] if unit.get("semantic_unit_id") else [],
                "source_evidence_refs": _refs(unit),
            })
    for visual in visual_units:
        if visual.get("visual_type") not in MEANINGFUL_VISUAL_TYPES or float(visual.get("confidence") or 0) < 0.6:
            continue
        relation = (visual.get("relation_to_speech") or {}).get("type")
        if relation not in {"illustrates_speech", "demonstrates_speech", "contextual_cutaway"}:
            continue
        window = _clipped_range(int(visual.get("start_ms") or 0), int(visual.get("end_ms") or 0), clip_start, clip_end)
        if window:
            protected.append({
                "start_ms": window[0], "end_ms": window[1],
                "reason": "source_visual_already_carries_meaning", "semantic_unit_ids": [],
                "source_evidence_refs": [str(visual.get("id"))] if visual.get("id") else [],
            })
    unique = {(item["start_ms"], item["end_ms"], item["reason"]): item for item in protected}
    return sorted(unique.values(), key=lambda item: (item["start_ms"], item["end_ms"], item["reason"]))


def _is_protected(start: int, end: int, protected: list[dict[str, Any]]) -> bool:
    return any(_overlap(start, end, item["start_ms"], item["end_ms"]) > 0 for item in protected)


def _opportunity(
    candidate_id: str, start: int, end: int, semantic_ids: list[str], reason: str,
    priority: str, role: str, refs: list[str], confidence: float, tier: int,
    *, requires_visual_cover: bool = False,
) -> dict[str, Any]:
    return {
        "opportunity_id": _stable_id(candidate_id, start, end, role, reason, semantic_ids),
        "candidate_id": candidate_id, "start_ms": start, "end_ms": end,
        "semantic_unit_ids": semantic_ids, "reason": reason, "priority": priority,
        "suggested_visual_role": role, "source_evidence_refs": list(dict.fromkeys(refs)),
        "safe_to_cover_speaker": True, "requires_visual_cover": requires_visual_cover,
        "confidence": round(max(0.0, min(1.0, confidence)), 4), "_tier": tier,
    }


def _semantic_opportunities(
    candidate_id: str, units: list[dict[str, Any]], visual_units: list[dict[str, Any]],
    protected: list[dict[str, Any]], clip_start: int, clip_end: int,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for unit in units:
        window = _window(int(unit.get("start_ms") or 0), int(unit.get("end_ms") or 0), clip_start, clip_end)
        if not window or _is_protected(*window, protected):
            continue
        unit_id = str(unit.get("semantic_unit_id") or "")
        semantic_ids = [unit_id] if unit_id else []
        refs = _refs(unit)
        confidence = float(unit.get("confidence") or 0.65)
        text = " ".join(str(unit.get(key) or "") for key in ("transcript", "semantic_summary"))
        roles = {str(unit.get("primary_story_role") or ""), *(str(item) for item in unit.get("secondary_roles") or [])}
        entities = _entities(unit)
        if entities:
            labels = ", ".join(item["label"] for item in entities[:3])
            entity_confidence = max(item["confidence"] for item in entities)
            output.append(_opportunity(
                candidate_id, *window, semantic_ids, f"reliable named entity mention: {labels}",
                "high", "person/entity visual", refs, min(confidence, entity_confidence), 2,
            ))
        if MONEY_NUMBER_RE.search(text):
            output.append(_opportunity(
                candidate_id, *window, semantic_ids, "concrete number or money claim has explicit transcript evidence",
                "high", "text/graphic", refs, min(0.84, max(0.72, confidence)), 2,
            ))
        proof = bool(roles & {"example", "proof", "evidence"}) or bool(EXAMPLE_RE.search(text))
        if proof:
            output.append(_opportunity(
                candidate_id, *window, semantic_ids, "example or proof unit can be illustrated",
                "medium", "illustrative_broll", refs, min(0.82, max(0.68, confidence)), 2,
            ))
        elif "claim" in roles:
            output.append(_opportunity(
                candidate_id, *window, semantic_ids, "explicit claim is a possible visual-support point",
                "medium", "illustrative_broll", refs, min(0.72, max(0.62, confidence)), 2,
            ))
        elif roles & {"explanation", "development"}:
            output.append(_opportunity(
                candidate_id, *window, semantic_ids, "explanation may benefit from supported illustration",
                "low", "illustrative_broll", refs, min(0.7, max(0.55, confidence)), 1,
            ))
    return output


def _select(opportunities: list[dict[str, Any]], policy: str) -> list[dict[str, Any]]:
    if policy == "off":
        return []
    minimum_tier = {"conservative": 2, "balanced": 2, "aggressive": 1}[policy]
    limit = {"conservative": 2, "balanced": 4, "aggressive": 6}[policy]
    ordered = sorted(
        opportunities,
        key=lambda item: (-item["_tier"], -item["confidence"], item["start_ms"], item["opportunity_id"]),
    )
    selected: list[dict[str, Any]] = []
    for item in ordered:
        if item["_tier"] < minimum_tier:
            continue
        if policy == "conservative" and item["_tier"] == 2 and (
            item["confidence"] < 0.78 or item["priority"] != "high"
        ):
            continue
        if any(
            item["reason"] == prior["reason"]
            and _overlap(item["start_ms"], item["end_ms"], prior["start_ms"], prior["end_ms"]) > 0
            for prior in selected
        ):
            continue
        selected.append(item)
        if len(selected) >= limit:
            break
    for item in selected:
        item.pop("_tier", None)
    return sorted(selected, key=lambda item: (item["start_ms"], item["opportunity_id"]))


def build_ai_edit_plan(
    *, selected_clips: list[dict[str, Any]], story_semantics: dict[str, Any] | None = None,
    visual_understanding: dict[str, Any] | None = None, source_editing: dict[str, Any] | None = None,
    safe_execution: dict[str, Any] | None = None, visual_join: dict[str, Any] | None = None,
    generation_config: dict[str, Any] | None = None, generation_config_run_id: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    story_semantics, visual_understanding = story_semantics or {}, visual_understanding or {}
    source_editing, safe_execution, visual_join = source_editing or {}, safe_execution or {}, visual_join or {}
    generation_config = generation_config or {}
    broll = generation_config.get("broll") or {}
    policy = str(broll.get("mode") or "off")
    presentation = str(broll.get("presentation") or "replace")
    if policy not in POLICIES:
        raise ValueError(f"unsupported_broll_policy:{policy}")
    if presentation not in PRESENTATIONS:
        raise ValueError(f"unsupported_broll_presentation:{presentation}")
    all_units = story_semantics.get("semantic_units") or []
    visual_units = visual_understanding.get("visual_units") or []
    clips = []
    suppressed = 0
    for index, clip in enumerate(selected_clips):
        clip_start, clip_end = _ms(clip, "start"), _ms(clip, "end")
        candidate_id = str(clip.get("candidate_id") or f"clip_{index:03d}_{clip_start:09d}_{clip_end:09d}")
        wanted = set(clip.get("semantic_unit_ids") or [])
        units = [
            unit for unit in all_units
            if (not wanted or unit.get("semantic_unit_id") in wanted)
            and _overlap(clip_start, clip_end, int(unit.get("start_ms") or 0), int(unit.get("end_ms") or 0)) > 0
        ]
        clip_visuals = _visuals_for(visual_units, clip_start, clip_end)
        protected = _protected_ranges(units, clip_visuals, clip_start, clip_end)
        covers = _visual_cover_requirements(candidate_id, clip_start, clip_end, safe_execution, visual_join)
        raw = [
            _opportunity(
                candidate_id, item["start_ms"], item["end_ms"], [],
                item["reason"], "high", "visual_cover", item["source_evidence_refs"], .98, 3,
                requires_visual_cover=True,
            )
            for item in covers
        ]
        raw.extend(_semantic_opportunities(
            candidate_id, units, clip_visuals, protected, clip_start, clip_end,
        ))
        opportunities = _select(raw, policy)
        suppressed += len(raw) - len(opportunities)
        clips.append({
            "clip_index": index, "candidate_id": candidate_id,
            "source_range": {"start_ms": clip_start, "end_ms": clip_end},
            "generation_config": {
                "config_version": generation_config.get("config_version"),
                "style_profile_id": generation_config.get("style_profile_id"),
                "generation_config_run_id": generation_config_run_id,
                "broll": {
                    "mode": policy, "presentation": presentation,
                    "still_vs_video": broll.get("still_vs_video"),
                    "source_preference": broll.get("source_preference"),
                },
            },
            "broll_policy": policy, "broll_presentation": presentation,
            "opportunities": opportunities, "protected_source_ranges": protected,
            "visual_cover_requirements": covers,
            "limitations": [
                "Suggestions describe possible coverage only; no asset was searched, generated, downloaded, or inserted.",
                "Source evidence does not establish that an insertion will improve retention.",
            ],
            "provenance": {
                "semantic_unit_ids": [str(item.get("semantic_unit_id")) for item in units if item.get("semantic_unit_id")],
                "visual_unit_ids": [str(item.get("id")) for item in clip_visuals if item.get("id")],
                "source_editing_event_ids": [
                    str(item.get("id")) for key in ("pattern_interrupts", "cuts")
                    for item in source_editing.get(key) or []
                    if item.get("id") and clip_start <= int(item.get("timestamp_ms") or item.get("start_ms") or 0) <= clip_end
                ],
            },
        })
    opportunity_count = sum(len(item["opportunities"]) for item in clips)
    return {
        "ai_edit_plan_version": VERSION, "schema_version": SCHEMA_VERSION, "status": "available",
        "generation_config_snapshot": {
            "config_version": generation_config.get("config_version"),
            "style_profile_id": generation_config.get("style_profile_id"),
            "generation_config_run_id": generation_config_run_id,
            "broll": {"mode": policy, "presentation": presentation},
        },
        "clip_count": len(clips), "clips": clips,
        "metrics": {
            "opportunity_count": opportunity_count, "actionable_opportunity_count": opportunity_count,
            "suppressed_opportunity_count": suppressed,
            "visual_cover_requirement_count": sum(len(item["visual_cover_requirements"]) for item in clips),
            "runtime_ms": round((time.perf_counter() - started) * 1000, 3),
        },
        "limitations": [
            "This plan is evidence-driven metadata, not a media-generation or insertion instruction.",
            "Named-entity opportunities require an explicit reliable entity field; names are not guessed from capitalization.",
        ],
        "provenance": {
            "method": "deterministic-broll-edit-plan-bridge-v1", "llm_used": False,
            "media_decode_used": False, "new_inference_used": False,
        },
    }
