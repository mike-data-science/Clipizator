from publikclip_pipeline.source_analysis.editing import build_source_editing, classify_transition


def _build(**overrides):
    values = {
        "duration": 12.0,
        "scene_times": [0.0, 3.0, 8.0],
        "scene_detector_outcome": "success_with_detections",
        "layout_changes": [],
        "visual_units": [],
        "caption_tracks": [],
        "overlays": [],
        "emphasis_events": [],
        "audio_events": [],
    }
    values.update(overrides)
    return build_source_editing(**values)


def test_scene_boundaries_become_stable_addressable_cuts_and_shots():
    first = _build(scene_times=[8.0, 0.0, 3.0])
    second = _build(scene_times=[0.0, 3.0, 8.0])
    assert [item["id"] for item in first["cuts"]] == [item["id"] for item in second["cuts"]]
    assert first["cuts"][0] == {
        "id": "edit_cut_000003000", "type": "shot_boundary", "timestamp_ms": 3000,
        "start_ms": 3000, "end_ms": 3000, "confidence": 0.8,
        "source": "detector", "status": "raw",
        "evidence": {"artifact": "scenes.json", "detector": "PySceneDetect ContentDetector", "threshold": 27.0},
    }
    assert [(item["id"], item["duration_ms"]) for item in first["shots"]] == [
        ("shot-001", 3000), ("shot-002", 5000), ("shot-003", 4000)
    ]
    assert first["metrics"]["cut_count"] == 2
    assert first["metrics"]["shot_duration_sec"]["median"] == 4.0


def test_transition_classification_does_not_invent_fades_or_dissolves():
    assert classify_transition({
        "confidence": 0.8, "provenance": {"detector": "PySceneDetect ContentDetector"}
    })[0] == "hard_cut"
    transition, confidence, evidence = classify_transition({
        "confidence": 0.9, "provenance": {"detector": "unknown detector"}
    })
    assert transition == "unknown"
    assert confidence <= 0.49
    assert "fade" in evidence["reason"]


def test_reframe_and_likely_zoom_require_strong_non_cut_evidence():
    source = _build(layout_changes=[{
        "start": 5.0, "end": 5.0, "confidence": 0.8,
        "from_bbox": {"x": .1, "y": .1, "width": .8, "height": .8},
        "to_bbox": {"x": 0, "y": 0, "width": 1.0, "height": 1.0},
    }, {
        # Equally large evidence close to a cut is ambiguous and excluded.
        "start": 8.2, "end": 8.2, "confidence": 0.8,
        "from_bbox": {"x": .1, "y": .1, "width": .8, "height": .8},
        "to_bbox": {"x": 0, "y": 0, "width": 1.0, "height": 1.0},
    }])
    assert [item["id"] for item in source["reframes"]] == ["edit_reframe_000005000"]
    assert source["zooms"][0]["subtype"] == "likely_punch_in"
    assert source["zooms"][0]["confidence"] <= 0.72
    assert source["evidence"]["layout_changes_excluded_near_cuts"] == 1


def test_pattern_interrupts_and_cross_modal_references_point_to_existing_ids():
    source = _build(
        scene_times=[0.0, 3.0],
        visual_units=[{"id": "visual-unit-001", "start_ms": 3000, "end_ms": 5000, "visual_type": "b_roll", "confidence": .75}],
        caption_tracks=[{"id": "caption-001", "start_ms": 3150, "end_ms": 4000}],
        audio_events=[{"id": "sfx-001", "start_ms": 2800, "end_ms": 3100}],
    )
    pattern_refs = {ref for item in source["pattern_interrupts"] for ref in item["evidence"]["source_event_ids"]}
    assert "edit_cut_000003000" in pattern_refs
    assert "visual-unit-001" in pattern_refs
    valid_edit_ids = {item["id"] for key in ("cuts", "reframes", "zooms") for item in source[key]}
    valid_targets = {"visual-unit-001", "caption-001", "sfx-001"}
    assert source["cross_modal_relationships"]
    assert len({item["id"] for item in source["cross_modal_relationships"]}) == len(source["cross_modal_relationships"])
    assert all(item["editing_event_id"] in valid_edit_ids for item in source["cross_modal_relationships"])
    assert all(item["target_event_id"] in valid_targets for item in source["cross_modal_relationships"])
    assert all(item["evidence"]["causality_inferred"] is False for item in source["cross_modal_relationships"])


def test_speed_changes_are_unavailable_instead_of_guessed_from_motion():
    source = _build()
    assert source["capabilities"]["speed_change_detection"]["status"] == "unavailable"
    assert "motion" in source["capabilities"]["speed_change_detection"]["reason"]
