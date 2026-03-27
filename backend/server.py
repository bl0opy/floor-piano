"""
FastAPI application: REST API + MJPEG video stream + WebSocket event bus.
Multi-region edition — each region plays its own note.

Architecture decisions
----------------------
- MJPEG stream keeps the frontend video element fed without WebRTC complexity.
- WebSocket carries only lightweight JSON events (region triggers, state changes).
- The CV pipeline runs in its own daemon thread; callbacks are forwarded to the
  asyncio event loop via run_coroutine_threadsafe.
"""

import asyncio
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import cv2
import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .audio_engine import AudioEngine
from .calibration import CalibrationManager
from .config_manager import (
    load_calibration, load_settings,
    save_calibration, save_settings,
)
from .cv_pipeline import DetectionPipeline
from .note_mapper import ALL_NOTES, ALL_NOTES_BY_NAME, DEFAULT_NOTES

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

# ---------------------------------------------------------------------------
# Application-level singletons
# ---------------------------------------------------------------------------

app = FastAPI(title="Floor Piano", version="2.0.0")

_calibration = CalibrationManager()
_audio = AudioEngine()
_pipeline = DetectionPipeline(_calibration)
_settings: Dict[str, Any] = {}
_clients: Set[WebSocket] = set()
_event_loop: Optional[asyncio.AbstractEventLoop] = None


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup() -> None:
    global _settings, _event_loop
    _event_loop = asyncio.get_running_loop()

    _settings = load_settings()
    cal_data = load_calibration()
    _calibration.from_dict(cal_data)

    _audio.initialize()
    threading.Thread(
        target=_audio.preload_notes,
        args=(DEFAULT_NOTES,),
        daemon=True,
        name="audio-preload",
    ).start()

    _pipeline.configure(_settings)
    _pipeline.on_region_entered = _on_region_entered
    _pipeline.on_region_exited = _on_region_exited
    _pipeline.on_key_triggered = None

    src = _settings.get("camera_source", 0)
    if isinstance(src, str) and src.isdigit():
        src = int(src)
    _pipeline.start(src)

    print("[Server] Floor Piano backend running — http://127.0.0.1:8000")


@app.on_event("shutdown")
async def _shutdown() -> None:
    _pipeline.stop()
    _audio.shutdown()


# ---------------------------------------------------------------------------
# Region enter/exit callbacks (called from CV thread)
# ---------------------------------------------------------------------------

def _on_region_entered(region_index: int) -> None:
    """Start the note assigned to the entered region and broadcast an event."""
    if region_index >= len(_calibration.regions):
        return
    note_name = _calibration.regions[region_index].note
    note = ALL_NOTES_BY_NAME.get(note_name)
    if note:
        _audio.note_on(note["name"], note["frequency"])

    event = {
        "type": "key_triggered",
        "region_index": region_index,
        "note_name": note_name,
        "note_label": note["label"] if note else note_name,
    }
    if _event_loop and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast(event), _event_loop)


def _on_region_exited(region_index: int) -> None:
    """Release the note assigned to the exited region and broadcast an event."""
    if region_index >= len(_calibration.regions):
        return
    note_name = _calibration.regions[region_index].note
    note = ALL_NOTES_BY_NAME.get(note_name)
    if note:
        _audio.note_off(note["name"])

    event = {
        "type": "key_released",
        "region_index": region_index,
        "note_name": note_name,
        "note_label": note["label"] if note else note_name,
    }
    if _event_loop and _event_loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast(event), _event_loop)


async def _broadcast(msg: Dict) -> None:
    dead: Set[WebSocket] = set()
    for ws in set(_clients):
        try:
            await ws.send_json(msg)
        except Exception:
            dead.add(ws)
    _clients.difference_update(dead)


# ---------------------------------------------------------------------------
# Static files & HTML
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((FRONTEND_DIR / "index.html").read_text())


@app.get("/game", response_class=HTMLResponse)
async def game() -> HTMLResponse:
    game_file = Path(__file__).parent.parent / "game" / "index.html"
    return HTMLResponse(game_file.read_text())


# ---------------------------------------------------------------------------
# MJPEG video stream
# ---------------------------------------------------------------------------

@app.get("/video_feed")
async def video_feed() -> StreamingResponse:
    async def _frames():
        blank = _make_blank_frame()
        try:
            while True:
                jpeg = _pipeline.get_latest_jpeg()
                if jpeg is None:
                    jpeg = blank
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
                await asyncio.sleep(1 / 30)
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        _frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


def _make_blank_frame() -> bytes:
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(img, "Waiting for camera…",
                (160, 240), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (180, 180, 180), 2)
    _, buf = cv2.imencode(".jpg", img)
    return buf.tobytes()


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    _clients.add(websocket)

    await websocket.send_json({
        "type": "state",
        **_pipeline.get_state(),
        "calibrated": _calibration.is_calibrated,
        "regions": _calibration.to_dict()["regions"],
        "available_notes": ALL_NOTES,
        "settings": _settings,
    })

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(websocket)


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

# ---------- State ----------

@app.get("/api/state")
async def api_state() -> Dict:
    return {
        **_pipeline.get_state(),
        "calibrated": _calibration.is_calibrated,
        "regions": _calibration.to_dict()["regions"],
        "available_notes": ALL_NOTES,
        "settings": _settings,
    }


# ---------- Notes ----------

@app.get("/api/notes")
async def api_notes() -> List:
    return ALL_NOTES


# ---------- Calibration ----------

class RegionPayload(BaseModel):
    points: list   # [[x,y], [x,y], [x,y], [x,y]]
    note: str


class CalibrationPayload(BaseModel):
    regions: List[RegionPayload]


@app.post("/api/calibration")
async def api_save_calibration(payload: CalibrationPayload) -> Dict:
    region_list = [{"points": r.points, "note": r.note} for r in payload.regions]
    ok = _calibration.set_regions(region_list)
    if not ok:
        return JSONResponse(
            {"success": False, "error": "Need 1–4 regions, each with exactly 4 points"},
            status_code=400,
        )

    save_calibration(_calibration.to_dict())

    # Preload the notes used by the saved regions
    notes_used = {r.note for r in _calibration.regions}
    notes_to_preload = [n for n in ALL_NOTES if n["name"] in notes_used]
    threading.Thread(target=_audio.preload_notes, args=(notes_to_preload,), daemon=True).start()

    await _broadcast({
        "type": "calibration_updated",
        "calibrated": True,
        "regions": _calibration.to_dict()["regions"],
    })
    return {"success": True, "num_regions": len(_calibration.regions)}


@app.get("/api/calibration")
async def api_get_calibration() -> Dict:
    return _calibration.to_dict()


@app.delete("/api/calibration")
async def api_clear_calibration() -> Dict:
    _calibration.regions = []
    save_calibration(_calibration.to_dict())
    await _broadcast({"type": "calibration_updated", "calibrated": False, "regions": []})
    return {"success": True}


# ---------- Settings ----------

class SettingsPayload(BaseModel):
    camera_source: Any = None
    sensitivity: Any = None
    min_blob_area: Any = None
    cooldown_ms: Any = None
    jpeg_quality: Any = None
    polyphony_limit: Any = None
    flip_horizontal: Any = None


@app.get("/api/settings")
async def api_get_settings() -> Dict:
    return _settings


@app.post("/api/settings")
async def api_save_settings(payload: SettingsPayload) -> Dict:
    global _settings
    update = {k: v for k, v in payload.dict().items() if v is not None}
    _settings.update(update)
    _pipeline.configure(_settings)
    save_settings(_settings)

    if "camera_source" in update:
        src = update["camera_source"]
        if isinstance(src, str) and src.isdigit():
            src = int(src)
        threading.Thread(
            target=lambda: _pipeline.restart_camera(src), daemon=True
        ).start()

    return {"success": True, "settings": _settings}


# ---------- Detection control ----------

@app.post("/api/detection/start")
async def api_detection_start() -> Dict:
    _pipeline.enable_detection(True)
    await _broadcast({"type": "detection_state", "enabled": True})
    return {"success": True}


@app.post("/api/detection/stop")
async def api_detection_stop() -> Dict:
    _pipeline.enable_detection(False)
    await _broadcast({"type": "detection_state", "enabled": False})
    return {"success": True}


@app.post("/api/detection/reset_background")
async def api_reset_background() -> Dict:
    was_on = _pipeline._detection_enabled
    _pipeline.enable_detection(False)
    await asyncio.sleep(0.05)
    _pipeline.enable_detection(was_on)
    return {"success": True}
