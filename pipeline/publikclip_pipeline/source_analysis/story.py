"""Evidence-backed semantic units and conservative story structure."""

from __future__ import annotations

import hashlib
import json
import re
import time
from statistics import mean
from typing import Any


STORY_ROLES = {
    "hook", "context", "setup", "question", "claim", "explanation", "development",
    "escalation", "conflict", "contrast", "surprise", "reveal", "payoff", "proof",
    "reaction", "transition", "CTA", "conclusion", "unresolved", "other",
}
RELATIONS = {
    "continuation", "supporting_detail", "tangent", "new_idea", "show_intro",
    "sponsor_branding", "outro_unrelated_transition", "uncertain",
}
HOOK_TYPES = {
    "textual", "spoken", "visual", "curiosity", "question", "bold_claim", "contradiction",
    "surprise", "status_money", "emotional", "conflict", "information_gap", "pattern_interrupt",
}
MAX_WINDOW_WORDS = 650
MAX_WINDOW_UNITS = 28
WINDOW_OVERLAP_UNITS = 3


LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "annotations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "input_index": {"type": "integer"},
                    "summary": {"type": "string"},
                    "topic": {"type": "string"},
                    "primary_role": {"type": "string", "enum": sorted(STORY_ROLES)},
                    "secondary_roles": {"type": "array", "items": {"type": "string", "enum": sorted(STORY_ROLES)}},
                    "relation_to_previous": {"type": "string", "enum": sorted(RELATIONS)},
                    "hook_types": {"type": "array", "items": {"type": "string", "enum": sorted(HOOK_TYPES)}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["input_index", "summary", "topic", "primary_role", "secondary_roles", "relation_to_previous", "hook_types", "confidence"],
            },
        }
    },
    "required": ["annotations"],
}


def _stable_id(prefix: str, start_ms: int, identity: str) -> str:
    digest = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}_{max(0, start_ms):09d}_{digest}"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.casefold())


def _speaker_ids(segment: dict[str, Any]) -> list[str]:
    values = {word.get("speaker") for word in segment.get("words") or [] if word.get("speaker") is not None}
    if segment.get("speaker") is not None:
        values.add(segment["speaker"])
    return [f"speaker-{value}" for value in sorted(values, key=str)]


def _transcript_inputs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for segment in segments:
        if not isinstance(segment, dict) or not str(segment.get("text") or "").strip():
            continue
        start_ms = round(float(segment.get("start") or 0) * 1000)
        end_ms = max(start_ms, round(float(segment.get("end") or segment.get("start") or 0) * 1000))
        text = " ".join(str(segment.get("text") or "").split())
        output.append({
            "input_index": len(output), "start_ms": start_ms, "end_ms": end_ms, "text": text,
            "speaker_ids": _speaker_ids(segment),
            "transcript_ref_id": _stable_id("transcript_ref", start_ms, f"{end_ms}:{text}"),
        })
    return output


def semantic_windows(
    inputs: list[dict[str, Any]], *, max_words: int = MAX_WINDOW_WORDS,
    max_units: int = MAX_WINDOW_UNITS, overlap_units: int = WINDOW_OVERLAP_UNITS,
) -> list[list[dict[str, Any]]]:
    """Bounded narrative windows whose shared units preserve cross-window context."""
    if not inputs:
        return []
    windows = []
    begin = 0
    while begin < len(inputs):
        end = begin
        words = 0
        while end < len(inputs) and end - begin < max_units:
            count = max(1, len(_words(inputs[end]["text"])))
            if end > begin and words + count > max_words:
                break
            words += count
            end += 1
        windows.append(inputs[begin:end])
        if end >= len(inputs):
            break
        begin = max(begin + 1, end - min(overlap_units, max(0, end - begin - 1)))
    return windows


def _fallback_annotation(item: dict[str, Any]) -> dict[str, Any]:
    text = item["text"]
    lower = text.casefold()
    roles: list[str] = []
    if "?" in text or re.match(r"^(who|what|when|where|why|how|can|could|would|do|did|is|are|tell me|talk to me|you're fresh off|you are fresh off)\b", lower) or re.search(r"\b(tell me|talk to me)\b", lower):
        roles.append("question")
    if re.search(r"\b(follow|subscribe|like and|link in bio|buy now|sign up|check out)\b", lower):
        roles.append("CTA")
    if re.search(r"\b(turns out|the truth is|here(?:'s| is) what|there it is|revealed?|found out|actually was)\b", lower):
        roles.append("reveal")
    if re.search(r"\b(because|this means|which means|the reason)\b", lower):
        roles.append("explanation")
    if re.search(r"\b(but|however|instead|whereas|on the other hand)\b", lower):
        roles.append("contrast")
    if re.search(r"\b(finally|in conclusion|to sum up|the takeaway|so ultimately)\b", lower):
        roles.append("conclusion")
    if re.search(r"\b(i think|i believe|the best|the worst|always|never|must|should)\b", lower):
        roles.append("claim")
    if not roles and re.search(r"(?:[$€£]\s?\d|\b\d[\d,.]*\s?(?:dollars?|euros?|pounds?|million|billion|grand|k)\b)", lower) and "?" not in text:
        roles.append("claim")
    if re.search(r"\b(wow|oh my|no way|that's crazy|unbelievable)\b", lower):
        roles.append("reaction")
    role = roles[0] if roles else "other"
    return {
        "input_index": item["input_index"], "summary": text[:180], "topic": " ".join(_words(text)[:10]),
        "primary_role": role, "secondary_roles": roles[1:3],
        "relation_to_previous": "uncertain", "hook_types": [],
        "confidence": 0.78 if role in {"question", "CTA"} else 0.62 if roles else 0.4,
        "annotation_source": "derived",
    }


def _prompt(window: list[dict[str, Any]], prior_topic: str | None) -> str:
    compact = [{
        "input_index": item["input_index"], "start_ms": item["start_ms"], "end_ms": item["end_ms"],
        "speakers": item["speaker_ids"], "text": item["text"],
    } for item in window]
    return (
        "Annotate the supplied transcript evidence conservatively. Do not invent events, speakers, intent, "
        "performance, or timestamps. Each annotation must use an exact input_index. A new idea requires a "
        "clear semantic topic change; answers, examples, elaboration, and supporting details continue the same idea. "
        "Use 'other' and 'uncertain' when evidence is weak. A hook type means hook-like structure only, not effectiveness. "
        "Keep summary/topic under 18 words.\n"
        f"Prior carried topic from the preceding overlapping window: {prior_topic or 'none'}\n"
        f"Evidence JSON: {json.dumps(compact, ensure_ascii=False, separators=(',', ':'))}"
    )


def _validated_annotations(payload: Any, valid_indices: set[int]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("annotations"), list):
        raise ValueError("story annotation payload is not an object with annotations")
    output = []
    for value in payload["annotations"]:
        if not isinstance(value, dict) or value.get("input_index") not in valid_indices:
            continue
        role = value.get("primary_role")
        relation = value.get("relation_to_previous")
        confidence = value.get("confidence")
        if role not in STORY_ROLES or relation not in RELATIONS or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            continue
        secondary = [item for item in value.get("secondary_roles") or [] if item in STORY_ROLES and item != role][:3]
        hooks = [item for item in value.get("hook_types") or [] if item in HOOK_TYPES][:4]
        output.append({
            "input_index": value["input_index"], "summary": str(value.get("summary") or "")[:180],
            "topic": str(value.get("topic") or "")[:120], "primary_role": role,
            "secondary_roles": secondary, "relation_to_previous": relation,
            "hook_types": hooks, "confidence": round(min(0.92, float(confidence)), 4), "annotation_source": "llm",
        })
    if not output:
        raise ValueError("story annotation payload contains no valid annotations")
    return output


def _annotations(inputs: list[dict[str, Any]], llm_client: Any | None) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    chosen = {item["input_index"]: _fallback_annotation(item) for item in inputs}
    windows = semantic_windows(inputs)
    calls = failures = 0
    prior_topic = None
    started = time.monotonic()
    if llm_client is not None:
        for window in windows:
            calls += 1
            try:
                payload = llm_client.generate_json(_prompt(window, prior_topic), LLM_SCHEMA)
                values = _validated_annotations(payload, {item["input_index"] for item in window})
                for value in values:
                    current = chosen[value["input_index"]]
                    # Preserve high-precision textual roles even when a model
                    # retreats to `other` or mislabels explicit punctuation.
                    if current["primary_role"] != "other" and current["confidence"] >= 0.6:
                        if value["primary_role"] != current["primary_role"] and value["primary_role"] != "other":
                            value["secondary_roles"] = list(dict.fromkeys([value["primary_role"], *value["secondary_roles"]]))[:3]
                        value["primary_role"] = current["primary_role"]
                        value["confidence"] = max(value["confidence"], current["confidence"])
                    # Overlap reconciliation is deterministic: retain an earlier
                    # annotation unless the later window is materially surer.
                    if current["annotation_source"] != "llm" or value["confidence"] >= current["confidence"] + 0.12:
                        chosen[value["input_index"]] = value
                if values:
                    prior_topic = next((item["topic"] for item in reversed(values) if item["topic"]), prior_topic)
            except Exception:  # noqa: BLE001 - semantic enrichment must degrade
                failures += 1
    return chosen, {
        "window_count": len(windows), "llm_call_count": calls, "llm_failure_count": failures,
        "window_overlap_units": WINDOW_OVERLAP_UNITS, "max_window_words": MAX_WINDOW_WORDS,
        "runtime_sec": round(time.monotonic() - started, 4),
    }


def _overlaps(start_ms: int, end_ms: int, item: dict[str, Any], pad_ms: int = 0) -> bool:
    item_start = int(item.get("start_ms") or item.get("timestamp_ms") or 0)
    item_end = int(item.get("end_ms") or item_start)
    return item_end >= start_ms - pad_ms and item_start <= end_ms + pad_ms


def _references(
    start_ms: int, end_ms: int, *, source_editing: dict[str, Any], visual_units: list[dict[str, Any]],
    caption_tracks: list[dict[str, Any]], emphasis_events: list[dict[str, Any]], audio_events: list[dict[str, Any]],
) -> dict[str, list[str]]:
    editing = []
    for key in ("cuts", "transitions", "reframes", "zooms", "pattern_interrupts"):
        editing.extend(str(item["id"]) for item in source_editing.get(key) or [] if item.get("id") and _overlaps(start_ms, end_ms, item, 150))
    return {
        "source_editing_event_ids": list(dict.fromkeys(editing)),
        "visual_unit_ids": [str(item["id"]) for item in visual_units if item.get("id") and _overlaps(start_ms, end_ms, item)],
        "caption_event_ids": list(dict.fromkeys([
            *[str(item["id"]) for item in caption_tracks if item.get("id") and _overlaps(start_ms, end_ms, item)],
            *[str(item["caption_track_id"]) for item in emphasis_events if item.get("caption_track_id") and _overlaps(start_ms, end_ms, item)],
        ])),
        "audio_event_ids": [str(item["id"]) for item in audio_events if item.get("id") and _overlaps(start_ms, end_ms, item)],
    }


def _speech_signals(unit: dict[str, Any]) -> list[dict[str, Any]]:
    text = unit["transcript"]
    lower = text.casefold()
    types = []
    if unit["primary_story_role"] == "question" or "?" in text:
        types.append("question")
    if unit["primary_story_role"] == "claim":
        types.append("claim")
    if re.search(r"(?:[$€£]\s?\d|\b\d[\d,.]*\s?(?:dollars?|euros?|pounds?|million|billion|grand|k)\b)", lower):
        types.extend(["number", "money_value"])
    elif re.search(r"\b\d[\d,.]*\b", lower):
        types.append("number")
    if re.search(r"\b(more than|less than|better than|worse than|versus|compared to|whereas)\b", lower):
        types.append("comparison")
    if unit["primary_story_role"] in {"conflict", "contrast"}:
        types.append("conflict_or_contradiction")
    if unit["primary_story_role"] in {"surprise", "reveal"}:
        types.append("surprise_or_reveal")
    if unit["primary_story_role"] == "CTA":
        types.append("CTA")
    tokens = _words(text)
    repeated = sorted({token for left, token in zip(tokens, tokens[1:]) if left == token and len(token) > 2})
    if repeated:
        types.append("immediate_repetition")
    return [{
        "id": _stable_id("speech_signal", unit["start_ms"], f"{kind}:{unit['semantic_unit_id']}"),
        "type": kind, "start_ms": unit["start_ms"], "end_ms": unit["end_ms"],
        "semantic_unit_id": unit["semantic_unit_id"], "confidence": unit["confidence"],
        "source": unit["source"], "status": "interpreted",
        "evidence": {"transcript_ref_ids": unit["evidence"]["transcript_ref_ids"], **({"repeated_tokens": repeated} if kind == "immediate_repetition" else {})},
    } for kind in dict.fromkeys(types)]


def _explicit_relation(previous: dict[str, Any], current: dict[str, Any]) -> tuple[str, float] | None:
    lower = current["transcript"].casefold()
    if re.search(r"\b(welcome back|you're watching|you are watching|welcome to (?:the|season)|today i'm joined|today i am joined)\b", lower):
        return "show_intro", 0.9
    if re.search(r"\b(next topic|moving on|another thing|on a different note|separately)\b", lower):
        return "new_idea", 0.82
    if re.search(r"\b(sponsor(?:ed)? by|thanks to .+ for sponsoring|this episode is brought to you)\b", lower):
        return "sponsor_branding", 0.9
    if re.search(r"\b(thanks for watching|see you next time|don't forget to subscribe)\b", lower):
        return "outro_unrelated_transition", 0.88
    # Direct interviewer prompts remain useful boundary evidence when
    # diarization mistakenly assigns both turns to one speaker. Consecutive
    # fragments of a single prompt are merged in _story_segments below.
    if current["primary_story_role"] == "question" and re.search(
        r"\b(tell me|talk to me|you're fresh off|you are fresh off)\b", lower
    ):
        return "new_idea", 0.76
    if (
        current["primary_story_role"] == "question"
        and previous["primary_story_role"] != "question"
        and current["speaker_ids"] and previous["speaker_ids"]
        and set(current["speaker_ids"]).isdisjoint(previous["speaker_ids"])
    ):
        return "new_idea", 0.68
    gap = (current["start_ms"] - previous["end_ms"]) / 1000
    prior_words, current_words = set(_words(previous["transcript"])), set(_words(current["transcript"]))
    overlap = len(prior_words & current_words) / max(1, min(len(prior_words), len(current_words)))
    if gap >= 4.0 and overlap < 0.08 and current["primary_story_role"] in {"hook", "question", "transition"}:
        return "new_idea", 0.64
    return None


def _story_segments(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not units:
        return []
    groups: list[tuple[list[dict[str, Any]], str, float]] = []
    current = [units[0]]
    start_reason, boundary_confidence = "source_start", units[0]["confidence"]
    boundary_relations = {"new_idea", "tangent", "show_intro", "sponsor_branding", "outro_unrelated_transition"}
    for previous, unit in zip(units, units[1:]):
        explicit = _explicit_relation(previous, unit)
        relation = explicit[0] if explicit else unit["evidence"].get("relation_to_previous")
        confidence = explicit[1] if explicit else unit["confidence"]
        if (
            relation == "new_idea"
            and previous["primary_story_role"] == "question"
            and unit["primary_story_role"] == "question"
            and unit["start_ms"] - previous["end_ms"] <= 1500
        ):
            relation = "supporting_detail"
        if relation in boundary_relations and confidence >= 0.62:
            groups.append((current, start_reason, boundary_confidence))
            current = [unit]
            start_reason, boundary_confidence = str(relation), float(confidence)
        else:
            current.append(unit)
    groups.append((current, start_reason, boundary_confidence))
    output = []
    for index, (group, reason, boundary_confidence) in enumerate(groups):
        roles = [item["primary_story_role"] for item in group]
        topic = next((str(item["evidence"].get("topic")) for item in group if item["evidence"].get("topic")), group[0]["semantic_summary"])
        has_setup = any(role in {"hook", "context", "setup", "question"} for role in roles)
        has_claim = any(role in {"claim", "explanation", "proof", "reveal", "payoff", "conclusion"} for role in roles)
        payoff = any(
            item["primary_story_role"] in {"reveal", "payoff"} or "payoff" in item["secondary_roles"]
            for item in group
        )
        conclusion = "conclusion" in roles
        unresolved = ("unresolved" in roles) or ("question" in roles and not payoff and not conclusion and not has_claim)
        next_topic = index < len(groups) - 1
        end_reason = groups[index + 1][1] if next_topic else "source_end"
        start_ms, end_ms = group[0]["start_ms"], group[-1]["end_ms"]
        output.append({
            "story_id": _stable_id("story", start_ms, f"{end_ms}:{':'.join(item['semantic_unit_id'] for item in group)}"),
            "start_ms": start_ms, "end_ms": end_ms,
            "semantic_unit_ids": [item["semantic_unit_id"] for item in group],
            "topic_summary": topic[:180], "start_reason": reason, "end_reason": end_reason,
            "completeness": {
                "setup_complete": has_setup and len(group) > 1, "claim_complete": has_claim,
                "payoff_present": payoff, "conclusion_present": conclusion,
                "unresolved": unresolved, "next_topic_started": next_topic,
                "likely_semantic_end_ms": end_ms,
            },
            "confidence": round(mean([item["confidence"] for item in group] + [boundary_confidence]), 4),
            "source": "llm" if any(item["source"] == "llm" for item in group) else "derived",
            "status": "interpreted",
            "evidence": {"boundary_relation": reason, "unit_roles": roles},
        })
    return output


def _payoff_relationships(stories: list[dict[str, Any]], units_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for story in stories:
        units = [units_by_id[item] for item in story["semantic_unit_ids"]]
        setups: list[str] = []
        for unit in units:
            if unit["primary_story_role"] in {"hook", "setup", "question", "context", "escalation"}:
                setups.append(unit["semantic_unit_id"])
            if unit["primary_story_role"] not in {"reveal", "payoff"} and "payoff" not in unit["secondary_roles"]:
                continue
            if not setups:
                continue
            output.append({
                "id": _stable_id("payoff_relation", unit["start_ms"], f"{story['story_id']}:{unit['semantic_unit_id']}"),
                "story_id": story["story_id"], "setup_unit_ids": setups[-4:],
                "payoff_unit_id": unit["semantic_unit_id"], "relationship": "setup_to_payoff",
                "confidence": round(min([unit["confidence"], *[units_by_id[item]["confidence"] for item in setups[-4:]]]), 4),
                "source": "derived", "status": "interpreted",
                "evidence": {"role_sequence": [units_by_id[item]["primary_story_role"] for item in setups[-4:]] + [unit["primary_story_role"]]},
            })
    return output


def _hooks(units: list[dict[str, Any]], title_hooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for unit in units:
        types = list(unit["evidence"].get("hook_types") or []) if unit["start_ms"] <= 8000 or unit["primary_story_role"] == "hook" else []
        if unit["start_ms"] <= 8000 and unit["primary_story_role"] == "question":
            types.extend(["spoken", "question", "information_gap"])
        if unit["start_ms"] <= 8000 and any(signal["type"] == "money_value" for signal in _speech_signals(unit)):
            types.extend(["spoken", "status_money"])
        if unit["start_ms"] <= 8000 and unit["references"]["source_editing_event_ids"]:
            types.append("pattern_interrupt")
        if not types and unit["primary_story_role"] != "hook":
            continue
        output.append({
            "id": _stable_id("hook", unit["start_ms"], unit["semantic_unit_id"]),
            "start_ms": unit["start_ms"], "end_ms": unit["end_ms"],
            "semantic_unit_id": unit["semantic_unit_id"], "hook_types": list(dict.fromkeys(types or ["spoken"])),
            "observation": "hook_like_structure", "effectiveness": "not_assessed",
            "confidence": unit["confidence"], "source": unit["source"], "status": "interpreted",
            "evidence": {"event_references": unit["references"]},
        })
    for title in title_hooks:
        start_ms, end_ms = round(float(title.get("start") or 0) * 1000), round(float(title.get("end") or 0) * 1000)
        output.append({
            "id": _stable_id("hook", start_ms, f"text:{title.get('track_id')}"),
            "start_ms": start_ms, "end_ms": end_ms, "semantic_unit_id": None,
            "hook_types": ["textual"], "observation": "hook_like_structure", "effectiveness": "not_assessed",
            "confidence": float(title.get("confidence") or 0), "source": "derived", "status": "interpreted",
            "evidence": {"text_track_ids": [title.get("track_id")]},
        })
    return output


def build_story_semantics(
    *, duration: float, transcript_segments: list[dict[str, Any]], source_editing: dict[str, Any],
    visual_units: list[dict[str, Any]], caption_tracks: list[dict[str, Any]],
    emphasis_events: list[dict[str, Any]], title_hooks: list[dict[str, Any]],
    audio_events: list[dict[str, Any]], llm_client: Any | None = None,
) -> dict[str, Any]:
    inputs = _transcript_inputs(transcript_segments)
    if not inputs:
        return {
            "schema_version": 1, "status": "unavailable", "semantic_units": [], "story_segments": [],
            "hooks": [], "speech_signals": [], "payoff_relationships": [], "structural_metrics": {},
            "evidence": {"transcript_segment_count": 0, "source_editing_ids_reused": []},
            "provenance": {"method": "semantic-story-hybrid-v1", "llm_used": False, "llm_call_count": 0},
            "limitations": ["No timestamped transcript evidence was available."],
        }
    annotations, inference = _annotations(inputs, llm_client)
    units = []
    for item in inputs:
        annotation = annotations[item["input_index"]]
        references = _references(
            item["start_ms"], item["end_ms"], source_editing=source_editing,
            visual_units=visual_units, caption_tracks=caption_tracks,
            emphasis_events=emphasis_events, audio_events=audio_events,
        )
        unit_id = _stable_id("semantic_unit", item["start_ms"], f"{item['end_ms']}:{item['text']}")
        units.append({
            "semantic_unit_id": unit_id, "start_ms": item["start_ms"], "end_ms": item["end_ms"],
            "speaker_ids": item["speaker_ids"], "transcript": item["text"],
            "transcript_refs": [{"id": item["transcript_ref_id"], "start_ms": item["start_ms"], "end_ms": item["end_ms"]}],
            "semantic_summary": annotation["summary"] or item["text"][:180],
            "primary_story_role": annotation["primary_role"], "secondary_roles": annotation["secondary_roles"],
            "confidence": annotation["confidence"], "source": annotation["annotation_source"], "status": "interpreted",
            "references": references,
            "evidence": {
                "transcript_ref_ids": [item["transcript_ref_id"]], "relation_to_previous": annotation["relation_to_previous"],
                "topic": annotation["topic"], "hook_types": annotation["hook_types"],
            },
        })
    # A prompt question followed promptly by a different speaker's direct
    # declarative response is observable answer/payoff structure even when the
    # response's primary role is a claim or explanation.
    for previous, current in zip(units, units[1:]):
        distinct_speakers = bool(previous["speaker_ids"] and current["speaker_ids"] and set(previous["speaker_ids"]).isdisjoint(current["speaker_ids"]))
        if (
            previous["primary_story_role"] == "question"
            and current["primary_story_role"] != "question"
            and current["start_ms"] - previous["end_ms"] <= 2500
            and distinct_speakers
        ):
            current["secondary_roles"] = list(dict.fromkeys([*current["secondary_roles"], "payoff"]))
            current["evidence"]["response_to_unit_id"] = previous["semantic_unit_id"]
    stories = _story_segments(units)
    units_by_id = {item["semantic_unit_id"]: item for item in units}
    signals = [signal for unit in units for signal in _speech_signals(unit)]
    hooks = _hooks(units, title_hooks)
    payoffs = _payoff_relationships(stories, units_by_id)
    metrics = {
        "semantic_unit_count": len(units), "story_segment_count": len(stories),
        "average_story_duration_sec": round(mean((item["end_ms"] - item["start_ms"]) / 1000 for item in stories), 4) if stories else None,
        "question_count": sum(item["type"] == "question" for item in signals),
        "claim_count": sum(item["type"] == "claim" for item in signals),
        "reveal_payoff_count": sum(
            item["primary_story_role"] in {"reveal", "payoff"} or "payoff" in item["secondary_roles"]
            for item in units
        ),
        "unresolved_segment_count": sum(bool(item["completeness"]["unresolved"]) for item in stories),
        "topic_change_count": max(0, len(stories) - 1), "hook_like_moment_count": len(hooks),
    }
    editing_ids = [event_id for unit in units for event_id in unit["references"]["source_editing_event_ids"]]
    return {
        "schema_version": 1, "status": "available" if any(item["source"] == "llm" for item in units) else "limited",
        "semantic_units": units, "story_segments": stories, "hooks": hooks,
        "speech_signals": signals, "payoff_relationships": payoffs, "structural_metrics": metrics,
        "evidence": {
            "transcript_segment_count": len(inputs), "source_editing_ids_reused": list(dict.fromkeys(editing_ids)),
            "visual_unit_ids_reused": [item.get("id") for item in visual_units if item.get("id")],
            "caption_track_ids_reused": [item.get("id") for item in caption_tracks if item.get("id")],
        },
        "provenance": {
            "method": "semantic-story-hybrid-v1", "llm_used": llm_client is not None,
            **inference,
        },
        "limitations": [
            "Semantic roles and topic boundaries are interpretations of ASR evidence and may be ambiguous.",
            "Named entities are not added without an existing reliable entity detector.",
            "Hook records describe structure only; effectiveness and retention impact are not assessed.",
            "False starts are reported only when directly observable and are not inferred from fluent ASR text.",
        ],
    }
