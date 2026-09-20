"""Canonical Video DNA v2 normalization without adding detector claims."""

from __future__ import annotations

from typing import Any

from .analysis_runs import ANALYZER_VERSION, VIDEO_DNA_SCHEMA_VERSION


TOP_LEVEL_SECTIONS = (
    "source", "provenance", "speech_story", "text_system", "layout", "visual",
    "source_editing", "audio", "performance", "uncertainty", "human_corrections",
)


def feature(
    value: Any, *, source: str, status: str, confidence: float | None = None,
    evidence: dict[str, Any] | None = None, model_or_detector: str | None = None,
) -> dict[str, Any]:
    return {
        "source": source,
        "confidence": confidence,
        "status": status,
        "evidence": evidence or {},
        "model_or_detector": model_or_detector,
        "value": value,
    }


def unavailable(reason: str) -> dict[str, Any]:
    return feature(None, source="derived", status="unavailable", evidence={"reason": reason})


def _timed_refs(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [
        {key: item.get(key) for key in ("start", "end") if item.get(key) is not None}
        for item in items if isinstance(item, dict)
    ]


def normalize_video_dna(
    *, source: dict[str, Any], transcript: dict[str, Any], speakers: dict[str, Any],
    scenes: dict[str, Any], source_analysis: dict[str, Any], audio: dict[str, Any],
    performance: dict[str, Any], provenance: dict[str, Any], corrections: list[dict[str, Any]],
    analysis_run: dict[str, Any],
) -> dict[str, Any]:
    segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []
    turns = speakers.get("turns") if isinstance(speakers.get("turns"), list) else []
    title_hooks = source_analysis.get("title_hook_candidates") or []
    text_blocks = source_analysis.get("text_blocks") or []
    caption_system = source_analysis.get("caption_system") or {}
    layout_value = source_analysis.get("source_layout")
    visual_observations = source_analysis.get("visual_observations") or []
    visual_understanding = source_analysis.get("visual_understanding") or {}
    audio_intelligence = audio.get("audio_intelligence") or {}
    editing = source_analysis.get("source_editing") or source_analysis.get("source_editing_evidence") or {}
    story = source_analysis.get("story_semantics") or {}
    events = audio.get("events") if isinstance(audio.get("events"), list) else []
    source_provenance = source_analysis.get("provenance") or {}
    run_id = analysis_run.get("analysis_run_id")
    source_analysis_available = bool(source_analysis.get("available"))
    scene_evidence_available = bool(scenes.get("timestamps")) or scenes.get("detector_outcome") is not None

    source_section = {
        "platform": source.get("platform"),
        "external_video_id": source.get("external_video_id"),
        "canonical_url": source.get("canonical_url") or source.get("source_url"),
        "creator": source.get("creator"),
        "creator_source_id": source.get("creator_source_id"),
        "creator_video_id": source.get("creator_video_id"),
        "title": source.get("title"),
        "duration_sec": source.get("duration_sec") or (source.get("probe") or {}).get("duration_sec"),
        "content_type": source.get("content_type"),
        "tab_origin": source.get("tab_origin"),
        "source_type": source.get("type"),
    }
    components = {
        "speech_to_text": {"model": transcript.get("model"), "device": provenance.get("asr_device")},
        "diarization": {"device": provenance.get("diarization_device")},
        "audio_events": {"device": provenance.get("event_device"), "arousal_source": audio.get("arousal_source")},
        "source_analysis": source_provenance,
        "llm": {"mode": provenance.get("llm_mode"), "model": provenance.get("model")},
    }
    semantic_visual_available = bool((visual_understanding.get("evidence") or {}).get("raw_semantic_observation_count"))
    captions_available = bool(caption_system.get("caption_tracks"))
    audio_evidence = audio_intelligence.get("evidence") or {}
    panns_audio_available = bool(audio_evidence.get("panns_intelligence_available"))
    audio_dynamics_available = bool(audio_evidence.get("rms_sample_count"))
    cross_modal_available = panns_audio_available and bool(
        visual_understanding.get("visual_units") or caption_system.get("emphasis_events") or editing.get("shot_cuts")
    )
    capabilities = {
        "b_roll_detection": (
            {"status": "experimental", "reason": "Sparse shot-level multi-signal classification is available."}
            if semantic_visual_available else
            {"status": "unavailable", "reason": "Sparse semantic frame evidence is unavailable for this run."}
        ),
        "object_action_understanding": (
            {"status": "limited", "reason": "Sparse CLIP zero-shot concepts support broad objects, scenes, and actions only."}
            if semantic_visual_available else
            {"status": "unavailable", "reason": "Sparse semantic frame evidence is unavailable for this run."}
        ),
        "caption_style_analysis": (
            {"status": "experimental", "reason": "Sparse OCR tracks and conservative frame-crop style evidence are available."}
            if captions_available else
            {"status": "unavailable", "reason": "No caption tracks with usable OCR evidence are available."}
        ),
        "music_segmentation": (
            {"status": "experimental", "reason": "Conservative PANNs music-presence spans are available."}
            if panns_audio_available else {"status": "unavailable", "reason": "The retained PANNs music channel is unavailable for this run."}
        ),
        "sound_effect_detection": (
            {"status": "limited", "reason": "A high-precision subset of supported AudioSet SFX labels is available."}
            if panns_audio_available else {"status": "unavailable", "reason": "Generalized SFX evidence is unavailable for this run."}
        ),
        "audio_dynamics": (
            {"status": "available", "reason": "Librosa RMS and spectral-flux source curves are available."}
            if audio_dynamics_available else {"status": "unavailable", "reason": "Source-audio signal curves are unavailable."}
        ),
        "cross_modal_audio_alignment": (
            {"status": "experimental", "reason": "SFX proximity to visual and caption events is derived with explicit deltas."}
            if cross_modal_available else {"status": "unavailable", "reason": "Required SFX and visual/text timing evidence is unavailable."}
        ),
        "story_beat_detection": (
            {"status": "experimental", "reason": "Timestamped semantic units and conservative idea boundaries are available."}
            if story.get("semantic_units") else
            {"status": "unavailable", "reason": "No timestamped semantic transcript evidence is available."}
        ),
        "source_speed_change_detection": (editing.get("capabilities") or {}).get("speed_change_detection") or {
            "status": "unavailable", "reason": "No source playback-rate evidence is available."
        },
    }
    correction_items = corrections if isinstance(corrections, list) else []
    return {
        "source": source_section,
        "provenance": {
            "analysis_run_id": run_id,
            "job_id": analysis_run.get("job_id"),
            "analyzer_version": analysis_run.get("analyzer_version") or ANALYZER_VERSION,
            "schema_version": VIDEO_DNA_SCHEMA_VERSION,
            "pipeline_version": analysis_run.get("pipeline_version"),
            "config_fingerprint": analysis_run.get("config_fingerprint"),
            "components": components,
        },
        "speech_story": {
            "schema_version": story.get("schema_version", 1),
            "status": story.get("status") or "unavailable",
            "transcript": feature(
                {"language": transcript.get("language"), "word_count": transcript.get("word_count")},
                source="detector", status="raw" if segments or transcript.get("model") else "unavailable",
                evidence={"artifact": "asr.json", "transcript_refs": _timed_refs(segments)},
                model_or_detector=transcript.get("model"),
            ),
            "speaker_structure": feature(
                {"speaker_count": speakers.get("count")}, source="detector",
                status="interpreted" if turns or speakers.get("count") is not None else "unavailable",
                evidence={"artifact": "diarize.json", "turn_refs": _timed_refs(turns)},
            ),
            "semantic_units": feature(
                story.get("semantic_units") or [],
                source="llm" if (story.get("provenance") or {}).get("llm_used") and (story.get("provenance") or {}).get("llm_failure_count", 0) < (story.get("provenance") or {}).get("llm_call_count", 0) else "derived",
                status="interpreted" if story.get("semantic_units") else "unavailable",
                evidence={"artifact": "source_analysis.json", "source_editing_ids_reused": (story.get("evidence") or {}).get("source_editing_ids_reused", [])},
                model_or_detector=(story.get("provenance") or {}).get("method"),
            ),
            "story_segments": feature(
                story.get("story_segments") or [], source="derived",
                status="interpreted" if story.get("story_segments") else "unavailable",
                evidence={"artifact": "source_analysis.json", "semantic_unit_ids": [unit.get("semantic_unit_id") for unit in story.get("semantic_units") or []]},
                model_or_detector="semantic-story-boundary-rules-v1",
            ),
            "story_beats": feature(
                story.get("story_segments") or [], source="derived",
                status="interpreted" if story.get("story_segments") else "unavailable",
                evidence={"alias_of": "story_segments"}, model_or_detector="semantic-story-boundary-rules-v1",
            ),
            "hooks": feature(
                story.get("hooks") or [], source="derived",
                status="interpreted" if story.get("hooks") else "unavailable",
                evidence={"effectiveness_assessed": False}, model_or_detector="semantic-story-hybrid-v1",
            ),
            "speech_signals": feature(
                story.get("speech_signals") or [], source="derived",
                status="interpreted" if story.get("semantic_units") else "unavailable",
                evidence={"artifact": "source_analysis.json"}, model_or_detector="semantic-story-hybrid-v1",
            ),
            "payoff_relationships": feature(
                story.get("payoff_relationships") or [], source="derived",
                status="interpreted" if story.get("payoff_relationships") else "unavailable",
                evidence={"artifact": "source_analysis.json", "causality_inferred": False},
                model_or_detector="semantic-story-hybrid-v1",
            ),
            "structural_metrics": story.get("structural_metrics") or {},
            "evidence": story.get("evidence") or {},
            "provenance": story.get("provenance") or {},
            "limitations": story.get("limitations") or [],
        },
        "text_system": {
            "title_hooks": feature(
                title_hooks, source="derived", status="interpreted" if source_analysis_available else "unavailable",
                confidence=title_hooks[0].get("confidence") if title_hooks else None,
                evidence={"artifact": "source_analysis.json", "track_ids": [item.get("track_id") for item in title_hooks]},
                model_or_detector="title-hook-text-block-rules/v2",
            ),
            "text_blocks": feature(
                text_blocks, source="derived", status="interpreted" if source_analysis_available else "unavailable",
                evidence={"artifact": "source_analysis.json", "track_ids": [track for block in text_blocks for track in block.get("source_track_ids", [])]},
                model_or_detector="RapidOCR/PP-OCRv3 + text-block-rules/v2",
            ),
            "caption_tracks": feature(
                caption_system.get("caption_tracks") or [], source="derived",
                status="interpreted" if captions_available else "unavailable",
                evidence={"artifact": "source_analysis.json", "raw_ocr_detection_count": (caption_system.get("evidence") or {}).get("raw_ocr_detection_count")},
                model_or_detector=(caption_system.get("provenance") or {}).get("method"),
            ),
            "emphasis_events": feature(
                caption_system.get("emphasis_events") or [], source="derived",
                status="interpreted" if captions_available else "unavailable",
                evidence={"artifact": "source_analysis.json", "caption_track_ids": [item.get("caption_track_id") for item in caption_system.get("emphasis_events") or []]},
                model_or_detector=(caption_system.get("provenance") or {}).get("method"),
            ),
            "overlays": caption_system.get("overlays") or [],
            "caption_metrics": caption_system.get("caption_metrics") or {},
            "caption_evidence": caption_system.get("evidence") or {},
            "caption_provenance": caption_system.get("provenance") or {},
            "caption_limitations": caption_system.get("limitations") or [],
            "caption_style": capabilities["caption_style_analysis"],
        },
        "layout": {
            "source_layout": feature(
                layout_value, source="derived", status="interpreted" if layout_value else "unavailable",
                confidence=layout_value.get("confidence") if isinstance(layout_value, dict) else None,
                evidence={"artifact": "source_analysis.json", "layout_signature": source_analysis.get("layout_signature")},
                model_or_detector=((layout_value or {}).get("provenance") or {}).get("detector") if isinstance(layout_value, dict) else None,
            ),
        },
        "visual": {
            "status": visual_understanding.get("status") or "unavailable",
            "visual_units": feature(
                visual_understanding.get("visual_units") or [], source="derived",
                status="interpreted" if visual_understanding else "unavailable",
                evidence={
                    "artifact": "source_analysis.json",
                    "source_shot_ids": (visual_understanding.get("evidence") or {}).get("source_shot_ids", []),
                    "generated_camera_data_excluded": True,
                },
                model_or_detector=(visual_understanding.get("provenance") or {}).get("method"),
            ),
            "b_roll_segments": feature(
                visual_understanding.get("b_roll_segments") or [], source="derived",
                status="interpreted" if semantic_visual_available else "unavailable",
                evidence={"artifact": "source_analysis.json", "visual_unit_ids": [
                    unit.get("id") for unit in visual_understanding.get("visual_units") or []
                    if unit.get("visual_type") == "b_roll"
                ]},
                model_or_detector=(visual_understanding.get("provenance") or {}).get("method"),
            ),
            "objects_entities_summary": visual_understanding.get("objects_entities_summary") or [],
            "scene_environment_summary": visual_understanding.get("scene_environment_summary") or [],
            "actions_summary": visual_understanding.get("actions_summary") or [],
            "ratios_statistics": visual_understanding.get("metrics") or {},
            "evidence": visual_understanding.get("evidence") or {},
            "provenance": visual_understanding.get("provenance") or {},
            "limitations": visual_understanding.get("limitations") or [],
            "observations": feature(
                visual_observations, source="detector", status="interpreted" if source_analysis_available else "unavailable",
                evidence={"artifact": "source_analysis.json", "timestamps": _timed_refs(visual_observations)},
                model_or_detector="UltraFace-RFB-320",
            ),
            "scene_markers": feature(
                scenes.get("timestamps") or [], source="detector",
                status="raw" if scene_evidence_available and scenes.get("detector_outcome") != "unavailable" else "unavailable",
                evidence={"artifact": "scenes.json", "detector_outcome": scenes.get("detector_outcome")},
                model_or_detector="PySceneDetect ContentDetector",
            ),
            "object_action_understanding": capabilities["object_action_understanding"],
            "b_roll_detection": capabilities["b_roll_detection"],
        },
        "source_editing": {
            "schema_version": editing.get("schema_version", 1),
            "status": editing.get("status") or ("available" if source_analysis_available else "unavailable"),
            "cuts": feature(
                editing.get("cuts") or editing.get("shot_cuts") or [], source="detector",
                status="raw" if source_analysis_available else "unavailable",
                evidence={"artifact": "source_analysis.json", "generated_camera_data_excluded": True},
                model_or_detector="PySceneDetect ContentDetector",
            ),
            "shots": feature(
                editing.get("shots") or [], source="derived",
                status="interpreted" if source_analysis_available else "unavailable",
                evidence={"artifact": "source_analysis.json", "cut_event_ids": [item.get("id") for item in editing.get("cuts") or []]},
                model_or_detector="source-editing-rules-v1",
            ),
            "transitions": feature(
                editing.get("transitions") or [], source="derived",
                status="interpreted" if source_analysis_available else "unavailable",
                evidence={"artifact": "source_analysis.json"}, model_or_detector="source-editing-rules-v1",
            ),
            "reframes": feature(
                editing.get("reframes") or editing.get("layout_changes") or [], source="derived",
                status="interpreted" if source_analysis_available else "unavailable",
                evidence={"artifact": "source_analysis.json", "generated_camera_data_excluded": True},
                model_or_detector="opencv-row-column-content-bounds",
            ),
            "zooms": feature(
                editing.get("zooms") or [], source="derived",
                status="interpreted" if editing.get("zooms") else "unavailable",
                evidence={"artifact": "source_analysis.json", "classification": "likely_not_confirmed"},
                model_or_detector="source-editing-rules-v1",
            ),
            "pattern_interrupts": feature(
                editing.get("pattern_interrupts") or [], source="derived",
                status="interpreted" if source_analysis_available else "unavailable",
                evidence={"artifact": "source_analysis.json", "retention_or_intent_inferred": False},
                model_or_detector="source-editing-rules-v1",
            ),
            "cross_modal_relationships": editing.get("cross_modal_relationships") or [],
            "metrics": editing.get("metrics") or {
                "visual_change_cadence_per_minute": editing.get("visual_change_density_per_minute")
            },
            "capabilities": editing.get("capabilities") or {
                "speed_change_detection": capabilities["source_speed_change_detection"]
            },
            "evidence": {**(editing.get("evidence") or {}), "generated_camera_data_excluded": True},
            "provenance": editing.get("provenance") or {},
            "limitations": editing.get("limitations") or [],
        },
        "audio": {
            "status": audio_intelligence.get("status") or "unavailable",
            "audio_segments": feature(
                audio_intelligence.get("audio_segments") or [], source="derived",
                status="interpreted" if audio_intelligence else "unavailable",
                evidence={"artifact": "source_analysis.json", "generated_render_audio_excluded": True},
                model_or_detector=(audio_intelligence.get("provenance") or {}).get("method"),
            ),
            "music_segments": feature(
                audio_intelligence.get("music_segments") or [], source="derived",
                status="interpreted" if panns_audio_available else "unavailable",
                evidence={"artifact": "events.json", "raw_audio_observation_count": audio_evidence.get("raw_audio_observation_count")},
                model_or_detector=(audio_intelligence.get("provenance") or {}).get("event_model"),
            ),
            "sfx_events": feature(
                audio_intelligence.get("sfx_events") or [], source="derived",
                status="interpreted" if panns_audio_available else "unavailable",
                evidence={"artifact": "events.json", "legacy_event_count": audio_evidence.get("legacy_event_count")},
                model_or_detector=(audio_intelligence.get("provenance") or {}).get("event_model"),
            ),
            "dynamics": audio_intelligence.get("dynamics") or {"status": "unavailable"},
            "ducking_events": audio_intelligence.get("ducking_events") or [],
            "cross_modal_relationships": audio_intelligence.get("cross_modal_relationships") or [],
            "metrics": audio_intelligence.get("metrics") or {},
            "provenance": audio_intelligence.get("provenance") or {},
            "evidence": audio_evidence,
            "limitations": audio_intelligence.get("limitations") or [],
            "events": feature(
                events, source="detector", status="raw" if events or audio.get("arousal_source") else "unavailable",
                evidence={"artifact": "events.json", "timestamps": _timed_refs(events)},
                model_or_detector=audio.get("arousal_source"),
            ),
            "signal_summaries": audio.get("curves") or [],
            "music_segmentation": capabilities["music_segmentation"],
            "sound_effect_detection": capabilities["sound_effect_detection"],
            "audio_dynamics": capabilities["audio_dynamics"],
            "cross_modal_audio_alignment": capabilities["cross_modal_audio_alignment"],
        },
        "performance": {
            "catalog_metrics": feature(
                performance.get("metrics") or {}, source="derived",
                status="raw" if performance.get("metrics") else "unavailable",
                evidence={"origin": performance.get("origin")},
            ),
            "classification": feature(
                performance.get("classification"), source="human" if performance.get("manual") else "derived",
                status="corrected" if performance.get("manual") else ("interpreted" if performance.get("classification") else "unavailable"),
                evidence={"metric": performance.get("metric")},
            ),
        },
        "uncertainty": {"capabilities": capabilities},
        "human_corrections": {
            "status": "corrected" if correction_items else "unavailable",
            "items": correction_items,
            "raw_outputs_preserved": True,
        },
    }
