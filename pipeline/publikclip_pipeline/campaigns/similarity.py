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


def find_clip_in_transcript(clip_text: str, transcript_segments: list[dict]) -> dict | None:
    """Finds the best matching window in the transcript for a given clip text.
    Returns {"start": float, "end": float, "matched_text": str, "score": float} or None.
    """
    if not clip_text or not transcript_segments:
        return None
        
    clip_tokens = _tokenize(clip_text)
    if not clip_tokens:
        return None
        
    best_score = 0.0
    best_match = None
    
    # Flatten transcript to word-level for easier matching
    flat_words = []
    for seg in transcript_segments:
        words = seg.get("words", [])
        if words:
            flat_words.extend(words)
        else:
            # Fallback if no word-level timestamps, just use segment
            for token in _tokenize(seg.get("text", "")):
                flat_words.append({
                    "word": token, 
                    "start": seg.get("start", 0), 
                    "end": seg.get("end", 0)
                })
                
    if not flat_words:
        return None
        
    window_size = len(clip_tokens)
    if window_size == 0:
        return None
        
    model = TfIdfModel([clip_text] + [" ".join(w.get("word", "") for w in flat_words)])
    clip_vec = model.vectorize(clip_text)

    # Slide window
    step = max(1, window_size // 4)
    
    for i in range(0, len(flat_words), step):
        window = flat_words[i : i + window_size + 15] # add a buffer
        if not window:
            continue
            
        window_text = " ".join(w.get("word", "") for w in window)
        window_vec = model.vectorize(window_text)
        score = _cosine_similarity(clip_vec, window_vec)
        
        if score > best_score:
            best_score = score
            best_match = {
                "start": window[0].get("start", 0),
                "end": window[-1].get("end", 0),
                "matched_text": window_text,
                "score": score
            }
            
    # Threshold for a "match". TF-IDF cosine sim can be relatively low if clip text has noise
    if best_score > 0.15:
        return best_match
    return None

