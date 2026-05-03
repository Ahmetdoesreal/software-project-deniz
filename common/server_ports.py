import json
import socket
import urllib.error
import urllib.request


def _bind_host(host: str | None) -> str:
    host = (host or "").strip()
    if not host or host == "0.0.0.0":
        return ""
    return host


def can_bind_tcp_port(host: str | None, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((_bind_host(host), int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def probe_local_server_id(port: int, *, timeout: float = 1.0) -> str | None:
    url = f"http://127.0.0.1:{int(port)}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = response.read().decode("utf-8", errors="replace")
    except (OSError, ValueError, urllib.error.URLError):
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    server_id = str(data.get("server_id", "") or "").strip()
    return server_id or None


def describe_port_conflict(
    expected_server_id: str,
    port: int,
    observed_server_id: str | None = None,
) -> str:
    expected_server_id = str(expected_server_id or "").strip()
    observed_server_id = str(observed_server_id or "").strip() or None

    if observed_server_id and observed_server_id == expected_server_id:
        return (
            f"A server with id '{expected_server_id}' is already running on port {port}. "
            "Stop that server, choose a different server ID, or choose a different port."
        )
    if observed_server_id:
        return (
            f"Port {port} is already used by server id '{observed_server_id}'. "
            "Choose a different port or stop that server."
        )
    return (
        f"Port {port} is already in use by another process. "
        "Choose a different port or stop the process using it."
    )


def detect_port_conflict(host: str | None, port: int, expected_server_id: str) -> str | None:
    if can_bind_tcp_port(host, port):
        return None
    observed_server_id = probe_local_server_id(port)
    return describe_port_conflict(expected_server_id, port, observed_server_id)
