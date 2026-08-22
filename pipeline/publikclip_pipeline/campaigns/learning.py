"""Feature weight learning and cross-campaign transfer.

Learns which text features and LLM scores actually predict views
by correlating them with real analytics.
"""

from __future__ import annotations

import json
from . import store

# Global default weights (fallback before campaign has enough data)
DEFAULT_WEIGHTS = {
    # Text features (instant)
    "specificity_score": 0.05,
    "question_density": 0.05,
    "first_person_ratio": 0.05,
    
    # Hook features (instant)
    "hook_density_score": 0.15,
    
    # Retention features (instant)
    "payoff_density": 0.15,
    "drop_off_risk": -0.15, # Penalty
    
    # LLM scores (expensive, top candidates only)
    "llm_hook_score": 0.20,
    "llm_funniness": 0.10,
    "llm_shock": 0.10,
    "llm_curiosity_gap": 0.10,
    "llm_value_score": 0.10,
    
    # Similarity
    "sim_to_top_clips": 0.20,
}


def _normalize_views(clips: list[dict]) -> dict[int, float]:
    """Normalize views to 0.0 - 1.0 scale, handling outliers via percentiles."""
    if not clips:
        return {}
        
    # Prefer views_per_subscriber, fallback to raw views
    scores = []
    for c in clips:
        if c.get("views_per_subscriber") is not None:
            scores.append(c["views_per_subscriber"])
        elif c.get("views") is not None:
            scores.append(float(c["views"]))
        else:
            scores.append(0.0)
            
    if not any(s > 0 for s in scores):
        return {c["id"]: 0.0 for c in clips}
        
    # Sort to find 90th percentile to cap outliers
    sorted_scores = sorted(scores)
    p90_idx = int(len(sorted_scores) * 0.9)
    p90 = sorted_scores[p90_idx] if p90_idx < len(sorted_scores) else sorted_scores[-1]
    
    if p90 <= 0:
        p90 = max(scores) # Fallback if p90 is 0
        
    result = {}
    for clip, score in zip(clips, scores):
        norm = min(1.0, score / p90) if p90 > 0 else 0.0
        result[clip["id"]] = norm
        
    return result


def compute_feature_weights(campaign_id: str) -> dict[str, float]:
    """Compute correlation between features and actual views in this campaign.
    
    If the campaign has < 10 clips with analytics, returns global defaults.
    Otherwise, returns weights fitted to this campaign's data.
    """
    # 1. Get clips with analytics
    clips = store.campaign_clips(campaign_id)
    clips_with_views = [c for c in clips if c.get("views") is not None and c.get("start_sec") is not None]
    
    if len(clips_with_views) < 10:
        return DEFAULT_WEIGHTS
        
    # 2. Get moments for these clips
    moments = store.campaign_moments(campaign_id, limit=1000)
    
    # 3. Match moments to normalized views
    norm_views = _normalize_views(clips_with_views)
    
    # Feature matrices
    features = list(DEFAULT_WEIGHTS.keys())
    X = [] # List of feature lists
    Y = [] # List of normalized views
    
    for clip in clips_with_views:
        # Find matching moment
        for m in moments:
            if m["video_url"] == clip["source_video_url"] and \
               m["start_sec"] <= clip["start_sec"] and m["end_sec"] >= clip["end_sec"]:
                
                # Extract features
                x_row = []
                for f in features:
                    val = m.get(f)
                    if val is None:
                        # Fallback for missing LLM scores
                        val = clip.get(f.replace("llm_", "") + "_score") or 0.0
                    x_row.append(float(val))
                    
                X.append(x_row)
                Y.append(norm_views[clip["id"]])
                break
                
    if len(X) < 10:
        return DEFAULT_WEIGHTS
        
    # 4. Very simple correlation-based weights (since we don't have sklearn)
    # Weight = correlation with Y
    weights = {}
    for i, f_name in enumerate(features):
        x_col = [row[i] for row in X]
        
        # Mean
        x_mean = sum(x_col) / len(x_col)
        y_mean = sum(Y) / len(Y)
        
        # Covariance & Variance
        cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_col, Y))
        var_x = sum((x - x_mean)**2 for x in x_col)
        var_y = sum((y - y_mean)**2 for y in Y)
        
        # Correlation
        corr = 0.0
        if var_x > 0 and var_y > 0:
            import math
            corr = cov / math.sqrt(var_x * var_y)
            
        weights[f_name] = corr
        
    # 5. Normalize weights (abs sum to 1.0)
    # For drop_off_risk, we expect negative correlation.
    abs_sum = sum(abs(w) for w in weights.values())
    if abs_sum > 0:
        weights = {k: v / abs_sum for k, v in weights.items()}
    else:
        weights = DEFAULT_WEIGHTS
        
    return weights


def predict_performance(features: dict, weights: dict[str, float]) -> float:
    """Predict performance score using learned weights.
    
    Returns a score roughly 0.0 to 10.0.
    """
    score = 0.0
    
    for f_name, weight in weights.items():
        val = features.get(f_name) or 0.0
        
        # Scale values roughly to 0-10 before applying weight
        if f_name == "specificity_score" or f_name == "question_density" or f_name == "first_person_ratio":
            # These are percentages (0-100), scale to 0-10
            val = min(10.0, val / 10.0)
        elif f_name == "drop_off_risk" or f_name == "payoff_density" or f_name == "sim_to_top_clips":
            # These are 0.0-1.0, scale to 0-10
            val = val * 10.0
        # The others (llm scores, hook_density) are already 0-10
        
        score += val * weight
        
    # Ensure it's bounded nicely
    return round(max(0.0, min(10.0, score)), 2)
