from copy import deepcopy

from publikclip_pipeline.candidates.selection import (
    _score,
    build_selection,
    debug_artifact,
    deduplicate,
    duplicate_reason,
    select_portfolio,
)


def _unit(identifier, start, end, role, text, *, secondary=None):
    return {
        "semantic_unit_id": identifier, "start_ms": start, "end_ms": end,
        "speaker_ids": ["speaker-0"], "transcript": text, "semantic_summary": text,
        "primary_story_role": role, "secondary_roles": secondary or [],
        "confidence": .84, "source": "derived", "status": "interpreted",
        "references": {
            "source_editing_event_ids": [f"edit-{identifier}"], "visual_unit_ids": [],
            "caption_event_ids": [], "audio_event_ids": [],
        },
        "evidence": {},
    }


def _story_fixture():
    units = [
        _unit("u-context", 0, 2000, "context", "Earlier unrelated context about the show."),
        _unit("u-question", 2100, 4000, "question", "How much revenue are you making?"),
        _unit("u-answer", 4200, 7000, "claim", "We're making 43 million dollars per year.", secondary=["payoff"]),
        _unit("u-next", 8100, 11000, "claim", "A different idea begins with a product claim."),
    ]
    story_a = {
        "story_id": "story-a", "start_ms": 0, "end_ms": 7000,
        "semantic_unit_ids": ["u-context", "u-question", "u-answer"],
        "topic_summary": "revenue disclosure", "start_reason": "source_start", "end_reason": "new_idea",
        "confidence": .84, "completeness": {
            "setup_complete": True, "claim_complete": True, "payoff_present": True,
            "conclusion_present": False, "unresolved": False, "next_topic_started": True,
            "likely_semantic_end_ms": 7000,
        },
    }
    story_b = {
        "story_id": "story-b", "start_ms": 8100, "end_ms": 11000,
        "semantic_unit_ids": ["u-next"], "topic_summary": "product claim",
        "start_reason": "new_idea", "end_reason": "source_end", "confidence": .8,
        "completeness": {
            "setup_complete": False, "claim_complete": True, "payoff_present": False,
            "conclusion_present": False, "unresolved": False, "next_topic_started": False,
            "likely_semantic_end_ms": 11000,
        },
    }
    return {
        "schema_version": 1, "semantic_units": units, "story_segments": [story_a, story_b],
        "hooks": [{"id": "hook-1", "semantic_unit_id": "u-question", "confidence": .85}],
        "speech_signals": [
            {"id": "signal-q", "type": "question", "semantic_unit_id": "u-question"},
            {"id": "signal-money", "type": "money_value", "semantic_unit_id": "u-answer"},
            {"id": "signal-claim", "type": "claim", "semantic_unit_id": "u-answer"},
        ],
        "payoff_relationships": [{
            "id": "payoff-1", "story_id": "story-a", "setup_unit_ids": ["u-question"],
            "payoff_unit_id": "u-answer", "confidence": .86,
        }],
    }


def _selection():
    return build_selection(
        story_semantics=_story_fixture(),
        source_editing={"metrics": {"cuts_per_minute": 4, "visual_change_cadence_per_minute": 6}},
        maximum=12,
    )


def test_story_aware_candidate_uses_minimum_context_and_excludes_next_topic():
    result = _selection()
    candidate = next(item for item in result["candidates"] if "setup_to_payoff" in item["discovery_origins"])
    assert candidate["story_id"] == "story-a"
    assert candidate["semantic_unit_ids"] == ["u-question", "u-answer"]
    assert candidate["start_ms"] == 2100
    assert candidate["end_ms"] == 7000
    assert candidate["next_topic_boundary_ms"] == 8100
    assert candidate["likely_semantic_end_ms"] == 7000
    assert candidate["start_reason"] == "hook_or_question"
    assert candidate["end_reason"] == "payoff_or_reveal_complete"
    assert candidate["setup_context_unit_ids"] == ["u-question"]
    assert candidate["optional_context_unit_ids"] == ["u-context"]
    assert candidate["completeness"]["context_present"] is True
    assert candidate["completeness"]["semantically_complete"] is True


def test_candidate_ids_are_stable_and_debug_artifact_is_serializable():
    first = _selection()
    second = _selection()
    assert [item["candidate_id"] for item in first["candidates"]] == [
        item["candidate_id"] for item in second["candidates"]
    ]
    artifact = debug_artifact(first)
    assert artifact["selection_version"] == "clip-selection-v2"
    assert artifact["final_count"] == len(artifact["final_candidates"])
    assert artifact["final_candidates"][0]["evidence"]["generated_summary_used_for_score"] is False

    corrected = deepcopy(_story_fixture())
    corrected["story_segments"][0]["story_id"] = "corrected-story-a"
    corrected["payoff_relationships"][0]["story_id"] = "corrected-story-a"
    after_story_correction = build_selection(story_semantics=corrected, source_editing={})
    original_units = next(item for item in first["candidates"] if "setup_to_payoff" in item["discovery_origins"])
    corrected_units = next(item for item in after_story_correction["candidates"] if "setup_to_payoff" in item["discovery_origins"])
    assert corrected_units["candidate_id"] == original_units["candidate_id"]


def test_scores_do_not_veto_semantic_shock_for_low_arousal_or_require_laughter():
    features = {
        "moment_strength": .92, "hook_strength": .8, "payoff_strength": .78,
        "insight_strength": .7, "tension_conflict": .9, "surprise": .9,
        "specificity": .75, "semantic_completeness": .9, "quotability": .9,
        "start_quality": .9, "end_quality": .9, "internal_flow": .9,
        "unresolved_penalty": 0, "intro_or_branding_contamination": 0,
        "estimated_dead_time_ratio": 0, "tangent_signal": 0,
        "context_required": 0, "context_present": 1, "delivery_energy": 0,
    }
    calm_score, calm_bucket = _score(features)
    energetic_score, _ = _score({**features, "delivery_energy": 1})
    assert calm_bucket in {"exceptional", "strong"}
    assert energetic_score - calm_score <= 3
    assert "laughter" not in features  # humor/reaction needs no acoustic veto in v2


def test_score_separation_produces_distinct_quality_buckets():
    strong = {key: .9 for key in (
        "moment_strength", "hook_strength", "payoff_strength", "insight_strength",
        "tension_conflict", "surprise", "specificity", "semantic_completeness",
        "quotability", "start_quality", "end_quality", "internal_flow",
    )}
    strong.update({"unresolved_penalty": 0, "intro_or_branding_contamination": 0, "estimated_dead_time_ratio": 0, "tangent_signal": 0, "context_required": 0, "context_present": 1})
    weak = {**strong, **{key: .2 for key in (
        "moment_strength", "hook_strength", "payoff_strength", "insight_strength",
        "tension_conflict", "surprise", "specificity", "semantic_completeness",
        "quotability", "start_quality", "end_quality", "internal_flow",
    )}}
    strong_score, strong_bucket = _score(strong)
    weak_score, weak_bucket = _score(weak)
    assert strong_score - weak_score >= 50
    assert strong_bucket == "exceptional"
    assert weak_bucket == "weak"


def test_semantic_and_temporal_duplicates_keep_strongest_representative():
    base = {
        "story_id": "story-a", "semantic_unit_ids": ["u1", "u2"],
        "start_ms": 1000, "end_ms": 5000, "topic_summary": "weight cut risks",
        "candidate_id": "strong", "score": 82, "related_candidates": [],
    }
    duplicate = {**base, "candidate_id": "weaker", "score": 65, "start_ms": 1200, "end_ms": 5100, "related_candidates": []}
    relation = duplicate_reason(base, duplicate)
    assert relation["semantic_unit_jaccard"] == 1
    kept, rejected = deduplicate([duplicate, base])
    assert [item["candidate_id"] for item in kept] == ["strong"]
    assert rejected[0]["duplicate_of"] == "strong"
    assert rejected[0]["rejection_reason"] == "semantic_temporal_duplicate"


def test_diversity_and_maximum_n_do_not_force_weak_candidates():
    candidates = [
        {"candidate_id": "a", "story_id": "s1", "semantic_unit_ids": ["a"], "score": 90, "quality_bucket": "exceptional", "start_ms": 0},
        {"candidate_id": "b", "story_id": "s2", "semantic_unit_ids": ["b"], "score": 72, "quality_bucket": "strong", "start_ms": 10},
        {"candidate_id": "c", "story_id": "s3", "semantic_unit_ids": ["c"], "score": 30, "quality_bucket": "weak", "start_ms": 20},
    ]
    selected, rejected = select_portfolio(candidates, maximum=12)
    assert [item["candidate_id"] for item in selected] == ["a", "b"]
    assert rejected[0]["rejection_reason"] == "below_usable_quality"


def test_source_highlight_flag_is_descriptive_not_an_automatic_rejection():
    result = build_selection(
        story_semantics=_story_fixture(),
        source_editing={"metrics": {"cuts_per_minute": 18, "visual_change_cadence_per_minute": 20}},
    )
    early = next(item for item in result["candidates"] if item["story_id"] == "story-a")
    assert early["source_preedited_likelihood"] >= .6
    assert early["source_highlight_origin"] is True
    assert early["rejection_reason"] is None


def test_missing_story_timeline_uses_legacy_fallback_contract():
    assert build_selection(story_semantics={}, source_editing={}) is None
