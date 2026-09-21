from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .jobs.queue import Stage, StageError
from .visual_join_treatment import apply_treatments, build_visual_join_plan


class _FrameLoader:
    def __init__(self, media: Path, clip_start: float, trajectory: dict[str, Any],
                 src_w: int, src_h: int, face_observations: list[dict[str, Any]]):
        from .render import ffmpeg_bin

        self.ffmpeg = ffmpeg_bin.ffmpeg()
        self.media = media
        self.clip_start = clip_start
        self.trajectory = trajectory
        self.src_w, self.src_h = src_w, src_h
        self.faces = face_observations
        self.cache: dict[int, dict[str, Any]] = {}

    def _box(self, timestamp_ms: int) -> list[float]:
        frames = self.trajectory.get("frames") or []
        fps = float(self.trajectory.get("fps") or 25)
        if frames:
            index = round((timestamp_ms / 1000 - self.clip_start) * fps)
            return list(map(float, frames[max(0, min(len(frames) - 1, index))]))
        height = float(self.src_h)
        width = min(float(self.src_w), height * 9 / 16)
        return [(self.src_w - width) / 2, 0.0, width, height]

    def __call__(self, timestamp_ms: int) -> dict[str, Any]:
        timestamp_ms = max(0, int(timestamp_ms))
        if timestamp_ms in self.cache:
            return self.cache[timestamp_ms]
        x, y, width, height = self._box(timestamp_ms)
        width = max(2, min(self.src_w, round(width) // 2 * 2))
        height = max(2, min(self.src_h, round(height) // 2 * 2))
        x = max(0, min(self.src_w - width, round(x)))
        y = max(0, min(self.src_h - height, round(y)))
        command = [
            self.ffmpeg, "-v", "error", "-ss", f"{timestamp_ms / 1000:.3f}",
            "-i", str(self.media), "-frames:v", "1",
            "-vf", f"crop={width}:{height}:{x}:{y},scale=96:54,format=gray",
            "-f", "rawvideo", "pipe:1",
        ]
        proc = subprocess.run(command, capture_output=True, timeout=60)
        if proc.returncode or len(proc.stdout) != 96 * 54:
            raise StageError(f"Could not decode visual join frame at {timestamp_ms} ms: {proc.stderr[-240:].decode(errors='replace')}")
        result: dict[str, Any] = {"pixels": proc.stdout}
        nearest = min(self.faces, key=lambda item: abs(float(item.get("timestamp", -9999)) * 1000 - timestamp_ms), default=None)
        if nearest and abs(float(nearest.get("timestamp", -9999)) * 1000 - timestamp_ms) <= 750:
            faces = nearest.get("faces") or []
            if faces:
                source_face = max(faces, key=lambda item: float((item.get("bbox") or item).get("width", 0)) * float((item.get("bbox") or item).get("height", 0)))
                box = source_face.get("bbox") or source_face
                fx, fy = float(box["x"]) * self.src_w, float(box["y"]) * self.src_h
                fw, fh = float(box["width"]) * self.src_w, float(box["height"]) * self.src_h
                result["face"] = {"x": (fx - x) / width, "y": (fy - y) / height,
                                  "width": fw / width, "height": fh / height}
        self.cache[timestamp_ms] = result
        return result


class VisualJoinTreatmentStage(Stage):
    name = "visual_join_treatment"
    schema_version = 1

    def run(self, ctx):
        prior = ctx.prior or {}
        execution = prior.get("safe_edit_execution") or {}
        if execution.get("status") == "legacy_fallback":
            return {"visual_join_treatment_version": "visual-join-treatment-v1", "schema_version": 1,
                    "status": "legacy_fallback", "candidates": []}
        if execution.get("execution_version") != "safe-edit-execution-v1":
            raise StageError("Visual Join Treatment v1 requires Safe Edit Execution v1.")
        ingest, diarize = prior.get("ingest") or {}, prior.get("diarize") or {}
        score, camera = prior.get("score") or {}, prior.get("camera") or {}
        source = prior.get("source_analysis") or {}
        media_raw = Path(str(ingest.get("media_path") or "media.mkv").replace("\\", "/"))
        media = media_raw if media_raw.exists() else ctx.job_dir / media_raw.name
        if not media.exists():
            raise StageError("Visual Join Treatment needs the ingested source media.")
        probe = ingest.get("probe") or {}
        src_w, src_h = int(probe.get("width") or 1920), int(probe.get("height") or 1080)
        fps = float(probe.get("fps") or 25)
        clips = score.get("clips") or []
        clip_indexes = {item.get("candidate_id"): index for index, item in enumerate(clips)}
        trajectories = camera.get("trajectories") or {}
        loaders: dict[str, _FrameLoader] = {}
        for candidate in execution.get("candidates") or []:
            candidate_id = candidate.get("candidate_id")
            index = clip_indexes.get(candidate_id)
            if index is None:
                continue
            trajectory_path = trajectories.get(str(index))
            trajectory = json.loads(Path(trajectory_path).read_text()) if trajectory_path and Path(trajectory_path).exists() else {"fps": fps, "frames": []}
            loaders[str(candidate_id)] = _FrameLoader(
                media, float(clips[index]["start"]), trajectory, src_w, src_h,
                source.get("raw_visual_observations") or [],
            )

        def load_frame(candidate_id: str, timestamp_ms: int):
            loader = loaders.get(candidate_id)
            if loader is None:
                raise StageError(f"No camera/clip mapping for visual join candidate {candidate_id}.")
            return loader(timestamp_ms)

        editing = source.get("source_editing_evidence") or source.get("source_editing") or {}
        raw_cuts = editing.get("shot_cuts") or editing.get("cuts") or []
        source_cuts = [round(float(item["start"]) * 1000) if "start" in item else int(item.get("timestamp_ms", item.get("start_ms", 0))) for item in raw_cuts]
        ctx.emit(.4, "Analyzing visual continuity at executed joins…")
        result = build_visual_join_plan(
            safe_execution=execution, segments=diarize.get("segments") or [],
            frame_loader=load_frame, source_cuts_ms=source_cuts, fps=fps,
        )

        from .edits.timeline import TimeRemap
        for candidate in result["candidates"]:
            index = clip_indexes.get(candidate.get("candidate_id"))
            trajectory_path = trajectories.get(str(index)) if index is not None else None
            if not trajectory_path or not Path(trajectory_path).exists():
                continue
            trajectory = json.loads(Path(trajectory_path).read_text())
            ranges = [(item["start_ms"] / 1000, item["end_ms"] / 1000) for item in candidate["render_retained_ranges"]]
            remap = TimeRemap(ranges)
            remapped = {**trajectory, "frames": remap.remap_trajectory(
                trajectory.get("frames") or [], float(trajectory.get("fps") or fps), float(clips[index]["start"]),
            )}
            _, conflicts = apply_treatments(remapped, candidate["joins"], src_w, src_h)
            candidate["camera_trajectory_conflicts"] = conflicts
            for join in candidate["joins"]:
                join["camera_trajectory_conflict"] = str(join.get("cut_id")) in conflicts
        result["metrics"]["camera_trajectory_conflict_count"] = sum(len(item.get("camera_trajectory_conflicts") or []) for item in result["candidates"])
        (ctx.job_dir / "visual_join_treatment_v1.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
        return result
