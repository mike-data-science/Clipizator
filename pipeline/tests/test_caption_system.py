from publikclip_pipeline.source_analysis.captions import build_caption_system


def track(identifier, text, start, end, *, classification="subtitles/captions", y=.48, ids=None, line_count=1):
    return {
        "id": identifier, "text": text, "start": start, "end": end, "duration": end - start,
        "sample_hits": 1, "confidence": .92, "classification": classification,
        "bbox": {"x": .30, "y": y, "width": .40, "height": .04}, "height_ratio": .04,
        "line_count": line_count, "raw_detection_ids": ids or [identifier], "canvas_position": "center",
    }


def raw(identifier, text, timestamp, *, height=.04):
    return {"id": identifier, "text": text, "timestamp": timestamp, "bbox": {"x": .3, "y": .48, "width": .12, "height": height}}


def style(identifier, *, color=None, confidence=None, size=.04):
    return {"source_detection_id": identifier, "dominant_text_color": color, "color_confidence": confidence, "relative_font_size": size}


def build(tracks, *, titles=None, raw_ocr=None, styles=None, transcript=None, duration=5):
    return build_caption_system(
        tracks=tracks, title_candidates=titles or [], raw_ocr_detections=raw_ocr or [],
        text_style_observations=styles or [], transcript_segments=transcript or [],
        visual_units=[{"id": "visual-unit-001", "start_ms": 0, "end_ms": duration * 1000}], duration=duration,
    )


def test_persistent_title_and_dynamic_captions_coexist_without_merging():
    title = track("title", "Car rental final boss", 0, 5, classification="title_hook", y=.16)
    result = build([title, track("cap-a", "last day", 0, 1), track("cap-b", "with the car", 1, 2)], titles=[{"track_id": "title", "evidence": {"source_track_ids": ["title"]}}])
    assert [item["text"] for item in result["caption_tracks"]] == ["last day", "with the car"]
    assert result["overlays"][0]["role"] == "title_hook"


def test_caption_alignment_and_multiline_caption_are_preserved():
    result = build(
        [track("cap", "you might actually", 1, 2, line_count=2)],
        transcript=[{"start": 1, "end": 2, "text": "You might actually win", "words": [{"word": "might", "start": 1.2, "end": 1.4}]}],
    )
    caption = result["caption_tracks"][0]
    assert caption["line_count"] == 2
    assert caption["transcript_alignment"]["status"] == "aligned"
    assert caption["visual_unit_ids"] == ["visual-unit-001"]


def test_highlighted_keyword_keeps_complete_caption_phrase():
    tracks = [track("cap", "you might actually", 0, 1, ids=["you", "might", "actually"])]
    result = build(
        tracks, raw_ocr=[raw("you", "you", .25), raw("might", "might", .25), raw("actually", "actually", .25)],
        styles=[style("you", color="blue", confidence=.8), style("might", color="yellow", confidence=.8), style("actually", color="blue", confidence=.8)],
    )
    assert result["caption_tracks"][0]["text"] == "you might actually"
    assert result["caption_tracks"][0]["role"] == "emphasized_caption"
    assert result["emphasis_events"][0]["emphasized_text"] == "might"
    assert result["emphasis_events"][0]["emphasis_type"] == "color_highlight"


def test_size_style_change_becomes_emphasis_but_stable_style_does_not():
    changed = build(
        [track("cap", "make this work", 0, 1, ids=["make", "this", "work"])],
        raw_ocr=[raw("make", "make", .25), raw("this", "this", .25, height=.06), raw("work", "work", .25)],
        styles=[style("make", size=.04), style("this", size=.06), style("work", size=.04)],
    )
    stable = build(
        [track("cap", "make this work", 0, 1, ids=["make", "this", "work"])],
        raw_ocr=[raw("make", "make", .25), raw("this", "this", .25), raw("work", "work", .25)],
        styles=[style("make", size=.04), style("this", size=.04), style("work", size=.04)],
    )
    assert changed["emphasis_events"][0]["emphasis_type"] == "size_emphasis"
    assert stable["emphasis_events"] == []


def test_adjacent_same_caption_consolidates_and_metrics_are_temporal():
    result = build([track("a", "keep going", 0, 1), track("b", "keep going", 1, 2)], duration=4)
    assert len(result["caption_tracks"]) == 1
    assert result["caption_tracks"][0]["end_ms"] == 2000
    assert result["caption_metrics"]["caption_coverage_ratio"] == .5
    assert result["caption_metrics"]["caption_event_count"] == 1


def test_cta_and_label_are_not_caption_tracks():
    result = build([track("cta", "Follow for more", 0, 4, classification="CTA"), track("label", "Part 2", 0, 4, classification="label")])
    assert result["caption_tracks"] == []
    assert {item["role"] for item in result["overlays"]} == {"cta", "label"}
