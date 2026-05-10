"""
outbound_buffer.py

Thread-safe FIFO queue for incident payloads that could not be sent
while the WebSocket was disconnected. Lives outside WebSocketSession so
it survives across reconnections in main_loop().

Usage:
    # in main_loop — created once, passed to every run_ws() call
    buffer = OutboundBuffer()
    await run_ws(..., incident_buffer=buffer)

On disconnect:  _report_incident() pushes unsent payloads here.
On reconnect:   WebSocketSession._flush_incident_buffer() drains and re-sends.
"""

import collections
import threading

BUFFER_MAX_SIZE = 100


class OutboundBuffer:
    def __init__(self, maxsize: int = BUFFER_MAX_SIZE):
        self._q: collections.deque[dict] = collections.deque(maxlen=maxsize)
        self._lock = threading.Lock()

    def push(self, payload: dict) -> bool:
        """Queue a payload. Returns False if the buffer was full and the oldest was evicted."""
        with self._lock:
            before = len(self._q)
            self._q.append(payload)
            evicted = before == self._q.maxlen and len(self._q) == self._q.maxlen
            return not evicted

    def pop_all(self) -> list[dict]:
        with self._lock:
            items = list(self._q)
            self._q.clear()
            return items

    def push_back(self, items: list[dict]):
        """Return items to the front of the queue after a failed flush."""
        with self._lock:
            self._q.extendleft(reversed(items))

    def size(self) -> int:
        with self._lock:
            return len(self._q)
