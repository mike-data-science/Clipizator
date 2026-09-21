import json
import subprocess

import pytest

from publikclip_pipeline.render import ffmpeg_bin, renderer
from publikclip_pipeline.visual_join_treatment import (
    VisualJoinPolicy,
    _transform,
    apply_treatments,
    build_visual_join_plan,
)


W, H = 96, 54


def image(kind="black"):
    if kind == "black":
        return {"pixels": bytes(W * H)}
    if kind == "white":
        return {"pixels": bytes([255]) * (W * H)}
    if kind == "checker":
        return {"pixels": bytes(240 if (x // 4 + y // 4) % 2 else 15 for y in range(H) for x in range(W))}
    raise ValueError(kind)


def safe_plan(*, window=(920, 1580)):
    return {
        "execution_version": "safe-edit-execution-v1",
        "candidates": [{
            "candidate_id": "candidate-a", "original_start_ms": 0, "original_end_ms": 3000,
            "planned_decisions": [{"decision_id": "decision-a", "recommended_cut_window_ms": list(window)}],
            "executed_removals": [{
                "cut_id": "cut-a", "decision_id": "decision-a",
                "refined_left_boundary_ms": 1000, "refined_right_boundary_ms": 1500,
                "visual_jump_risk": "medium",
            }],
            "final_retained_ranges": [{"start_ms": 0, "end_ms": 1000}, {"start_ms": 1500, "end_ms": 3000}],
        }],
    }


def run(loader, *, segments=None, policy=None):
    return build_visual_join_plan(
        safe_execution=safe_plan(), segments=segments or [],
        frame_loader=lambda _candidate, timestamp: loader(timestamp), fps=25,
        policy=policy,
    )["candidates"][0]


def test_already_good_join_uses_none():
    result = run(lambda _timestamp: image("checker"))
    assert result["joins"][0]["treatment"] == "none"
    assert result["render_retained_ranges"] == result["semantic_retained_ranges"]


def test_better_nearby_frame_uses_boundary_shift():
    def loader(timestamp):
        return image("white" if timestamp <= 900 or timestamp >= 1500 else "black")

    join = run(loader)["joins"][0]
    assert join["treatment"] == "boundary_shift"
    assert join["selected_boundary_ms"]["left"] < 1000
    assert join["visual_discontinuity_after"] < join["visual_discontinuity_before"]


def test_poor_join_uses_subtle_punch():
    policy = VisualJoinPolicy(acceptable_score=.005, treatment_improvement=.001)
    right = {**image("checker"), "face": {"x": .38, "y": .2, "width": .20, "height": .35}}
    left = _transform(right, 1.08, 0, 0, policy)
    result = run(lambda timestamp: left if timestamp < 1000 else right, policy=policy)
    assert result["joins"][0]["treatment"] == "subtle_punch_in"
    assert 1.04 <= result["joins"][0]["scale_after"] <= 1.12


def test_reframe_stays_inside_crop_limits():
    trajectory = {"fps": 25, "frames": [[0, 0, 608, 1080]] * 100, "cuts": [], "punches": []}
    joins = [{"cut_id": "cut-a", "output_join_ms": 1000, "treatment": "reframe",
              "scale_after": 1.0, "reframe_dx": -.05, "reframe_dy": -.04,
              "treatment_duration_ms": 1000, "return_duration_ms": 200}]
    output, _ = apply_treatments(trajectory, joins, 1920, 1080)
    assert all(x >= 0 and y >= 0 and x + w <= 1920 and y + h <= 1080 for x, y, w, h in output["frames"])


def test_unsafe_boundary_shift_across_word_is_rejected():
    def loader(timestamp):
        return image("white" if timestamp <= 900 or timestamp >= 1500 else "black")

    segments = [{"words": [{"word": "required", "start": .90, "end": .99}]}]
    join = run(loader, segments=segments)["joins"][0]
    assert join["selected_boundary_ms"]["left"] == 1000
    assert join["treatment"] != "boundary_shift"


def test_unresolved_join_requires_visual_cover():
    result = run(lambda timestamp: image("black") if timestamp < 1000 else image("white"))
    join = result["joins"][0]
    assert join["treatment"] == "visual_cover_required"
    assert join["requires_visual_cover"] is True
    assert join["suggested_cover_end_ms"] > join["suggested_cover_start_ms"]


def test_treatment_keeps_semantic_ranges_immutable():
    source = safe_plan()
    original = json.loads(json.dumps(source["candidates"][0]["final_retained_ranges"]))
    run(lambda timestamp: image("black") if timestamp < 1000 else image("white"))
    assert source["candidates"][0]["final_retained_ranges"] == original


def test_artifact_serialization_is_stable():
    kwargs = dict(safe_execution=safe_plan(), segments=[],
                  frame_loader=lambda _candidate, _timestamp: image("checker"), fps=25)
    first, second = build_visual_join_plan(**kwargs), build_visual_join_plan(**kwargs)
    first["metrics"].pop("runtime_ms")
    second["metrics"].pop("runtime_ms")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


@pytest.mark.slow
def test_treated_multirange_render_keeps_av_sync(tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    subprocess.run([
        ffmpeg_bin.ffmpeg(), "-v", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=4",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(source),
    ], check=True, timeout=60)
    monkeypatch.setattr(renderer, "OUT_W", 360)
    monkeypatch.setattr(renderer, "OUT_H", 640)
    monkeypatch.setattr(renderer, "cuda_scale_available", lambda: False)
    monkeypatch.setattr(renderer, "nvenc_available", lambda: False)
    monkeypatch.setattr(renderer, "videotoolbox_available", lambda: False)
    ranges = [(0.0, 1.4), (2.0, 4.0)]
    trajectory = {"fps": 25, "frames": [[70, 0, 180, 240]] * 85, "cuts": [], "punches": []}
    joins = [{"cut_id": "cut-a", "output_join_ms": 1400, "treatment": "reframe",
              "scale_after": 1.0, "reframe_dx": .04, "reframe_dy": 0,
              "treatment_duration_ms": 1000, "return_duration_ms": 200}]
    treated, _ = apply_treatments(trajectory, joins, 320, 240)
    output = tmp_path / "treated.mp4"
    renderer.render_clip(str(source), output, 0, 4, treated, None, None,
                         src_w=320, src_h=240, retained_ranges=ranges,
                         crossfades_ms=[20], timeout=90)
    check = renderer.verify_output(output, 3.4)
    assert check["ok"], check
    assert check["av_sync_delta"] < .08
