import json
from types import SimpleNamespace

import pytest

from publikclip_pipeline.candidates import stage as candidates_stage
from publikclip_pipeline.candidates import windows
from publikclip_pipeline.jobs.queue import StageError


def test_normal_clipping_still_fails_when_candidate_generation_is_empty(monkeypatch, tmp_path):
    curves = tmp_path / "curves.json"
    curves.write_text(json.dumps({
        "dynamics": [0.0] * 40, "grid_sec": 1.0,
        "arousal": [0.0] * 40, "arousal_grid_sec": 1.0,
    }))
    monkeypatch.setattr(candidates_stage, "detect_scenes", lambda media_path: [])
    monkeypatch.setattr(windows, "extract", lambda *args, **kwargs: [])
    ctx = SimpleNamespace(
        prior={
            "ingest": {"probe": {"duration_sec": 40.0}, "media_path": "media.mkv", "heatmap": None},
            "diarize": {"segments": [], "turns": []},
            "events": {"curves_path": str(curves), "timeline": []},
        },
        job_dir=tmp_path,
        emit=lambda *args, **kwargs: None,
    )
    with pytest.raises(StageError, match="No candidate moments found"):
        candidates_stage.CandidatesStage().run(ctx)
