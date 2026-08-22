import asyncio
import json
import queue
import shutil
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config
from .cli import _stages
from .jobs import queue as job_queue
from .edits import render_clip as rc
from .edits import store, visuals
from .insights import calibration, instagram

app = FastAPI(title="Publikclip API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- WebSocket Event Bus ----
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        # We need to send text, so we dump to JSON
        text = json.dumps(message)
        for connection in self.active_connections:
            try:
                await connection.send_text(text)
            except RuntimeError:
                pass # Connection closed

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # We don't really expect client messages, but keep alive
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Helper to run pipeline and broadcast progress
def run_and_broadcast(job: job_queue.Job, command: str = "run", clip: int | None = None):
    def emit(stage: str, fraction: float, message: str) -> None:
        asyncio.run_coroutine_threadsafe(
            manager.broadcast({"event": "progress", "stage": stage, "fraction": fraction, "message": message}),
            asyncio.get_running_loop()
        )

    def run_pipeline():
        try:
            if command == "run" or command == "resume":
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"event": "job", "job_id": job.id, "dir": str(job.dir)}),
                    asyncio.get_running_loop()
                )
                results = job_queue.run_stages(job, _stages(), emit)
                summary = {
                    "ok": True,
                    "job_id": job.id,
                    "stages": list(results.keys()),
                    "title": results.get("ingest", {}).get("title"),
                    "heatmap_segments": len(results.get("ingest", {}).get("heatmap") or []),
                }
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"event": "result", **summary}),
                    asyncio.get_running_loop()
                )
            elif command == "render-clip":
                entry = rc.render_clip_edit(Path(job.dir), clip, lambda f, m: emit("render", f, m))
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast({"event": "result", "ok": True, "output": entry}),
                    asyncio.get_running_loop()
                )
        except Exception as err:
            asyncio.run_coroutine_threadsafe(
                manager.broadcast({"event": "result", "ok": False, "error": str(err)}),
                asyncio.get_running_loop()
            )

    # Start pipeline in a background thread
    asyncio.create_task(asyncio.to_thread(run_pipeline))

# ---- Models ----
class RunRequest(BaseModel):
    source: str
    llm: str | None = None
    captions: str | None = None
    camera: str | None = None

class ResumeRequest(BaseModel):
    llm: str | None = None
    captions: str | None = None
    camera: str | None = None

class KeyRequest(BaseModel):
    key: str

class IgConnectRequest(BaseModel):
    appId: str
    appSecret: str

class IgLinkRequest(BaseModel):
    job_id: str
    clip: int
    media_id: str
    source: str

class IgMediaIdRequest(BaseModel):
    media_id: str

class IgRejectRequest(BaseModel):
    media_id: str
    job_id: str
    clip: int

# ---- Endpoints ----

@app.post("/api/jobs")
async def run_job(req: RunRequest):
    source_type = "url" if req.source.startswith(("http://", "https://")) else "file"
    settings = config.Settings()
    if req.llm:
        settings.llm_mode = req.llm
    if req.captions:
        settings.caption_preset = req.captions
    if req.camera:
        settings.camera.speaker_change = req.camera
    
    job = job_queue.create_job(source_type, req.source, json.dumps(settings.to_json()))
    run_and_broadcast(job, command="run")
    return {"ok": True}

@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: str, req: ResumeRequest):
    job = job_queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    if req.llm or req.captions or req.camera:
        settings = config.Settings.from_json(json.loads(job.settings_json))
        if req.llm:
            settings.llm_mode = req.llm
        if req.captions:
            settings.caption_preset = req.captions
        if req.camera:
            settings.camera.speaker_change = req.camera
        
        new_json = json.dumps(settings.to_json())
        with job_queue._connect() as conn:
            conn.execute("UPDATE jobs SET settings_json = ? WHERE id = ?", (new_json, job.id))
        job = job_queue.get_job(job_id)

    run_and_broadcast(job, command="resume")
    return {"ok": True}

@app.get("/api/jobs/{job_id}/results")
async def job_results(job_id: str):
    job = job_queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    
    dir_path = Path(job.dir)
    def read_stage(name: str):
        p = dir_path / f"{name}.json"
        if p.exists():
            try:
                return json.loads(p.read_text())["data"]
            except Exception:
                return None
        return None

    return {
        "job_id": job_id,
        "dir": str(dir_path),
        "ingest": read_stage("ingest"),
        "score": read_stage("score"),
        "camera": read_stage("camera"),
        "render": read_stage("render"),
        "events": read_stage("events"),
        "candidates": read_stage("candidates"),
    }

@app.get("/api/jobs")
async def list_jobs():
    out = []
    jobs_dir = config.jobs_dir()
    if jobs_dir.exists():
        for d in jobs_dir.iterdir():
            if d.is_dir():
                id = d.name
                has_render = (d / "render.json").exists()
                has_ingest = (d / "ingest.json").exists()
                title = None
                if has_ingest:
                    try:
                        title = json.loads((d / "ingest.json").read_text())["data"]["title"]
                    except Exception:
                        pass
                out.append({
                    "id": id, "title": title,
                    "ingested": has_ingest, "rendered": has_render,
                })
    out.sort(key=lambda x: x["id"], reverse=True)
    return out

@app.post("/api/settings/gemini-key")
async def save_gemini_key(req: KeyRequest):
    home = config.home_dir()
    home.mkdir(parents=True, exist_ok=True)
    path = home / "secrets.json"
    current = {}
    if path.exists():
        current = json.loads(path.read_text())
    current["gemini_api_key"] = req.key.strip()
    path.write_text(json.dumps(current, indent=2))
    return True

@app.post("/api/settings/pexels-key")
async def save_pexels_key(req: KeyRequest):
    home = config.home_dir()
    home.mkdir(parents=True, exist_ok=True)
    path = home / "secrets.json"
    current = {}
    if path.exists():
        current = json.loads(path.read_text())
    current["pexels_api_key"] = req.key.strip()
    path.write_text(json.dumps(current, indent=2))
    return True

@app.get("/api/setup")
async def get_setup_state():
    secrets = config.home_dir() / "secrets.json"
    has_key = False
    if secrets.exists():
        try:
            has_key = bool(json.loads(secrets.read_text()).get("gemini_api_key"))
        except Exception:
            pass
    onboarded = (config.home_dir() / "onboarded").exists()
    return {"has_gemini_key": has_key, "onboarded": onboarded}

@app.post("/api/setup/onboard")
async def mark_onboarded():
    home = config.home_dir()
    home.mkdir(parents=True, exist_ok=True)
    (home / "onboarded").write_text("1")
    return {"ok": True}

@app.get("/api/ollama/status")
async def check_ollama():
    import urllib.request
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                models = [m["name"] for m in data.get("models", [])]
                return {"running": True, "models": models}
    except Exception:
        pass
    return {"running": False, "models": []}

@app.post("/api/jobs/{job_id}/edit/{edit_cmd}")
async def edit_tool(job_id: str, edit_cmd: str, req: dict = None):
    job = job_queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job_dir = Path(job.dir)

    if edit_cmd == "context":
        clip = int(req.get("clip", 0))
        return {"ok": True, **rc.context_for_clip(job_dir, clip)}

    if edit_cmd == "suggest-visuals":
        clip_idx = int(req.get("clip", 0))
        prefer = req.get("prefer", "pexels")
        score = json.loads((job_dir / "score.json").read_text())["data"]
        clip = score["clips"][clip_idx]
        edit = store.edit_for_clip(job_dir, clip_idx, clip)
        diarize = json.loads((job_dir / "diarize.json").read_text())["data"]
        words = [
            {"word": w["word"], "start": w["start"] - edit.start, "end": w["end"] - edit.start}
            for seg in diarize["segments"]
            for w in seg.get("words", [])
            if edit.start <= w["start"] < edit.end
        ]
        settings = config.Settings.from_json(json.loads(job.settings_json))
        try:
            suggestions = visuals.suggest(job_dir, words, settings.llm_mode, prefer=prefer)
        except Exception as err:
            return {"ok": False, "error": str(err)}
        
        edits = store.load(job_dir)
        current = edits.get(str(clip_idx), edit)
        known = {o.id for o in current.overlays}
        current.overlays.extend(o for o in suggestions if o.id not in known)
        edits[str(clip_idx)] = current
        store.save(job_dir, edits)
        return {"ok": True, "edit": current.to_json()}

    raise HTTPException(status_code=400, detail="Unknown edit command")

@app.post("/api/jobs/{job_id}/clips/{clip_index}/render")
async def run_edit_render(job_id: str, clip_index: int):
    job = job_queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    run_and_broadcast(job, command="render-clip", clip=clip_index)
    return {"ok": True}

@app.put("/api/jobs/{job_id}/edits")
async def save_clip_edits(job_id: str, edits: dict):
    job = job_queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    path = Path(job.dir) / "clip_edits.json"
    current = {}
    if path.exists():
        current = json.loads(path.read_text())
    
    for k, v in edits.items():
        current[k] = v
        
    path.write_text(json.dumps(current, indent=2))
    return {"ok": True}

@app.get("/api/instagram/status")
async def ig_status():
    path = config.home_dir() / "instagram.json"
    if path.exists():
        try:
            v = json.loads(path.read_text())
            return {
                "connected": True,
                "username": v.get("username"),
                "obtained_at": v.get("token_obtained_at"),
            }
        except Exception:
            pass
    return {"connected": False}

@app.post("/api/instagram/connect")
async def ig_connect(req: IgConnectRequest):
    try:
        conn = instagram.connect(req.appId, req.appSecret)
        return {"ok": True, "username": conn.get("username")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/instagram/sync")
async def ig_sync():
    summary = calibration.sync()
    return summary

@app.get("/api/instagram/overview")
async def ig_overview():
    return calibration.overview()

@app.post("/api/instagram/link")
async def ig_link(req: IgLinkRequest):
    job = job_queue.get_job(req.job_id)
    if job is None:
        return {"ok": False, "error": "job not found"}
    score_data = json.loads((Path(job.dir) / "score.json").read_text())["data"]
    clips = score_data["clips"]
    calibration.link_clip(
        req.job_id, req.clip, req.media_id, clips[req.clip],
        link_source=req.source,
        config_version=score_data.get("scoring_config_version", 1),
    )
    return {"ok": True}

@app.post("/api/instagram/unlink")
async def ig_unlink(req: IgMediaIdRequest):
    removed = calibration.unlink(req.media_id)
    return {"ok": True, "removed": removed}

@app.post("/api/instagram/reject")
async def ig_reject(req: IgRejectRequest):
    calibration.reject_match(req.media_id, req.job_id, req.clip)
    return {"ok": True}

# Serve MEDIA files
# This serves ~/.publikclip at /media
config.ensure_home()
app.mount("/media", StaticFiles(directory=str(config.home_dir())), name="media")

