"""
discovery.py -- UDP broadcast-based server discovery.

The server periodically broadcasts a small beacon packet on the LAN.
The client listens for that beacon to find the server automatically.

Uses UDP broadcast on port 5353 (configurable).
"""

import asyncio
import json
import socket


DISCOVERY_PORT = 5354
BROADCAST_ADDR = "255.255.255.255"
BEACON_MAGIC = "6064-SERVER"  # simple identifier so we ignore unrelated traffic


# -- Server side: announce ------------------------------------------------

class ServerAnnouncer:
    """Broadcasts a beacon every `interval` seconds so clients can find us."""

    def __init__(self, server_host: str, server_port: int,
                 server_id: str = "default", interval: float = 3.0):
        self.server_host = server_host
        self.server_port = server_port
        self.server_id = server_id
        self.interval = interval
        self._sock = None
        self._task = None

    def _make_beacon(self) -> bytes:
        # Get actual LAN IP (not 0.0.0.0)
        ip = self._get_local_ip()
        payload = json.dumps({
            "magic": BEACON_MAGIC,
            "server_id": self.server_id,
            "host": ip,
            "port": self.server_port,
        })
        return payload.encode("ascii")

    @staticmethod
    def _get_local_ip() -> str:
        """Best-effort LAN IP detection."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))  # doesn't actually send anything
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    async def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.setblocking(False)
        self._task = asyncio.create_task(self._loop())
        print(f"[DISCOVERY] Announcing '{self.server_id}' on UDP port {DISCOVERY_PORT} every {self.interval}s")

    async def _loop(self):
        beacon = self._make_beacon()
        try:
            while True:
                self._sock.sendto(beacon, (BROADCAST_ADDR, DISCOVERY_PORT))
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            pass
        finally:
            self._sock.close()

    async def stop(self):
        if self._task:
            self._task.cancel()
            await self._task


# -- Client side: discover ------------------------------------------------

async def discover_server(server_id: str = "default", timeout: float = 10.0):
    """
    Listen for a server beacon on UDP broadcast.
    Only matches servers with the given server_id.
    Returns (host, port) of the first matching server, or None on timeout.
    """
    print(f"[DISCOVERY] Searching for server '{server_id}' (timeout {timeout}s)...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("", DISCOVERY_PORT))
        sock.setblocking(False)
    except OSError as e:
        print(f"[DISCOVERY] ERROR: Could not bind to UDP port {DISCOVERY_PORT}: {e}")
        return None

    loop = asyncio.get_event_loop()

    try:
        end_time = loop.time() + timeout
        while loop.time() < end_time:
            remaining = end_time - loop.time()
            try:
                data = await asyncio.wait_for(
                    loop.sock_recv(sock, 1024),
                    timeout=min(remaining, 1.0),
                )
                msg = json.loads(data.decode("ascii"))
                if msg.get("magic") == BEACON_MAGIC and msg.get("server_id") == server_id:
                    host = msg["host"]
                    port = msg["port"]
                    print(f"[DISCOVERY] Found server '{server_id}' at {host}:{port}")
                    return host, port
            except asyncio.TimeoutError:
                continue
            except (json.JSONDecodeError, KeyError):
                continue
    finally:
        sock.close()

    print("[DISCOVERY] No server found.")
    return None


# -- Pre-start check: duplicate server ID ---------------------------------

async def check_duplicate_server(server_id: str, timeout: float = 5.0):
    """
    Listen briefly for beacons. If we hear another server with the same ID,
    return its (host, port). Otherwise return None (safe to start).
    """
    print(f"[CHECK] Checking for existing server '{server_id}' on the network...")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, 'SO_REUSEPORT'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("", DISCOVERY_PORT))
        sock.setblocking(False)
    except OSError as e:
        print(f"[CHECK] WARNING: Could not bind UDP port {DISCOVERY_PORT}: {e}")
        print("[CHECK] Skipping duplicate check, proceeding anyway.")
        return None

    loop = asyncio.get_event_loop()

    try:
        end_time = loop.time() + timeout
        while loop.time() < end_time:
            remaining = end_time - loop.time()
            try:
                data = await asyncio.wait_for(
                    loop.sock_recv(sock, 1024),
                    timeout=min(remaining, 1.0),
                )
                msg = json.loads(data.decode("ascii"))
                if msg.get("magic") == BEACON_MAGIC and msg.get("server_id") == server_id:
                    host = msg["host"]
                    port = msg["port"]
                    return host, port
            except asyncio.TimeoutError:
                continue
            except (json.JSONDecodeError, KeyError):
                continue
    finally:
        sock.close()

    return None

