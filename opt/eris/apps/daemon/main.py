import asyncio
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import uvicorn
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

from adapters.chromium import ChromiumAdapter
from adapters.media_stub import list_media, play
from models.state import ErisState, ServiceStatus
from utils.system import (
    DEFAULT_CONFIG_PATH,
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
WEBUI_PATH = Path("/opt/eris/apps/webui/dist")
WEBUI_ASSETS = WEBUI_PATH / "assets"
INDEX_PATH = WEBUI_PATH / "index.html"
CONFIG_PATH = Path(DEFAULT_CONFIG_PATH)
X_SOCKET_DIR = Path("/tmp/.X11-unix")

app = FastAPI(title="Eris Core Daemon", version=ERIS_VERSION)

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
service_monitor_task: Optional[asyncio.Task] = None
_last_prereq_errors: List[str] = []
_flags_warning_emitted = False


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


def set_service_status(name: str, status: str, detail: Optional[str] = None) -> bool:
    current = state.services.get(name)
    if current and current.status == status and current.detail == detail:
        return False
    state.services[name] = ServiceStatus(status=status, detail=detail)
    return True


def _compute_display_socket(display: str) -> Path:
    display_value = display.lstrip(":")
    if not display_value:
        display_value = "0"
    if "." in display_value:
        display_value = display_value.split(".", 1)[0]
    socket_name = f"X{display_value}"
    return X_SOCKET_DIR / socket_name


def _collect_prerequisite_errors() -> List[str]:
    global _flags_warning_emitted

    errors: List[str] = []
    if not CONFIG_PATH.exists():
        errors.append(f"Configuration file missing at {CONFIG_PATH}")

    binary_path = Path(chromium_adapter.binary)
    if not binary_path.exists():
        errors.append(f"Chromium binary missing at {binary_path}")

    display = os.environ.get("DISPLAY") or ":0"
    os.environ.setdefault("DISPLAY", display)
    socket_path = _compute_display_socket(display)
    if not socket_path.exists():
        errors.append(
            f"X server unavailable for DISPLAY {display}; expected socket {socket_path}"
        )

    flags_path = Path(CONFIG["chromium"]["flags_file"])
    if not flags_path.exists() and not _flags_warning_emitted:
        logger.warning(
            "Chromium flags file %s missing; continuing without additional flags.",
            flags_path,
        )
        _flags_warning_emitted = True

    return errors


def build_health_payload() -> Dict[str, object]:
    payload: Dict[str, object] = {
        "uptime": compute_uptime(),
        "version": ERIS_VERSION,
        "cpu": get_cpu_percent(),
        "mem": get_memory_percent(),
        "temp": get_temperature(),
    }
    if state.services:
        payload["services"] = {
            name: service.dict() for name, service in state.services.items()
        }
    return payload


def build_health_event() -> Dict[str, object]:
    payload = build_health_payload()
    event: Dict[str, object] = {"type": "health", "status": "ok"}
    event.update(payload)
    return event


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
    await broadcast({"type": "state", "status": "ok", "data": state.dict()})


async def periodic_health() -> None:
    try:
        while True:
            await asyncio.sleep(5)
            await broadcast(build_health_event())
    except asyncio.CancelledError:
        logger.debug("Health publisher cancelled.")


async def monitor_services() -> None:
    global _last_prereq_errors
    try:
        while True:
            await asyncio.sleep(5)
            errors = _collect_prerequisite_errors()
            if errors:
                if errors != _last_prereq_errors:
                    for error in errors:
                        logger.error("Prerequisite check failed: %s", error)
                    changed = set_service_status("chromium", "error", "; ".join(errors))
                    if changed:
                        await broadcast_state()
                _last_prereq_errors = errors
                continue

            if _last_prereq_errors:
                logger.info("Prerequisite checks recovered; resuming Chromium supervision.")
                _last_prereq_errors = []

            if not chromium_adapter.is_alive():
                detail = "Restarting Chromium process"
                changed = set_service_status("chromium", "starting", detail)
                if changed:
                    await broadcast_state()
                try:
                    await _run_in_executor(
                        chromium_adapter.start, state.url or CONFIG["device"]["homepage"]
                    )
                except Exception as exc:
                    logger.exception("Failed to (re)start Chromium during health check.")
                    detail = str(exc) or exc.__class__.__name__
                    changed = set_service_status("chromium", "error", detail)
                    if changed:
                        await broadcast_state()
                    continue

                changed = set_service_status("chromium", "running", None)
                if changed:
                    await broadcast_state()
            else:
                changed = set_service_status("chromium", "running", None)
                if changed:
                    await broadcast_state()
    except asyncio.CancelledError:
        logger.debug("Service monitor cancelled.")


async def _run_in_executor(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


@app.on_event("startup")
async def startup_event() -> None:
    global health_task, service_monitor_task
    logger.info("Eris daemon starting.")
    prereq_errors = _collect_prerequisite_errors()
    if prereq_errors:
        for error in prereq_errors:
            logger.error("Prerequisite check failed: %s", error)
        set_service_status("chromium", "error", "; ".join(prereq_errors))
    else:
        set_service_status("chromium", "starting", "Launching Chromium")
        try:
            await _run_in_executor(chromium_adapter.start, CONFIG["device"]["homepage"])
        except FileNotFoundError:
            detail = f"Chromium binary missing at {chromium_adapter.binary}"
            logger.error(detail)
            set_service_status("chromium", "error", detail)
        except Exception as exc:
            logger.exception("Failed to launch Chromium.")
            detail = str(exc) or exc.__class__.__name__
            set_service_status("chromium", "error", detail)
        else:
            set_service_status("chromium", "running", None)

    health_task = asyncio.create_task(periodic_health())
    service_monitor_task = asyncio.create_task(monitor_services())

    if STATIC_ROUTES_READY:
        logger.info("✅ Web UI static routing active — serving from %s", WEBUI_PATH)
    await broadcast_state()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global service_monitor_task
    logger.info("Eris daemon shutting down.")
    if health_task:
        health_task.cancel()
        try:
            await health_task
        except asyncio.CancelledError:
            pass
    if service_monitor_task:
        service_monitor_task.cancel()
        try:
            await service_monitor_task
        except asyncio.CancelledError:
            pass
    await _run_in_executor(chromium_adapter.stop)


@api_router.get("/health")
async def api_health() -> Dict[str, float]:
    return build_health_payload()


@api_router.get("/state")
async def api_state() -> Dict[str, object]:
    state.uptime = compute_uptime()
    return state.dict()


@api_router.post("/web/navigate")
async def api_web_navigate(request: NavigateRequest) -> Dict[str, str]:
    target_url = str(request.url)
    detail = f"Navigating to {target_url}"
    if set_service_status("chromium", "starting", detail):
        await broadcast_state()

    try:
        await _run_in_executor(chromium_adapter.restart, target_url)
    except FileNotFoundError:
        message = f"Chromium binary missing at {chromium_adapter.binary}"
        set_service_status("chromium", "error", message)
        await broadcast_state()
        raise HTTPException(status_code=500, detail=message) from None
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        set_service_status("chromium", "error", message)
        await broadcast_state()
        raise HTTPException(status_code=500, detail=message) from exc

    state.mode = "web"
    state.url = target_url
    set_service_status("chromium", "running", None)
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
    if not chromium_adapter.is_alive():
        message = "Chromium process is not running; cannot execute browser action."
        set_service_status("chromium", "error", message)
        await broadcast_state()
        raise HTTPException(status_code=503, detail=message)

    try:
        await _run_in_executor(mapping[action])
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        set_service_status("chromium", "error", message)
        await broadcast_state()
        raise HTTPException(status_code=500, detail=message) from exc

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
        await websocket.send_json({"type": "state", "status": "ok", "data": state.dict()})
        await websocket.send_json(build_health_event())
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


class SafeStaticFiles(StaticFiles):
    async def __call__(self, scope, receive, send):  # type: ignore[override]
        if scope["type"] != "http":
            # Defer non-HTTP scopes (e.g., websocket) to avoid StaticFiles assertions.
            return await self.app(scope, receive, send)
        return await super().__call__(scope, receive, send)


STATIC_ROUTES_READY = False
if not WEBUI_PATH.is_dir():
    logger.warning("Web UI directory %s missing; static assets will not be served.", WEBUI_PATH)
elif not INDEX_PATH.is_file():
    logger.warning("Web UI index %s missing; routes will 404.", INDEX_PATH)
else:
    if WEBUI_ASSETS.is_dir():
        app.mount("/assets", SafeStaticFiles(directory=str(WEBUI_ASSETS)), name="assets")
        STATIC_ROUTES_READY = True
    else:
        logger.warning("Web UI assets directory %s missing; /assets will not be mounted.", WEBUI_ASSETS)


def _serve_index() -> FileResponse:
    if not INDEX_PATH.is_file():
        raise HTTPException(status_code=404, detail="Web UI not built")
    return FileResponse(str(INDEX_PATH))


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str, request: Request) -> Response:
    blocked_prefixes = ("api/", "ws", "assets/")
    if full_path and any(full_path.startswith(prefix) for prefix in blocked_prefixes):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    path = request.url.path.lstrip("/")
    if path and any(path.startswith(prefix) for prefix in blocked_prefixes):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return _serve_index()


def run() -> None:
    port = int(CONFIG["ui"].get("port", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    run()
