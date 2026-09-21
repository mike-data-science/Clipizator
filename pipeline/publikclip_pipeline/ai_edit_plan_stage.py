from __future__ import annotations

import json

from .ai_edit_plan import build_ai_edit_plan
from .jobs.queue import Stage


class AiEditPlanStage(Stage):
    name = "ai_edit_plan"
    schema_version = 1

    def run(self, ctx):
        prior = ctx.prior or {}
        source = prior.get("source_analysis") or {}
        ctx.emit(.9, "Building evidence-backed B-roll opportunities…")
        result = build_ai_edit_plan(
            selected_clips=(prior.get("score") or {}).get("clips") or [],
            story_semantics=source.get("story_semantics") or {},
            visual_understanding=source.get("visual_understanding") or {},
            source_editing=source.get("source_editing") or source.get("source_editing_evidence") or {},
            safe_execution=prior.get("safe_edit_execution") or {},
            visual_join=prior.get("visual_join_treatment") or {},
            generation_config=ctx.generation_config,
            generation_config_run_id=ctx.generation_config_run_id,
        )
        (ctx.job_dir / "ai_edit_plan_v1.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=1, sort_keys=True)
        )
        return result

    def artifacts_ok(self, ctx, data):
        return (ctx.job_dir / "ai_edit_plan_v1.json").exists()
