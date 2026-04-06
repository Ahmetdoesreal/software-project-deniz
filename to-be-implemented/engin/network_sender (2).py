"""
network_sender.py
=================
YOUR MODULE — Network Sender (WebSocket version)
Task: Receive structured monitoring data from PayloadBuilder,
      wrap it in the message format the server expects,
      and transmit it in real-time over WebSocket.

Compatible with server teammate's websockets server on port 8765.

What you need from teammates
------------------------------
FROM server teammate (already known):
    SERVER_IP  : instructor machine IP
    WS_PORT    : 8765  (from their code: websockets.serve(..., 8765))

FROM security teammate (Naz):
    session_token : returned by server after register()
                    server code says: "Naz'ın auth modülüyle şifreli
                    token doğrulaması buraya gelecek"
                    For now, server uses: f"token_{student_id}_gizli"

FROM exam control teammate:
    EXAM_ID : the exam identifier to pass during registration
"""

import asyncio
import hashlib
import json
import time
import threading
import websockets

# ── CONFIG — fill these in once teammates confirm ─────────────────────────
SERVER_IP  = "192.168.1.1"   # ← instructor machine IP
WS_PORT    = 8765             # ← from server teammate's code
STUDENT_ID = "std_01"        # ← must match across all your modules
EXAM_ID    = "exam_001"      # ← get from exam control teammate
# ──────────────────────────────────────────────────────────────────────────

WS_URL = f"ws://{SERVER_IP}:{WS_PORT}"


class NetworkSender:
    """
    Handles all outgoing WebSocket communication from the student machine.

    How it works:
        - Connects to server via WebSocket on startup
        - Sends "request_start_exam" to register and get session_token
        - Sends "status_update" every heartbeat cycle with monitoring data
        - Keeps connection alive in a background thread

    Usage:
        sender = NetworkSender()
        sender.register()                  # once at startup
        sender.send_heartbeat(payload)     # every 5 seconds by MonitorLoop
        sender.disconnect()                # when exam ends
    """

    def __init__(self):
        self._session_token = None    # received from server after register()
        self._ws            = None    # active WebSocket connection
        self._loop          = None    # asyncio event loop (runs in background thread)
        self._connected     = False
        self._start_background_loop()

    # ── Startup ───────────────────────────────────────────────────────────

    def _start_background_loop(self):
        """
        Starts a dedicated asyncio event loop in a background thread.
        This lets the async WebSocket code run alongside the rest of the
        synchronous monitoring code (PayloadBuilder, MonitorLoop etc.)
        """
        self._loop = asyncio.new_event_loop()
        t = threading.Thread(target=self._loop.run_forever, daemon=True)
        t.start()

    def _run(self, coro):
        """
        Submits an async coroutine to the background event loop and
        blocks until it completes. This bridges sync → async code.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=10)

    # ── Public API ────────────────────────────────────────────────────────

    def register(self) -> bool:
        """
        Connects to the WebSocket server and sends a registration message.
        Must be called once before send_heartbeat().

        Server expects:
            { "action": "request_start_exam",
              "student_id": "std_01",
              "exam_id": "exam_001" }

        Server responds with:
            { "action": "exam_started_ack",
              "status": "success",
              "session_token": "token_std_01_gizli",
              "reconnected": false,
              "total_duration_minutes": 40 }

        The session_token from this response is stored and used in every
        subsequent status_update message for authentication.

        ── SECURITY TEAMMATE (Naz) INTEGRATION POINT ─────────────────────
        The server currently uses a plain token. When Naz's auth module
        is ready, the token verification happens server-side — no change
        needed here. If Naz provides a client-side encrypt() function:

            message_bytes = json.dumps(message).encode()
            encrypted = naz_security.encrypt(message_bytes)
            await self._ws.send(encrypted)

        Replace the plain send line with that call.
        ──────────────────────────────────────────────────────────────────
        """
        return self._run(self._async_register())

    def send_heartbeat(self, payload: dict):
        """
        Sends a status_update message to the server.
        Called every HEARTBEAT_INTERVAL seconds by MonitorLoop.

        Converts the payload from PayloadBuilder into the format
        the server's "status_update" handler expects.

        If there are violation flags, violation_alert is set to True
        so the server freezes the student's exam state automatically.
        """
        if not self._connected or self._ws is None:
            print("[NET] Not connected — attempting reconnect...")
            self.register()
            return

        self._run(self._async_send_heartbeat(payload))

    def disconnect(self):
        """Closes the WebSocket connection cleanly."""
        if self._ws:
            self._run(self._async_disconnect())

    # ── Message builders ──────────────────────────────────────────────────

    def _build_registration_message(self) -> str:
        """
        Builds the registration message the server expects.
        """
        message = {
            "action":     "request_start_exam",
            "student_id": STUDENT_ID,
            "exam_id":    EXAM_ID,
        }
        return json.dumps(message)

    def _build_status_update(self, payload: dict) -> str:
        """
        Converts PayloadBuilder output into the server's status_update format.

        Server reads these specific fields from security{}:
            violation_alert  : bool  — True if any flags present
            violation_type   : str   — first/most critical flag
            timestamp        : str   — human readable time
            details          : dict  — raw monitoring data
                active_window, open_apps, idle_seconds, flags

        This is the core message format contract with the server teammate.
        """
        flags           = payload.get("flags", [])
        has_violation   = len(flags) > 0
        violation_type  = flags[0] if flags else None

        message = {
            "action":        "status_update",
            "student_id":    STUDENT_ID,
            "session_token": self._session_token,
            "security": {
                "violation_alert": has_violation,
                "violation_type":  violation_type,
                "timestamp":       time.strftime("%H:%M:%S"),
                "details": {
                    "active_window": payload.get("active_window", ""),
                    "open_apps":     payload.get("open_apps", []),
                    "idle_seconds":  payload.get("idle_seconds", -1),
                    "exam_running":  payload.get("exam_running", False),
                    "flags":         flags,
                }
            }
        }
        return json.dumps(message)

    # ── Async internals ───────────────────────────────────────────────────

    async def _async_register(self) -> bool:
        """Opens WebSocket connection and sends registration message."""
        try:
            self._ws = await websockets.connect(WS_URL)
            self._connected = True
            print(f"[NET] Connected to server at {WS_URL}")

            # Send registration
            await self._ws.send(self._build_registration_message())

            # Wait for server acknowledgement
            raw  = await asyncio.wait_for(self._ws.recv(), timeout=5)
            resp = json.loads(raw)

            if resp.get("status") == "success":
                self._session_token = resp.get("session_token")
                reconnected         = resp.get("reconnected", False)
                time_left           = resp.get("time_left_seconds")

                if reconnected:
                    print(f"[NET] Reconnected! Time left: {time_left}s")
                else:
                    mins = resp.get("total_duration_minutes", 40)
                    print(f"[NET] Registered. Exam duration: {mins} min")

                return True

            else:
                print(f"[NET] Registration rejected: {resp.get('message')}")
                return False

        except ConnectionRefusedError:
            print(f"[NET] Could not connect to {WS_URL} — is the server running?")
        except asyncio.TimeoutError:
            print("[NET] Server did not respond to registration")
        except Exception as e:
            print(f"[NET] Registration error: {e}")

        self._connected = False
        return False

    async def _async_send_heartbeat(self, payload: dict):
        """Sends the status_update message over the open WebSocket."""
        try:
            message = self._build_status_update(payload)
            await self._ws.send(message)

            # Log compactly
            flags = payload.get("flags", [])
            flag_str = ", ".join(flags) if flags else "clean"
            print(f"[NET] Sent → violation={len(flags)>0} | flags=[{flag_str}]")

        except websockets.ConnectionClosed:
            print("[NET] Connection closed — will retry on next heartbeat")
            self._connected = False
            self._ws        = None
        except Exception as e:
            print(f"[NET] Send error: {e}")

    async def _async_disconnect(self):
        """Closes the WebSocket connection."""
        try:
            await self._ws.close()
            print("[NET] Disconnected from server.")
        except Exception:
            pass
        self._connected = False
        self._ws        = None


# ── Standalone test (no real server needed) ───────────────────────────────

if __name__ == "__main__":
    print("=" * 55)
    print("  NETWORK SENDER — message format test")
    print("  (Shows what gets sent, no real server needed)")
    print("=" * 55)

    sender = NetworkSender()

    fake_payload = {
        "student_id":    STUDENT_ID,
        "student_name":  "Test Student",
        "active_window": "Google Chrome - Gmail",
        "open_apps":     ["chrome", "examapp"],
        "exam_running":  True,
        "idle_seconds":  12.3,
        "flags":         ["FOCUS_LOST", "BANNED:chrome"],
    }

    print("\n── Registration message (sent once at startup) ──")
    print(json.dumps(json.loads(sender._build_registration_message()), indent=2))

    # Temporarily set a fake token to show status_update format
    sender._session_token = "token_std_01_gizli"

    print("\n── Status update message (sent every 5 seconds) ──")
    print(json.dumps(json.loads(sender._build_status_update(fake_payload)), indent=2))

    print("\n── Clean session (no flags) ──")
    clean_payload = {**fake_payload, "flags": [], "active_window": "ExamApp"}
    print(json.dumps(json.loads(sender._build_status_update(clean_payload)), indent=2))
