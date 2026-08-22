"""Hook pattern matching and density scoring (instant, no LLM)."""

from __future__ import annotations

import re


def classify_hook_template(first_15_words: str) -> str:
    """Classify the opening into a known hook template pattern."""
    text = first_15_words.lower()
    
    # 1. Number hook
    if re.search(r'\b(three|four|five|six|seven|eight|nine|ten|\d+)\s+(things|reasons|ways|secrets|habits|tips)\b', text):
        return "number_hook"
        
    # 2. Impossible question / Curiosity gap
    if re.search(r'^(how|what|why) did (he|she|they|you)\b', text) or \
       re.search(r'what happens (when|if)\b', text) or \
       re.search(r'have you ever wondered\b', text):
        return "impossible_question"
        
    # 3. Controversial claim / Absolutes
    if re.search(r'^(nobody|everyone) (is|actually)\b', text) or \
       re.search(r'\b(is a lie|are wrong|is dead)\b', text):
        return "controversial_claim"
        
    # 4. Direct address
    if re.search(r'^(if you|stop doing|you need to|listen to me)\b', text):
        return "direct_address"
        
    # 5. Story mid-action
    if re.search(r'^(so i( was|\'m)|and then i|there i was)\b', text):
        return "story_mid_action"
        
    # 6. Mid-sentence entry (usually starts with "and" or lowercase without proper noun context)
    # Hard to detect perfectly without case sensitivity, but "and" is a strong signal.
    if text.startswith("and ") or text.startswith("so "):
        # Check if it's just a conjunction
        return "mid_sentence_entry"
        
    return "none"


def hook_density(text: str) -> dict:
    """Analyze the density and speed of the hook."""
    words = text.split()
    if not words:
        return {
            "hook_density_score": 0.0,
            "first_word_quality": 0.0,
            "time_to_curiosity": -1.0,
        }
        
    # Time to curiosity: how many words until a question mark or WH-word?
    time_to_curiosity = -1.0
    for i, w in enumerate(words):
        if '?' in w or w.lower() in {'how', 'why', 'what', 'who', 'where', 'when'}:
            time_to_curiosity = i * 0.33 # Rough approx: 3 words per second
            break
            
    # First word quality: is it a strong action word, WH-word, or pronoun?
    first_word = words[0].lower().strip(',.!?')
    fw_quality = 0.0
    strong_starts = {
        'how', 'why', 'what', 'who', 'imagine', 'stop', 'listen', 'look', 
        'this', 'here', 'if', 'nobody', 'everyone', 'never', 'always'
    }
    if first_word in strong_starts:
        fw_quality = 1.0
    elif first_word in {'so', 'and', 'but', 'because'}:
        fw_quality = 0.8 # Mid-sentence entries are good
    elif first_word in {'i', 'you', 'we', 'they', 'he', 'she'}:
        fw_quality = 0.5
        
    # Hook density score: heuristic based on early engagement signals
    # More punctuation, shorter words, strong starts = higher density
    density_score = 0.0
    first_15 = " ".join(words[:15])
    if '?' in first_15: density_score += 2.0
    if '!' in first_15: density_score += 1.0
    if len(first_15) < 70: density_score += 1.0 # Short, punchy words
    density_score += (fw_quality * 2.0)
    
    # Normalize roughly 0-10
    density_score = min(10.0, density_score * 2.0)
    
    return {
        "hook_density_score": round(density_score, 2),
        "first_word_quality": round(fw_quality, 2),
        "time_to_curiosity": round(time_to_curiosity, 2),
    }


def extract_hook_text(text: str) -> str:
    """Extract roughly the first 3 seconds (~9 words)."""
    words = text.split()
    return " ".join(words[:10])
