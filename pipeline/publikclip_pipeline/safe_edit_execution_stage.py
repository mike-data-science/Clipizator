from __future__ import annotations

import json

from .jobs.queue import Stage, StageError
from .safe_edit_execution import build_execution_plan, preserve_duration_contract


class SafeEditExecutionStage(Stage):
    name = "safe_edit_execution"
    schema_version = 1

    def run(self, ctx):
        prior = ctx.prior or {}
        compression = prior.get("semantic_compression") or {}
        if compression.get("semantic_compression_version") != "semantic-compression-v1.1":
            if compression.get("status") == "legacy_fallback":
                return {
                    "execution_version": "safe-edit-execution-v1", "schema_version": 1,
                    "status": "legacy_fallback", "candidate_count": 0, "candidates": [],
                    "warnings": ["Semantic Compression v1.1 was unavailable; legacy clips remain continuous."],
                }
            raise StageError("Safe Edit Execution v1 requires Semantic Compression v1.1.")
        diarize = prior.get("diarize") or {}
        source = prior.get("source_analysis") or {}
        ingest = prior.get("ingest") or {}
        curves = {}
        events = prior.get("events") or {}
        curves_path = events.get("curves_path")
        if curves_path:
            path = ctx.job_dir / str(curves_path).replace("\\", "/").split("/")[-1]
            if path.exists():
                curves = json.loads(path.read_text())
        ctx.emit(.9, "Building safe executable edit ranges…")
        editing = source.get("source_editing") or source.get("source_editing_evidence") or {}
        if editing.get("shot_cuts") and not editing.get("cuts"):
            editing = {**editing, "cuts": [
                {"timestamp_ms": (round(float(item["start"]) * 1000) if "start" in item else int(item.get("start_ms", 0)))}
                for item in editing["shot_cuts"]
            ]}
        result = preserve_duration_contract(build_execution_plan(
            semantic_compression=compression, segments=diarize.get("segments") or [],
            source_editing=editing, rms=curves.get("rms") or [],
            rms_grid_sec=float(curves.get("grid_sec") or .1),
            fps=float((ingest.get("probe") or {}).get("fps") or 25),
        ), (ctx.generation_config or {}).get("clip_length"))
        (ctx.job_dir / "safe_edit_execution_v1.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
        return result
