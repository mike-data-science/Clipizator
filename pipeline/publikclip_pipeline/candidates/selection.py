"""Story-aware candidate construction, scoring, deduplication, and diversity."""

from __future__ import annotations

import hashlib
import math
import re
from statistics import mean
from typing import Any


MAX_FINALISTS = 12
MAX_CANDIDATE_DURATION_MS = 90_000
STRONG_ROLES = {
    "hook", "question", "claim", "escalation", "conflict", "contrast", "surprise",
    "reveal", "payoff", "proof", "reaction", "conclusion", "unresolved",
}
ROLE_STRENGTH = {
    "hook": .9, "context": .25, "setup": .35, "question": .55, "claim": .72,
    "explanation": .48, "development": .38, "escalation": .78, "conflict": .88,
    "contrast": .72, "surprise": .9, "reveal": .96, "payoff": .96, "proof": .76,
    "reaction": .62, "transition": .2, "CTA": .25, "conclusion": .62,
    "unresolved": .42, "other": .18,
}
SIGNAL_STRENGTH = {
    "question": .52, "claim": .7, "number": .58, "money_value": .88,
    "comparison": .72, "conflict_or_contradiction": .84,
    "surprise_or_reveal": .9, "CTA": .2, "immediate_repetition": .35,
}


def _stable_id(prefix: str, identity: str) -> str:
    return f"{prefix}_{hashlib.sha1(identity.encode('utf-8')).hexdigest()[:12]}"


def _words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", value.casefold())


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def temporal_iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    intersection = _overlap((left["start_ms"], left["end_ms"]), (right["start_ms"], right["end_ms"]))
    union = max(left["end_ms"], right["end_ms"]) - min(left["start_ms"], right["start_ms"])
    return intersection / max(1, union)


def semantic_overlap(left: dict[str, Any], right: dict[str, Any]) -> float:
    a, b = set(left["semantic_unit_ids"]), set(right["semantic_unit_ids"])
    return len(a & b) / max(1, len(a | b))


def topic_similarity(left: str, right: str) -> float:
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "for", "is", "on", "about"}
    a, b = set(_words(left)) - stop, set(_words(right)) - stop
    return len(a & b) / max(1, len(a | b))


def duplicate_reason(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    temporal = temporal_iou(left, right)
    semantic = semantic_overlap(left, right)
    topic = topic_similarity(left.get("topic_summary") or "", right.get("topic_summary") or "")
    duplicate = semantic >= .6 or (
        left.get("story_id") == right.get("story_id") and temporal >= .72
    ) or (temporal >= .45 and topic >= .72)
    if not duplicate:
        return None
    return {
        "temporal_iou": round(temporal, 4), "semantic_unit_jaccard": round(semantic, 4),
        "topic_similarity": round(topic, 4),
    }


def _unit_signal_types(unit_id: str, signals: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("type")) for item in signals if item.get("semantic_unit_id") == unit_id}


def _text_strength(text: str) -> dict[str, float]:
    lower = text.casefold()
    number = bool(re.search(r"(?:[$€£]\s?\d|\b\d[\d,.]*\s?(?:million|billion|percent|%|dollars?|pounds?|euros?)?\b)", lower))
    tension = bool(re.search(r"\b(kill|fight|hurt|sleep|destroy|hate|scared|nervous|risk|danger|drugs?|failed?|rejected?|against|challenge)\b", lower))
    surprise = bool(re.search(r"\b(crazy|shocking|unexpected|turns out|couldn't believe|no way|actually)\b", lower))
    emotion = bool(re.search(r"\b(love|hate|afraid|terrified|hurt|cry|angry|proud|emotional|heart)\b", lower))
    first_person = len(re.findall(r"\b(i|i'm|i've|me|my)\b", lower)) >= 2
    title_names = re.findall(r"(?<![.!?]\s)\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b", text)
    return {
        "specificity": .85 if number else .65 if title_names else .4,
        "tension": .9 if tension else .15,
        "surprise": .82 if surprise else .12,
        "emotional": .78 if emotion else .18,
        "personal": .68 if first_person else .2,
        "entity": .72 if title_names else .2,
    }


def _energy(values: list[float], grid_sec: float, start_ms: int, end_ms: int) -> float | None:
    if not values or grid_sec <= 0:
        return None
    start = max(0, int(start_ms / 1000 / grid_sec))
    end = min(len(values), max(start + 1, math.ceil(end_ms / 1000 / grid_sec)))
    if start >= len(values):
        return None
    window = mean(values[start:end])
    ordered = sorted(float(value) for value in values)
    return round(sum(value <= window for value in ordered) / len(ordered), 4)


def _montage_likelihood(candidate: dict[str, Any], editing: dict[str, Any], story_count_early: int) -> float:
    metrics = editing.get("metrics") or {}
    cut_rate = float(metrics.get("cuts_per_minute") or 0)
    pattern_rate = float(metrics.get("visual_change_cadence_per_minute") or 0)
    early = candidate["start_ms"] < 30_000
    early_cuts = sum(int(item.get("timestamp_ms") or item.get("start_ms") or 0) < 30_000 for item in editing.get("cuts") or [])
    early_patterns = sum(int(item.get("timestamp_ms") or item.get("start_ms") or 0) < 30_000 for item in editing.get("pattern_interrupts") or [])
    signals = [
        early, cut_rate >= 12 or early_cuts >= 5,
        pattern_rate >= 14 or early_patterns >= 7,
        story_count_early >= 2, candidate["end_ms"] <= 45_000,
    ]
    weights = [.15, .25, .2, .35, .1]
    return round(min(1.0, sum(weight for signal, weight in zip(signals, weights) if signal)), 4)


def _score(features: dict[str, float | None]) -> tuple[float, str]:
    value = lambda key: float(features.get(key) or 0)
    core_values = sorted([
        value("moment_strength"), value("hook_strength"), value("payoff_strength"),
        value("insight_strength"), value("tension_conflict"), value("surprise"),
    ], reverse=True)
    score = 100 * (
        .48 * core_values[0] + .14 * core_values[1]
        + .09 * value("specificity") + .09 * value("semantic_completeness")
        + .07 * value("quotability") + .05 * value("start_quality")
        + .05 * value("end_quality") + .03 * value("internal_flow")
    )
    score += max(0, value("delivery_energy") - .65) * 6  # support only, never a veto
    score -= 18 * value("unresolved_penalty")
    score -= 18 * value("intro_or_branding_contamination")
    score -= 9 * value("estimated_dead_time_ratio")
    score -= 8 * value("tangent_signal")
    if value("context_required") > 0 and value("context_present") < 1:
        score -= 14
    score = round(max(0, min(100, score)), 1)
    bucket = "exceptional" if score >= 86 else "strong" if score >= 74 else "usable" if score >= 56 else "weak"
    return score, bucket


def _candidate(
    *, story: dict[str, Any], chosen_ids: list[str], units_by_id: dict[str, dict[str, Any]],
    story_units: list[dict[str, Any]], hooks_by_unit: dict[str, list[dict[str, Any]]],
    signals: list[dict[str, Any]], payoff: dict[str, Any] | None, origin: str,
    source_editing: dict[str, Any], rms: list[float], grid_sec: float, story_count_early: int,
) -> dict[str, Any] | None:
    positions = {item["semantic_unit_id"]: index for index, item in enumerate(story_units)}
    selected = [units_by_id[item] for item in chosen_ids if item in units_by_id and item in positions]
    if not selected:
        return None
    first_index, last_index = min(positions[item["semantic_unit_id"]] for item in selected), max(positions[item["semantic_unit_id"]] for item in selected)
    interval_units = story_units[first_index:last_index + 1]
    start_ms, end_ms = interval_units[0]["start_ms"], interval_units[-1]["end_ms"]
    if end_ms <= start_ms or end_ms - start_ms > MAX_CANDIDATE_DURATION_MS:
        return None
    transcript = " ".join(item.get("transcript") or "" for item in interval_units).strip()
    if len(_words(transcript)) < 4:
        return None
    roles = [item.get("primary_story_role") or "other" for item in interval_units]
    signal_types = set().union(*(_unit_signal_types(item["semantic_unit_id"], signals) for item in interval_units))
    required_context = list(dict.fromkeys((payoff or {}).get("setup_unit_ids") or []))
    required_context = [item for item in required_context if item in positions and positions[item] <= last_index]
    included_ids = [item["semantic_unit_id"] for item in interval_units]
    missing_context = [item for item in required_context if item not in included_ids]
    optional_context = [item["semantic_unit_id"] for item in story_units[max(0, first_index - 1):first_index] if item["semantic_unit_id"] not in required_context]
    all_unrelated = [item["semantic_unit_id"] for item in story_units if item["semantic_unit_id"] not in included_ids and item["semantic_unit_id"] not in optional_context]
    unrelated = all_unrelated[:12]
    hooks = [hook for item in interval_units for hook in hooks_by_unit.get(item["semantic_unit_id"], [])]
    hook_unit_id = hooks[0].get("semantic_unit_id") if hooks else next((item["semantic_unit_id"] for item in interval_units if item.get("primary_story_role") == "hook"), None)
    payoff_ids = []
    if payoff and payoff.get("payoff_unit_id") in included_ids:
        payoff_ids.append(payoff["payoff_unit_id"])
    payoff_ids.extend(item["semantic_unit_id"] for item in interval_units if item.get("primary_story_role") in {"payoff", "reveal"} or "payoff" in (item.get("secondary_roles") or []))
    payoff_ids = list(dict.fromkeys(payoff_ids))
    first_role, last_role = roles[0], roles[-1]
    lower = transcript.casefold()
    contamination = 1.0 if re.search(r"\b(welcome back|presented by|sponsored by|you're watching|subscribe|season \w+)\b", lower) else .65 if story.get("start_reason") in {"show_intro", "sponsor_branding", "outro_unrelated_transition"} else 0.0
    starts_with_dependency = bool(re.match(r"^(and|but|so|it|they|he|she|this|that|because)\b", lower))
    start_quality = 1.0 if first_role in {"hook", "question", "claim", "conflict", "contrast", "surprise", "reveal"} and not starts_with_dependency else .82 if required_context and not missing_context else .55
    end_quality = 1.0 if last_role in {"payoff", "reveal", "conclusion"} or payoff_ids and payoff_ids[-1] == interval_units[-1]["semantic_unit_id"] else .88 if last_role in {"claim", "proof", "reaction", "explanation"} else .76 if end_ms == story.get("completeness", {}).get("likely_semantic_end_ms") else .5
    gaps = sum(max(0, right["start_ms"] - left["end_ms"]) for left, right in zip(interval_units, interval_units[1:]))
    dead_time = min(1.0, gaps / max(1, end_ms - start_ms))
    text_features = _text_strength(transcript)
    role_strength = max(ROLE_STRENGTH.get(role, .18) for role in roles)
    signal_strength = max([SIGNAL_STRENGTH.get(signal, .2) for signal in signal_types] or [.2])
    hook_strength = max([float(item.get("confidence") or 0) for item in hooks] or [ROLE_STRENGTH.get(first_role, .2) if first_role in {"hook", "question"} else .15])
    payoff_strength = max([float((payoff or {}).get("confidence") or 0) if payoff_ids else 0, .92 if "reveal" in roles else 0])
    insight = max(.82 if any(role in {"claim", "proof", "conclusion"} for role in roles) else 0, .72 if "explanation" in roles else .2)
    complete = 1.0 if payoff_ids or last_role in {"conclusion", "claim", "proof", "explanation"} else .72 if not story.get("completeness", {}).get("unresolved") else .35
    unresolved = 1.0 if (last_role in {"question", "unresolved"} and not payoff_ids) else .6 if story.get("completeness", {}).get("unresolved") else 0.0
    word_count = len(_words(transcript))
    quotability = .9 if 5 <= word_count <= 45 and role_strength >= .7 else .7 if word_count <= 80 else .42
    features: dict[str, float | None] = {
        "moment_strength": round(max(role_strength, signal_strength, text_features["tension"], text_features["surprise"]), 4),
        "hook_strength": round(hook_strength, 4),
        "curiosity_gap": round(max(hook_strength if first_role == "question" else .2, .8 if "question" in signal_types else .2), 4),
        "tension_conflict": round(max(text_features["tension"], .9 if any(role in {"conflict", "escalation"} for role in roles) else .15), 4),
        "surprise": round(max(text_features["surprise"], .92 if any(role in {"surprise", "reveal"} for role in roles) else .12), 4),
        "novelty": None,
        "specificity": round(max(text_features["specificity"], .9 if signal_types & {"money_value", "number"} else .3), 4),
        "stakes": round(max(text_features["tension"], .82 if signal_types & {"money_value", "conflict_or_contradiction"} else .25), 4),
        "emotional_charge": round(max(text_features["emotional"], .8 if any(role in {"reaction", "conflict"} for role in roles) else .2), 4),
        "quotability": quotability,
        "payoff_strength": round(payoff_strength, 4), "insight_strength": insight,
        "context_required": round(len(required_context) / max(1, len(interval_units)), 4),
        "context_present": 0.0 if missing_context else 1.0,
        "semantic_completeness": complete, "unresolved_penalty": unresolved,
        "start_quality": start_quality, "end_quality": end_quality,
        "internal_flow": round(max(.2, 1 - dead_time * 2), 4),
        "delivery_energy": _energy(rms, grid_sec, start_ms, end_ms),
        "estimated_dead_time_ratio": round(dead_time, 4),
        "repetition_signal": .75 if "immediate_repetition" in signal_types else 0.0,
        "tangent_signal": .8 if story.get("start_reason") == "tangent" else 0.0,
        "intro_or_branding_contamination": contamination,
        "source_highlight_montage_likelihood": 0.0,
    }
    candidate = {
        # Candidate identity follows the source interval and durable semantic
        # unit IDs. A later correction to the containing story boundary must
        # not rename an otherwise unchanged candidate.
        "candidate_id": _stable_id("candidate", f"{start_ms}:{end_ms}:{':'.join(included_ids)}"),
        "story_id": story["story_id"], "semantic_unit_ids": included_ids,
        "start_ms": start_ms, "end_ms": end_ms, "start": round(start_ms / 1000, 3), "end": round(end_ms / 1000, 3),
        "hook_unit_id": hook_unit_id, "setup_context_unit_ids": required_context,
        "optional_context_unit_ids": optional_context, "unrelated_unit_ids": unrelated,
        "unrelated_unit_count": len(all_unrelated),
        "payoff_reveal_unit_ids": payoff_ids,
        "likely_semantic_end_ms": min(end_ms, int(story.get("completeness", {}).get("likely_semantic_end_ms") or end_ms)),
        "next_topic_boundary_ms": None, "next_topic_started": bool(story.get("completeness", {}).get("next_topic_started")),
        "completeness": {
            "context_present": not missing_context, "payoff_present": bool(payoff_ids),
            "semantically_complete": complete >= .72, "unresolved": unresolved > 0,
        },
        "start_quality": start_quality,
        "start_reason": "hook_or_question" if first_role in {"hook", "question"} else "strong_claim_or_conflict" if first_role in {"claim", "conflict", "contrast", "surprise"} else "minimum_required_context" if required_context else "semantic_unit_start",
        "end_quality": end_quality,
        "end_reason": "payoff_or_reveal_complete" if payoff_ids and payoff_ids[-1] == included_ids[-1] else "conclusion_complete" if last_role == "conclusion" else "final_supported_claim" if last_role in {"claim", "proof", "explanation"} else "semantic_unit_end",
        "semantic_closure_confidence": round(min(1.0, (end_quality + float(story.get("confidence") or .5)) / 2), 4),
        "origin": origin, "discovery_origins": [origin], "topic_summary": story.get("topic_summary") or "",
        "source_transcript": transcript, "features": features,
        "source_preedited_likelihood": 0.0, "source_highlight_origin": False,
        "related_candidates": [], "duplicate_of": None, "rejection_reason": None,
        "evidence": {
            "semantic_unit_ids": included_ids,
            "source_editing_event_ids": list(dict.fromkeys(event_id for item in interval_units for event_id in (item.get("references") or {}).get("source_editing_event_ids", []))),
            "visual_unit_ids": list(dict.fromkeys(event_id for item in interval_units for event_id in (item.get("references") or {}).get("visual_unit_ids", []))),
            "caption_event_ids": list(dict.fromkeys(event_id for item in interval_units for event_id in (item.get("references") or {}).get("caption_event_ids", []))),
            "audio_event_ids": list(dict.fromkeys(event_id for item in interval_units for event_id in (item.get("references") or {}).get("audio_event_ids", []))),
            "score_uses_source_transcript": True, "generated_summary_used_for_score": False,
        },
        "provenance": {"method": "clip-selection-v2", "source": "derived", "status": "interpreted"},
    }
    montage = _montage_likelihood(candidate, source_editing, story_count_early)
    candidate["source_preedited_likelihood"] = montage
    candidate["source_highlight_origin"] = montage >= .6
    features["source_highlight_montage_likelihood"] = montage
    candidate["score"], candidate["quality_bucket"] = _score(features)
    return candidate


def _seed_sets(
    story: dict[str, Any], story_units: list[dict[str, Any]], signals: list[dict[str, Any]],
    payoffs: list[dict[str, Any]], hooks_by_unit: dict[str, list[dict[str, Any]]],
) -> list[tuple[list[str], str, dict[str, Any] | None]]:
    seeds: list[tuple[list[str], str, dict[str, Any] | None]] = []
    positions = {item["semantic_unit_id"]: index for index, item in enumerate(story_units)}
    for payoff in payoffs:
        target = payoff.get("payoff_unit_id")
        if target not in positions:
            continue
        required = [item for item in payoff.get("setup_unit_ids") or [] if item in positions]
        seeds.append(([*(required[-3:]), target], "setup_to_payoff", payoff))
    strong_indices = []
    for index, unit in enumerate(story_units):
        unit_id = unit["semantic_unit_id"]
        role = unit.get("primary_story_role") or "other"
        signal_types = _unit_signal_types(unit_id, signals)
        text_strength = _text_strength(unit.get("transcript") or "")
        strength = max(
            ROLE_STRENGTH.get(role, .18),
            max([SIGNAL_STRENGTH.get(item, .2) for item in signal_types] or [.2]),
            text_strength["tension"], text_strength["surprise"], text_strength["emotional"],
            text_strength["personal"], text_strength["entity"] if role in {"claim", "proof", "reveal"} else 0,
        )
        if strength < .58 and unit_id not in hooks_by_unit:
            continue
        strong_indices.append(index)
        chosen = [unit_id]
        origin = f"semantic_{role}"
        linked_payoff = next((item for item in payoffs if item.get("payoff_unit_id") == unit_id), None)
        if linked_payoff:
            chosen = [*[item for item in linked_payoff.get("setup_unit_ids") or [] if item in positions][-3:], unit_id]
            origin = "payoff_or_reveal"
        elif role == "question":
            for following in story_units[index + 1:min(len(story_units), index + 4)]:
                if "payoff" in (following.get("secondary_roles") or []) or following.get("primary_story_role") in {"claim", "explanation", "payoff", "reveal"}:
                    chosen.append(following["semantic_unit_id"])
                    linked_payoff = next((item for item in payoffs if item.get("payoff_unit_id") == following["semantic_unit_id"]), None)
                    origin = "question_answer"
                    break
        elif index > 0 and re.match(r"^(and|but|so|it|they|he|she|this|that|because)\b", (unit.get("transcript") or "").casefold()):
            chosen.insert(0, story_units[index - 1]["semantic_unit_id"])
            origin = "claim_with_required_context"
        seeds.append((chosen, origin, linked_payoff))
    if len(strong_indices) >= 2:
        first, last = min(strong_indices), max(strong_indices)
        if story_units[last]["end_ms"] - story_units[first]["start_ms"] <= MAX_CANDIDATE_DURATION_MS:
            seeds.append(([item["semantic_unit_id"] for item in story_units[first:last + 1]], "significant_story_span", None))
    return seeds


def deduplicate(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: (-item["score"], item["start_ms"], item["candidate_id"])):
        duplicate = next(((prior, duplicate_reason(candidate, prior)) for prior in kept if duplicate_reason(candidate, prior)), None)
        if duplicate is None:
            kept.append(candidate)
            continue
        prior, relationship = duplicate
        candidate["duplicate_of"] = prior["candidate_id"]
        candidate["rejection_reason"] = "semantic_temporal_duplicate"
        candidate["related_candidates"].append({"candidate_id": prior["candidate_id"], "relationship": "duplicate", **relationship})
        prior["related_candidates"].append({"candidate_id": candidate["candidate_id"], "relationship": "duplicate", **relationship})
        rejected.append(candidate)
    return kept, rejected


def select_portfolio(candidates: list[dict[str, Any]], maximum: int = MAX_FINALISTS) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    story_counts: dict[str, int] = {}
    for candidate in sorted(candidates, key=lambda item: (-item["score"], item["start_ms"])):
        if candidate["quality_bucket"] == "weak":
            candidate["rejection_reason"] = "below_usable_quality"
            rejected.append(candidate)
            continue
        if len(selected) >= maximum:
            candidate["rejection_reason"] = "maximum_portfolio_size"
            rejected.append(candidate)
            continue
        same_story = [item for item in selected if item["story_id"] == candidate["story_id"]]
        if len(same_story) >= 2 and any(semantic_overlap(item, candidate) >= .2 for item in same_story):
            candidate["rejection_reason"] = "story_diversity_limit"
            rejected.append(candidate)
            continue
        story_counts[candidate["story_id"]] = story_counts.get(candidate["story_id"], 0) + 1
        selected.append(candidate)
    return selected, rejected


def build_selection(
    *, story_semantics: dict[str, Any], source_editing: dict[str, Any],
    rms: list[float] | None = None, grid_sec: float = .1, maximum: int = MAX_FINALISTS,
) -> dict[str, Any] | None:
    units = story_semantics.get("semantic_units") or []
    stories = story_semantics.get("story_segments") or []
    if not units or not stories:
        return None
    units_by_id = {item["semantic_unit_id"]: item for item in units if item.get("semantic_unit_id")}
    hooks_by_unit: dict[str, list[dict[str, Any]]] = {}
    for hook in story_semantics.get("hooks") or []:
        if hook.get("semantic_unit_id"):
            hooks_by_unit.setdefault(hook["semantic_unit_id"], []).append(hook)
    signals = story_semantics.get("speech_signals") or []
    payoffs = story_semantics.get("payoff_relationships") or []
    story_count_early = sum(int(item.get("start_ms") or 0) < 30_000 for item in stories)
    broad: list[dict[str, Any]] = []
    for story_index, story in enumerate(stories):
        story_units = [units_by_id[item] for item in story.get("semantic_unit_ids") or [] if item in units_by_id]
        if not story_units or story.get("start_reason") in {"show_intro", "sponsor_branding", "outro_unrelated_transition"}:
            continue
        story_payoffs = [item for item in payoffs if item.get("story_id") == story.get("story_id")]
        for chosen, origin, payoff in _seed_sets(story, story_units, signals, story_payoffs, hooks_by_unit):
            candidate = _candidate(
                story=story, chosen_ids=chosen, units_by_id=units_by_id, story_units=story_units,
                hooks_by_unit=hooks_by_unit, signals=signals, payoff=payoff, origin=origin,
                source_editing=source_editing, rms=rms or [], grid_sec=grid_sec,
                story_count_early=story_count_early,
            )
            if candidate:
                if story_index + 1 < len(stories):
                    candidate["next_topic_boundary_ms"] = stories[story_index + 1]["start_ms"]
                broad.append(candidate)
    # Stable exact-seed collapse before overlap-aware dedupe.
    unique: dict[str, dict[str, Any]] = {}
    for item in broad:
        if item["candidate_id"] in unique:
            prior = unique[item["candidate_id"]]
            prior["discovery_origins"] = list(dict.fromkeys([*prior["discovery_origins"], *item["discovery_origins"]]))
            if item["score"] > prior["score"]:
                item["discovery_origins"] = prior["discovery_origins"]
                unique[item["candidate_id"]] = item
        else:
            unique[item["candidate_id"]] = item
    broad = list(unique.values())
    deduped, duplicate_rejections = deduplicate(broad)
    selected, diversity_rejections = select_portfolio(deduped, maximum=maximum)
    buckets = {name: sum(item["quality_bucket"] == name for item in deduped) for name in ("exceptional", "strong", "usable", "weak")}
    return {
        "schema_version": 2, "selection_version": "clip-selection-v2",
        "status": "available", "broad_candidate_count": len(broad),
        "post_dedupe_count": len(deduped), "final_count": len(selected),
        "quality_bucket_counts": buckets, "candidates": deduped,
        "portfolio": selected,
        "rejected_high_ranking": sorted([*duplicate_rejections, *diversity_rejections], key=lambda item: -item["score"])[:24],
        "provenance": {
            "method": "story-aware-clip-selection-v2", "story_schema_version": story_semantics.get("schema_version"),
            "llm_calls_added": 0, "new_decode_or_inference": False,
        },
        "limitations": [
            "Candidates remain continuous source intervals; internal semantic compression is not performed.",
            "Novelty is unavailable without a comparison corpus and is left null.",
            "Source-highlight likelihood is descriptive and does not reject a candidate.",
        ],
    }


def debug_artifact(selection: dict[str, Any]) -> dict[str, Any]:
    """Compact benchmark artifact: final decisions plus highest rejected alternatives."""
    def compact(candidate: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "candidate_id", "story_id", "start_ms", "end_ms", "semantic_unit_ids",
            "hook_unit_id", "setup_context_unit_ids", "optional_context_unit_ids",
            "payoff_reveal_unit_ids", "likely_semantic_end_ms", "next_topic_boundary_ms",
            "next_topic_started", "completeness", "start_quality", "start_reason",
            "end_quality", "end_reason", "semantic_closure_confidence", "discovery_origins",
            "features", "score", "quality_bucket", "source_preedited_likelihood",
            "source_highlight_origin", "related_candidates", "duplicate_of", "rejection_reason",
            "evidence", "provenance",
        )
        return {
            **{key: candidate.get(key) for key in keys},
            "source_transcript_excerpt": str(candidate.get("source_transcript") or "")[:600],
        }
    return {
        "schema_version": selection["schema_version"], "selection_version": selection["selection_version"],
        "status": selection["status"], "broad_candidate_count": selection["broad_candidate_count"],
        "post_dedupe_count": selection["post_dedupe_count"], "final_count": selection["final_count"],
        "quality_bucket_counts": selection["quality_bucket_counts"],
        "final_candidates": [compact(item) for item in selection["portfolio"]],
        "rejected_high_ranking": [compact(item) for item in selection["rejected_high_ranking"]],
        "provenance": selection["provenance"], "limitations": selection["limitations"],
    }
