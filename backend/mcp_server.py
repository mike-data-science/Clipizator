import sys
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# Add the pipeline to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "pipeline"))

from publikclip_pipeline.campaigns import analyzer
from publikclip_pipeline import config

mcp = FastMCP("PublikClip Scorer")

@mcp.tool()
def get_pending_scoring_tasks(campaign_id: str) -> str:
    """Returns a JSON string of candidate moments that need LLM scoring for a given campaign."""
    from publikclip_pipeline.campaigns import store
    campaign_dir = store.get_campaign_dir(campaign_id)
    pending_file = config.jobs_dir() / campaign_dir / "pending_scoring.json"
    if not pending_file.exists():
        return json.dumps({"status": "error", "message": "No pending tasks found. Run prepare_analysis first."})
    
    tasks = json.loads(pending_file.read_text())
    return json.dumps({"status": "success", "campaign_id": campaign_id, "tasks": tasks}, indent=2)

@mcp.tool()
def submit_scored_tasks(campaign_id: str, scores_json: str) -> str:
    """Submits the LLM-scored candidate moments back to the backend to complete the analysis.
    
    Args:
        campaign_id: The ID of the campaign.
        scores_json: A JSON string of the candidates array, where each candidate has been augmented
                     with LLM scoring keys like `llm_hook_score`, `llm_funniness`, `llm_summary`, etc.
    """
    try:
        scored_candidates = json.loads(scores_json)
        # Ensure it's a list
        if not isinstance(scored_candidates, list):
            return json.dumps({"status": "error", "message": "scores_json must be a JSON array of candidates."})
            
        def progress(pct, msg):
            print(f"MCP Progress: {pct*100:.1f}% - {msg}")
            
        analyzer.complete_analysis(campaign_id, scored_candidates, progress=progress)
        return json.dumps({"status": "success", "message": f"Successfully completed analysis for {len(scored_candidates)} moments."})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})

if __name__ == "__main__":
    # Start the standard stdio server
    mcp.run()
