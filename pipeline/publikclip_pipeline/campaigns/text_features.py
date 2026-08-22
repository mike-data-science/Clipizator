"""Quantifiable text features for campaign analytics.

These features run in milliseconds per moment and do not require an LLM.
They measure structural, lexical, and pacing attributes that correlate
with retention and performance.
"""

from __future__ import annotations

import re


def extract_features(text: str) -> dict:
    """Extract structural and lexical features from transcript text."""
    if not text or not text.strip():
        return {
            "sentence_count": 0,
            "avg_sentence_length": 0.0,
            "question_density": 0.0,
            "specificity_score": 0.0,
            "controversy_score": 0.0,
            "emotional_arc_type": "flat",
            "first_person_ratio": 0.0,
            "imperative_density": 0.0,
            "dialogue_ratio": 0.0,
            "incomplete_thought": 1,
        }

    words = text.split()
    word_count = len(words)
    if word_count == 0:
        return {}

    # Sentences
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = len(sentences)
    avg_sentence_length = word_count / max(1, sentence_count)
    
    # Incomplete thought (does it end without punctuation?)
    incomplete_thought = 1 if not re.search(r'[.!?]$', text.strip()) else 0

    # Questions
    questions = len(re.findall(r'\?', text))
    question_density = (questions / word_count) * 100

    # Specificity (numbers, units, capitalized multi-word phrases)
    numbers = len(re.findall(r'\b\d+(?:[,.]\d+)?(?:[kKmMbB]|%|s|th)?\b', text))
    money = len(re.findall(r'\$\d+', text))
    # Simple Named Entity rough approximation: 2+ capitalized words
    entities = len(re.findall(r'[A-Z][a-z]+\s+[A-Z][a-z]+', text))
    specificity_score = ((numbers + money + entities) / word_count) * 100

    # Controversy / Absolutes
    absolutes = len(re.findall(r'\b(never|always|everyone|nobody|nothing|everything|worst|best|impossible|wrong|right)\b', text, re.IGNORECASE))
    negations = len(re.findall(r'\b(not|don\'t|can\'t|won\'t|isn\'t|aren\'t)\b', text, re.IGNORECASE))
    controversy_score = ((absolutes * 2 + negations) / word_count) * 100

    # Pronouns
    first_person = len(re.findall(r'\b(I|me|my|mine|we|us|our|ours)\b', text, re.IGNORECASE))
    first_person_ratio = (first_person / word_count) * 100

    # Imperatives (very rough approximation using common command verbs at start of sentences)
    imperatives = 0
    command_verbs = {'look', 'listen', 'think', 'stop', 'wait', 'imagine', 'remember', 'let', 'make', 'do', 'go', 'try'}
    for sentence in sentences:
        words_in_sentence = sentence.split()
        if words_in_sentence and words_in_sentence[0].lower() in command_verbs:
            imperatives += 1
    imperative_density = (imperatives / word_count) * 100

    # Dialogue ratio (quotes)
    quotes = len(re.findall(r'["\']([^"\']+)["\']', text))
    dialogue_ratio = min(100.0, (quotes * 10) / max(1, sentence_count) * 100) # Proxy

    # Emotional arc (proxy using positive/negative word counts in thirds)
    arc_type = _compute_arc_proxy(text)

    return {
        "sentence_count": sentence_count,
        "avg_sentence_length": round(avg_sentence_length, 2),
        "question_density": round(question_density, 2),
        "specificity_score": round(specificity_score, 2),
        "controversy_score": round(controversy_score, 2),
        "emotional_arc_type": arc_type,
        "first_person_ratio": round(first_person_ratio, 2),
        "imperative_density": round(imperative_density, 2),
        "dialogue_ratio": round(dialogue_ratio, 2),
        "incomplete_thought": incomplete_thought,
    }

def _compute_arc_proxy(text: str) -> str:
    """Very rough proxy for emotional arc using a small sentiment lexicon."""
    pos = {'good', 'great', 'love', 'amazing', 'happy', 'best', 'win', 'success'}
    neg = {'bad', 'terrible', 'hate', 'awful', 'sad', 'worst', 'lose', 'fail', 'died', 'dead', 'scared'}
    
    words = text.lower().split()
    n = len(words)
    if n < 3:
        return "flat"
    
    thirds = [words[:n//3], words[n//3:2*n//3], words[2*n//3:]]
    scores = []
    for part in thirds:
        score = 0
        for w in part:
            if w in pos: score += 1
            elif w in neg: score -= 1
        scores.append(score)
    
    s1, s2, s3 = scores
    
    if s1 < s2 < s3: return "rising"
    if s1 > s2 > s3: return "declining"
    if s2 > s1 and s2 > s3: return "peak_valley" # peak in middle
    if s2 < s1 and s2 < s3: return "twist" # valley in middle
    return "flat"
