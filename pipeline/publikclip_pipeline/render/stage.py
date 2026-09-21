"""Render stage: finalist clips + trajectories + captions → finished 9:16
MP4s, each verified (streams present, duration sane) before being reported."""

from __future__ import annotations

import json
from pathlib import Path

from ..jobs.queue import Stage, StageContext, StageError


class RenderStage(Stage):
    name = "render"
    schema_version = 1

    def artifacts_ok(self, ctx: StageContext, data: dict) -> bool:
        if data.get("caption_preset") != ctx.settings.caption_preset:
            return False  # restyle requested → re-render
        if data.get("caption_color") != ctx.settings.caption_color:
            return False  # color changed → re-render
        return all(Path(c["path"]).exists() for c in data.get("outputs", []))

    def run(self, ctx: StageContext) -> dict:
        import numpy as np

        from ..captions import ass as ass_mod
        from ..edits.timeline import TimeRemap
        from ..visual_join_treatment import apply_treatments
        from . import ffmpeg_bin, renderer

        if not ffmpeg_bin.supports_captions():
            ctx.emit(-1, "No caption-capable ffmpeg found — fetching one…")
            if not ffmpeg_bin.ensure_capable(progress=lambda f, m: ctx.emit(f, m)):
                ctx.emit(-1, "Caption burning unavailable — rendering without captions.")

        prior = ctx.prior or {}
        ingest = prior.get("ingest")
        diarize = prior.get("diarize")
        events = prior.get("events")
        score = prior.get("score")
        camera = prior.get("camera")
        if not (ingest and diarize and events and score and camera):
            raise StageError("Render needs every prior stage output.")

        media_str = ingest.get("media_path", "").replace("\\", "/")
        media = Path(media_str)
        if not media.exists():
            media = ctx.job_dir / Path(media_str).name
        media = str(media)
        
        probe = ingest["probe"]
        src_w, src_h = int(probe["width"]), int(probe["height"])
        segments = diarize["segments"]
        timeline = events["timeline"]
        curves = json.loads(Path(events["curves_path"]).read_text())
        rms = curves["rms"]
        grid = float(curves["grid_sec"])

        captions_ok = ffmpeg_bin.supports_captions()
        emoji_ok = ass_mod.emoji_probe() if captions_ok else False
        ctx.emit(-1, f"Emoji support: {'yes' if emoji_ok else 'no (dropping emoji)'}")

        out_dir = ctx.job_dir / "clips"
        out_dir.mkdir(exist_ok=True)
        preset = ctx.settings.caption_preset
        caption_color = ctx.settings.caption_color
        outputs = []
        clips = score["clips"]
        execution_by_candidate = {
            item.get("candidate_id"): item
            for item in (prior.get("safe_edit_execution") or {}).get("candidates") or []
            if item.get("candidate_id")
        }
        visual_join_by_candidate = {
            item.get("candidate_id"): item
            for item in (prior.get("visual_join_treatment") or {}).get("candidates") or []
            if item.get("candidate_id")
        }
        scaling = "CUDA" if renderer.cuda_scale_available() else "CPU"
        encoding = "NVENC" if renderer.nvenc_available() else "VideoToolbox" if renderer.videotoolbox_available() else "CPU"
        ctx.emit(-1, f"Render acceleration: {scaling} scaling, {encoding} encoding")
        for i, clip in enumerate(clips):
            traj_path = camera["trajectories"].get(str(i))
            if not traj_path or not Path(traj_path).exists():
                continue
            trajectory = json.loads(Path(traj_path).read_text())
            start, end = clip["start"], clip["end"]
            execution = execution_by_candidate.get(clip.get("candidate_id"))
            visual_join = visual_join_by_candidate.get(clip.get("candidate_id"))
            ranges = [
                (float(item["start_ms"]) / 1000, float(item["end_ms"]) / 1000)
                for item in ((visual_join or {}).get("render_retained_ranges") or (execution or {}).get("final_retained_ranges") or [])
            ] or [(start, end)]
            remap = TimeRemap(ranges)
            if len(ranges) > 1 or ranges != [(start, end)]:
                trajectory = {
                    **trajectory,
                    "frames": remap.remap_trajectory(
                        trajectory.get("frames") or [], float(trajectory.get("fps", 25)), start,
                    ),
                }
            trajectory, visual_join_conflicts = apply_treatments(
                trajectory, (visual_join or {}).get("joins") or [], src_w, src_h,
            )
            ctx.emit(i / max(1, len(clips)), f"Rendering clip {i + 1}/{len(clips)}…")

            # Words within the clip, clip-relative times.
            source_words = []
            for seg in segments:
                for w in seg.get("words", []):
                    if start <= w["start"] < end:
                        source_words.append(w)
            source_caption_words = [
                ass_mod.Word(text=w["word"], start=round(w["start"] - start, 3), end=round(min(w["end"], end) - start, 3))
                for w in source_words
            ]
            ass_mod.mark_emphasis(source_caption_words, rms, grid, clip_start=start)
            remapped_words = remap.remap_words([
                {"word": w["word"], "start": w["start"], "end": min(w["end"], end)} for w in source_words
            ])
            words = []
            source_index = 0
            for w in source_words:
                survives = remap.to_output((w["start"] + min(w["end"], end)) / 2) is not None
                if survives:
                    mapped = remapped_words[len(words)]
                    rendered = ass_mod.Word(text=mapped["word"], start=mapped["start"], end=mapped["end"])
                    rendered.emphasized = source_caption_words[source_index].emphasized
                    words.append(rendered)
                source_index += 1
            clip_events = []
            for event in timeline:
                if event["end"] <= start or event["start"] >= end or event["type"] == "pause":
                    continue
                midpoint = (event["start"] + event["end"]) / 2
                if remap.to_output(midpoint) is None:
                    continue
                clip_events.append({
                    "type": event["type"],
                    "start": remap.to_output_clamped(max(start, event["start"])),
                    "end": remap.to_output_clamped(min(end, event["end"])),
                })
            ass_path = out_dir / f"clip_{i:02d}.ass"
            ass_path.write_text(
                ass_mod.build_ass(words, clip_events, preset_name=preset, emoji_ok=emoji_ok, primary_color=caption_color)
            )

            out_path = out_dir / f"clip_{i:02d}.mp4"
            try:
                renderer.render_clip(
                    media, out_path, start, end, trajectory,
                    ass_path if captions_ok else None, ass_mod.FONTS_DIR,
                    lufs=ctx.settings.lufs_target,
                    true_peak=ctx.settings.true_peak_db,
                    src_w=src_w, src_h=src_h,
                    progress=lambda fraction: ctx.emit(
                        (i + fraction) / max(1, len(clips)),
                        f"Rendering clip {i + 1}/{len(clips)}…",
                    ),
                    retained_ranges=ranges,
                    crossfades_ms=[item.get("audio_crossfade_ms", 0) for item in (execution or {}).get("executed_removals") or []],
                )
            except RuntimeError as err:
                raise StageError(str(err)) from err
            check = renderer.verify_output(out_path, remap.output_duration)
            if not check["ok"]:
                raise StageError(
                    f"Clip {i} failed verification (duration {check['duration']:.1f}s, "
                    f"{check['width']}x{check['height']})."
                )
            outputs.append(
                {
                    "clip": i,
                    "path": str(out_path),
                    "ass": str(ass_path),
                    "score": clip["score"],
                    "best_platform": clip["best_platform"],
                    "duration": round(check["duration"], 2),
                    "words": len(words),
                    "event_tags": len(clip_events),
                    "safe_edit_execution": {
                        "status": (execution or {}).get("execution_status", "legacy_continuous"),
                        "internal_cut_count": len((execution or {}).get("executed_removals") or []),
                    },
                    "visual_join_treatment": {
                        "join_count": len((visual_join or {}).get("joins") or []),
                        "camera_trajectory_conflicts": visual_join_conflicts,
                    },
                }
            )

        if not outputs:
            raise StageError("No clips were rendered.")
        return {
            "outputs": outputs,
            "emoji_ok": emoji_ok,
            "captions_burned": captions_ok,
            "caption_preset": preset,
            "caption_color": caption_color,
            "acceleration": {"scaling": scaling, "encoding": encoding},
        }
