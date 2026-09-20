"""Candidate scoring/finalization stage.

Clip Selection v2 candidates are already scored from source evidence and pass
through without new LLM or vision calls. Legacy candidate artifacts retain the
existing T1/T2 scoring path for compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..candidates.windows import detect_candidate_types
from ..jobs.queue import Stage, StageContext, StageError
from ..music import brief as music_brief
from . import constants as constants_mod
from . import frames as frames_mod
from . import llm as llm_mod
from . import rubric

SELECT_COUNT = 12


def _transcript_slice(segments: list[dict], start: float, end: float) -> tuple[str, str]:
    """(speaker-labeled transcript, flat text) for a window."""
    lines: list[str] = []
    flat: list[str] = []
    for seg in segments:
        if seg["end"] < start or seg["start"] > end:
            continue
        words = [w for w in seg.get("words", []) if start <= w["start"] < end]
        if not words:
            continue
        text = " ".join(w["word"] for w in words)
        speaker = seg.get("speaker", 0)
        lines.append(f"S{speaker}: {text}")
        flat.append(text)
    return "\n".join(lines), " ".join(flat)


def _events_in(timeline: list[dict], start: float, end: float, pad: float = 0.0) -> list[dict]:
    return [e for e in timeline if e["end"] >= start - pad and e["start"] <= end + pad]


def _events_desc(events: list[dict]) -> str:
    if not events:
        return "none detected"
    parts = []
    for e in events[:12]:
        parts.append(f"{e['type']} at {e['start'] - 0:.0f}s (conf {e.get('confidence', 0):.2f})")
    return "; ".join(parts)


def _window_pct(values: np.ndarray, grid_sec: float, start: float, end: float) -> float:
    """Percentile rank of this window's mean vs the whole video."""
    if len(values) == 0:
        return 0.0
    a, b = int(start / grid_sec), max(int(start / grid_sec) + 1, int(end / grid_sec))
    window_mean = float(np.mean(values[a : min(b, len(values))])) if a < len(values) else 0.0
    return float(np.mean(values <= window_mean))


DEEP_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "short title idea for this candidate clip"},
        "hook": {"type": "string", "description": "first 1-2 lines that hook the viewer in the first 3 seconds"},
        "story_angle": {"type": "string", "description": "one sentence describing why this moment is compelling"},
        "why_it_hits": {"type": "array", "items": {"type": "string"}, "description": "three short reasons the moment works"},
        "risk_flags": {"type": "array", "items": {"type": "string"}, "description": "possible reasons this could underperform"},
        "recommended_length": {"type": "integer", "description": "target clip length in seconds"},
        "cta": {"type": "string", "description": "optional on-screen CTA, leave blank if none"},
    },
    "required": ["headline", "hook", "story_angle", "why_it_hits", "risk_flags", "recommended_length", "cta"],
}


def _deep_judge_prompt(transcript: str, candidate_types: list[str], context: dict) -> str:
    """Deep pass prompt: only a candidate slice, never the whole source transcript."""
    types = ", ".join(candidate_types) if candidate_types else "story"
    duration = float(context.get("duration", 0) or 0)
    return (
        "You are running a second-pass clip intelligence pass on a single candidate slice from a longer video. "
        "Use ONLY this candidate transcript; never send the full long-form source to the model.\n\n"
        f"Candidate type signals: {types}\n"
        f"Candidate duration: {duration:.0f}s\n\n"
        f"Transcript:\n{transcript}\n\n"
        "Decide how this clip should be framed for short-form performance. "
        "Return concise, structured output for: headline, hook, story angle, why it hits, risk flags, recommended length, and CTA."
    )


def _selection_v2_output(candidates: dict, segments: list[dict]) -> dict:
    clips = []
    for candidate in candidates.get("portfolio") or []:
        start, end = float(candidate["start"]), float(candidate["end"])
        labeled, flat = _transcript_slice(segments, start, end)
        features = candidate.get("features") or {}
        score = float(candidate.get("score") or 0)
        evidence_keys = {
            "source_editing": "source_editing_event_ids", "visual": "visual_unit_ids",
            "captions": "caption_event_ids", "audio": "audio_event_ids",
        }
        fired = [name for name, key in evidence_keys.items() if (candidate.get("evidence") or {}).get(key)]
        clips.append({
            **{key: value for key, value in candidate.items() if key != "source_transcript"},
            "start": start, "end": end, "score": score,
            "platform_scores": {"tiktok": score, "reels": score, "shorts": score},
            "best_platform": "source_material",
            "subscores": {
                key: round(float(value) * 10, 2)
                for key, value in features.items() if isinstance(value, (int, float))
            },
            "adjustments": [], "signals_fired": fired,
            "signals_missing": [name for name in ("visual", "captions", "audio") if name not in fired],
            "confidence": "high" if float(candidate.get("semantic_closure_confidence") or 0) >= .8 else "standard",
            # This is source transcript, not an embellished generated summary.
            "summary": flat[:320], "candidate_types": [candidate.get("origin") or "semantic_moment"],
            "arousal_pct": features.get("delivery_energy") or 0.0, "heatmap_pct": None,
            "curve_score": features.get("moment_strength") or 0.0,
            "channel_scores": {}, "t1_raw": None, "t2": None, "music": None,
            "source_transcript_excerpt": labeled[:1200],
        })
    return {
        "selection_version": "clip-selection-v2", "llm_mode": "selection-v2",
        "model": "story-aware-rules-v2", "llm_generation": {
            "thinking_enabled": None, "generation_options": {}, "call_count": 0,
        },
        "clips": clips, "scored_count": int(candidates.get("post_dedupe_count") or len(candidates.get("candidates") or [])),
        "portfolio_maximum": SELECT_COUNT,
        "quality_bucket_counts": candidates.get("quality_bucket_counts") or {},
        "t2_ran": False, "scoring_config_version": "clip-selection-v2",
        "scoring_constants": {},
    }


class ScoreStage(Stage):
    name = "score"
    schema_version = 2

    def run(self, ctx: StageContext) -> dict:
        prior = ctx.prior or {}
        ingest = prior.get("ingest")
        diarize = prior.get("diarize")
        events = prior.get("events")
        cands = prior.get("candidates")
        if not (ingest and diarize and events and cands):
            raise StageError("Scoring needs ingest + diarize + events + candidates.")

        if cands.get("selection_version") == "clip-selection-v2":
            ctx.emit(0.95, "Finalizing diverse story-aware candidate portfolio…")
            return _selection_v2_output(cands, diarize.get("segments") or [])

        llm_mode = ctx.settings.llm_mode
        client = None
        if llm_mode != "manual":
            try:
                client = llm_mod.make_client(
                    llm_mode,
                    gemini_model=ctx.settings.gemini_model,
                    ollama_model=ctx.settings.ollama_model,
                    ollama_base_url=ctx.settings.ollama_base_url,
                    ollama_num_predict=ctx.settings.ollama_num_predict,
                )
            except llm_mod.LlmError as err:
                raise StageError(str(err)) from err

        segments = diarize["segments"]
        timeline = events["timeline"]
        curves = json.loads(Path(events["curves_path"]).read_text())
        arousal = np.asarray(curves.get("arousal", []), dtype=float)
        arousal_grid = float(curves.get("arousal_grid_sec", 0.5))
        arousal_source = curves.get("arousal_source", "dsp-proxy")
        heatmap = ingest.get("heatmap")
        scene_times = json.loads((ctx.job_dir / "scenes.json").read_text()) if (ctx.job_dir / "scenes.json").exists() else []

        heat_values = None
        if heatmap:
            duration = float(ingest["probe"]["duration_sec"])
            heat_values = np.zeros(int(np.ceil(duration)))
            for seg in heatmap:
                a, b = int(seg["start_time"]), int(np.ceil(seg["end_time"]))
                heat_values[max(0, a) : min(len(heat_values), b)] = seg["value"]

        # Calibrated constants (decision #13): loaded once per run, version
        # stamped into every clip's provenance.
        scoring_config = constants_mod.active()
        cv_constants = scoring_config["constants"]

        candidates = cands["candidates"]
        scored: list[dict] = []
        
        # --- MANUAL MODE PROMPT GENERATION ---
        manual_scores = None
        if llm_mode == "manual":
            scores_path = ctx.job_dir / "manual_scores.json"
            if not scores_path.exists():
                manual_prompts = []
                for i, cand in enumerate(candidates):
                    start, end = cand["start"], cand["end"]
                    labeled, flat = _transcript_slice(segments, start, end)
                    if len(flat.split()) < 20:
                        continue
                    window_events = _events_in(timeline, start, end)
                    context = {
                        "duration": end - start,
                        "events_desc": _events_desc(window_events),
                    }
                    manual_prompts.append({
                        "candidate_index": i,
                        "prompt": rubric.t1_prompt(labeled, context),
                        "schema": rubric.T1_SCHEMA
                    })
                if not manual_prompts:
                    raise StageError("No candidate produced a scoreable transcript.")
                (ctx.job_dir / "manual_prompts.json").write_text(json.dumps(manual_prompts, indent=2))
                raise StageError("Paused for manual scoring. See manual_prompts.json in the job directory. Place your answers in manual_scores.json and Resume.")
            else:
                try:
                    manual_scores_list = json.loads(scores_path.read_text())
                    manual_scores = { int(item["candidate_index"]): item["result"] for item in manual_scores_list }
                except Exception as e:
                    raise StageError(f"Failed to parse manual_scores.json: {e}")

        # --- CANDIDATE SCORING LOOP ---
        for i, cand in enumerate(candidates):
            start, end = cand["start"], cand["end"]
            ctx.emit(i / max(1, len(candidates)) * 0.6, f"Scoring moment {i + 1}/{len(candidates)}…")
            labeled, flat = _transcript_slice(segments, start, end)
            if len(flat.split()) < 20:
                continue
            window_events = _events_in(timeline, start, end)
            near_laughs = [e for e in _events_in(timeline, start, end, pad=3.0) if e["type"] == "laugh"]
            context = {
                "duration": end - start,
                "events_desc": _events_desc(window_events),
            }
            candidate_types = cand.get("candidate_types") or detect_candidate_types(flat)
            try:
                if llm_mode == "manual":
                    if manual_scores and i not in manual_scores:
                        continue
                    t1 = manual_scores[i]
                else:
                    t1 = client.generate_json(rubric.t1_prompt(labeled, context), rubric.T1_SCHEMA)
            except llm_mod.LlmError:
                raise
            except Exception as err:  # noqa: BLE001
                ctx.emit(-1, f"moment {i + 1} scoring failed, skipping: {err}")
                continue

            arousal_pct = _window_pct(arousal, arousal_grid, start, end)
            heatmap_pct = (
                _window_pct(heat_values, 1.0, start, end) if heat_values is not None else None
            )
            sub, adjustments = rubric.cross_validate(
                t1,
                laughs_near=near_laughs,
                arousal_pct=arousal_pct,
                heatmap_pct=heatmap_pct,
                constants=cv_constants,
            )
            scored.append(
                {
                    "start": start,
                    "end": end,
                    "curve_score": cand["curve_score"],
                    "channel_scores": cand["channel_scores"],
                    "candidate_types": candidate_types,
                    "t1_raw": t1,
                    "subscores": {k: round(v, 2) for k, v in sub.items()},
                    "adjustments": adjustments,
                    "arousal_pct": round(arousal_pct, 3),
                    "heatmap_pct": round(heatmap_pct, 3) if heatmap_pct is not None else None,
                    "summary": t1.get("summary", ""),
                    "transcript": labeled,
                }
            )

        if not scored:
            raise StageError("No candidate produced a scoreable transcript.")

        # Rank by best pre-visual platform score, take the finalists.
        def _text_rank(entry: dict) -> float:
            scores, _ = rubric.composite(
                entry["subscores"], entry["curve_score"], entry["heatmap_pct"], None,
                constants=cv_constants,
            )
            return max(scores.values())

        scored.sort(key=_text_rank, reverse=True)
        finalists = scored[:SELECT_COUNT]

        # Second-pass candidate intelligence on finalists only. This keeps the
        # judge slice-scoped and avoids sending the full session transcript to
        # the model. The output is structured metadata used by ranking and UI.
        supports_deep_judge = bool(client and getattr(client, "backend", None) in {"ollama", "gemini"})
        for j, entry in enumerate(finalists):
            if supports_deep_judge:
                try:
                    entry["deep_pass"] = client.generate_json(
                        _deep_judge_prompt(entry["transcript"], entry.get("candidate_types", []), {"duration": entry["end"] - entry["start"]}),
                        DEEP_JUDGE_SCHEMA,
                    )
                except Exception:  # noqa: BLE001
                    entry["deep_pass"] = None
            else:
                entry["deep_pass"] = None

        # T2 visual pass + music brief on finalists only.
        supports_vision = client.backend == "gemini" if client else False
        for j, entry in enumerate(finalists):
            ctx.emit(0.6 + j / max(1, len(finalists)) * 0.35, f"Visual pass {j + 1}/{len(finalists)}…")
            visual = None
            if supports_vision:
                times = frames_mod.sample_times(entry["start"], entry["end"], scene_times)
                media_str = ingest.get("media_path", "").replace("\\", "/")
                media_path = Path(media_str)
                if not media_path.exists():
                    media_path = ctx.job_dir / Path(media_str).name
                    
                imgs = frames_mod.extract_frames(
                    str(media_path), times, ctx.job_dir / "t2frames"
                )
                if imgs:
                    try:
                        visual = client.generate_json(
                            "Rate these frames sampled from one candidate vertical clip. "
                            "Judge visual interest for short-form: expressions, motion, variety.",
                            rubric.T2_SCHEMA,
                            images=imgs,
                        )
                    except Exception:  # noqa: BLE001 — visual is optional evidence
                        visual = None
            entry["t2"] = visual
            if entry.get("deep_pass"):
                entry["headline"] = entry["deep_pass"].get("headline")
                entry["hook_line"] = entry["deep_pass"].get("hook")
                entry["story_angle"] = entry["deep_pass"].get("story_angle")
                entry["why_it_hits"] = entry["deep_pass"].get("why_it_hits")
                entry["risk_flags"] = entry["deep_pass"].get("risk_flags")

            platform_scores, comp_adjustments = rubric.composite(
                entry["subscores"], entry["curve_score"], entry["heatmap_pct"], visual,
                constants=cv_constants,
            )
            entry["adjustments"].extend(comp_adjustments)
            entry["platform_scores"] = platform_scores
            entry["score"] = max(platform_scores.values())
            entry["best_platform"] = max(platform_scores, key=platform_scores.get)

            window_events = _events_in(timeline, entry["start"], entry["end"])
            fired, missing = rubric.signals_summary(
                laughs_near=[e for e in window_events if e["type"] == "laugh"],
                events_in_window=window_events,
                arousal_pct=entry["arousal_pct"],
                heatmap_pct=entry["heatmap_pct"],
                t2_ran=visual is not None,
                arousal_source=arousal_source,
            )
            entry["signals_fired"] = fired
            entry["signals_missing"] = missing
            entry["confidence"] = "standard" if (client and client.backend == "gemini") else "local-estimate"

            prior_mood = music_brief.mood_prior(window_events, entry["arousal_pct"])
            if client is None:
                entry["music"] = None
            else:
                try:
                    entry["music"] = client.generate_json(
                        music_brief.music_prompt(
                            entry["summary"], entry["transcript"], prior_mood, _events_desc(window_events)
                        ),
                        music_brief.MUSIC_SCHEMA,
                    )
                    entry["music"]["mood_prior"] = prior_mood
                except Exception:  # noqa: BLE001 — a clip without a music brief still ships
                    entry["music"] = None

        finalists.sort(key=lambda e: e["score"], reverse=True)
        for entry in finalists:
            entry.pop("transcript", None)  # bulky; review UI re-slices from diarize

        if client and hasattr(client, "unload"):
            client.unload()

        return {
            "llm_mode": llm_mode,
            "model": client.model if client else "manual",
            "llm_generation": client.generation_metadata() if client else {
                "thinking_enabled": None,
                "generation_options": {},
            },
            "clips": finalists,
            "scored_count": len(scored),
            "t2_ran": supports_vision,
            "scoring_config_version": scoring_config["version"],
            "scoring_constants": cv_constants,
        }
