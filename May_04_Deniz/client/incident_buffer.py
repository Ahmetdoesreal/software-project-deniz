"""
incident_buffer.py

Persistent incident queue with sequence ordering and ack tracking.

Disk layout (one folder per connection attempt):
    data/client/{uuid}/buffer/{connect_timestamp}/
        packets.jsonl   — one payload per line, seq number stamped on each
        index.jsonl     — append-only status log (queued / sent / acked)

Packet lifecycle:
    queued  →  sent  →  acked

Seq numbers are stable across reconnects — the same seq is re-used when
retrying an unacked packet. This lets the server detect gaps:
if it receives seq 1, 2, 4 it knows seq 3 never arrived.

Integration points in ws_client.py:
    __init__           call begin_session(uuid)
    _report_incident   call enqueue() before send, mark_sent() after
    INCIDENT_RECEIVED  call mark_acked(incident_id)
    _flush_...         call get_unacked() and mark_sent() for each flushed
"""

import json
import os
import threading

from common import protocol


class IncidentBuffer:
    def __init__(self):
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._memory: dict[int, dict] = {}       # seq -> entry
        self._id_to_seq: dict[str, int] = {}     # incident_id -> seq
        self._packets_path: str | None = None
        self._index_path: str | None = None

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def begin_session(self, uuid: str) -> int:
        """
        Call at the start of each WebSocket connection.
        Creates a new timestamped folder, recovers unacked payloads from all
        previous session folders, and advances the seq counter past all known seqs.
        Returns the number of payloads restored.
        """
        unacked = self._collect_unacked(uuid)

        if unacked:
            max_seq = max(int(p.get("seq", 0)) for p in unacked)
            with self._seq_lock:
                self._seq = max(self._seq, max_seq)

        timestamp = protocol.now_iso().replace(":", "-").replace(".", "-")
        folder = os.path.join("data", "client", uuid, "buffer", timestamp)
        os.makedirs(folder, exist_ok=True)
        self._packets_path = os.path.join(folder, "packets.jsonl")
        self._index_path = os.path.join(folder, "index.jsonl")

        self._memory = {}
        self._id_to_seq = {}

        for payload in unacked:
            seq = int(payload.get("seq", 0))
            incident_id = str(payload.get("incident_id", ""))
            self._memory[seq] = {
                "seq": seq,
                "incident_id": incident_id,
                "status": "queued",
                "payload": payload,
            }
            if incident_id:
                self._id_to_seq[incident_id] = seq
            self._write_packet(payload)
            self._append_index(seq, incident_id, "queued", note="restored")

        return len(unacked)

    # ── Public API ────────────────────────────────────────────────────────────

    def enqueue(self, payload: dict) -> dict:
        """
        Assign the next seq number, write to disk, register in memory.
        Returns a copy of the payload with 'seq' stamped on it.
        Call this before attempting to send — the packet is safe on disk
        regardless of whether the send succeeds.
        """
        with self._seq_lock:
            self._seq += 1
            seq = self._seq

        payload = dict(payload)
        payload["seq"] = seq
        incident_id = str(payload.get("incident_id", ""))

        self._memory[seq] = {
            "seq": seq,
            "incident_id": incident_id,
            "status": "queued",
            "payload": payload,
        }
        if incident_id:
            self._id_to_seq[incident_id] = seq

        self._write_packet(payload)
        self._append_index(seq, incident_id, "queued")
        return payload

    def mark_sent(self, seq: int):
        """Call after a successful send. Packet is now awaiting server ack."""
        entry = self._memory.get(seq)
        if not entry or entry["status"] == "acked":
            return
        entry["status"] = "sent"
        self._append_index(seq, entry["incident_id"], "sent")

    def mark_acked(self, incident_id: str):
        """Call when incident_received arrives from the server."""
        seq = self._id_to_seq.get(incident_id)
        if seq is None:
            return
        entry = self._memory.get(seq)
        if not entry:
            return
        entry["status"] = "acked"
        self._append_index(seq, incident_id, "acked")

    def get_unacked(self) -> list[dict]:
        """
        Return all payloads not yet acked (queued or sent), ordered by seq.
        Used to flush on reconnect — sent-but-unacked packets are retried
        because we can't be sure the server received them.
        """
        return [
            e["payload"]
            for e in sorted(self._memory.values(), key=lambda x: x["seq"])
            if e["status"] in {"queued", "sent"}
        ]

    def unacked_count(self) -> int:
        return sum(1 for e in self._memory.values() if e["status"] != "acked")

    # ── Disk helpers ──────────────────────────────────────────────────────────

    def _write_packet(self, payload: dict):
        if not self._packets_path:
            return
        try:
            with open(self._packets_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload) + "\n")
        except Exception as exc:
            print(f"[BUFFER] Failed to write packet: {exc}")

    def _append_index(self, seq: int, incident_id: str, status: str, note: str = ""):
        if not self._index_path:
            return
        entry: dict = {
            "seq": seq,
            "incident_id": incident_id,
            "status": status,
            "timestamp": protocol.now_iso(),
        }
        if note:
            entry["note"] = note
        try:
            with open(self._index_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as exc:
            print(f"[BUFFER] Failed to update index: {exc}")

    def _collect_unacked(self, uuid: str) -> list[dict]:
        """
        Scan all previous session folders for this UUID.
        For each folder, read index.jsonl to get the final status of every seq.
        Return payloads whose final status is not 'acked'.
        """
        buffer_root = os.path.join("data", "client", uuid, "buffer")
        if not os.path.isdir(buffer_root):
            return []

        unacked: list[dict] = []

        for session_name in sorted(os.listdir(buffer_root)):
            folder = os.path.join(buffer_root, session_name)
            packets_path = os.path.join(folder, "packets.jsonl")
            index_path = os.path.join(folder, "index.jsonl")

            if not os.path.isfile(packets_path) or not os.path.isfile(index_path):
                continue

            # Build final-status map: seq -> last known status
            final_status: dict[int, str] = {}
            try:
                with open(index_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        row = json.loads(line)
                        final_status[int(row["seq"])] = row["status"]
            except Exception as exc:
                print(f"[BUFFER] Could not read index {index_path}: {exc}")
                continue

            # Collect payloads not acked
            try:
                with open(packets_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        payload = json.loads(line)
                        seq = int(payload.get("seq", 0))
                        if final_status.get(seq) != "acked":
                            unacked.append(payload)
            except Exception as exc:
                print(f"[BUFFER] Could not read packets {packets_path}: {exc}")

        return unacked
