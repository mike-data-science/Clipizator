from publikclip_pipeline.events.intelligence import build_audio_intelligence


def build(*, duration=4.0, speech=None, raw=None, legacy=None, rms=None, flux=None, cuts=None, emphasis=None, visual=None, text=None, available=True):
    samples = int(duration * 10)
    return build_audio_intelligence(
        duration=duration, transcript_segments=speech or [], legacy_events=legacy or [],
        raw_audio_observations=raw or [], curves={"grid_sec": .1, "rms": rms if rms is not None else [.1] * samples, "flux": flux if flux is not None else [0] * samples},
        visual_units=visual or [], shot_cuts=cuts or [], caption_emphasis_events=emphasis or [],
        text_tracks=text or [], panns_intelligence_available=available,
    )


def observation(identifier, kind, start, end, confidence=.8, subtype=None):
    return {
        "id": identifier, "type": kind, "subtype": subtype, "start": start, "end": end,
        "confidence": confidence, "source_detector_labels": [subtype or kind], "model_or_detector": "PANNs",
    }


def test_speech_and_music_create_mixed_temporal_segments():
    result = build(
        speech=[{"start": 1, "end": 3, "text": "spoken phrase"}],
        raw=[observation("music", "music", 0, 4)],
    )
    assert [item["type"] for item in result["audio_segments"]] == ["music", "mixed", "music"]
    assert result["music_segments"][0]["speech_overlap_ratio"] == .5
    assert result["metrics"]["speech_coverage_ratio"] == .5
    assert result["metrics"]["music_coverage_ratio"] == 1.0


def test_music_absent_is_preserved_as_empty_detection():
    result = build(speech=[{"start": 0, "end": 4, "text": "speech"}])
    assert result["music_segments"] == []
    assert result["metrics"]["music_coverage_ratio"] == 0.0
    assert result["evidence"]["panns_intelligence_available"] is True


def test_near_silence_region_is_consolidated():
    rms = [.1] * 10 + [.0001] * 10 + [.1] * 20
    result = build(rms=rms)
    silence = [item for item in result["audio_segments"] if item["type"] == "silence"]
    assert len(silence) == 1
    assert (silence[0]["start_ms"], silence[0]["end_ms"]) == (1000, 2000)
    assert result["metrics"]["silence_ratio"] == .25


def test_short_asr_boundary_gap_is_consolidated_without_bridging_silence():
    result = build(speech=[{"start": 0, "end": 1}, {"start": 1.2, "end": 2}])
    speech = [item for item in result["audio_segments"] if item["type"] == "speech"]
    assert len(speech) == 1
    assert (speech[0]["start_ms"], speech[0]["end_ms"]) == (0, 2000)
    assert speech[0]["evidence"]["bridged_sparse_timing_gap_ms"] == 200


def test_transient_sfx_consolidates_and_weak_event_is_filtered():
    result = build(raw=[
        observation("a", "sfx", 1.0, 1.2, subtype="impact/hit"),
        observation("b", "sfx", 1.35, 1.55, subtype="impact/hit"),
        observation("weak", "sfx", 3, 3.2, confidence=.3, subtype="whoosh"),
    ])
    assert len(result["sfx_events"]) == 1
    assert result["sfx_events"][0]["subtype"] == "impact/hit"
    assert result["sfx_events"][0]["end_ms"] == 1550


def test_probable_ducking_requires_music_and_measured_level_reduction():
    rms = [.2] * 10 + [.1] * 10 + [.2] * 20
    result = build(
        speech=[{"start": 1, "end": 2, "text": "hello"}],
        raw=[observation("music", "music", 0, 4)], rms=rms,
    )
    assert len(result["ducking_events"]) == 1
    assert result["ducking_events"][0]["type"] == "probable_ducking"
    assert result["ducking_events"][0]["before_energy"] > result["ducking_events"][0]["during_energy"]


def test_sfx_alignment_with_cut_and_caption_preserves_delta():
    result = build(
        raw=[observation("impact", "sfx", .9, 1.1, subtype="impact/hit")], cuts=[1.12],
        emphasis=[{"caption_track_id": "caption-1", "start_ms": 1050, "end_ms": 1200}],
        visual=[{"id": "visual-2", "start_ms": 1120, "end_ms": 2000}],
    )
    relations = result["cross_modal_relationships"]
    cut = next(item for item in relations if item["relation_type"] == "aligned_with_cut")
    caption = next(item for item in relations if item["relation_type"] == "aligned_with_caption_emphasis")
    assert cut["delta_ms"] == 120
    assert caption["target_id_reference"] == "caption-1"


def test_dynamics_metrics_and_generated_audio_exclusion():
    rms = [.01, .02, .01, .25] * 10
    flux = [0, 0, 0, 1.0] * 10
    result = build(rms=rms, flux=flux)
    assert result["dynamics"]["dynamic_range_rms"] > 0
    assert result["metrics"]["impact_transient_count"] > 0
    assert result["evidence"]["generated_render_audio_excluded"] is True


def test_applause_legacy_event_maps_to_supported_sfx_only():
    result = build(legacy=[{"type": "applause", "start": 1, "end": 2, "confidence": .8, "sources": ["panns"]}])
    assert result["sfx_events"][0]["subtype"] == "clap/applause"
