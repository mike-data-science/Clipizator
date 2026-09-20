import pytest

from publikclip_pipeline.source_analysis.core import (
    canvas_position,
    classify_text_tracks,
    merge_ocr_detections,
    normalize_bbox,
    normalize_layout_signature,
    relation_to_primary_content,
)
from publikclip_pipeline.source_analysis.stage import SourceAnalysisStage


def detection(identifier, timestamp, text="$3.5M car btw", confidence=0.95, y=0.12):
    return {
        "id": identifier, "timestamp": timestamp, "text": text, "confidence": confidence,
        "bbox": {"x": 0.27, "y": y, "width": 0.39, "height": 0.04},
    }


def test_source_analysis_checkpoint_schema_version_is_current():
    assert SourceAnalysisStage.schema_version == 9


def _track(identifier, text, y, *, start=0.25, end=10.25, x=0.2, width=0.55, height=0.03, hits=8):
    return {
        "id": identifier, "text": text, "start": start, "end": end,
        "duration": end - start, "sample_hits": hits, "confidence": 0.95,
        "bbox": {"x": x, "y": y, "width": width, "height": height},
        "center_x": x + width / 2, "center_y": y + height / 2,
        "relative_size": width * height, "height_ratio": height,
        "raw_detection_ids": [identifier],
    }


def _classify(tracks, duration=12.0):
    return classify_text_tracks(
        tracks, {"x": 0.0, "y": 0.25, "width": 1.0, "height": 0.65}, duration,
        "unrelated spoken transcript", include_blocks=True,
    )


def test_separate_ocr_word_boxes_reconstruct_spacing_from_geometry():
    detections = [
        {"id": f"word-{index}", "timestamp": 0.25, "text": text, "confidence": 0.96,
         "bbox": {"x": x, "y": 0.12, "width": width, "height": 0.03}}
        for index, (text, x, width) in enumerate((("The", 0.10, 0.08), ("Car", 0.20, 0.08), ("Rental", 0.30, 0.13), ("Final", 0.45, 0.10), ("Boss", 0.57, 0.10)))
    ]
    tracks = merge_ocr_detections(detections, sample_interval=1.0, video_duration=2.0, detector="test", detector_version="1")
    assert tracks[0]["text"] == "The Car Rental Final Boss"
    assert tracks[0]["raw_detection_ids"] == [f"word-{index}" for index in range(5)]


def test_existing_ocr_spacing_is_preserved():
    detections = [{
        "id": "line", "timestamp": 0.25, "text": "The Car Rental Final Boss", "confidence": 0.9,
        "bbox": {"x": 0.1, "y": 0.12, "width": 0.55, "height": 0.03},
    }]
    tracks = merge_ocr_detections(detections, sample_interval=1.0, video_duration=2.0, detector="test", detector_version="1")
    assert tracks[0]["text"] == "The Car Rental Final Boss"


def test_observed_spaced_variant_beats_higher_confidence_concatenated_variant():
    detections = [
        {"id": "compact", "timestamp": 0.25, "text": "TheCarRentalFinalBoss", "confidence": 0.99,
         "bbox": {"x": 0.1, "y": 0.12, "width": 0.55, "height": 0.03}},
        {"id": "spaced", "timestamp": 1.25, "text": "The Car Rental Final Boss", "confidence": 0.91,
         "bbox": {"x": 0.1, "y": 0.12, "width": 0.55, "height": 0.03}},
    ]
    tracks = merge_ocr_detections(detections, sample_interval=1.0, video_duration=3.0, detector="test", detector_version="1")
    assert tracks[0]["text"] == "The Car Rental Final Boss"


def test_two_line_persistent_title_becomes_one_candidate_block():
    _, candidates, blocks = _classify([
        _track("top", "delivery team didn't", 0.12),
        _track("bottom", "believe the $4.5M car is his", 0.16, x=0.14, width=0.66),
    ])
    assert len(blocks) == len(candidates) == 1
    assert candidates[0]["text"] == "delivery team didn't believe the $4.5M car is his"
    assert blocks[0]["line_count"] == 2


def test_three_line_title_groups_into_one_block_with_timing_tolerance():
    _, candidates, blocks = _classify([
        _track("one", "First line", 0.10, start=0.25, end=8.25),
        _track("two", "second line", 0.145, start=1.25, end=8.25),
        _track("three", "third line", 0.19, start=0.25, end=7.25),
    ])
    assert len(blocks) == len(candidates) == 1
    assert candidates[0]["text"] == "First line second line third line"
    assert candidates[0]["start"] == 0.25
    assert candidates[0]["end"] == 8.25


def test_persistent_title_lines_allow_one_sparse_sample_edge_mismatch():
    _, candidates, blocks = _classify([
        _track("one", "My boyfriend bought me a", 0.10, start=0.25, end=2.25),
        _track("two", "Koenigsegg as a gift ?", 0.14, start=1.75, end=3.75),
    ], duration=4.0)
    assert len(blocks) == len(candidates) == 1
    assert candidates[0]["text"] == "My boyfriend bought me a Koenigsegg as a gift ?"


def test_dynamic_captions_do_not_become_title_blocks():
    tracks, candidates, blocks = _classify([
        _track("caption-a", "first spoken caption", 0.50, start=0.25, end=1.25, x=0.25, width=0.45, hits=1),
        _track("caption-b", "second spoken caption", 0.50, start=1.25, end=2.25, x=0.25, width=0.45, hits=1),
    ])
    assert [track["classification"] for track in tracks] == ["subtitles/captions", "subtitles/captions"]
    assert blocks == []
    assert candidates == []


def test_spatially_unrelated_lines_do_not_merge():
    _, candidates, blocks = _classify([
        _track("title", "Top title", 0.10),
        _track("label", "Separate lower label", 0.42),
    ])
    assert len(blocks) == len(candidates) == 2
    assert all(block["line_count"] == 1 for block in blocks)


def test_grouped_title_uses_union_bbox_and_source_track_evidence():
    _, candidates, blocks = _classify([
        _track("one", "Top line", 0.10, x=0.25, width=0.35),
        _track("two", "Wider second line", 0.15, x=0.10, width=0.70),
    ])
    block, candidate = blocks[0], candidates[0]
    assert block["bbox"] == {"x": 0.1, "y": 0.1, "width": 0.7, "height": 0.08}
    assert block["content_relation"] == "above_content"
    assert candidate["evidence"]["source_track_ids"] == ["one", "two"]
    assert candidate["provenance"]["source_track_ids"] == ["one", "two"]


def test_bbox_normalization_clamps_to_canvas():
    box = normalize_bbox([[-10, 10], [110, 10], [110, 60], [-10, 60]], 100, 100)
    assert box == {"x": 0.0, "y": 0.1, "width": 1.0, "height": 0.5}


def test_ocr_track_merging_creates_one_persistent_interval():
    tracks = merge_ocr_detections(
        [detection("a", 0.25), detection("b", 1.25, "$3.5M car btw!"), detection("c", 2.25)],
        sample_interval=1.0, video_duration=3.4, detector="test-ocr", detector_version="1",
    )
    assert len(tracks) == 1
    assert tracks[0]["start"] == 0.25
    assert tracks[0]["end"] == 3.25
    assert tracks[0]["duration"] == 3.0
    assert tracks[0]["sample_hits"] == 3
    assert tracks[0]["center_x"] == pytest.approx(0.465)


def test_same_text_after_a_gap_is_not_folded_into_old_track():
    tracks = merge_ocr_detections(
        [detection("a", 0.25), detection("b", 4.25)], sample_interval=1.0,
        video_duration=6.0, detector="test-ocr", detector_version="1",
    )
    assert len(tracks) == 2


def test_similar_but_changed_persistent_title_starts_a_new_track():
    tracks = merge_ocr_detections(
        [detection("a", 0.25, "His post from yesterday"), detection("b", 1.25, "His post today")],
        sample_interval=1.0, video_duration=3.0, detector="test-ocr", detector_version="1",
    )
    assert len(tracks) == 2


def test_title_hook_is_derived_separately_from_raw_track():
    tracks = merge_ocr_detections(
        [detection(str(i), i + 0.25) for i in range(8)], sample_interval=1.0,
        video_duration=9.0, detector="test-ocr", detector_version="1",
    )
    content = {"x": 0.0, "y": 0.22, "width": 1.0, "height": 0.62}
    classified, titles = classify_text_tracks(tracks, content, 9.0, "a spoken transcript without the visual title")
    assert classified[0]["classification"] == "title_hook"
    assert titles[0]["track_id"] == classified[0]["id"]
    assert titles[0]["text"] == "$3.5M car btw"
    assert titles[0]["evidence"]["near_start"] is True
    assert "evidence" not in classified[0]


@pytest.mark.parametrize(
    ("y", "expected"),
    [(0.05, "top"), (0.25, "upper_middle"), (0.45, "center"), (0.65, "lower_middle"), (0.85, "bottom")],
)
def test_canvas_position_bands(y, expected):
    assert canvas_position({"x": 0.1, "y": y, "width": 0.2, "height": 0.02}) == expected


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        ({"x": 0.2, "y": 0.10, "width": 0.5, "height": 0.04}, "above_content"),
        ({"x": 0.2, "y": 0.24, "width": 0.5, "height": 0.04}, "overlay_top"),
        ({"x": 0.2, "y": 0.50, "width": 0.5, "height": 0.04}, "overlay_center"),
        ({"x": 0.2, "y": 0.75, "width": 0.5, "height": 0.04}, "overlay_bottom"),
        ({"x": 0.2, "y": 0.90, "width": 0.5, "height": 0.04}, "below_content"),
    ],
)
def test_text_relation_to_primary_content(box, expected):
    content = {"x": 0.0, "y": 0.20, "width": 1.0, "height": 0.65}
    assert relation_to_primary_content(box, content) == expected


def test_layout_signature_is_normalized_and_descriptive():
    layout = {
        "canvas_aspect_ratio": 0.5624999, "primary_content_aspect_ratio": 0.750001,
        "primary_content_bbox": {"x": 0, "y": 0.2, "width": 1, "height": 0.75},
        "layout_mode": "centered_3:4_in_9:16", "approximate_shape": "rectangle",
        "rounded_corners": False, "split_screen": False, "background_relationship": "letterbox_bars",
    }
    signature = normalize_layout_signature(layout, [{"content_relation": "above_content"}])
    assert signature["version"] == 1
    assert signature["canvas_aspect_ratio"] == 0.5625
    assert signature["title_relationship"] == "above_content"
    assert "template_id" not in signature
