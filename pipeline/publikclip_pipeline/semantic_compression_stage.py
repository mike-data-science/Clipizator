from __future__ import annotations
import json
from .jobs.queue import Stage
from .semantic_compression import build_plan

class SemanticCompressionStage(Stage):
    name = "semantic_compression"
    schema_version = 1
    def run(self, ctx):
        prior=ctx.prior or {}; candidates=prior.get("candidates") or {}
        if candidates.get("selection_version") != "clip-selection-v2":
            return {"semantic_compression_version":"semantic-compression-v1.1","status":"legacy_fallback","candidate_count":0,"candidates":[]}
        source=prior.get("source_analysis") or {}
        ctx.emit(.9,"Building conservative internal edit decisions…")
        plan=build_plan(candidates=candidates.get("portfolio") or candidates.get("candidates") or [],segments=(prior.get("diarize") or {}).get("segments") or [],story_semantics=source.get("story_semantics") or {},source_editing=source.get("source_editing") or {})
        (ctx.job_dir/"semantic_compression_v1.json").write_text(json.dumps(plan,ensure_ascii=False,indent=1))
        return plan
