import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, HttpUrl

from adapters.chromium import ChromiumAdapter
from adapters.media import MediaLibrary, MediaPlayer
from models.state import ErisState, ServiceStatus
from controllers.content import ContentRouter
from controllers.scheduler import PlaybackScheduler, PlaylistStore
from utils.display import DisplayManager
from utils.auth import AuthError, AuthManager
from utils.media_store import MediaMetadataStore
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

os.environ.setdefault("DISPLAY", CONFIG.get("display", {}).get("name", ":0"))

app = FastAPI(title="Eris Core Daemon", version=ERIS_VERSION)

api_router = APIRouter(prefix="/api")

display_cfg = CONFIG.get("display", {})
display_manager = DisplayManager(
    display=display_cfg.get("name", ":0"),
    launcher=display_cfg.get("launcher"),
    startup_timeout=float(display_cfg.get("startup_timeout", 12.0)),
    logger=logging.getLogger("eris.display"),
)

chromium_adapter = ChromiumAdapter(
    homepage=CONFIG["device"]["homepage"],
    flags_file=CONFIG["chromium"]["flags_file"],
    binary=CONFIG["chromium"].get("binary", "/usr/bin/chromium-browser"),
    debug_port=int(CONFIG["chromium"].get("debug_port", 9222)),
    logger=logging.getLogger("eris.chromium"),
)

media_cfg = CONFIG.get("media", {})
state_cfg = CONFIG.get("state", {})
media_roots = []

local_root = Path(media_cfg.get("local_path", "/var/lib/eris/media/local"))
cache_root = Path(media_cfg.get("cache_path", "/var/lib/eris/media/cache"))
for root in (local_root, cache_root):
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Unable to ensure media directory %s exists.", root)

if media_cfg.get("use_network") and media_cfg.get("mount_point"):
    network_root = Path(media_cfg["mount_point"])
    media_roots.append(("network", network_root))
else:
    network_root = None
media_roots.append(("local", local_root))
media_roots.append(("cache", cache_root))

metadata_path = Path(media_cfg.get("metadata_path", local_root.parent / "metadata.json"))
media_metadata_store = MediaMetadataStore(metadata_path, logger=logging.getLogger("eris.media.meta"))

media_library = MediaLibrary(
    media_roots,
    logger=logging.getLogger("eris.media.library"),
    metadata_store=media_metadata_store,
)

MEDIA_ROOTS: Dict[str, Path] = {"local": local_root, "cache": cache_root}
if network_root:
    MEDIA_ROOTS["network"] = network_root

MAX_UPLOAD_BYTES = int(media_cfg.get("max_upload_mb", 200)) * 1024 * 1024
media_player = MediaPlayer(
    mpv_binary=media_cfg.get("mpv_binary", "mpv"),
    imv_binary=media_cfg.get("imv_binary", "imv"),
    logger=logging.getLogger("eris.media.player"),
)

STATE_STORE_PATH = Path(state_cfg.get("path", "/var/lib/eris/state.json"))

content_router = ContentRouter(
    chromium=chromium_adapter,
    media_player=media_player,
    library=media_library,
    homepage=CONFIG["device"]["homepage"],
    state_path=STATE_STORE_PATH,
    logger=logging.getLogger("eris.content"),
)

PLAYLIST_STORE_PATH = Path(CONFIG.get("state", {}).get("playlist_path", STATE_STORE_PATH.with_name("playlists.json")))
playlist_store = PlaylistStore(PLAYLIST_STORE_PATH, logger=logging.getLogger("eris.playlists"))

scheduler_cfg = CONFIG.get("scheduler", {})
playback_scheduler = PlaybackScheduler(
    store=playlist_store,
    content_router=content_router,
    media_library=media_library,
    homepage=CONFIG["device"].get("homepage", "https://example.com"),
    logger=logging.getLogger("eris.scheduler"),
    tick_interval=int(scheduler_cfg.get("tick_interval", 15)),
    default_image_duration=int(media_cfg.get("image_duration", 30)),
)

initial_status = content_router.status()
state = ErisState(
    mode=initial_status.get("mode", "web"),
    url=initial_status.get("url", CONFIG["device"]["homepage"]),
    media=initial_status.get("media"),
    paused=initial_status.get("paused", False),
)


def _update_state_from_content(status: Dict[str, object]) -> None:
    state.mode = status.get("mode", state.mode)
    state.url = status.get("url", state.url)
    state.media = status.get("media")
    state.paused = bool(status.get("paused", state.paused))


def _safe_filename(filename: str) -> str:
    candidate = Path(filename or "").name
    if not candidate:
        raise ValueError("Filename required")
    return re.sub(r"[^A-Za-z0-9._-]", "_", candidate)


def _resolve_media_path(source: str, relative_path: str) -> Path:
    root = MEDIA_ROOTS.get(source)
    if not root:
        raise ValueError("Unknown media source")
    cleaned = Path(*[part for part in Path(relative_path).parts if part not in ("..", "")])
    target = (root / cleaned).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise ValueError("Path traversal detected")
    return target


auth_cfg = CONFIG.get("security", {})
auth_manager = AuthManager(
    password_hash=auth_cfg.get("password_hash", ""),
    token_secret=auth_cfg.get("token_secret"),
    token_ttl_seconds=int(auth_cfg.get("token_ttl", 3600)),
)

if not auth_cfg.get("token_secret"):
    logger.warning("Token secret missing in configuration; generated ephemeral secret for this session.")

security_scheme = HTTPBearer(auto_error=False)


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme),
) -> Dict[str, object]:
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    try:
        return auth_manager.verify_token(credentials.credentials)
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

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
    identifier: str
    refresh: bool = False


class LoginRequest(BaseModel):
    password: str


class PlaylistItemModel(BaseModel):
    media_id: str
    duration: Optional[int] = None


class PlaylistModel(BaseModel):
    id: str
    name: str
    items: List[PlaylistItemModel] = []
    loop: bool = True


class ScheduleModel(BaseModel):
    id: str
    playlist_id: str
    start: str
    end: str
    days: List[str] = []


class FallbackModel(BaseModel):
    mode: str = "web"
    url: Optional[str] = None
    playlist_id: Optional[str] = None


class MediaTagRequest(BaseModel):
    tags: List[str] = []


def compute_uptime() -> float:
    return time.time() - START_TIME


def set_service_status(name: str, status: str, detail: Optional[str] = None) -> bool:
    current = state.services.get(name)
    if current and current.status == status and current.detail == detail:
        return False
    state.services[name] = ServiceStatus(status=status, detail=detail)
    return True


def _collect_prerequisite_errors() -> List[str]:
    global _flags_warning_emitted

    errors: List[str] = []
    if not CONFIG_PATH.exists():
        errors.append(f"Configuration file missing at {CONFIG_PATH}")

    binary_path = Path(chromium_adapter.binary)
    if not binary_path.exists():
        errors.append(f"Chromium binary missing at {binary_path}")

    flags_path = Path(CONFIG["chromium"]["flags_file"])
    if not flags_path.exists() and not _flags_warning_emitted:
        logger.warning(
            "Chromium flags file %s missing; continuing without additional flags.",
            flags_path,
        )
        _flags_warning_emitted = True

    if not auth_manager.password_hash:
        errors.append("Admin password hash missing; run setup to configure credentials.")

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
    content_snapshot = await _run_in_executor(content_router.status)
    _update_state_from_content(content_snapshot)
    payload = state.dict()
    payload["player"] = content_snapshot.get("player")
    await broadcast({"type": "state", "status": "ok", "data": payload})


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
            display_ready = await _run_in_executor(display_manager.ensure_running)
            if not display_ready:
                detail = display_manager.last_error() or (
                    f"Display session unavailable for DISPLAY {display_manager.display}"
                )
                changed = set_service_status("display", "error", detail)
                if changed:
                    await broadcast_state()
                if chromium_adapter.is_alive():
                    await _run_in_executor(chromium_adapter.stop)
                changed = set_service_status(
                    "chromium", "error", "Display session unavailable; Chromium stopped."
                )
                if changed:
                    await broadcast_state()
                continue
            else:
                changed = set_service_status("display", "running", None)
                if changed:
                    await broadcast_state()

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

            content_status = await _run_in_executor(content_router.status)
            mode = content_status.get("mode")
            player_status = content_status.get("player", {}) or {}

            scheduler_status = playback_scheduler.status()
            scheduler_state = "running" if scheduler_status.get("active") else "idle"
            scheduler_detail = scheduler_status.get("playlist_id")
            changed = set_service_status("scheduler", scheduler_state, scheduler_detail)
            if changed:
                await broadcast_state()

            media_state = "idle"
            media_detail = None
            if player_status.get("playing"):
                media_state = "running"
                media_detail = (content_status.get("media") or {}).get("name")
            elif player_status.get("paused"):
                media_state = "paused"
                media_detail = (content_status.get("media") or {}).get("name")
            elif mode == "media":
                media_state = "ready"
                media_detail = (content_status.get("media") or {}).get("name")

            changed = set_service_status("media", media_state, media_detail)
            if changed:
                await broadcast_state()

            if mode == "media":
                changed = set_service_status("chromium", "paused", "Media playback active")
                if changed:
                    await broadcast_state()
                continue

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

    loop = asyncio.get_running_loop()

    def _on_content_state_change(status: Dict[str, object]) -> None:
        _update_state_from_content(status)
        asyncio.create_task(broadcast_state())

    content_router.bind_notifier(loop, _on_content_state_change)

    set_service_status("display", "starting", "Ensuring X session")
    try:
        await _run_in_executor(display_manager.start)
    except Exception as exc:
        detail = str(exc) or exc.__class__.__name__
        logger.exception("Failed to start display session.")
        set_service_status("display", "error", detail)
    else:
        set_service_status("display", "running", None)

    prereq_errors = _collect_prerequisite_errors()
    if prereq_errors:
        for error in prereq_errors:
            logger.error("Prerequisite check failed: %s", error)
        set_service_status("chromium", "error", "; ".join(prereq_errors))
    else:
        set_service_status("chromium", "starting", "Initialising content pipeline")
        try:
            await _run_in_executor(content_router.restore)
        except FileNotFoundError:
            detail = f"Chromium binary missing at {chromium_adapter.binary}"
            logger.error(detail)
            set_service_status("chromium", "error", detail)
        except Exception as exc:
            logger.exception("Failed to initialise content state.")
            detail = str(exc) or exc.__class__.__name__
            set_service_status("chromium", "error", detail)
        else:
            content_status = await _run_in_executor(content_router.status)
            mode = content_status.get("mode")
            if mode == "media":
                set_service_status("chromium", "paused", "Media playback active")
            elif chromium_adapter.is_alive():
                set_service_status("chromium", "running", None)
            else:
                set_service_status("chromium", "error", "Chromium not running after restore")

    health_task = asyncio.create_task(periodic_health())
    service_monitor_task = asyncio.create_task(monitor_services())
    set_service_status("scheduler", "starting", "Evaluating playlists")
    await playback_scheduler.start()

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
    await playback_scheduler.stop()
    await _run_in_executor(chromium_adapter.stop)
    await _run_in_executor(display_manager.stop)


@api_router.get("/health")
async def api_health() -> Dict[str, float]:
    return build_health_payload()


@api_router.post("/auth/login")
async def api_auth_login(request: LoginRequest) -> Dict[str, object]:
    try:
        if not auth_manager.verify_password(request.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    except AuthError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    token_data = auth_manager.issue_token()
    return token_data


@api_router.get("/state")
async def api_state(_: Dict[str, object] = Depends(require_auth)) -> Dict[str, object]:
    state.uptime = compute_uptime()
    return state.dict()


@api_router.post("/web/navigate")
async def api_web_navigate(
    request: NavigateRequest,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, str]:
    target_url = str(request.url)
    detail = f"Navigating to {target_url}"
    if set_service_status("chromium", "starting", detail):
        await broadcast_state()

    try:
        await _run_in_executor(content_router.navigate, target_url)
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

    status_snapshot = await _run_in_executor(content_router.status)
    _update_state_from_content(status_snapshot)
    set_service_status("chromium", "running", None)
    await broadcast_state()
    return {"status": "ok"}


@api_router.post("/web/action")
async def api_web_action(
    request: WebActionRequest,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, str]:
    try:
        action = request.validate_command()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if state.mode != "web":
        raise HTTPException(status_code=409, detail="Chromium is not the active display mode.")

    if action == "home":
        detail = "Navigating to homepage"
        if set_service_status("chromium", "starting", detail):
            await broadcast_state()
        try:
            await _run_in_executor(content_router.navigate, CONFIG["device"]["homepage"])
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            set_service_status("chromium", "error", message)
            await broadcast_state()
            raise HTTPException(status_code=500, detail=message) from exc

        status_snapshot = await _run_in_executor(content_router.status)
        _update_state_from_content(status_snapshot)
        set_service_status("chromium", "running", None)
        await broadcast_state()
        return {"status": "ok"}

    mapping = {
        "reload": chromium_adapter.reload,
        "back": chromium_adapter.back,
        "forward": chromium_adapter.forward,
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
async def api_display_blank(
    request: DisplayBlankRequest,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, str]:
    await _run_in_executor(set_display_blank, request.on)
    return {"status": "ok"}


@api_router.get("/media")
async def api_media(
    refresh: bool = False,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, List[Dict[str, object]]]:
    items = await _run_in_executor(media_library.scan, refresh)
    return {"items": [item.to_dict() for item in items]}


@api_router.post("/media/upload")
async def api_media_upload(
    file: UploadFile = File(...),
    folder: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, object]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing")

    try:
        filename = _safe_filename(file.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    destination = MEDIA_ROOTS["local"].resolve()
    if folder:
        cleaned_folder = Path(folder)
        safe_folder = Path(*[part for part in cleaned_folder.parts if part not in ("..", "")])
        destination = (destination / safe_folder).resolve()
        if not str(destination).startswith(str(MEDIA_ROOTS["local"].resolve())):
            raise HTTPException(status_code=400, detail="Invalid destination folder")

    destination.mkdir(parents=True, exist_ok=True)
    target_path = destination / filename

    if target_path.exists():
        raise HTTPException(status_code=409, detail="A file with that name already exists")

    size = 0
    try:
        with target_path.open("wb") as buffer:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if MAX_UPLOAD_BYTES and size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds configured limit")
                buffer.write(chunk)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            target_path.unlink()
        raise

    relative = target_path.relative_to(MEDIA_ROOTS["local"]).as_posix()
    identifier = f"local:{relative}"

    parsed_tags: List[str] = []
    if tags:
        try:
            parsed_tags = json.loads(tags) if tags.strip().startswith("[") else [token.strip() for token in tags.split(",") if token.strip()]
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid tags format") from exc
    if parsed_tags:
        media_metadata_store.set_tags(identifier, parsed_tags)

    media_library.invalidate_cache()
    playback_scheduler.request_refresh()

    item = media_library.get_by_identifier(identifier)
    payload = item.to_dict() if item else {"identifier": identifier}
    return {"status": "ok", "item": payload}


@api_router.delete("/media/{source}/{media_path:path}")
async def api_media_delete(
    source: str,
    media_path: str,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, str]:
    try:
        target = _resolve_media_path(source, media_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not target.exists():
        raise HTTPException(status_code=404, detail="Media not found")

    target.unlink()

    root = MEDIA_ROOTS[source]
    identifier = f"{source}:{target.relative_to(root).as_posix()}"
    media_metadata_store.remove(identifier)
    media_library.invalidate_cache()
    playback_scheduler.request_refresh()
    return {"status": "ok"}


@api_router.post("/media/{source}/{media_path:path}/tags")
async def api_media_tags(
    source: str,
    media_path: str,
    request: MediaTagRequest,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, object]:
    try:
        target = _resolve_media_path(source, media_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not target.exists():
        raise HTTPException(status_code=404, detail="Media not found")

    root = MEDIA_ROOTS[source]
    identifier = f"{source}:{target.relative_to(root).as_posix()}"
    media_metadata_store.set_tags(identifier, request.tags)
    media_library.invalidate_cache()
    return {"status": "ok", "tags": request.tags}


@api_router.post("/media/play")
async def api_media_play(
    request: MediaPlayRequest,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, object]:
    identifier = request.identifier
    if request.refresh:
        await _run_in_executor(media_library.scan, True)

    detail = f"Starting media item {identifier}"
    if set_service_status("media", "starting", detail):
        await broadcast_state()

    try:
        item = await _run_in_executor(content_router.play_media, identifier)
    except FileNotFoundError:
        message = "Media item not found"
        set_service_status("media", "error", message)
        await broadcast_state()
        raise HTTPException(status_code=404, detail=message) from None
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        set_service_status("media", "error", message)
        await broadcast_state()
        raise HTTPException(status_code=500, detail=message) from exc

    status_snapshot = await _run_in_executor(content_router.status)
    _update_state_from_content(status_snapshot)

    set_service_status("media", "running", None)
    set_service_status("chromium", "paused", "Media playback active")
    await broadcast_state()
    return {"status": "ok", "item": item.to_dict()}


@api_router.post("/media/stop")
async def api_media_stop(
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, str]:
    try:
        await _run_in_executor(content_router.stop_media)
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        set_service_status("media", "error", message)
        await broadcast_state()
        raise HTTPException(status_code=500, detail=message) from exc

    status_snapshot = await _run_in_executor(content_router.status)
    _update_state_from_content(status_snapshot)
    set_service_status("media", "idle", None)
    set_service_status("chromium", "running", None)
    await broadcast_state()
    return {"status": "ok"}


@api_router.post("/media/pause")
async def api_media_pause(
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, str]:
    await _run_in_executor(content_router.pause_media)
    status_snapshot = await _run_in_executor(content_router.status)
    _update_state_from_content(status_snapshot)
    set_service_status("media", "paused", None)
    set_service_status("chromium", "paused", "Media playback active")
    await broadcast_state()
    return {"status": "ok"}


@api_router.post("/media/resume")
async def api_media_resume(
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, str]:
    await _run_in_executor(content_router.resume_media)
    status_snapshot = await _run_in_executor(content_router.status)
    _update_state_from_content(status_snapshot)
    set_service_status("media", "running", None)
    set_service_status("chromium", "paused", "Media playback active")
    await broadcast_state()
    return {"status": "ok"}


@api_router.get("/media/status")
async def api_media_status(
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, object]:
    return await _run_in_executor(content_router.status)


@api_router.get("/playlists")
async def api_playlists(_: Dict[str, object] = Depends(require_auth)) -> Dict[str, object]:
    return {"playlists": playlist_store.list_playlists()}


@api_router.post("/playlists")
async def api_playlist_upsert(
    playlist: PlaylistModel,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, object]:
    try:
        stored = playlist_store.upsert_playlist(playlist.dict())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    playback_scheduler.request_refresh()
    playlists = playlist_store.list_playlists()
    response = next((entry for entry in playlists if entry.get("id") == stored.playlist_id), None)
    return {"playlist": response}


@api_router.delete("/playlists/{playlist_id}")
async def api_playlist_delete(
    playlist_id: str,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, str]:
    playlist_store.delete_playlist(playlist_id)
    playback_scheduler.request_refresh()
    return {"status": "ok"}


@api_router.get("/schedules")
async def api_schedules(_: Dict[str, object] = Depends(require_auth)) -> Dict[str, object]:
    return {"schedules": playlist_store.list_schedules()}


@api_router.post("/schedules")
async def api_schedule_upsert(
    schedule: ScheduleModel,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, object]:
    try:
        stored = playlist_store.upsert_schedule(schedule.dict())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    playback_scheduler.request_refresh()
    schedules = playlist_store.list_schedules()
    response = next((entry for entry in schedules if entry.get("id") == stored.schedule_id), None)
    return {"schedule": response}


@api_router.delete("/schedules/{schedule_id}")
async def api_schedule_delete(
    schedule_id: str,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, str]:
    playlist_store.delete_schedule(schedule_id)
    playback_scheduler.request_refresh()
    return {"status": "ok"}


@api_router.get("/scheduler/status")
async def api_scheduler_status(
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, object]:
    return {
        "scheduler": playback_scheduler.status(),
        "fallback": playlist_store.get_fallback(),
    }


@api_router.post("/scheduler/fallback")
async def api_scheduler_fallback(
    fallback: FallbackModel,
    _: Dict[str, object] = Depends(require_auth),
) -> Dict[str, object]:
    try:
        playlist_store.set_fallback(fallback.dict())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    playback_scheduler.request_refresh()
    return {"fallback": playlist_store.get_fallback()}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1]
    if not token:
        await websocket.close(code=4401)
        return

    try:
        auth_manager.verify_token(token)
    except AuthError:
        await websocket.close(code=4401)
        return

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
    display_manager.stop()
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
