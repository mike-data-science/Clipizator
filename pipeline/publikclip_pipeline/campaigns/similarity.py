"""Embedding-based moment similarity (TF-IDF).

Finds unclipped moments that are textually similar to proven winners.
Uses TF-IDF which is lightweight, has no API cost, and works well for
topic/keyword matching.
"""

from __future__ import annotations

import math
from collections import Counter


def _tokenize(text: str) -> list[str]:
    """Simple lowercase word tokenization."""
    import re
    return re.findall(r'\b[a-z0-9]+\b', text.lower())


def _compute_tf(tokens: list[str]) -> dict[str, float]:
    """Term Frequency."""
    counts = Counter(tokens)
    total = max(1, len(tokens))
    return {word: count / total for word, count in counts.items()}


class TfIdfModel:
    """Lightweight TF-IDF model built on a specific corpus."""
    
    def __init__(self, corpus: list[str]):
        self.doc_count = len(corpus)
        self.idf: dict[str, float] = {}
        
        # Compute IDF
        df: Counter = Counter()
        for doc in corpus:
            tokens = set(_tokenize(doc))
            for t in tokens:
                df[t] += 1
                
        for word, count in df.items():
            self.idf[word] = math.log((1 + self.doc_count) / (1 + count)) + 1.0

    def vectorize(self, text: str) -> dict[str, float]:
        """Convert text to TF-IDF sparse vector."""
        tokens = _tokenize(text)
        tf = _compute_tf(tokens)
        vec = {}
        norm_sq = 0.0
        for word, val in tf.items():
            # Use 1.0 for unknown words IDF
            weight = val * self.idf.get(word, 1.0)
            vec[word] = weight
            norm_sq += weight * weight
            
        # L2 normalize
        if norm_sq > 0:
            norm = math.sqrt(norm_sq)
            for word in vec:
                vec[word] /= norm
                
        return vec


def _cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
    """Cosine similarity between two sparse L2-normalized vectors."""
    score = 0.0
    # Iterate over the smaller vector
    if len(vec1) > len(vec2):
        vec1, vec2 = vec2, vec1
    for word, val in vec1.items():
        if word in vec2:
            score += val * vec2[word]
    return score


def similarity_score(moment_text: str, top_clips_texts: list[str]) -> float:
    """Score a moment's similarity against a set of top performing clips.
    
    Returns the maximum similarity to any of the top clips.
    """
    if not moment_text or not top_clips_texts:
        return 0.0
        
    model = TfIdfModel(top_clips_texts + [moment_text])
    moment_vec = model.vectorize(moment_text)
    
    max_sim = 0.0
    for clip_text in top_clips_texts:
        clip_vec = model.vectorize(clip_text)
        sim = _cosine_similarity(moment_vec, clip_vec)
        if sim > max_sim:
            max_sim = sim
            
    return round(max_sim, 3)
