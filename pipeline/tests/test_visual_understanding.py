from publikclip_pipeline.source_analysis.visual import build_visual_understanding


LAYOUT = {"layout_mode": "full_canvas"}


def face(timestamp, area=0.08):
    side = area ** 0.5
    return {
        "timestamp": timestamp, "face_count": 1,
        "faces": [{"bbox": {"x": 0.4, "y": 0.2, "width": side, "height": side}, "confidence": 0.95}],
    }


def no_face(timestamp):
    return {"timestamp": timestamp, "face_count": 0, "faces": []}


def semantic(timestamp, *, obj=None, environment=None, action=None, style="natural camera footage", change=0.08):
    item = {
        "timestamp": timestamp, "frame_ref": f"source@{timestamp:.3f}s",
        "frame_change_from_previous": change,
        "objects": [], "environments": [], "actions": [], "visual_style": [],
    }
    if obj:
        item["objects"] = [{"label": obj, "confidence": 0.72}]
    if environment:
        item["environments"] = [{"label": environment, "confidence": 0.66}]
    if action:
        item["actions"] = [{"label": action, "confidence": 0.7}]
    if style:
        item["visual_style"] = [{"label": style, "confidence": 0.65}]
    return item


def analyze(*, duration=4.0, scenes=None, faces=None, semantics=None, transcript=None, ocr=None):
    return build_visual_understanding(
        duration=duration, scene_times=scenes or [], raw_faces=faces or [],
        semantic_observations=semantics or [], raw_ocr=ocr or [],
        transcript_segments=transcript or [], layout=LAYOUT,
        semantic_runtime={"sampled_frames": len(semantics or []), "inference_batches": 1},
    )


def test_obvious_persistent_face_sequence_is_talking_head():
    result = analyze(
        faces=[face(0.25), face(1.25), face(2.25), face(3.25)],
        semantics=[semantic(1.25, action="person speaking to camera"), semantic(2.25, action="person speaking to camera")],
        transcript=[{"start": 0, "end": 4, "text": "I want to explain this"}],
    )
    unit = result["visual_units"][0]
    assert unit["visual_type"] == "talking_head"
    assert unit["relation_to_speech"]["type"] == "speaker_visible"


def test_no_face_semantic_cutaway_is_not_broll_without_speech_support():
    result = analyze(
        scenes=[2.0], faces=[face(0.25), face(1.25), no_face(2.25), no_face(3.25)],
        semantics=[semantic(2.25, obj="car"), semantic(3.25, obj="car")],
        transcript=[{"start": 2, "end": 4, "text": "This is completely unrelated"}],
    )
    assert result["visual_units"][-1]["visual_type"] != "b_roll"
    assert result["b_roll_segments"] == []


def test_clear_semantic_cutaway_matching_transcript_is_broll():
    result = analyze(
        scenes=[2.0], faces=[face(0.25), face(1.25), no_face(2.25), no_face(3.25)],
        semantics=[semantic(2.25, obj="car"), semantic(3.25, obj="car")],
        transcript=[{"start": 2, "end": 4, "text": "The Koenigsegg car was a gift"}],
    )
    unit = result["visual_units"][-1]
    assert unit["visual_type"] == "b_roll"
    assert unit["relation_to_speech"]["type"] == "illustrates_speech"
    assert result["b_roll_segments"][0]["visual_subject"] == "car"


def test_static_interface_with_ocr_support_is_screenshot():
    ocr = [
        {"timestamp": timestamp, "bbox": {"width": 0.2, "height": 0.03}}
        for timestamp in (0.25, 0.25, 1.25, 1.25)
    ]
    result = analyze(
        duration=2.0, faces=[no_face(0.25), no_face(1.25)], ocr=ocr,
        semantics=[
            semantic(0.25, obj="social media post", environment="computer screen or interface", style="static screenshot", change=None),
            semantic(1.25, obj="social media post", environment="computer screen or interface", style="static screenshot", change=0.01),
        ],
    )
    assert result["visual_units"][0]["visual_type"] == "screenshot"


def test_insufficient_evidence_stays_uncertain():
    result = analyze(faces=[no_face(0.25), no_face(1.25)])
    assert result["visual_units"][0]["visual_type"] == "uncertain"
    assert result["visual_units"][0]["uncertainty"]["status"] == "uncertain"


def test_adjacent_compatible_shots_are_temporally_consolidated():
    result = analyze(
        scenes=[2.0], faces=[face(0.25), face(1.25), face(2.25), face(3.25)],
        transcript=[{"start": 0, "end": 4, "text": "continuous explanation"}],
    )
    assert len(result["visual_units"]) == 1
    assert result["visual_units"][0]["source_shot_ids"] == ["shot-001", "shot-002"]


def test_transcript_overlap_and_broll_ratio_are_temporal():
    result = analyze(
        scenes=[2.0], faces=[face(0.25), face(1.25), no_face(2.25), no_face(3.25)],
        semantics=[semantic(2.25, obj="phone"), semantic(3.25, obj="phone")],
        transcript=[{"start": 2.1, "end": 3.8, "text": "I checked the phone"}],
    )
    b_roll = result["b_roll_segments"][0]
    assert b_roll["related_transcript_span"][0]["text"] == "I checked the phone"
    assert result["metrics"]["talking_head_ratio"] == 0.5
    assert result["metrics"]["b_roll_ratio"] == 0.5
    assert result["metrics"]["shot_count"] == 2


def test_generated_camera_data_is_explicitly_excluded():
    result = analyze(faces=[face(0.25), face(1.25)])
    assert result["evidence"]["generated_camera_data_excluded"] is True
    assert "camera" not in result["provenance"]
