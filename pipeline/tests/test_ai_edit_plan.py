import json

from publikclip_pipeline.ai_edit_plan import build_ai_edit_plan


def _unit(unit_id, start, end, role="development", text="A useful explanation", **extra):
    return {
        "semantic_unit_id": unit_id, "start_ms": start, "end_ms": end,
        "primary_story_role": role, "secondary_roles": [], "transcript": text,
        "confidence": .86, "references": {"source_editing_event_ids": [f"edit-{unit_id}"]},
        **extra,
    }


def _build(policy="balanced", *, units=None, visual=None, safe=None, join=None, presentation="mixed"):
    return build_ai_edit_plan(
        selected_clips=[{"candidate_id": "candidate-a", "start_ms": 0, "end_ms": 12_000,
                         "semantic_unit_ids": [item["semantic_unit_id"] for item in units or []]}],
        story_semantics={"semantic_units": units or []},
        visual_understanding={"visual_units": visual or []},
        safe_execution=safe or {}, visual_join=join or {},
        generation_config={"config_version": 1, "style_profile_id": "test", "broll": {
            "mode": policy, "presentation": presentation,
        }}, generation_config_run_id="run-test",
    )


def test_policy_off_emits_no_actionable_opportunities():
    plan = _build("off", units=[_unit("u1", 1000, 3000, text="Revenue was $43 million")])
    assert plan["clips"][0]["opportunities"] == []


def test_conservative_emits_fewer_than_balanced():
    units = [
        _unit("u1", 1000, 2600, text="For example, this is the evidence."),
        _unit("u2", 4000, 6000, role="claim", text="Revenue was $43 million"),
    ]
    conservative = _build("conservative", units=units)["clips"][0]["opportunities"]
    balanced = _build("balanced", units=units)["clips"][0]["opportunities"]
    assert len(conservative) < len(balanced)


def test_payoff_and_reaction_are_protected_from_ordinary_coverage():
    units = [
        _unit("payoff", 1000, 2600, role="payoff", text="The payoff was $2 million"),
        _unit("reaction", 3000, 4600, role="reaction", text="For example, the reaction proves it"),
    ]
    clip = _build("aggressive", units=units)["clips"][0]
    assert {item["reason"] for item in clip["protected_source_ranges"]} == {"protected_payoff", "protected_reaction"}
    assert clip["opportunities"] == []


def test_visual_cover_requirement_becomes_high_priority_opportunity():
    join = {"candidates": [{"candidate_id": "candidate-a", "joins": [{
        "cut_id": "cut-1", "requires_visual_cover": True,
        "suggested_cover_start_ms": 4800, "suggested_cover_end_ms": 6200,
        "reason": "pose discontinuity",
    }]}]}
    clip = _build("conservative", join=join)["clips"][0]
    assert clip["visual_cover_requirements"][0]["cut_id"] == "cut-1"
    assert clip["opportunities"][0]["priority"] == "high"
    assert clip["opportunities"][0]["suggested_visual_role"] == "visual_cover"
    assert clip["opportunities"][0]["requires_visual_cover"] is True


def test_source_broll_carrying_meaning_is_protected():
    visual = [{
        "id": "visual-1", "start_ms": 1000, "end_ms": 3000, "visual_type": "b_roll",
        "confidence": .9, "relation_to_speech": {"type": "illustrates_speech"},
    }]
    clip = _build("aggressive", units=[_unit("u1", 1000, 3000)], visual=visual)["clips"][0]
    assert any(item["reason"] == "source_visual_already_carries_meaning" for item in clip["protected_source_ranges"])
    assert clip["opportunities"] == []


def test_stable_ids_generation_config_mapping_and_serialization():
    unit = _unit("u1", 1000, 3000, text="Revenue was $43 million")
    first = _build("balanced", units=[unit], presentation="overlay")
    second = _build("balanced", units=[unit], presentation="overlay")
    left, right = first["clips"][0], second["clips"][0]
    assert left["opportunities"][0]["opportunity_id"] == right["opportunities"][0]["opportunity_id"]
    assert left["generation_config"]["broll"] == {
        "mode": "balanced", "presentation": "overlay",
        "still_vs_video": None, "source_preference": None,
    }
    assert json.loads(json.dumps(first, sort_keys=True))["ai_edit_plan_version"] == "ai-edit-plan-v1"
