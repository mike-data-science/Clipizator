"""PANNs Cnn14_DecisionLevelMax channel: framewise posteriors over the
AudioSet ontology, reduced to the event types the bus cares about.

Laughter-only decision (#2): crying classes are intentionally ABSENT from
the map — no battle-tested adult-crying model exists, and one false positive
would fire on three surfaces at once through the shared bus. PANNs' AudioSet
laughter classes stay in as the fusion partner for the jrgillick specialist.

Processes audio in 30 s chunks with 1 s overlap — Cnn14 on 2 h of audio at
once would need tens of GB of activations.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import torch

from ..vendor.panns import models as panns_models

# AudioSet display_name → bus event type. Laughter classes fuse with the
# jrgillick channel; the rest are solo PANNs detections.
CLASS_MAP: dict[str, str] = {
    "Laughter": "laugh",
    "Giggle": "laugh",
    "Belly laugh": "laugh",
    "Chuckle, chortle": "laugh",
    "Snicker": "laugh",
    "Gasp": "gasp",
    "Screaming": "scream",
    "Shout": "shout",
    "Yell": "shout",
    "Applause": "applause",
    "Cheering": "cheer",
    "Clapping": "applause",
}

# Extra AudioSet evidence retained only for Video DNA audio intelligence.
# These labels never enter the legacy shared event bus, so existing clipping
# behavior remains unchanged.
INTELLIGENCE_CLASS_MAP: dict[str, str] = {
    "Music": "music",
    "Background music": "music",
    "Whoosh, swoosh, swish": "sfx:whoosh",
    "Thump, thud": "sfx:impact/hit",
    "Bang": "sfx:impact/hit",
    "Slam": "sfx:impact/hit",
    "Clicking": "sfx:click/shutter",
    "Camera": "sfx:click/shutter",
    "Beep, bleep": "sfx:beep/notification",
    "Ding": "sfx:beep/notification",
    "Ding-dong": "sfx:beep/notification",
    "Engine": "sfx:engine/mechanical",
    "Engine knocking": "sfx:engine/mechanical",
    "Engine starting": "sfx:engine/mechanical",
    "Crowd": "sfx:crowd",
}

CHUNK_SEC = 30.0
OVERLAP_SEC = 1.0

# Zero-shot PANNs posteriors on conversational audio run far below the
# dedicated-SED range the default DCASE thresholds assume: measured on a
# 2 h two-host comedy podcast, laughter tops out ~0.30 and gasps ~0.24
# while true negatives (applause/cheer in a studio) stay under 0.004.
# (enter, stay) per type; confidence is normalized by CONF_SCALE so a
# strong conversational laugh reads ~1.0 downstream.
THRESHOLDS: dict[str, tuple[float, float]] = {
    "laugh": (0.10, 0.05),
    "gasp": (0.10, 0.05),
    "scream": (0.15, 0.08),
    "shout": (0.15, 0.08),
    "applause": (0.15, 0.08),
    "cheer": (0.15, 0.08),
}
INTELLIGENCE_THRESHOLDS: dict[str, tuple[float, float]] = {
    "music": (0.18, 0.10),
    "sfx:whoosh": (0.20, 0.10),
    "sfx:impact/hit": (0.20, 0.10),
    "sfx:click/shutter": (0.22, 0.12),
    "sfx:beep/notification": (0.20, 0.10),
    "sfx:engine/mechanical": (0.20, 0.10),
    "sfx:crowd": (0.20, 0.10),
}
CONF_SCALE = 0.30


def load_class_indices(class_map: dict[str, str] | None = None) -> dict[int, str]:
    """AudioSet index → bus event type, for the classes we track."""
    class_map = class_map or CLASS_MAP
    csv_path = Path(__file__).parent.parent / "vendor" / "panns" / "class_labels_indices.csv"
    mapping: dict[int, str] = {}
    with open(csv_path) as fh:
        for row in csv.DictReader(fh):
            name = row["display_name"].strip('"')
            if name in class_map:
                mapping[int(row["index"])] = class_map[name]
    return mapping


def framewise_probs(
    model: panns_models.Cnn14_DecisionLevelMax,
    y32k: np.ndarray,
    device: torch.device,
    progress=None,
    class_map: dict[str, str] | None = None,
) -> tuple[dict[str, np.ndarray], float]:
    """Per-event-type framewise posteriors on the model's 100 fps grid.
    Same-type classes collapse via max (a giggle IS a laugh)."""
    class_idx = load_class_indices(class_map)
    types = sorted(set(class_idx.values()))
    sr = panns_models.SAMPLE_RATE
    fps = panns_models.FRAMES_PER_SEC
    chunk = int(CHUNK_SEC * sr)
    overlap = int(OVERLAP_SEC * sr)
    total_frames = int(np.ceil(len(y32k) / sr * fps))
    out = {t: np.zeros(total_frames, dtype=np.float32) for t in types}

    pos = 0
    with torch.inference_mode():
        while pos < len(y32k):
            end = min(pos + chunk, len(y32k))
            seg = y32k[max(0, pos - overlap) : end]
            x = torch.from_numpy(seg.astype(np.float32)).unsqueeze(0).to(device)
            framewise = model(x)["framewise_output"][0].cpu().numpy()  # (frames, 527)
            lead_frames = int(round((pos - max(0, pos - overlap)) / sr * fps))
            frame0 = int(round(pos / sr * fps))
            usable = framewise[lead_frames:]
            n = min(len(usable), total_frames - frame0)
            for cls, etype in class_idx.items():
                np.maximum(
                    out[etype][frame0 : frame0 + n], usable[:n, cls], out=out[etype][frame0 : frame0 + n]
                )
            if progress:
                progress(end / len(y32k))
            pos = end
    return out, fps
