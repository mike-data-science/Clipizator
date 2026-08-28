"""The Moment Analyzer — the core learning pipeline.

Scores every candidate window across all transcripts using cheap text
features, then LLM rubric on top candidates, then similarity and learned
weights to compute a final recommendation score.
"""

from __future__ import annotations

import json
from typing import Callable

from ..scoring import llm as llm_mod
from ..scoring import rubric
from . import hooks
from . import learning
from . import retention_predictor
from . import similarity
from . import store
from . import text_features

ProgressFn = Callable[[float, str], None]


def _extract_windows(segments: list[dict], duration: float) -> list[dict]:
    """Simple sliding window extraction for text since we don't have audio curves here.
    
    Generates ~15-60s windows snapping to segment boundaries.
    """
    windows = []
    n = len(segments)
    for i in range(n):
        start_seg = segments[i]
        start_time = start_seg["start"]
        
        # Look ahead to build windows of varying lengths
        text_parts = [start_seg["text"]]
        words = list(start_seg.get("words", []))
        
        for j in range(i + 1, min(i + 15, n)):
            end_seg = segments[j]
            end_time = end_seg["end"]
            length = end_time - start_time
            
            text_parts.append(end_seg["text"])
            words.extend(end_seg.get("words", []))
            
            # Generate windows between 20s and 65s
            if 20.0 <= length <= 65.0:
                windows.append({
                    "start": start_time,
                    "end": end_time,
                    "text": " ".join(text_parts),
                    "words": list(words),
                })
            elif length > 65.0:
                break
                
    # Basic deduplication (keep longest window for highly overlapping ones)
    windows.sort(key=lambda w: (w["end"] - w["start"]), reverse=True)
    deduped = []
    for w in windows:
        overlap = False
        for d in deduped:
            # IOU > 0.7 means too similar
            inter = min(w["end"], d["end"]) - max(w["start"], d["start"])
            if inter > 0:
                union = max(w["end"], d["end"]) - min(w["start"], d["start"])
                if inter / union > 0.7:
                    overlap = True
                    break
        if not overlap:
            deduped.append(w)
            
    return sorted(deduped, key=lambda w: w["start"])


def prepare_analysis(
    campaign_id: str,
    llm_mode: str = "ollama",
    gemini_model: str = "gemini-1.5-flash-8b",
    progress: ProgressFn | None = None,
    video_urls: list[str] | None = None,
) -> int:
    """Run the full analysis pipeline on all transcripts in a campaign.
    
    Returns number of moments analyzed.
    """
    emit = progress or (lambda f, m: None)
    
    transcripts = store.campaign_transcripts(campaign_id)
    if not transcripts:
        emit(1.0, "No transcripts to analyze. Fetch them first.")
        return 0
        
    if video_urls is not None:
        transcripts = [t for t in transcripts if t.get("video_url") in video_urls]
        if not transcripts:
            emit(1.0, "No transcripts match the selected videos.")
            return 0
            
    emit(0.05, "Extracting candidate windows…")
    all_candidates = []
    for t in transcripts:
        video_url = t["video_url"]
        segs = t["transcript"]
        duration = t["duration_sec"] or (segs[-1]["end"] if segs else 0)
        
        windows = _extract_windows(segs, duration)
        for w in windows:
            w["video_url"] = video_url
            all_candidates.append(w)
            
    if not all_candidates:
        emit(1.0, "No candidates found.")
        return 0
        
    # Phase 1: Cheap features (instant)
    emit(0.1, f"Computing cheap features for {len(all_candidates)} moments…")
    scored_candidates = []
    for c in all_candidates:
        text = c["text"]
        
        # 1. Text Features
        feats = text_features.extract_features(text)
        
        # 2. Hooks
        first_15 = " ".join(text.split()[:15])
        hook_text = hooks.extract_hook_text(text)
        hook_template = hooks.classify_hook_template(first_15)
        h_dens = hooks.hook_density(text)
        
        # 3. Retention
        ret_pred = retention_predictor.predict_retention(text)
        
        # Merge all cheap features
        cheap_score = (
            h_dens["hook_density_score"] * 0.4 + 
            ret_pred["payoff_density"] * 0.4 - 
            ret_pred["drop_off_risk"] * 5.0 +
            (feats["question_density"] / 10.0) * 0.2
        )
        
        result = {
            "video_url": c["video_url"],
            "start_sec": c["start"],
            "end_sec": c["end"],
            "transcript_text": text,
            "word_count": len(text.split()),
            "cheap_score": cheap_score,
            
            # Text feats
            **feats,
            
            # Hook feats
            "hook_text": hook_text,
            "hook_template": hook_template,
            **h_dens,
            
            # Retention feats
            **ret_pred,
        }
        scored_candidates.append(result)
        
    # Filter to top candidates for LLM scoring (cost gating)
    # Take top 15 per video to keep costs low
    scored_candidates.sort(key=lambda x: x["cheap_score"], reverse=True)
    video_counts = {}
    top_candidates = []
    for c in scored_candidates:
        vid = c["video_url"]
        count = video_counts.get(vid, 0)
        if count < 15:
            top_candidates.append(c)
            video_counts[vid] = count + 1
            
    # Save pending tasks to a JSON file for the MCP server
    emit(0.2, f"Prepared {len(top_candidates)} candidates for AI scoring.")
    
    from pathlib import Path
    from . import config
    
    campaign_dir = store.get_campaign_dir(campaign_id)
    pending_dir = config.jobs_dir() / campaign_dir
    pending_dir.mkdir(parents=True, exist_ok=True)
    pending_file = pending_dir / "pending_scoring.json"
    
    pending_file.write_text(json.dumps(top_candidates, indent=2))
    
    emit(1.0, f"Analysis paused: {len(top_candidates)} moments ready for AI scoring via MCP.")
    return len(top_candidates)


def complete_analysis(
    campaign_id: str,
    scored_candidates: list[dict],
    progress: ProgressFn | None = None,
) -> int:
    """Resume the analysis pipeline using the AI-scored candidates.
    
    Returns number of moments analyzed.
    """
    emit = progress or (lambda f, m: None)
    
    if not scored_candidates:
        emit(1.0, "No scored candidates provided.")
        return 0

    emit(0.85, "Computing similarity to proven winners…")
    clips = store.campaign_clips(campaign_id)
    top_clips = [c for c in clips if c.get("views") and c.get("transcript_excerpt")]
    top_clips.sort(key=lambda c: c.get("views_per_subscriber") or c.get("views", 0), reverse=True)
    top_texts = [c["transcript_excerpt"] for c in top_clips[:10]] # Top 10 winners
    
    for c in scored_candidates:
        c["sim_to_top_clips"] = similarity.similarity_score(c["transcript_text"], top_texts)
        
    # Phase 4: Final weights & Active learning
    emit(0.9, "Applying learned campaign weights…")
    weights = learning.compute_feature_weights(campaign_id)
    
    for c in scored_candidates:
        predicted = learning.predict_performance(c, weights)
        c["predicted_virality"] = predicted
        
        # Uncertainty (simple proxy: inverse of similarity to existing clips + low LLM confidence)
        # If we have no top clips, everything is uncertain
        uncertainty = 1.0 - c.get("sim_to_top_clips", 0.0) if top_texts else 0.5
        c["uncertainty"] = round(uncertainty, 3)
        
        # Active learning recommendation score (alpha = 0.7, favor predicted)
        alpha = 0.7
        rec = (alpha * predicted) + ((1 - alpha) * (uncertainty * 10.0))
        c["feedback_adjustment"] = learning.feedback_adjustment(campaign_id, c)
        c["recommendation_score"] = round(max(0.0, min(10.0, rec + c["feedback_adjustment"])), 3)
        
    # Store everything
    emit(0.95, "Saving results…")
    store.store_moments(campaign_id, scored_candidates)
    
    # Cross-reference with existing clips
    store.update_moment_clips(campaign_id)
    
    # Cleanup pending file
    from . import config
    campaign_dir = store.get_campaign_dir(campaign_id)
    pending_file = config.jobs_dir() / campaign_dir / "pending_scoring.json"
    if pending_file.exists():
        pending_file.unlink()
        
    emit(1.0, f"Analysis complete for {len(scored_candidates)} moments.")
    return len(scored_candidates)
