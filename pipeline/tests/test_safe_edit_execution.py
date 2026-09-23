import json

from publikclip_pipeline.safe_edit_execution import ExecutionPolicy, build_execution_plan, preserve_duration_contract


def decision(decision_id, start, end, *, action="remove", reason="false_start", cut_risk="low", audio="low", visual="low"):
    return {
        "decision_id": decision_id, "start_ms": start, "end_ms": end,
        "action": action, "reason": reason, "confidence": .9,
        "cut_risk": cut_risk,
        "join_risk": {
            "audio_join_risk": audio, "visual_jump_risk": visual,
            "sentence_join_risk": reason == "false_start", "semantic_join_quality": "high",
        },
        "recommended_cut_window_ms": [start - 80, end + 80],
    }


def plan(decisions, *, integrity="preserved", protected=None, start=0, end=5000, segments=None, policy=None):
    compression = {
        "semantic_compression_version": "semantic-compression-v1.1",
        "candidates": [{
            "candidate_id": "candidate-one", "original_start_ms": start, "original_end_ms": end,
            "semantic_integrity_status": integrity, "decisions": decisions,
            "protected_ranges": protected or [],
        }],
    }
    return build_execution_plan(
        semantic_compression=compression, segments=segments or [], policy=policy,
    )["candidates"][0]


def test_optional_keep_never_auto_executes():
    result = plan([decision("d1", 1000, 1300, action="optional_keep", reason="filler")])
    assert not result["executed_removals"]
    assert result["skipped_removals"][0]["skip_reason"] == "optional_keep_retained"
    assert result["execution_status"] == "unchanged"


def test_high_risk_cut_is_skipped_by_default():
    result = plan([decision("d1", 1000, 1500, cut_risk="high")], integrity="needs_review")
    assert not result["executed_removals"]
    assert result["skipped_removals"][0]["skip_reason"] == "high_risk_join"
    assert result["execution_status"] == "review_required"


def test_safe_remove_executes_and_constructs_retained_ranges():
    result = plan([decision("d1", 1000, 1500)])
    cut = result["executed_removals"][0]
    assert [(r["start_ms"], r["end_ms"]) for r in result["final_retained_ranges"]] == [(0, cut["refined_left_boundary_ms"]), (cut["refined_right_boundary_ms"], 5000)]
    assert result["time_saved_ms"] == cut["refined_right_boundary_ms"] - cut["refined_left_boundary_ms"]
    assert result["execution_status"] == "auto_safe"


def test_duration_contract_restores_continuous_source_when_compression_is_too_short():
    result = plan([decision("d1", 1000, 5000)], start=0, end=32_000)
    protected = preserve_duration_contract({"candidates": [result]}, {"min_seconds": 30, "max_seconds": 60})["candidates"][0]
    assert protected["final_duration_ms"] == 32_000
    assert protected["final_retained_ranges"] == [{"start_ms": 0, "end_ms": 32_000}]
    assert protected["execution_status"] == "duration_contract_preserved_source_continuous"


def test_multiple_safe_removals_are_ordered_without_overlap():
    result = plan([decision("d2", 3000, 3400), decision("d1", 1000, 1500)])
    first, second = result["executed_removals"]
    assert [(r["start_ms"], r["end_ms"]) for r in result["final_retained_ranges"]] == [
        (0, first["refined_left_boundary_ms"]),
        (first["refined_right_boundary_ms"], second["refined_left_boundary_ms"]),
        (second["refined_right_boundary_ms"], 5000),
    ]
    assert all(a["end_ms"] <= b["start_ms"] for a, b in zip(result["final_retained_ranges"], result["final_retained_ranges"][1:]))


def test_overlapping_and_invalid_decisions_degrade_safely():
    result = plan([decision("d1", 1000, 1800), decision("d2", 1700, 2200), decision("d3", 4000, 3900)])
    reasons = {item["skip_reason"] for item in result["skipped_removals"]}
    assert "overlapping_removal" in reasons
    assert "invalid_or_too_short_interval" in reasons
    assert all(r["end_ms"] > r["start_ms"] for r in result["final_retained_ranges"])


def test_boundary_refinement_stays_inside_recommended_window():
    words = [{"words": [
        {"word": "before", "start": .8, "end": 1.02},
        {"word": "restart", "start": 1.08, "end": 1.42},
        {"word": "after", "start": 1.48, "end": 1.8},
    ]}]
    item = decision("d1", 1050, 1450)
    item["recommended_cut_window_ms"] = [1020, 1480]
    result = plan([item], segments=words)
    cut = result["executed_removals"][0]
    assert 1020 <= cut["refined_left_boundary_ms"] <= 1480
    assert 1020 <= cut["refined_right_boundary_ms"] <= 1480


def test_crossfade_is_bounded_and_reviewed_false_start_can_execute():
    policy = ExecutionPolicy(false_start_crossfade_ms=200, max_crossfade_ms=80)
    result = plan([decision("d1", 1000, 1500, cut_risk="medium")], integrity="needs_review", policy=policy)
    assert result["executed_removals"][0]["audio_crossfade_ms"] == 80
    assert result["execution_status"] == "auto_safe"


def test_protected_cut_is_skipped():
    result = plan([decision("d1", 1000, 1500)], protected=[{"start_ms": 900, "end_ms": 1600}])
    assert result["skipped_removals"][0]["skip_reason"] == "protected_content"


def test_legacy_continuous_candidate_and_serialization_and_stable_ids():
    first = plan([])
    second = plan([decision("d1", 1000, 1500)])
    third = plan([decision("d1", 1000, 1500)])
    assert first["final_retained_ranges"] == [{"start_ms": 0, "end_ms": 5000}]
    assert first["execution_status"] == "unchanged"
    assert second["executed_removals"][0]["cut_id"] == third["executed_removals"][0]["cut_id"]
    json.dumps(first)


def test_partial_status_and_suppressed_micro_cut_are_inspectable():
    suppressed = decision("d2", 2500, 2700)
    suppressed["micro_cut_suppressed"] = True
    result = plan([decision("d1", 1000, 1500), suppressed])
    assert result["execution_status"] == "partial_safe"
    assert result["skipped_removals"][0]["skip_reason"] == "micro_cut_suppressed"


def test_visual_cover_fallback_is_flagged_without_executing():
    result = plan([decision("d1", 1000, 1500, visual="high")])
    assert not result["executed_removals"]
    assert result["skipped_removals"][0]["requires_visual_cover"] is True
    assert result["visual_cover_required_count"] == 1
    assert result["final_retained_ranges"] == [{"start_ms": 0, "end_ms": 5000}]


def test_full_artifact_is_stably_serializable():
    compression = {
        "semantic_compression_version": "semantic-compression-v1.1",
        "candidates": [{
            "candidate_id": "candidate-one", "original_start_ms": 0, "original_end_ms": 5000,
            "semantic_integrity_status": "preserved", "decisions": [decision("d1", 1000, 1500)],
            "protected_ranges": [],
        }],
    }
    first = build_execution_plan(semantic_compression=compression, segments=[])
    second = build_execution_plan(semantic_compression=compression, segments=[])
    first["metrics"].pop("runtime_ms")
    second["metrics"].pop("runtime_ms")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
