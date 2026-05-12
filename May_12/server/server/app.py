import asyncio
from aiohttp import web
from aiohttp.web_runner import GracefulExit

from common.discovery import ServerAnnouncer, _candidate_ipv4_hosts, _normalize_ipv4, check_duplicate_server
from common.runtime_logging import install_asyncio_exception_logging
from .state import state
from .shutdown import SHUTDOWN_GRACE_SECONDS, ServerShutdownRoutine
from .handlers import (
    auth_status,
    client_artifact_upload,
    health,
    login_handler,
    exam_config,
    exam_files,
    exam_submission,
    websocket_handler,
)
from .projector import projector_css, projector_events, projector_js, projector_page
from .tasks import time_broadcaster, console_reader, _launch_server_gui


def _duplicate_guard_timeout(announce_interval: float) -> float:
    return max(5.0, announce_interval * 2.0 + 1.0)


def _server_identity_hosts(bind_host: str) -> set[str]:
    hosts = {host for host in _candidate_ipv4_hosts() if host}
    explicit_host = _normalize_ipv4(bind_host)
    if explicit_host and explicit_host != "0.0.0.0":
        hosts.add(explicit_host)
    return hosts


def _is_same_server_instance(app: web.Application, host: str, port: int) -> bool:
    hosts = app.get("server_identity_hosts") or _server_identity_hosts(app["host"])
    return port == app["port"] and host in hosts


def _shutdown_grace_seconds(args) -> float:
    return float(getattr(args, "shutdown_grace_seconds", SHUTDOWN_GRACE_SECONDS))


async def duplicate_server_guard(app: web.Application):
    timeout = _duplicate_guard_timeout(app["announce_interval"])
    loop = asyncio.get_running_loop()

    while True:
        found = await check_duplicate_server(
            app["server_id"],
            timeout=timeout,
            local_port=None,
            known_self_ipv4s=app.get("server_identity_hosts"),
            self_port=app["port"],
        )
        if found is None:
            continue

        host, port = found
        if _is_same_server_instance(app, host, port):
            continue

        print(f"[ERROR] Duplicate server detected for id '{app['server_id']}' at {host}:{port}")
        print("[ERROR] Refusing to continue while another server with the same id is reachable.")

        def _raise_graceful_exit():
            raise GracefulExit()

        loop.call_soon(_raise_graceful_exit)
        return


async def start_background_tasks(app: web.Application):
    install_asyncio_exception_logging(asyncio.get_running_loop())
    app["time_broadcaster"] = asyncio.create_task(time_broadcaster(app))
    app["console_reader"] = asyncio.create_task(console_reader(app))
    # Start UDP discovery announcer
    announcer = ServerAnnouncer(server_host=app["host"], server_port=app["port"],
                                server_id=app["server_id"],
                                interval=app["announce_interval"])
    await announcer.start()
    app["announcer"] = announcer
    app["duplicate_guard"] = asyncio.create_task(duplicate_server_guard(app))
    if app.get("launch_gui_on_start", False):
        _launch_server_gui(asyncio.get_running_loop(), app)


async def cleanup_background_tasks(app: web.Application):
    await app["shutdown_routine"].run()

    for task_name in ("time_broadcaster", "console_reader", "duplicate_guard"):
        app[task_name].cancel()
        try:
            await app[task_name]
        except asyncio.CancelledError:
            pass

    await app["announcer"].stop()
    
    if state.gui_process and state.gui_process.poll() is None:
        state.gui_process.kill()
    gui_ipc = getattr(state, "gui_ipc_server", None)
    if gui_ipc:
        gui_ipc.stop()
        state.gui_ipc_server = None


def create_app(args) -> web.Application:
    state.load_users()
    app = web.Application(client_max_size=512 * 1024 * 1024)
    app["server_id"] = args.id
    app["host"] = args.host
    app["port"] = args.port
    app["server_identity_hosts"] = _server_identity_hosts(args.host)
    app["broadcast_interval"] = args.interval
    app["announce_interval"] = args.announce
    app["exam_duration"] = args.exam_duration
    app["exam_files"] = args.exam_files
    app["settings_state"] = state
    app["exam_phase"] = "waiting"
    app["exam_start_enabled"] = False
    app["shutdown_grace_seconds"] = _shutdown_grace_seconds(args)
    app["max_submission_bytes"] = int(args.max_submission_mb) * 1024 * 1024
    app["max_artifact_bytes"] = int(args.max_artifact_mb) * 1024 * 1024
    app["shutdown_routine"] = ServerShutdownRoutine(app)
    app["gui_module"] = getattr(args, "gui_module", "server.gui")
    app["project_dir"] = getattr(args, "project_dir", None)
    app["python_executable"] = getattr(args, "python_executable", None)
    app["launch_gui_on_start"] = bool(getattr(args, "gui", False))
    app["auth_secret"] = str(getattr(args, "auth_secret", None) or "")
    app["auth_bypass"] = {"cats_until": 0.0, "ad_until": 0.0}
    app["auth_validation"] = {"requests": {}, "approvals": {}}
    app["ipc_transport"] = str(getattr(args, "ipc_transport", "auto") or "auto")
    gui_ui = str(getattr(args, "ui", "tk") or "tk").strip().lower()
    if gui_ui not in {"tk", "qt"}:
        gui_ui = "tk"
    app["gui_ui"] = gui_ui
    
    app.router.add_get("/health", health)
    app.router.add_get("/auth/status", auth_status)
    app.router.add_get("/projector", projector_page)
    app.router.add_get("/projector/assets/projector.css", projector_css)
    app.router.add_get("/projector/assets/projector.js", projector_js)
    app.router.add_get("/projector/events", projector_events)
    app.router.add_post("/login", login_handler)
    app.router.add_get("/exam/config", exam_config)
    app.router.add_get("/exam/files", exam_files)
    app.router.add_post("/exam/submission", exam_submission)
    app.router.add_post("/client/artifact", client_artifact_upload)
    app.router.add_get("/ws", websocket_handler)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    return app
