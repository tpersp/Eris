import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl
from starlette.routing import Mount

from adapters.chromium import ChromiumAdapter
from adapters.media_stub import list_media, play
from models.state import ErisState
from utils.system import (
    get_cpu_percent,
    get_memory_percent,
    get_temperature,
    load_config,
    set_display_blank,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("eris.daemon")

CONFIG = load_config()
ERIS_VERSION = "0.1.0"
START_TIME = time.time()

app = FastAPI(title="Eris Core Daemon", version=ERIS_VERSION)

WEBUI_PATH = "/opt/eris/apps/webui/dist"
if os.path.isdir(WEBUI_PATH):
    app.mount("/", StaticFiles(directory=WEBUI_PATH, html=True), name="webui")
    print(f"Serving Web UI from {WEBUI_PATH}")
else:
    print(f"⚠️  Web UI directory not found: {WEBUI_PATH}")

api_router = APIRouter(prefix="/api")
state = ErisState(mode="web", url=CONFIG["device"]["homepage"])

chromium_adapter = ChromiumAdapter(
    homepage=CONFIG["device"]["homepage"],
    flags_file=CONFIG["chromium"]["flags_file"],
    binary=CONFIG["chromium"].get("binary", "/usr/bin/chromium-browser"),
    logger=logging.getLogger("eris.chromium"),
)

ws_clients: Set[WebSocket] = set()
ws_lock = asyncio.Lock()
health_task: Optional[asyncio.Task] = None


class NavigateRequest(BaseModel):
    url: HttpUrl


class WebActionRequest(BaseModel):
    cmd: str

    def validate_command(self) -> str:
        valid_commands = {"reload", "back", "forward", "home"}
        if self.cmd not in valid_commands:
            raise ValueError(f"Invalid command '{self.cmd}'.")
        return self.cmd


class DisplayBlankRequest(BaseModel):
    on: bool


class MediaPlayRequest(BaseModel):
    path: str


def compute_uptime() -> float:
    return time.time() - START_TIME


def build_health_payload() -> Dict[str, float]:
    return {
        "uptime": compute_uptime(),
        "version": ERIS_VERSION,
        "cpu": get_cpu_percent(),
        "mem": get_memory_percent(),
        "temp": get_temperature(),
    }


async def broadcast(payload: Dict[str, object]) -> None:
    async with ws_lock:
        targets = list(ws_clients)

    dead: List[WebSocket] = []
    for ws in targets:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)

    if dead:
        async with ws_lock:
            for ws in dead:
                ws_clients.discard(ws)


async def broadcast_state() -> None:
    state.uptime = compute_uptime()
    await broadcast({"type": "state", "data": state.dict()})


async def periodic_health() -> None:
    try:
        while True:
            await asyncio.sleep(5)
            await broadcast({"type": "health", "data": build_health_payload()})
    except asyncio.CancelledError:
        logger.debug("Health publisher cancelled.")


async def _run_in_executor(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


@app.on_event("startup")
async def startup_event() -> None:
    global health_task
    logger.info("Eris daemon starting.")
    try:
        await _run_in_executor(chromium_adapter.start, CONFIG["device"]["homepage"])
    except FileNotFoundError:
        logger.error("Chromium binary missing; web rendering disabled until installed.")
    except Exception:
        logger.exception("Failed to launch Chromium.")

    health_task = asyncio.create_task(periodic_health())


@app.on_event("shutdown")
async def shutdown_event() -> None:
    logger.info("Eris daemon shutting down.")
    if health_task:
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
    await _run_in_executor(chromium_adapter.stop)


@api_router.get("/health")
async def api_health() -> Dict[str, float]:
    return build_health_payload()


@api_router.get("/state")
async def api_state() -> Dict[str, object]:
    state.uptime = compute_uptime()
    return {"mode": state.mode, "url": state.url, "uptime": state.uptime}


@api_router.post("/web/navigate")
async def api_web_navigate(request: NavigateRequest) -> Dict[str, str]:
    target_url = str(request.url)
    await _run_in_executor(chromium_adapter.restart, target_url)
    state.mode = "web"
    state.url = target_url
    await broadcast_state()
    return {"status": "ok"}


@api_router.post("/web/action")
async def api_web_action(request: WebActionRequest) -> Dict[str, str]:
    try:
        action = request.validate_command()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mapping = {
        "reload": chromium_adapter.reload,
        "back": chromium_adapter.back,
        "forward": chromium_adapter.forward,
        "home": chromium_adapter.home,
    }
    await _run_in_executor(mapping[action])
    return {"status": "ok"}


@api_router.post("/display/blank")
async def api_display_blank(request: DisplayBlankRequest) -> Dict[str, str]:
    await _run_in_executor(set_display_blank, request.on)
    return {"status": "ok"}


@api_router.get("/media")
async def api_media() -> Dict[str, List[str]]:
    items = await _run_in_executor(list_media)
    return {"items": items}


@api_router.post("/media/play")
async def api_media_play(request: MediaPlayRequest) -> Dict[str, str]:
    await _run_in_executor(play, request.path)
    state.mode = "media"
    state.url = request.path
    await broadcast_state()
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    async with ws_lock:
        ws_clients.add(websocket)
    try:
        await websocket.send_json({"type": "state", "data": state.dict()})
        await websocket.send_json({"type": "health", "data": build_health_payload()})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
    except Exception:
        logger.exception("WebSocket error.")
    finally:
        async with ws_lock:
            ws_clients.discard(websocket)


def handle_sigterm(signum, frame) -> None:
    logger.info("SIGTERM received; shutting down Chromium.")
    chromium_adapter.stop()
    sys.exit(0)


signal.signal(signal.SIGTERM, handle_sigterm)


app.include_router(api_router)

def _ensure_webui_mount_last() -> None:
    webui_route = None
    for route in list(app.router.routes):
        if isinstance(route, Mount) and route.name == "webui":
            webui_route = route
            break
    if webui_route:
        app.router.routes.remove(webui_route)
        app.router.routes.append(webui_route)


_ensure_webui_mount_last()

WEBUI_DIST = Path("/opt/eris/apps/webui/dist")

if WEBUI_DIST.is_dir():
    logger.info("Serving Web UI from %s", WEBUI_DIST)
else:
    logger.warning("Web UI dist directory %s missing; UI will not be served.", WEBUI_DIST)


def run() -> None:
    port = int(CONFIG["ui"].get("port", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    run()
