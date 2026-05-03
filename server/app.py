import asyncio
from aiohttp import web
from aiohttp.web_runner import GracefulExit

from common.discovery import ServerAnnouncer, _candidate_ipv4_hosts, _normalize_ipv4, check_duplicate_server
from common.runtime_logging import install_asyncio_exception_logging
from .state import state
from .shutdown import ServerShutdownRoutine
from .handlers import (
    client_artifact_upload,
    health,
    login_handler,
    exam_config,
    exam_files,
    exam_submission,
    websocket_handler,
)
from .tasks import time_broadcaster, console_reader


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
    app["exam_phase"] = "waiting"
    app["exam_start_enabled"] = False
    app["shutdown_grace_seconds"] = 2.0
    app["max_submission_bytes"] = 512 * 1024 * 1024
    app["max_artifact_bytes"] = 512 * 1024 * 1024
    app["shutdown_routine"] = ServerShutdownRoutine(app)
    app["gui_path"] = getattr(args, "gui_path", None)
    app["python_executable"] = getattr(args, "python_executable", None)
    
    app.router.add_get("/health", health)
    app.router.add_post("/login", login_handler)
    app.router.add_get("/exam/config", exam_config)
    app.router.add_get("/exam/files", exam_files)
    app.router.add_post("/exam/submission", exam_submission)
    app.router.add_post("/client/artifact", client_artifact_upload)
    app.router.add_get("/ws", websocket_handler)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    return app
