"""Text-based retention curve prediction.

Predicts drop-off risk by analyzing the energy shape of the text.
Moments where the middle is significantly weaker than the hook
are likely to lose viewers.
"""

from __future__ import annotations


def predict_retention(text: str) -> dict:
    """Predict retention based on text structure."""
    words = text.split()
    n = len(words)
    if n < 30:
        return {
            "payoff_density": 0.0,
            "middle_energy": 0.0,
            "drop_off_risk": 0.0,
            "energy_shape": "flat",
        }

    # Split into thirds
    third = max(1, n // 3)
    p1 = words[:third]
    p2 = words[third:2*third]
    p3 = words[2*third:]

    # Energy score per third (very rough proxy using punctuation and word length)
    def _energy(part: list[str]) -> float:
        if not part:
            return 0.0
        # Shorter words = higher energy/pacing. More punctuation = more dynamics.
        avg_len = sum(len(w) for w in part) / len(part)
        punct = sum(1 for w in part if any(c in w for c in '.!?'))
        # Base energy 5.0, adjusted by pacing and dynamics
        e = 5.0 + (5.0 - min(5.0, avg_len)) + (punct * 0.5)
        return min(10.0, max(0.0, e))

    e1 = _energy(p1)
    e2 = _energy(p2)
    e3 = _energy(p3)

    # Energy shape
    if e1 > e2 and e1 > e3:
        shape = "front_loaded"
    elif e3 > e1 and e3 > e2:
        shape = "back_loaded"
    elif e2 < e1 and e2 < e3:
        shape = "valley"
    elif abs(e1 - e2) < 1.0 and abs(e2 - e3) < 1.0:
        shape = "even"
    else:
        shape = "fluctuating"

    # Drop-off risk: high if middle energy is very low compared to hook
    drop_off_risk = 0.0
    if e2 < e1 - 2.0:
        drop_off_risk = min(1.0, (e1 - e2) / 10.0 + 0.2)
    if shape == "valley":
        drop_off_risk = min(1.0, drop_off_risk + 0.3)
        
    # Payoff density: peaks in last third vs setup in first two
    setup_energy = (e1 + e2) / 2.0
    payoff_density = 0.0
    if setup_energy > 0:
        payoff_density = e3 / setup_energy

    return {
        "payoff_density": round(payoff_density, 2),
        "middle_energy": round(e2, 2),
        "drop_off_risk": round(drop_off_risk, 2),
        "energy_shape": shape,
    }
