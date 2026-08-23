"""publikclip web backend.

Replaces the Tauri/Rust shell with a FastAPI server that:
 - exposes the same operations as HTTP endpoints
 - streams pipeline progress over WebSocket
 - serves rendered clip files at /media/
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ---- resolve the pipeline package ------------------------------------------
# The pipeline lives at ../pipeline relative to this file. Add it to sys.path
# so we can import it directly (same as the Tauri shell did via `uv run`).
BACKEND_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = BACKEND_DIR.parent / "pipeline"
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

# ---- hotfix: speechbrain lazy module inspector crash -----------------------
# When tools like uvicorn watchfiles or sklearn threadpoolctl scan sys.modules,
# they check hasattr(module, '__file__'). SpeechBrain's k2_fsa LazyModule
# intercepts this, fails to load k2, and throws an ImportError that crashes
# the pipeline. We patch it to correctly raise AttributeError for '__file__'.
try:
    import speechbrain.utils.importutils
    _orig_getattr = speechbrain.utils.importutils.LazyModule.__getattr__
    def _safe_getattr(self, item):
        if item == "__file__":
            raise AttributeError()
        return _orig_getattr(self, item)
    speechbrain.utils.importutils.LazyModule.__getattr__ = _safe_getattr
except ImportError:
    pass

from publikclip_pipeline import config  # noqa: E402
# Force reload to pick up ytdlp.py changes
from publikclip_pipeline.jobs import queue  # noqa: E402

# ---- app setup -------------------------------------------------------------
app = FastAPI(title="publikclip", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- WebSocket hub for pipeline events ------------------------------------
_ws_clients: set[WebSocket] = set()
_ws_lock = threading.Lock()


async def _broadcast(payload: dict) -> None:
    """Send a JSON event to every connected WebSocket client."""
    data = json.dumps(payload)
    with _ws_lock:
        clients = list(_ws_clients)
    for ws in clients:
        try:
            await ws.send_text(data)
        except Exception:
            with _ws_lock:
                _ws_clients.discard(ws)


def _broadcast_sync(payload: dict) -> None:
    """Thread-safe broadcast from a non-async context (pipeline threads)."""
    data = json.dumps(payload)
    with _ws_lock:
        clients = list(_ws_clients)
    for ws in clients:
        try:
            asyncio.run_coroutine_threadsafe(ws.send_text(data), _loop)
        except Exception:
            with _ws_lock:
                _ws_clients.discard(ws)


_loop: asyncio.AbstractEventLoop  # set in startup


@app.on_event("startup")
async def _capture_loop() -> None:
    global _loop
    _loop = asyncio.get_running_loop()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    with _ws_lock:
        _ws_clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive; we don't need client msgs
    except WebSocketDisconnect:
        pass
    finally:
        with _ws_lock:
            _ws_clients.discard(ws)


# ---- helpers ---------------------------------------------------------------
def _home() -> Path:
    return config.home_dir()


def _stages():
    """Lazy-load the pipeline stages (avoids paying the torch import tax at startup)."""
    from publikclip_pipeline.asr.stage import AsrStage
    from publikclip_pipeline.camera.stage import CameraStage
    from publikclip_pipeline.candidates.stage import CandidatesStage
    from publikclip_pipeline.diarize.stage import DiarizeStage
    from publikclip_pipeline.events.stage import EventsStage
    from publikclip_pipeline.ingest.stage import IngestStage
    from publikclip_pipeline.render.stage import RenderStage
    from publikclip_pipeline.scoring.stage import ScoreStage

    return [
        IngestStage(),
        AsrStage(),
        DiarizeStage(),
        EventsStage(),
        CandidatesStage(),
        ScoreStage(),
        CameraStage(),
        RenderStage(),
    ]


def _read_stage(job_dir: Path, name: str):
    """Read a checkpoint file and return its data section, or None."""
    path = job_dir / f"{name}.json"
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text(errors="replace"))
        return envelope.get("data")
    except (json.JSONDecodeError, OSError):
        return None


# ---- API endpoints ---------------------------------------------------------

# -- Setup & Settings --

@app.get("/api/setup")
def get_setup():
    secrets = _home() / "secrets.json"
    has_key = False
    if secrets.exists():
        try:
            data = json.loads(secrets.read_text(errors="replace"))
            has_key = bool(data.get("gemini_api_key", "").strip())
        except Exception:
            pass
    onboarded = (_home() / "onboarded").exists()
    return {"has_gemini_key": has_key, "onboarded": onboarded}


@app.post("/api/setup/onboard")
def mark_onboarded():
    config.ensure_home()
    (_home() / "onboarded").write_text("1")
    return {"ok": True}


@app.post("/api/settings/gemini-key")
async def save_gemini_key(body: dict):
    key = body.get("key", "").strip()
    if not key:
        raise HTTPException(400, "key is required")
    config.ensure_home()
    path = _home() / "secrets.json"
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(errors="replace"))
        except Exception:
            pass
    current["gemini_api_key"] = key
    path.write_text(json.dumps(current, indent=2))
    return True


@app.post("/api/settings/pexels-key")
async def save_pexels_key(body: dict):
    key = body.get("key", "").strip()
    if not key:
        raise HTTPException(400, "key is required")
    config.ensure_home()
    path = _home() / "secrets.json"
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(errors="replace"))
        except Exception:
            pass
    current["pexels_api_key"] = key
    path.write_text(json.dumps(current, indent=2))
    return True


@app.get("/api/ollama/status")
def check_ollama():
    import subprocess
    try:
        out = subprocess.run(
            ["curl", "-s", "-m", "3", "http://localhost:11434/api/tags"],
            capture_output=True, timeout=5,
        )
        if out.returncode != 0:
            return {"running": False, "models": []}
        data = json.loads(out.stdout)
        models = [m["name"] for m in data.get("models", [])]
        return {"running": True, "models": models}
    except Exception:
        return {"running": False, "models": []}


# -- Jobs --

@app.get("/api/jobs")
def list_jobs():
    jobs_dir = _home() / "jobs"
    out = []
    if jobs_dir.exists():
        for entry in jobs_dir.iterdir():
            if not entry.is_dir():
                continue
            job_id = entry.name
            has_render = (entry / "render.json").exists()
            has_ingest = (entry / "ingest.json").exists()
            title = None
            if has_ingest:
                try:
                    d = json.loads((entry / "ingest.json").read_text(errors="replace"))
                    title = d.get("data", {}).get("title")
                except Exception:
                    pass
            out.append({
                "id": job_id,
                "title": title,
                "ingested": has_ingest,
                "rendered": has_render,
            })
    out.sort(key=lambda x: x["id"], reverse=True)
    return out


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    import shutil
    job_dir = _home() / "jobs" / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)
    return {"status": "ok"}


@app.get("/api/jobs/{job_id}/results")
def job_results(job_id: str):
    job_dir = _home() / "jobs" / job_id
    if not job_dir.exists():
        raise HTTPException(404, f"no job dir for {job_id}")
    return {
        "job_id": job_id,
        "dir": str(job_dir),
        "ingest": _read_stage(job_dir, "ingest"),
        "score": _read_stage(job_dir, "score"),
        "camera": _read_stage(job_dir, "camera"),
        "render": _read_stage(job_dir, "render"),
        "events": _read_stage(job_dir, "events"),
        "candidates": _read_stage(job_dir, "candidates"),
    }


def _run_pipeline_thread(job: queue.Job, stages_to_run: list | None = None, source: str = "studio") -> None:
    """Run the pipeline in a background thread, broadcasting progress via WS."""
    def emit(stage: str, fraction: float, message: str) -> None:
        _broadcast_sync({
            "event": "progress",
            "job_id": job.id,
            "stage": stage,
            "fraction": fraction,
            "message": message,
            "source": source,
        })

    _broadcast_sync({"event": "job", "job_id": job.id, "dir": str(job.dir), "source": source})
    try:
        results = queue.run_stages(job, stages_to_run or _stages(), emit)
        summary = {
            "event": "result",
            "ok": True,
            "job_id": job.id,
            "stages": list(results.keys()),
            "title": results.get("ingest", {}).get("title"),
            "source": source,
        }
        _broadcast_sync(summary)
    except Exception as err:
        _broadcast_sync({
            "event": "result",
            "ok": False,
            "job_id": job.id,
            "error": str(err),
        })


@app.post("/api/jobs")
async def run_job(body: dict):
    source = body.get("source", "")
    llm = body.get("llm")
    gemini_model = body.get("gemini_model")
    captions = body.get("captions")
    asr_model = body.get("asr_model")
    if not source:
        raise HTTPException(400, "source is required")

    source_type = "url" if source.startswith(("http://", "https://")) else "file"
    settings = config.Settings()
    if llm:
        settings.llm_mode = llm
    if gemini_model:
        settings.gemini_model = gemini_model
    if captions:
        settings.caption_preset = captions
    if asr_model:
        settings.asr_model = asr_model

    job = queue.create_job(source_type, source, json.dumps(settings.to_json()))
    
    # Studio pipeline skips ingest and asr stages because they are handled by the Queue
    studio_stages = [s for s in _stages() if s.name not in ("ingest", "asr")]
    threading.Thread(target=_run_pipeline_thread, args=(job, studio_stages), daemon=True).start()
    
    # Wait for the file to be ingested before returning the job ID
    # (The shell used to do this synchronously too)
    while True:
        if (job.dir / "ingest.json").exists() or (job.dir / "asr.json").exists() or (job.dir / "diarize.json").exists():
            break
        import time
        time.sleep(0.1)

    return {"ok": True, "job_id": job.id}


# -- Queue --

@app.get("/api/queue/pending_download")
def get_queue_pending_download():
    from publikclip_pipeline.campaigns import store
    videos = []
    for c in store.list_campaigns():
        cvs = store.campaign_videos(c["id"])
        for cv in cvs:
            # Check if job exists and has ingest
            has_ingest = False
            if cv.get("job_id"):
                job_dir = _home() / "jobs" / cv["job_id"]
                if job_dir.exists() and (job_dir / "ingest.json").exists():
                    has_ingest = True
            
            if not has_ingest:
                videos.append({
                    "campaign_id": c["id"],
                    "campaign_name": c["name"],
                    "video_url": cv.get("video_url"),
                    "title": cv.get("title"),
                    "job_id": cv.get("job_id"),
                })
    return videos

@app.get("/api/queue/pending_transcribe")
def get_queue_pending_transcribe():
    from publikclip_pipeline.campaigns import store
    videos = []
    for c in store.list_campaigns():
        cvs = store.campaign_videos(c["id"])
        for cv in cvs:
            # Check if job exists, has ingest, but NO asr
            has_ingest = False
            has_asr = False
            if cv.get("job_id"):
                job_dir = _home() / "jobs" / cv["job_id"]
                if job_dir.exists():
                    if (job_dir / "ingest.json").exists():
                        has_ingest = True
                    if (job_dir / "asr.json").exists():
                        has_asr = True
            
            if has_ingest and not has_asr:
                videos.append({
                    "campaign_id": c["id"],
                    "campaign_name": c["name"],
                    "video_url": cv.get("video_url"),
                    "title": cv.get("title"),
                    "job_id": cv.get("job_id"),
                })
    return videos


def _get_or_create_job_for_queue(body: dict):
    from publikclip_pipeline.campaigns import store
    video_url = body.get("video_url")
    campaign_id = body.get("campaign_id")
    if not video_url:
        raise HTTPException(400, "video_url is required")
        
    settings = config.Settings()
    
    # Do we have an existing job for this video?
    job_id = None
    if campaign_id:
        cvs = store.campaign_videos(campaign_id)
        for cv in cvs:
            if cv["video_url"] == video_url:
                job_id = cv.get("job_id")
                break
                
    if job_id:
        job = queue.get_job(job_id)
        if not job:
            job = queue.create_job("url", video_url, json.dumps(settings.to_json()))
    else:
        job = queue.create_job("url", video_url, json.dumps(settings.to_json()))
        if campaign_id:
            # Update the video record with the new job_id
            with store._connect() as conn:
                conn.execute(
                    "UPDATE campaign_videos SET job_id = ? WHERE campaign_id = ? AND video_url = ?",
                    (job.id, campaign_id, video_url)
                )
    return job

@app.post("/api/queue/run_download")
async def run_queue_download(body: dict):
    job = _get_or_create_job_for_queue(body)
    queue_stages = [s for s in _stages() if s.name == "ingest"]
    
    def _run_download():
        _run_pipeline_thread(job, queue_stages, source="queue")
        
    threading.Thread(target=_run_download, daemon=True).start()
    return {"ok": True, "job_id": job.id}

@app.post("/api/queue/run_transcribe")
async def run_queue_transcribe(body: dict):
    job = _get_or_create_job_for_queue(body)
    queue_stages = [s for s in _stages() if s.name in ("ingest", "asr")]
    
    def _run_and_upload():
        _run_pipeline_thread(job, queue_stages, source="queue")
        # Azure cloud sync
        azure_url = os.environ.get("AZURE_SYNC_URL")
        if azure_url:
            try:
                import requests
                print(f"Syncing {job.id} to Azure...")
                mp4_path = job.dir / "video.mp4"
                asr_path = job.dir / "asr.json"
                files = {}
                if mp4_path.exists():
                    files["video"] = open(mp4_path, "rb")
                if asr_path.exists():
                    files["transcript"] = open(asr_path, "rb")
                if files:
                    requests.post(azure_url, files=files, data={"job_id": job.id})
                    print(f"Synced {job.id} to Azure successfully.")
            except Exception as e:
                print(f"Failed to sync {job.id} to Azure: {e}")
        
    threading.Thread(target=_run_and_upload, daemon=True).start()
    return {"ok": True, "job_id": job.id}


@app.post("/api/jobs/upload")
async def upload_and_run(
    video: UploadFile = File(...),
    llm: str = "gemini",
    gemini_model: str | None = None,
    captions: str = "classic",
    asr_model: str | None = None,
):
    """Accept a video file upload, save to a temp location, and start a job."""
    config.ensure_home()
    upload_dir = _home() / "uploads"
    upload_dir.mkdir(exist_ok=True)

    dest = upload_dir / video.filename
    with open(dest, "wb") as f:
        content = await video.read()
        f.write(content)

    settings = config.Settings()
    settings.llm_mode = llm
    if gemini_model:
        settings.gemini_model = gemini_model
    settings.caption_preset = captions
    if asr_model:
        settings.asr_model = asr_model

    job = queue.create_job("file", str(dest), json.dumps(settings.to_json()))
    threading.Thread(target=_run_pipeline_thread, args=(job,), daemon=True).start()
    return {"ok": True, "job_id": job.id}


@app.post("/api/jobs/{job_id}/resume")
async def resume_job(job_id: str, body: dict | None = None):
    body = body or {}
    job = queue.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"No job {job_id}")

    llm = body.get("llm")
    gemini_model = body.get("gemini_model")
    captions_val = body.get("captions")
    camera = body.get("camera")
    asr_model = body.get("asr_model")
    if llm or gemini_model or captions_val or camera or asr_model:
        settings = config.Settings.from_json(json.loads(job.settings_json))
        if llm:
            settings.llm_mode = llm
        if gemini_model:
            settings.gemini_model = gemini_model
        if captions_val:
            settings.caption_preset = captions_val
        if camera:
            settings.camera.speaker_change = camera
        if asr_model:
            settings.asr_model = asr_model
        new_json = json.dumps(settings.to_json())
        with queue._connect() as conn:
            conn.execute("UPDATE jobs SET settings_json = ? WHERE id = ?", (new_json, job.id))
        job = queue.get_job(job_id)

    threading.Thread(target=_run_pipeline_thread, args=(job,), daemon=True).start()
    return {"ok": True, "job_id": job_id}


# -- Clip editing --

@app.post("/api/jobs/{job_id}/edit/{edit_cmd}")
async def edit_tool(job_id: str, edit_cmd: str, body: dict | None = None):
    """Synchronous edit commands: context, suggest-visuals."""
    body = body or {}
    job = queue.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")

    job_dir = Path(job.dir)
    clip = body.get("clip", 0)

    if edit_cmd == "context":
        from publikclip_pipeline.edits import render_clip as rc
        return {"ok": True, **rc.context_for_clip(job_dir, clip)}

    if edit_cmd == "suggest-visuals":
        from publikclip_pipeline.edits import store, visuals
        score = json.loads((job_dir / "score.json").read_text(errors="replace"))["data"]
        clip_data = score["clips"][clip]
        edit = store.edit_for_clip(job_dir, clip, clip_data)
        diarize = json.loads((job_dir / "diarize.json").read_text(errors="replace"))["data"]
        words = [
            {"word": w["word"], "start": w["start"] - edit.start, "end": w["end"] - edit.start}
            for seg in diarize["segments"]
            for w in seg.get("words", [])
            if edit.start <= w["start"] < edit.end
        ]
        settings = config.Settings.from_json(json.loads(job.settings_json))
        prefer = body.get("prefer", "pexels")
        try:
            suggestions = visuals.suggest(job_dir, words, settings.llm_mode, prefer=prefer)
        except Exception as err:
            return {"ok": False, "error": str(err)}
        edits = store.load(job_dir)
        current = edits.get(str(clip), edit)
        known = {o.id for o in current.overlays}
        current.overlays.extend(o for o in suggestions if o.id not in known)
        edits[str(clip)] = current
        store.save(job_dir, edits)
        return {"ok": True, "edit": current.to_json()}

    raise HTTPException(400, f"unknown edit command: {edit_cmd}")


@app.post("/api/jobs/{job_id}/clips/{clip_index}/render")
async def render_clip(job_id: str, clip_index: int):
    """Start a clip re-render in a background thread with WS progress."""
    job = queue.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")

    def do_render():
        from publikclip_pipeline.edits import render_clip as rc
        job_dir = Path(job.dir)

        def emit(fraction: float, message: str):
            _broadcast_sync({
                "event": "progress",
                "stage": "render",
                "fraction": fraction,
                "message": message,
            })

        try:
            entry = rc.render_clip_edit(job_dir, clip_index, lambda f, m: emit(f, m))
            _broadcast_sync({"event": "result", "ok": True, "output": entry})
        except Exception as err:
            _broadcast_sync({"event": "result", "ok": False, "error": str(err)})

    threading.Thread(target=do_render, daemon=True).start()
    return {"ok": True}


@app.put("/api/jobs/{job_id}/edits")
async def save_clip_edits(job_id: str, body: dict):
    job_dir = _home() / "jobs" / job_id
    if not job_dir.exists():
        raise HTTPException(404, f"no job {job_id}")
    path = job_dir / "clip_edits.json"
    current = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(errors="replace"))
        except Exception:
            pass
    if isinstance(body, dict):
        current.update(body)
    path.write_text(json.dumps(current, indent=2))
    return {"ok": True}


# -- Export --

@app.get("/api/jobs/{job_id}/clips/{clip_index}/download")
async def download_clip(job_id: str, clip_index: int, title: str | None = None):
    """Serve a rendered clip file for browser download."""
    job_dir = _home() / "jobs" / job_id
    render_data = _read_stage(job_dir, "render")
    if not render_data:
        raise HTTPException(404, "no render data")
    outputs = render_data.get("outputs", [])
    match = next((o for o in outputs if o.get("clip") == clip_index), None)
    if not match:
        raise HTTPException(404, f"no output for clip {clip_index}")
    clip_path = Path(match["path"])
    if not clip_path.exists():
        raise HTTPException(404, "clip file missing")
    filename = f"{title or 'publikclip-clip'}.mp4"
    return FileResponse(clip_path, media_type="video/mp4", filename=filename)


# -- Instagram --

@app.get("/api/instagram/status")
def ig_status():
    path = _home() / "instagram.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(errors="replace"))
            return {"connected": True, "username": data.get("username")}
        except Exception:
            pass
    return {"connected": False}


@app.post("/api/instagram/connect")
async def ig_connect(body: dict):
    from publikclip_pipeline.insights import instagram
    app_id = body.get("appId", "")
    app_secret = body.get("appSecret", "")
    if not app_id or not app_secret:
        raise HTTPException(400, "appId and appSecret required")
    try:
        conn = instagram.connect(app_id, app_secret)
        return {"ok": True, "username": conn.get("username")}
    except Exception as err:
        raise HTTPException(500, str(err))


@app.post("/api/instagram/sync")
def ig_sync():
    from publikclip_pipeline.insights import calibration
    return calibration.sync()


@app.get("/api/instagram/overview")
def ig_overview():
    from publikclip_pipeline.insights import calibration
    return calibration.overview()


@app.post("/api/instagram/link")
async def ig_link(body: dict):
    from publikclip_pipeline.insights import calibration
    job_id = body["job_id"]
    clip = body["clip"]
    media_id = body["media_id"]
    source = body.get("source", "manual")
    job = queue.get_job(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")
    score_data = queue.read_checkpoint(job, "score", 1)
    if not score_data:
        raise HTTPException(400, "job has no score checkpoint")
    clips = score_data["clips"]
    if not 0 <= clip < len(clips):
        raise HTTPException(400, f"clip index out of range (0..{len(clips) - 1})")
    calibration.link_clip(
        job_id, clip, media_id, clips[clip],
        link_source=source,
        config_version=score_data.get("scoring_config_version", 1),
    )
    return {"ok": True}


@app.post("/api/instagram/unlink")
async def ig_unlink(body: dict):
    from publikclip_pipeline.insights import calibration
    removed = calibration.unlink(body["media_id"])
    return {"ok": True, "removed": removed}


@app.post("/api/instagram/reject")
async def ig_reject(body: dict):
    from publikclip_pipeline.insights import calibration
    calibration.reject_match(body["media_id"], body["job_id"], body["clip"])
    return {"ok": True}


# -- Campaigns & Analytics --

@app.get("/api/campaigns")
def list_campaigns():
    from publikclip_pipeline.campaigns import store
    return store.list_campaigns()

@app.post("/api/campaigns")
def create_campaign(body: dict):
    from publikclip_pipeline.campaigns import store
    name = body.get("name")
    if not name:
        raise HTTPException(400, "name required")
    return store.create_campaign(name, body.get("description", ""), body.get("rules", ""))

@app.get("/api/campaigns/{campaign_id}")
def get_campaign(campaign_id: str):
    from publikclip_pipeline.campaigns import store
    c = store.get_campaign(campaign_id)
    if not c:
        raise HTTPException(404, "campaign not found")
        
    # Check local job status for videos
    for v in c.get("videos", []):
        job_id = v.get("job_id")
        has_ingest = False
        has_asr = False
        if job_id:
            job_dir = _home() / "jobs" / job_id
            if job_dir.exists():
                if (job_dir / "ingest.json").exists():
                    has_ingest = True
                if (job_dir / "asr.json").exists():
                    has_asr = True
        v["has_ingest"] = has_ingest
        v["has_asr"] = has_asr
        
    # Include moments too
    c["moments"] = store.campaign_moments(campaign_id, limit=100)
    return c

@app.put("/api/campaigns/{campaign_id}")
def update_campaign(campaign_id: str, body: dict):
    from publikclip_pipeline.campaigns import store
    if not store.update_campaign(campaign_id, body.get("name"), body.get("description"), body.get("rules")):
        raise HTTPException(404, "campaign not found")
    return {"ok": True}

@app.delete("/api/campaigns/{campaign_id}")
def delete_campaign(campaign_id: str):
    from publikclip_pipeline.campaigns import store
    store.delete_campaign(campaign_id)
    return {"ok": True}

@app.post("/api/campaigns/{campaign_id}/videos")
def add_campaign_video(campaign_id: str, body: dict):
    from publikclip_pipeline.campaigns import store, transcripts
    url = body.get("url")
    if not url:
        raise HTTPException(400, "url required")
    # Quick metadata fetch if possible, else just add
    try:
        from publikclip_pipeline.ingest import ytdlp
        meta = ytdlp.fetch_meta(url, lambda f, m: None)
        video = store.add_video(
            campaign_id, url,
            title=meta.title,
            duration_sec=meta.duration_sec,
            channel_subscribers=meta.raw.get("channel_follower_count"),
            channel=meta.raw.get("channel") or meta.raw.get("uploader")
        )
    except Exception:
        video = store.add_video(campaign_id, url)
    return video

@app.delete("/api/campaigns/{campaign_id}/videos/{video_id}")
def delete_campaign_video(campaign_id: str, video_id: int):
    from publikclip_pipeline.campaigns import store
    store.remove_video(campaign_id, video_id)
    return {"ok": True}

@app.get("/api/campaigns/{campaign_id}/transcripts")
def get_campaign_transcripts(campaign_id: str, q: str | None = None):
    from publikclip_pipeline.campaigns import store
    if q:
        return store.search_transcripts(campaign_id, q)
    return store.campaign_transcripts(campaign_id)

@app.post("/api/campaigns/{campaign_id}/clips")
def add_campaign_clip(campaign_id: str, body: dict):
    from publikclip_pipeline.campaigns import store
    role = body.get("role", "mine")
    if "clip_url" not in body:
        raise HTTPException(400, "clip_url required")
    return store.add_clip(campaign_id, role, **body)

@app.put("/api/campaigns/{campaign_id}/clips/{clip_id}")
def update_campaign_clip(campaign_id: str, clip_id: int, body: dict):
    from publikclip_pipeline.campaigns import store
    if not store.update_clip(clip_id, **body):
        raise HTTPException(404, "clip not found")
    return {"ok": True}

@app.delete("/api/campaigns/{campaign_id}/clips/{clip_id}")
def delete_campaign_clip(campaign_id: str, clip_id: int):
    from publikclip_pipeline.campaigns import store
    store.delete_clip(clip_id)
    return {"ok": True}

@app.post("/api/campaigns/{campaign_id}/clips/analyze")
def api_analyze_clip(campaign_id: str, body: dict):
    from publikclip_pipeline.campaigns import clip_analyzer, store
    url = body.get("url")
    role = body.get("role", "competitor")
    if not url:
        raise HTTPException(400, "url required")
        
    def _do_analyze():
        def emit(fraction: float, message: str):
            _broadcast_sync({
                "event": "progress",
                "stage": "clip_analysis",
                "campaign_id": campaign_id,
                "url": url,
                "fraction": fraction,
                "message": message
            })
            
        try:
            result = clip_analyzer.analyze_clip(campaign_id, url, role, emit)
            clip = store.add_clip_from_analysis(campaign_id, result)
            _broadcast_sync({
                "event": "result",
                "ok": True,
                "stage": "clip_analysis",
                "campaign_id": campaign_id,
                "url": url,
                "clip": clip,
            })
        except Exception as err:
            _broadcast_sync({
                "event": "result",
                "ok": False,
                "stage": "clip_analysis",
                "campaign_id": campaign_id,
                "url": url,
                "error": str(err)
            })
            
    threading.Thread(target=_do_analyze, daemon=True).start()
    return {"ok": True, "message": "Analysis started"}

@app.post("/api/campaigns/{campaign_id}/clips/import-csv")
async def api_import_clips_csv(campaign_id: str, request: Request):
    from publikclip_pipeline.campaigns import store
    import csv
    import io
    
    body = await request.body()
    try:
        text = body.decode('utf-8')
        reader = csv.DictReader(io.StringIO(text))
        
        updated_count = 0
        for row in reader:
            # Map YouTube Studio CSV headers to our fields
            # E.g. "Video Title", "Views", "Average percentage viewed (%)"
            title = row.get("Video title", row.get("Video Title", ""))
            
            # Find the clip by title or another identifier (we might need to search by title)
            clips = store.campaign_clips(campaign_id)
            match = next((c for c in clips if title in (c.get("title") or "")), None)
            
            if match:
                updates = {}
                
                # Helper to safely parse numbers
                def parse_num(val):
                    try:
                        return float(val.replace(',', '').replace('%', ''))
                    except:
                        return None
                        
                views = parse_num(row.get("Views", ""))
                if views is not None:
                    updates["views"] = int(views)
                    
                likes = parse_num(row.get("Likes", ""))
                if likes is not None:
                    updates["likes"] = int(likes)
                    
                watch_pct = parse_num(row.get("Average percentage viewed (%)", ""))
                if watch_pct is not None:
                    updates["watch_time_pct"] = watch_pct
                    
                avg_view_dur = row.get("Average view duration", "")
                if avg_view_dur:
                    parts = avg_view_dur.split(':')
                    if len(parts) == 3: # hh:mm:ss
                        updates["avg_view_duration_sec"] = int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
                        
                impressions = parse_num(row.get("Impressions", ""))
                if impressions is not None:
                    updates["impressions"] = int(impressions)
                    
                ctr = parse_num(row.get("Impressions click-through rate (%)", ""))
                if ctr is not None:
                    updates["ctr"] = ctr
                    
                if updates:
                    store.update_clip(match["id"], **updates)
                    updated_count += 1
                    
        return {"ok": True, "updated": updated_count}
    except Exception as e:
        raise HTTPException(400, f"Failed to parse CSV: {str(e)}")

@app.post("/api/campaigns/{campaign_id}/analyze")
async def analyze_campaign(campaign_id: str, request: Request):
    """Trigger the pipeline to extract and score clips for a campaign."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
        
    from publikclip_pipeline.campaigns import analyzer
    llm = body.get("llm_mode", "gemini")
    gemini_model = body.get("gemini_model", "gemini-3.6-flash")
    video_urls = body.get("video_urls", None)
    
    def _do_analyze():
        def emit(fraction: float, message: str):
            _broadcast_sync({
                "event": "progress",
                "stage": "analysis",
                "campaign_id": campaign_id,
                "fraction": fraction,
                "message": message
            })

        try:
            count = analyzer.prepare_analysis(campaign_id, llm, gemini_model, emit, video_urls)
            
            # Auto-run the LLM scoring step without requiring manual MCP intervention
            from publikclip_pipeline import config
            import json
            pending_file = config.jobs_dir() / campaign_id / "pending_scoring.json"
            
            if pending_file.exists():
                from publikclip_pipeline.scoring import llm as llm_mod, rubric
                from concurrent.futures import ThreadPoolExecutor
                
                candidates = json.loads(pending_file.read_text(errors="replace"))
                emit(0.2, f"Starting AI scoring for {len(candidates)} candidates...")
                
                client = llm_mod.make_client(llm, gemini_model)
                
                def score_candidate(c):
                    text = c.get("transcript_text", "")
                    context = {"duration": c.get("end_sec", 0) - c.get("start_sec", 0), "events_desc": "none detected"}
                    prompt = rubric.t1_prompt(text, context)
                    try:
                        scored = client.generate_json(prompt, rubric.T1_SCHEMA)
                        c["t1_raw"] = scored
                        c["llm_hook_score"] = scored.get("hook", 0)
                        c["llm_funniness"] = scored.get("funniness", 0)
                        c["llm_shock"] = scored.get("shock", 0)
                        c["llm_curiosity_gap"] = scored.get("curiosity_gap", 0)
                        c["llm_value_score"] = scored.get("value", 0)
                        c["llm_summary"] = scored.get("summary", "")
                        c["llm_self_contained"] = scored.get("self_contained", True)
                        c["llm_hook_type"] = scored.get("hook_type", "none")
                    except Exception as e:
                        print(f"Error scoring candidate: {e}")
                    return c

                scored_candidates = []
                completed = 0
                with ThreadPoolExecutor(max_workers=5) as ex:
                    for c in ex.map(score_candidate, candidates):
                        scored_candidates.append(c)
                        completed += 1
                        if completed % 5 == 0 or completed == len(candidates):
                            emit(0.2 + (0.6 * (completed / max(1, len(candidates)))), f"Scored {completed}/{len(candidates)} moments...")

                emit(0.85, "Finalizing analysis...")
                analyzer.complete_analysis(campaign_id, scored_candidates, progress=emit)

            _broadcast_sync({
                "event": "result",
                "ok": True,
                "stage": "analysis_prepared",
                "campaign_id": campaign_id,
                "count": count,
                "message": "Analysis fully completed!"
            })
        except Exception as err:
            _broadcast_sync({
                "event": "result",
                "ok": False,
                "stage": "analysis_prepared",
                "campaign_id": campaign_id,
                "error": str(err),
            })
    threading.Thread(target=_do_analyze, daemon=True).start()
    return {"ok": True}

@app.get("/api/campaigns/{campaign_id}/moments")
def get_campaign_moments(campaign_id: str, unclipped: bool = False):
    from publikclip_pipeline.campaigns import store
    return store.campaign_moments(campaign_id, unclipped_only=unclipped)

@app.get("/api/campaigns/{campaign_id}/hooks")
def get_campaign_hooks(campaign_id: str):
    from publikclip_pipeline.campaigns import store
    clips = store.campaign_clips(campaign_id)
    # Aggregate by template
    templates = {}
    for c in clips:
        if c.get("views") and c.get("hook_template"):
            t = c["hook_template"]
            if t not in templates:
                templates[t] = {"count": 0, "total_views": 0, "clips": []}
            templates[t]["count"] += 1
            templates[t]["total_views"] += c["views"]
            templates[t]["clips"].append({
                "text": c.get("hook_text"),
                "views": c["views"],
                "role": c.get("role")
            })
            
    result = []
    for t, data in templates.items():
        data["clips"].sort(key=lambda x: x["views"], reverse=True)
        result.append({
            "template": t,
            "count": data["count"],
            "avg_views": round(data["total_views"] / data["count"]),
            "top_clips": data["clips"][:3]
        })
    result.sort(key=lambda x: x["avg_views"], reverse=True)
    return result

@app.get("/api/campaigns/{campaign_id}/insights")
def get_campaign_insights(campaign_id: str):
    from publikclip_pipeline.campaigns import store, learning
    weights = learning.compute_feature_weights(campaign_id)
    # Just return the feature importances for now, we can add LLM summary later
    return {"feature_weights": weights}


# -- Media file serving ------------------------------------------------------

# This replaces Tauri's convertFileSrc().

@app.get("/media/{path:path}")
async def serve_media(path: str):
    """Serve files from PUBLIKCLIP_HOME. The frontend requests paths relative
    to the home dir (e.g. /media/jobs/<id>/render_0.mp4)."""
    full = _home() / path
    if not full.exists():
        raise HTTPException(404, "file not found")
    # Determine content type from extension
    ext = full.suffix.lower()
    ct_map = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".json": "application/json",
    }
    content_type = ct_map.get(ext, "application/octet-stream")
    return FileResponse(full, media_type=content_type)

# -- Static Frontend serving for Azure --
@app.exception_handler(404)
async def custom_404_handler(request, exc):
    frontend_dist = BACKEND_DIR.parent / "app" / "dist"
    index = frontend_dist / "index.html"
    
    # If the user is requesting an API route that doesn't exist, return JSON 404
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
        
    # If they are requesting a file that exists in dist, serve it
    file_path = frontend_dist / request.url.path.lstrip("/")
    if file_path.is_file():
        return FileResponse(file_path)
        
    # Otherwise, fallback to index.html for React Router
    if index.exists():
        return FileResponse(index)
        
    return JSONResponse({"detail": "Not Found"}, status_code=404)
