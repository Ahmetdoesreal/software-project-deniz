#!/usr/bin/env python3
"""Standalone web UI for reviewing server-side runtime data.

The tool is intentionally self-contained: Python stdlib backend, static files
under ./web, and all data access scoped to a selected data/server directory.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left, bisect_right
import csv
import errno
import fnmatch
import io
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse


UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
VIDEO_SUFFIXES = {".ts", ".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}
TEXT_SCAN_LIMIT_BYTES = 96 * 1024 * 1024
RECENT_PROCESS_LIMIT = 900
REPLAY_INCIDENT_WINDOW_SECONDS = 90.0
MAX_MATCHED_REPLAYS_PER_INCIDENT = 6
MAX_MATCHED_INCIDENTS_PER_REPLAY = 12
CLIENT_DISCONNECT_WINERRORS = {10053, 10054, 10058}
CLIENT_DISCONNECT_ERRNOS = {
    errno.EPIPE,
    errno.ECONNRESET,
    errno.ECONNABORTED,
}
REPLAY_WINDOW_RE = re.compile(r"replay_window_(\d{8}T\d{6}Z)", re.IGNORECASE)
REPLAY_SAVE_ID_RE = re.compile(r"window_(\d{8}T\d{6}Z)", re.IGNORECASE)
REPLAY_PREFIX_RE = re.compile(r"^(\d{8})_(\d{6})")

mimetypes.add_type("video/mp2t", ".ts")
mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/quicktime", ".mov")


def is_client_disconnect(exc: BaseException) -> bool:
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    if isinstance(exc, OSError):
        if getattr(exc, "winerror", None) in CLIENT_DISCONNECT_WINERRORS:
            return True
        if getattr(exc, "errno", None) in CLIENT_DISCONNECT_ERRNOS:
            return True
    return False


def now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def json_load_file(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return fallback


def iter_jsonl_file(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            try:
                yield line_no, json.loads(text), text
            except json.JSONDecodeError:
                yield line_no, None, text


def normalize_process_name(value: Any) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if "\\" in clean:
        clean = PureWindowsPath(clean).name
    return os.path.basename(clean).lower()


def process_name_matches(pattern: str, process_name: str) -> bool:
    normalized_pattern = normalize_process_name(pattern)
    normalized_name = normalize_process_name(process_name)
    if not normalized_pattern or not normalized_name:
        return False
    if any(marker in normalized_pattern for marker in ("*", "?", "[")):
        return fnmatch.fnmatchcase(normalized_name, normalized_pattern)
    return normalized_name == normalized_pattern


def first_process_match(process_name: str, patterns: list[str]) -> str:
    for pattern in patterns:
        if process_name_matches(pattern, process_name):
            return pattern
    return ""


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def clean_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines: list[str] = []
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                lines.append(line)
    except Exception:
        return []
    return lines


def isoish(value: Any) -> str:
    return str(value or "").strip()


def parse_timestamp(value: Any) -> datetime | None:
    text = isoish(value)
    if not text:
        return None
    if re.fullmatch(r"\d{8}T\d{6}Z", text):
        try:
            return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if re.fullmatch(r"\d{8}_\d{6}", text):
        try:
            return datetime.strptime(text, "%Y%m%d_%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def timestamp_seconds(value: Any) -> float | None:
    parsed = parse_timestamp(value)
    return parsed.timestamp() if parsed else None


def timestamp_iso(value: Any) -> str:
    parsed = parse_timestamp(value)
    if not parsed:
        return ""
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def incident_time(incident: dict) -> str:
    for key in ("event_at", "timestamp", "reported_at", "server_received_at", "saved_at", "queued_at"):
        value = isoish(incident.get(key))
        if value:
            return value
    return ""


def incident_row_time(incident: dict) -> str:
    return isoish(incident.get("at")) or incident_time(incident)


def incident_display_row(incident: dict, source_ref: str) -> dict:
    raw_processes = incident.get("raw_processes")
    return {
        "at": incident_time(incident),
        "incident_id": str(incident.get("incident_id", "") or ""),
        "rule_id": str(incident.get("rule_id") or incident.get("event_type") or ""),
        "event_type": str(incident.get("event_type") or ""),
        "status": str(incident.get("status") or ""),
        "severity": str(incident.get("severity") or ""),
        "summary": str(incident.get("summary") or ""),
        "process_name": str(incident.get("process_name") or ""),
        "pid": incident.get("pid", ""),
        "window_title": str(incident.get("window_title") or incident.get("observed_window_title") or ""),
        "evidence_status": str(incident.get("evidence_status") or ""),
        "raw_process_count": len(raw_processes) if isinstance(raw_processes, list) else 0,
        "source_ref": source_ref,
    }


def replay_time_from_value(value: Any) -> str:
    text = isoish(value)
    if not text:
        return ""
    for pattern in (REPLAY_SAVE_ID_RE, REPLAY_WINDOW_RE):
        match = pattern.search(text)
        if match:
            return timestamp_iso(match.group(1))
    prefix = REPLAY_PREFIX_RE.match(text)
    if prefix:
        return timestamp_iso(f"{prefix.group(1)}_{prefix.group(2)}")
    return timestamp_iso(text)


def replay_time_from_name(name: str) -> str:
    return replay_time_from_value(Path(name).name)


def replay_time_from_sidecar(sidecar: dict, name: str) -> str:
    metadata = sidecar.get("metadata") if isinstance(sidecar.get("metadata"), dict) else {}
    for value in (
        metadata.get("save_id"),
        name,
        sidecar.get("saved_at"),
        sidecar.get("created_at"),
        sidecar.get("timestamp"),
    ):
        replay_at = replay_time_from_value(value)
        if replay_at:
            return replay_at
    return ""


def replay_key(replay: dict) -> str:
    if replay.get("container") == "zip":
        return f"{replay.get('zip_path', '')}#{replay.get('member', '')}"
    return str(replay.get("path") or "")


def resolve_data_root(candidate: str | Path) -> Path:
    base = Path(candidate).expanduser().resolve()
    candidates = [
        base,
        base / "data" / "server",
        base / "server" / "data" / "server",
        base / "May_12" / "server" / "data" / "server",
    ]
    for item in candidates:
        if item.is_dir():
            return item.resolve()
    return base


def default_data_root() -> Path:
    cwd = Path.cwd()
    for candidate in (
        cwd / "data" / "server",
        cwd / "server" / "data" / "server",
        cwd / "May_12" / "server" / "data" / "server",
        cwd / "Software" / "server_data" / "data" / "server",
    ):
        if candidate.is_dir():
            return candidate.resolve()
    return (cwd / "data" / "server").resolve()


def rel_to_root(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def student_id_from_rel(rel: str) -> str:
    parts = Path(rel).parts
    for prefix in ("artifacts", "submissions"):
        if len(parts) >= 2 and parts[0].lower() == prefix:
            return parts[1]
    for part in parts:
        if UUID_RE.match(part):
            return part
    return ""


def bytes_label(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


class ServerDataIndex:
    def __init__(self, data_root: Path):
        self.data_root = data_root.resolve()
        self.students: dict[str, dict] = {}
        self.login_to_client: dict[str, str] = {}
        self.client_to_login: dict[str, str] = {}
        self.blacklist: list[str] = []
        self.exam_policy: dict = {}
        self.process_definitions: list[dict] = []
        self.incident_rules: list[dict] = []
        self.errors: list[str] = []
        self.source_payloads: dict[str, dict] = {}
        self.generated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._blacklist_seen: set[tuple[str, str, str, str, str]] = set()

    def build(self) -> dict:
        self._load_settings()
        self._load_users()
        self._scan_incidents()
        self._scan_submissions()
        self._scan_direct_runtime_files()
        self._scan_replays()
        self._finalize_students()
        return self.to_summary()

    def _load_settings(self):
        self.blacklist = clean_lines(self.data_root / "process_blacklist.txt")
        self.exam_policy = json_load_file(self.data_root / "exam_policy.json", {}) or {}
        definitions = json_load_file(self.data_root / "process_definitions.json", []) or []
        if isinstance(definitions, dict):
            definitions = definitions.get("entries", [])
        self.process_definitions = definitions if isinstance(definitions, list) else []
        rules = json_load_file(self.data_root / "incident_rules.json", []) or []
        if isinstance(rules, dict):
            rules = rules.get("entries", [])
        self.incident_rules = rules if isinstance(rules, list) else []

    def _load_users(self):
        users = json_load_file(self.data_root / "server_users.json", {}) or {}
        if not isinstance(users, dict):
            return
        for login_id, user in users.items():
            if not isinstance(user, dict):
                continue
            client_id = str(user.get("uuid", "") or "").strip()
            student = self._student(client_id=client_id, login_id=str(login_id))
            student["user"] = user
            student["login_id"] = str(login_id)
            student["client_id"] = client_id or student["id"]
            if client_id:
                self.login_to_client[str(login_id)] = client_id
                self.client_to_login[client_id] = str(login_id)

    def _scan_incidents(self):
        path = self.data_root / "incidents.jsonl"
        if not path.is_file():
            return
        for line_no, incident, raw in iter_jsonl_file(path):
            if not isinstance(incident, dict):
                self.errors.append(f"incidents.jsonl:{line_no}: invalid JSON object")
                continue
            client_id = str(incident.get("client_id") or incident.get("session_uuid") or "").strip()
            login_id = str(incident.get("login_id") or "").strip()
            student = self._student(client_id=client_id, login_id=login_id)
            incident["client_id"] = student.get("client_id") or client_id
            if login_id:
                incident["login_id"] = login_id
            source_ref = self._register_source(
                student,
                "incident",
                incident,
                f"incidents.jsonl:{line_no}",
                f"{student.get('login_id') or student.get('client_id') or 'student'}_incident_{incident.get('incident_id') or line_no}.json",
            )
            student["incidents"].append(incident_display_row(incident, source_ref))
            if incident.get("rule_id") == "process_blacklist" and incident.get("status") == "opened":
                student["known_blacklist_incident_count"] += 1
            title = incident.get("window_title") or incident.get("observed_window_title")
            if title:
                self._record_title(
                    student,
                    {
                        "timestamp": incident_time(incident),
                        "event_type": incident.get("event_type") or incident.get("rule_id") or "incident",
                        "process_name": incident.get("process_name", ""),
                        "pid": incident.get("pid", ""),
                        "window_title": title,
                        "source": "incidents.jsonl",
                        "rule_id": incident.get("rule_id", ""),
                        "incident_id": incident.get("incident_id", ""),
                        "source_ref": source_ref,
                    },
                )
            raw_processes = incident.get("raw_processes")
            if isinstance(raw_processes, list):
                for process in raw_processes:
                    self._record_process(
                        student,
                        process,
                        incident_time(incident),
                        "incidents.jsonl/raw_processes",
                        source_payload={
                            "incident_id": incident.get("incident_id", ""),
                            "rule_id": incident.get("rule_id", ""),
                            "status": incident.get("status", ""),
                            "summary": incident.get("summary", ""),
                            "process": process,
                        },
                    )
            if incident.get("process_name"):
                self._record_process(student, incident, incident_time(incident), "incidents.jsonl", source_ref=source_ref)

    def _scan_submissions(self):
        submissions_root = self.data_root / "submissions"
        if not submissions_root.is_dir():
            return
        for zip_path in sorted(submissions_root.rglob("*.zip")):
            rel = rel_to_root(zip_path, self.data_root)
            client_id = student_id_from_rel(rel)
            student = self._student(client_id=client_id)
            entry = {
                "path": rel,
                "name": zip_path.name,
                "size_bytes": self._file_size(zip_path),
                "size_label": bytes_label(self._file_size(zip_path)),
                "modified_at": self._mtime(zip_path),
                "runtime_files": [],
                "replay_members": [],
                "error": "",
            }
            student["submissions"].append(entry)
            try:
                with zipfile.ZipFile(zip_path) as archive:
                    self._scan_submission_archive(student, entry, archive, rel)
            except Exception as exc:
                entry["error"] = str(exc)
                self.errors.append(f"{rel}: {exc}")

    def _scan_submission_archive(self, student: dict, submission: dict, archive: zipfile.ZipFile, zip_rel: str):
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            lower = name.lower()
            suffix = Path(name).suffix.lower()
            if suffix in VIDEO_SUFFIXES:
                replay_at = replay_time_from_name(name)
                replay_entry = {
                    "container": "zip",
                    "zip_path": zip_rel,
                    "member": name,
                    "replay_key": f"{zip_rel}#{name}",
                    "name": Path(name).name,
                    "size_bytes": int(info.file_size),
                    "size_label": bytes_label(int(info.file_size)),
                    "modified_at": "",
                    "saved_at": "",
                    "replay_at": replay_at,
                    "kind": "submission_bundle",
                    "incident_id": "",
                    "rule_id": "",
                    "matched_incidents": [],
                    "matched_incident_count": 0,
                }
                submission["replay_members"].append(replay_entry)
                student["replays"].append(replay_entry)
                continue
            if info.file_size > TEXT_SCAN_LIMIT_BYTES:
                continue
            if lower.endswith("runtime/processes.jsonl") or lower.endswith("/processes.jsonl") or lower == "processes.jsonl":
                submission["runtime_files"].append(name)
                self._scan_zip_process_jsonl(student, archive, info, f"{zip_rel}!{name}")
            elif lower.endswith("runtime/process_report_requested.json") or "process_report_requested" in lower:
                submission["runtime_files"].append(name)
                payload = self._read_zip_json(archive, info)
                if isinstance(payload, dict):
                    source = f"{zip_rel}!{name}"
                    self._scan_process_payload(
                        student,
                        payload,
                        source,
                        self._locator_from_source(source),
                    )
            elif lower.endswith("runtime/focused_window.jsonl") or lower.endswith("/focused_window.jsonl") or lower == "focused_window.jsonl":
                submission["runtime_files"].append(name)
                self._scan_zip_focus_jsonl(student, archive, info, f"{zip_rel}!{name}")
            elif lower.endswith("runtime/focused_window_snapshot.json") or lower.endswith("/focused_window_snapshot.json"):
                submission["runtime_files"].append(name)
                payload = self._read_zip_json(archive, info)
                if isinstance(payload, dict):
                    self._scan_focus_payload(student, payload, f"{zip_rel}!{name}")

    def _scan_direct_runtime_files(self):
        names = {
            "processes.jsonl",
            "focused_window.jsonl",
            "focused_window_snapshot.json",
        }
        for path in sorted(self.data_root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".zip":
                continue
            name = path.name.lower()
            rel = rel_to_root(path, self.data_root)
            client_id = student_id_from_rel(rel)
            if not client_id and path.parent == self.data_root:
                continue
            student = self._student(client_id=client_id)
            try:
                if name == "processes.jsonl":
                    for line_no, payload, _raw in iter_jsonl_file(path):
                        if isinstance(payload, dict):
                            self._scan_process_payload(
                                student,
                                payload,
                                rel,
                                {"type": "file_jsonl", "path": rel, "line": line_no},
                            )
                elif name.startswith("process_report_requested") and name.endswith(".json"):
                    payload = json_load_file(path, {})
                    if isinstance(payload, dict):
                        self._scan_process_payload(
                            student,
                            payload,
                            rel,
                            {"type": "file_json", "path": rel},
                        )
                elif name == "focused_window.jsonl":
                    for _line_no, payload, _raw in iter_jsonl_file(path):
                        if isinstance(payload, dict):
                            self._scan_focus_payload(student, payload, rel)
                elif name in names:
                    payload = json_load_file(path, {})
                    if isinstance(payload, dict):
                        self._scan_focus_payload(student, payload, rel)
            except Exception as exc:
                self.errors.append(f"{rel}: {exc}")

    def _scan_replays(self):
        for path in sorted(self.data_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in VIDEO_SUFFIXES:
                continue
            rel = rel_to_root(path, self.data_root)
            sidecar = json_load_file(path.with_suffix(path.suffix + ".json"), {}) or {}
            sidecar_metadata = sidecar.get("metadata") if isinstance(sidecar.get("metadata"), dict) else {}
            conversion_meta = read_conversion_metadata(path)
            client_id = str(sidecar.get("client_id") or student_id_from_rel(rel) or "").strip()
            login_id = str(sidecar.get("login_id") or "").strip()
            student = self._student(client_id=client_id, login_id=login_id)
            converted = bool(conversion_meta.get("converted")) or path.name.lower().endswith("_compatible.mp4")
            original_path = str(
                conversion_meta.get("original_path")
                or conversion_meta.get("converted_from")
                or guessed_original_path(self.data_root, path)
                or ""
            )
            saved_at = isoish(sidecar.get("saved_at"))
            replay_at = replay_time_from_sidecar(sidecar, path.name)
            incident_id = str(sidecar_metadata.get("incident_id") or sidecar.get("incident_id") or "")
            rule_id = str(sidecar_metadata.get("rule_id") or sidecar.get("rule_id") or "")
            metadata = {
                key: sidecar.get(key)
                for key in ("saved_at", "sha256", "kind", "login_id", "client_id")
                if key in sidecar
            }
            for key in ("save_id", "coalesce_window_seconds", "source", "incident_id", "rule_id"):
                if key in sidecar_metadata:
                    metadata[key] = sidecar_metadata.get(key)
            replay = {
                "container": "file",
                "path": rel,
                "replay_key": rel,
                "name": path.name,
                "size_bytes": self._file_size(path),
                "size_label": bytes_label(self._file_size(path)),
                "modified_at": self._mtime(path),
                "saved_at": saved_at,
                "replay_at": replay_at,
                "kind": Path(rel).parts[2] if len(Path(rel).parts) >= 3 and Path(rel).parts[0] == "artifacts" else path.parent.name,
                "incident_id": incident_id,
                "rule_id": rule_id,
                "converted": converted,
                "original_path": original_path,
                "has_converted": False,
                "converted_path": "",
                "converted_name": "",
                "matched_incidents": [],
                "matched_incident_count": 0,
                "metadata": metadata,
            }
            if conversion_meta:
                replay["metadata"]["conversion"] = {
                    key: conversion_meta.get(key)
                    for key in ("converted_at", "returncode", "duration_seconds")
                    if key in conversion_meta
                }
            if not any(existing.get("container") == "file" and existing.get("path") == rel for existing in student["replays"]):
                student["replays"].append(replay)
        for student in self.students.values():
            converted_by_original = {
                replay.get("original_path"): replay
                for replay in student["replays"]
                if replay.get("container") == "file" and replay.get("converted") and replay.get("original_path")
            }
            for replay in student["replays"]:
                converted_replay = converted_by_original.get(replay.get("path"))
                if converted_replay:
                    replay["has_converted"] = True
                    replay["converted_path"] = converted_replay.get("path", "")
                    replay["converted_name"] = converted_replay.get("name", "")

    def _scan_zip_process_jsonl(self, student: dict, archive: zipfile.ZipFile, info: zipfile.ZipInfo, source: str):
        with archive.open(info) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
            for line_no, raw_line in enumerate(text, 1):
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    self._scan_process_payload(
                        student,
                        payload,
                        source,
                        self._locator_from_source(source, line_no=line_no),
                    )

    def _scan_zip_focus_jsonl(self, student: dict, archive: zipfile.ZipFile, info: zipfile.ZipInfo, source: str):
        with archive.open(info) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
            for raw_line in text:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    self._scan_focus_payload(student, payload, source)

    def _read_zip_json(self, archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> Any:
        try:
            with archive.open(info) as raw:
                return json.loads(raw.read().decode("utf-8", errors="replace"))
        except Exception:
            return None

    def _scan_process_payload(self, student: dict, payload: dict, source: str, source_locator: dict | None = None):
        timestamp = isoish(payload.get("timestamp") or payload.get("created_at"))
        source_ref = self._register_source(
            student,
            "process_report",
            payload if source_locator is None else None,
            source,
            f"{student.get('login_id') or student.get('client_id') or 'student'}_process_report_{len(self.source_payloads) + 1}.json",
            locator=source_locator,
        )
        for key, action in (("processes", "seen"), ("added", "added"), ("removed", "removed")):
            values = payload.get(key)
            if not isinstance(values, list):
                continue
            for process in values:
                self._record_process(
                    student,
                    process,
                    timestamp,
                    source,
                    action=action,
                    source_ref=source_ref,
                    source_payload=process,
                )

    def _scan_focus_payload(self, student: dict, payload: dict, source: str):
        timestamp = isoish(payload.get("timestamp") or payload.get("created_at"))
        event_type = isoish(payload.get("event_type") or payload.get("type") or "focused_window")
        source_ref = self._register_source(
            student,
            "focused_window",
            payload,
            source,
            f"{student.get('login_id') or student.get('client_id') or 'student'}_focused_window_{len(student['title_history']) + 1}.json",
        )
        if isinstance(payload.get("window"), dict):
            self._record_title(student, self._title_entry(payload["window"], timestamp, event_type, source, source_ref))
        if isinstance(payload.get("current"), dict):
            self._record_title(student, self._title_entry(payload["current"], timestamp, event_type, source, source_ref))
        if isinstance(payload.get("snapshot"), dict):
            self._record_title(student, self._title_entry(payload["snapshot"], timestamp, event_type, source, source_ref))

    def _title_entry(self, window: dict, timestamp: str, event_type: str, source: str, source_ref: str) -> dict:
        return {
            "timestamp": timestamp,
            "event_type": event_type,
            "process_name": window.get("process_name") or window.get("process") or window.get("executable") or "",
            "pid": window.get("pid", ""),
            "window_title": window.get("window_title") or window.get("title") or "",
            "source": source,
            "source_ref": source_ref,
        }

    def _record_title(self, student: dict, entry: dict):
        title = isoish(entry.get("window_title"))
        process_name = isoish(entry.get("process_name"))
        if not title and not process_name:
            return
        policy = self._title_policy_status(title)
        entry["policy_status"] = policy.get("status", "")
        entry["matched_pattern"] = policy.get("pattern", "")
        entry["matched_rule"] = policy.get("rule", "")
        key = (
            isoish(entry.get("timestamp")),
            normalize_text(title),
            normalize_text(process_name),
            isoish(entry.get("source")),
        )
        if key in student["_title_seen"]:
            return
        student["_title_seen"].add(key)
        student["title_history"].append(entry)
        if entry["policy_status"] in {"blocked", "not_allowed", "rule_match"}:
            student["title_policy_hit_count"] += 1

    def _record_process(
        self,
        student: dict,
        process: Any,
        timestamp: str,
        source: str,
        *,
        action: str = "seen",
        source_ref: str = "",
        source_payload: Any = None,
    ):
        pid, name, username, process_path = self._process_parts(process)
        if not name:
            return
        normalized_name = normalize_process_name(name)
        normalized_path = normalize_text(process_path)
        key = f"{normalized_name}|{normalized_path}"
        process_entry = student["_process_index"].setdefault(
            key,
            {
                "process_name": name,
                "normalized_process_name": normalized_name,
                "process_path": process_path,
                "process_username": username,
                "first_seen": timestamp,
                "last_seen": timestamp,
                "count": 0,
                "pids": [],
                "sources": [],
                "source_ref": source_ref,
            },
        )
        process_entry["count"] += 1
        if timestamp and (not process_entry.get("first_seen") or timestamp < process_entry["first_seen"]):
            process_entry["first_seen"] = timestamp
        if timestamp and timestamp > process_entry.get("last_seen", ""):
            process_entry["last_seen"] = timestamp
        if pid and pid not in process_entry["pids"] and len(process_entry["pids"]) < 20:
            process_entry["pids"].append(pid)
        if source not in process_entry["sources"] and len(process_entry["sources"]) < 8:
            process_entry["sources"].append(source)
        if source_ref and not process_entry.get("source_ref"):
            process_entry["source_ref"] = source_ref
        if len(student["recent_process_events"]) < RECENT_PROCESS_LIMIT:
            student["recent_process_events"].append(
                {
                    "timestamp": timestamp,
                    "action": action,
                    "pid": pid,
                    "process_name": name,
                    "process_username": username,
                    "process_path": process_path,
                    "source": source,
                    "source_ref": source_ref,
                }
            )
        match = first_process_match(name, self.blacklist)
        if match:
            match_key = (student["id"], timestamp, normalized_name, str(pid), source)
            if match_key not in self._blacklist_seen:
                self._blacklist_seen.add(match_key)
                match_ref = source_ref or self._register_source(
                    student,
                    "blacklist_match",
                    {
                        "timestamp": timestamp,
                        "action": action,
                        "source": source,
                        "matched_blacklist_entry": match,
                        "process": source_payload if source_payload is not None else process,
                    },
                    source,
                    f"{student.get('login_id') or student.get('client_id') or 'student'}_blacklist_match_{len(student['retro_blacklist_matches']) + 1}.json",
                )
                student["retro_blacklist_matches"].append(
                    {
                        "timestamp": timestamp,
                        "pid": pid,
                        "process_name": name,
                        "process_username": username,
                        "process_path": process_path,
                        "matched_blacklist_entry": match,
                        "source": source,
                        "source_ref": match_ref,
                    }
                )

    def _process_parts(self, process: Any) -> tuple[int, str, str, str]:
        if isinstance(process, dict):
            pid = int(process.get("pid", 0) or 0)
            name = str(process.get("process_name") or process.get("name") or process.get("normalized_process_name") or "")
            username = str(process.get("process_username") or process.get("username") or "")
            process_path = str(process.get("process_path") or process.get("path") or "")
            return pid, name, username, process_path
        if isinstance(process, (list, tuple)) and len(process) >= 2:
            pid = int(process[0] or 0)
            name = str(process[1] or "")
            username = str(process[2] or "") if len(process) > 2 and process[2] else ""
            process_path = str(process[3] or "") if len(process) > 3 and process[3] else ""
            return pid, name, username, process_path
        return 0, "", "", ""

    def _title_policy_status(self, title: str) -> dict:
        if not title:
            return {}
        focused = (self.exam_policy.get("rules") or {}).get("focused_window") or {}
        mode = str(focused.get("window_title_match_mode") or "contains").lower()
        blocked = [str(item) for item in focused.get("blocked_window_titles", []) if str(item).strip()]
        allowed = [str(item) for item in focused.get("allowed_window_titles", []) if str(item).strip()]
        blocked_match = self._first_title_match(title, blocked, mode)
        if blocked_match:
            return {"status": "blocked", "pattern": blocked_match, "rule": "focused_window.blocked_window_titles"}
        if allowed and not self._first_title_match(title, allowed, mode):
            return {"status": "not_allowed", "pattern": "", "rule": "focused_window.allowed_window_titles"}
        for rule in self.incident_rules:
            if not isinstance(rule, dict):
                continue
            if str(rule.get("rule_id") or "") != "focused_window_policy":
                continue
            patterns = [str(item) for item in rule.get("window_title_patterns", []) if str(item).strip()]
            match = self._first_title_match(title, patterns, str(rule.get("match_mode") or "contains"))
            if match:
                return {
                    "status": "rule_match",
                    "pattern": match,
                    "rule": str(rule.get("name") or rule.get("definition_id") or "incident_rule"),
                }
        return {"status": "ok", "pattern": "", "rule": ""}

    def _first_title_match(self, title: str, patterns: list[str], mode: str) -> str:
        normalized_title = normalize_text(title)
        for pattern in patterns:
            normalized_pattern = normalize_text(pattern)
            if not normalized_pattern:
                continue
            if mode == "exact" and normalized_title == normalized_pattern:
                return pattern
            if mode != "exact" and normalized_pattern in normalized_title:
                return pattern
        return ""

    def _locator_from_source(self, source: str, *, line_no: int | None = None) -> dict:
        if "!" in source:
            zip_path, member = source.split("!", 1)
            locator = {"type": "zip_jsonl" if line_no else "zip_json", "zip_path": zip_path, "member": member}
            if line_no:
                locator["line"] = line_no
            return locator
        locator = {"type": "file_jsonl" if line_no else "file_json", "path": source}
        if line_no:
            locator["line"] = line_no
        return locator

    def _register_source(
        self,
        student: dict,
        kind: str,
        payload: Any,
        label: str,
        filename: str,
        *,
        locator: dict | None = None,
    ) -> str:
        ref = f"src{len(self.source_payloads) + 1}"
        safe_filename = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in filename).strip("._")
        self.source_payloads[ref] = {
            "student_id": student.get("id", ""),
            "login_id": student.get("login_id", ""),
            "client_id": student.get("client_id", ""),
            "kind": kind,
            "label": label,
            "filename": safe_filename or f"{ref}.json",
            "payload": payload,
            "locator": locator or {},
        }
        return ref

    def source_json(self, ref: str) -> dict | None:
        source = self.source_payloads.get(str(ref or "").strip())
        if not source:
            return None
        if source.get("payload") is None and source.get("locator"):
            source = dict(source)
            source["payload"] = self._load_source_locator(source.get("locator", {}))
        return source

    def _load_source_locator(self, locator: dict) -> Any:
        locator_type = str(locator.get("type") or "")
        if locator_type == "file_json":
            return json_load_file(self.data_root / str(locator.get("path") or ""), {})
        if locator_type == "file_jsonl":
            path = self.data_root / str(locator.get("path") or "")
            return self._read_jsonl_line(path, int(locator.get("line", 0) or 0))
        if locator_type == "zip_json":
            return self._read_zip_member_json(
                self.data_root / str(locator.get("zip_path") or ""),
                str(locator.get("member") or ""),
            )
        if locator_type == "zip_jsonl":
            return self._read_zip_member_jsonl_line(
                self.data_root / str(locator.get("zip_path") or ""),
                str(locator.get("member") or ""),
                int(locator.get("line", 0) or 0),
            )
        return {}

    def _read_jsonl_line(self, path: Path, line_no: int) -> Any:
        if line_no <= 0 or not path.is_file():
            return {}
        for current_line, payload, _raw in iter_jsonl_file(path):
            if current_line == line_no:
                return payload if isinstance(payload, dict) else {}
        return {}

    def _read_zip_member_json(self, zip_path: Path, member: str) -> Any:
        try:
            with zipfile.ZipFile(zip_path) as archive:
                with archive.open(member) as raw:
                    return json.loads(raw.read().decode("utf-8", errors="replace"))
        except Exception:
            return {}

    def _read_zip_member_jsonl_line(self, zip_path: Path, member: str, line_no: int) -> Any:
        if line_no <= 0:
            return {}
        try:
            with zipfile.ZipFile(zip_path) as archive:
                with archive.open(member) as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                    for current_line, raw_line in enumerate(text, 1):
                        if current_line != line_no:
                            continue
                        return json.loads(raw_line)
        except Exception:
            return {}
        return {}

    def _student(self, *, client_id: str = "", login_id: str = "") -> dict:
        client_id = str(client_id or "").strip()
        login_id = str(login_id or "").strip()
        if not client_id and login_id:
            client_id = self.login_to_client.get(login_id, "")
        if not login_id and client_id:
            login_id = self.client_to_login.get(client_id, "")
        key = client_id or (f"login:{login_id}" if login_id else "unknown")
        if key not in self.students:
            self.students[key] = {
                "id": key,
                "client_id": client_id,
                "login_id": login_id,
                "user": {},
                "incidents": [],
                "submissions": [],
                "replays": [],
                "title_history": [],
                "title_policy_hit_count": 0,
                "recent_process_events": [],
                "retro_blacklist_matches": [],
                "known_blacklist_incident_count": 0,
                "_process_index": {},
                "_title_seen": set(),
            }
        student = self.students[key]
        if client_id and not student.get("client_id"):
            student["client_id"] = client_id
        if login_id and not student.get("login_id"):
            student["login_id"] = login_id
        return student

    def _finalize_students(self):
        for student in self.students.values():
            student["processes"] = sorted(
                student["_process_index"].values(),
                key=lambda item: (-int(item.get("count", 0)), str(item.get("normalized_process_name", ""))),
            )
            self._match_incidents_and_replays(student)
            student["incidents"].sort(key=incident_row_time, reverse=True)
            student["title_history"].sort(key=lambda item: item.get("timestamp", ""), reverse=True)
            student["retro_blacklist_matches"].sort(key=lambda item: item.get("timestamp", ""), reverse=True)
            student["replays"].sort(key=lambda item: item.get("replay_at") or item.get("modified_at", ""), reverse=True)
            student["submissions"].sort(key=lambda item: item.get("modified_at", ""), reverse=True)
            student.pop("_process_index", None)
            student.pop("_title_seen", None)

    def _match_incidents_and_replays(self, student: dict):
        incidents = student.get("incidents", [])
        replays = student.get("replays", [])
        if not incidents or not replays:
            for incident in incidents:
                incident["matched_replays"] = []
                incident["matched_replay_count"] = 0
            for replay in replays:
                replay["replay_key"] = replay_key(replay)
                replay["matched_incidents"] = []
                replay["matched_incident_count"] = 0
            return

        replay_by_path = {
            replay.get("path"): replay
            for replay in replays
            if replay.get("container") == "file" and replay.get("path")
        }
        for replay in replays:
            replay["replay_key"] = replay_key(replay)
            replay["matched_incidents"] = []
            replay["matched_incident_count"] = 0
            original = replay_by_path.get(replay.get("original_path"))
            if original:
                for key in ("incident_id", "rule_id", "replay_at", "saved_at"):
                    if not replay.get(key) and original.get(key):
                        replay[key] = original.get(key)

        for incident in incidents:
            incident["matched_replays"] = []
            incident["matched_replay_count"] = 0

        incidents_by_id: dict[str, list[dict]] = {}
        timed_incidents: list[tuple[float, int, dict]] = []
        for index, incident in enumerate(incidents):
            incident_id = str(incident.get("incident_id") or "")
            if incident_id:
                incidents_by_id.setdefault(incident_id, []).append(incident)
            seconds = timestamp_seconds(incident_row_time(incident))
            if seconds is not None:
                timed_incidents.append((seconds, index, incident))
        timed_incidents.sort(key=lambda item: item[0])
        incident_seconds = [item[0] for item in timed_incidents]

        for replay in replays:
            matches: dict[int, tuple[dict, str, float | None]] = {}

            def add_match(incident: dict, reason: str, delta_seconds: float | None):
                key = id(incident)
                current = matches.get(key)
                if current is None:
                    matches[key] = (incident, reason, delta_seconds)
                    return
                current_reason = current[1]
                current_delta = current[2]
                if self._match_rank(reason, delta_seconds) < self._match_rank(current_reason, current_delta):
                    matches[key] = (incident, reason, delta_seconds)

            direct_incident_id = str(replay.get("incident_id") or "")
            if direct_incident_id:
                for incident in incidents_by_id.get(direct_incident_id, []):
                    add_match(incident, "incident_id", self._min_delta_seconds(incident, replay))

            for replay_seconds in self._replay_seconds_candidates(replay):
                left = bisect_left(incident_seconds, replay_seconds - REPLAY_INCIDENT_WINDOW_SECONDS)
                right = bisect_right(incident_seconds, replay_seconds + REPLAY_INCIDENT_WINDOW_SECONDS)
                for incident_seconds_value, _index, incident in timed_incidents[left:right]:
                    add_match(incident, "near_time", abs(incident_seconds_value - replay_seconds))

            ordered = sorted(
                matches.values(),
                key=lambda item: self._match_rank(item[1], item[2]),
            )
            replay["matched_incident_count"] = len(ordered)
            for incident, reason, delta_seconds in ordered[:MAX_MATCHED_INCIDENTS_PER_REPLAY]:
                replay["matched_incidents"].append(self._incident_match_summary(incident, reason, delta_seconds))
                incident["matched_replays"].append(self._replay_match_summary(replay, reason, delta_seconds))

        for incident in incidents:
            incident["matched_replays"].sort(key=lambda item: self._match_rank(item.get("match_reason", ""), item.get("delta_seconds")))
            incident["matched_replay_count"] = len(incident["matched_replays"])
            incident["matched_replays"] = incident["matched_replays"][:MAX_MATCHED_REPLAYS_PER_INCIDENT]

    def _match_rank(self, reason: str, delta_seconds: Any) -> tuple[int, float]:
        reason_rank = 0 if reason == "incident_id" else 1
        if delta_seconds is None:
            return (reason_rank, float("inf"))
        try:
            delta = float(delta_seconds)
        except (TypeError, ValueError):
            delta = float("inf")
        return (reason_rank, delta)

    def _replay_seconds_candidates(self, replay: dict) -> list[float]:
        values = [
            replay.get("replay_at"),
            replay.get("saved_at"),
            replay.get("modified_at"),
        ]
        metadata = replay.get("metadata") if isinstance(replay.get("metadata"), dict) else {}
        values.extend([metadata.get("save_id"), metadata.get("saved_at")])
        seconds: list[float] = []
        seen: set[float] = set()
        for value in values:
            replay_at = replay_time_from_value(value) or isoish(value)
            parsed_seconds = timestamp_seconds(replay_at)
            if parsed_seconds is None or parsed_seconds in seen:
                continue
            seen.add(parsed_seconds)
            seconds.append(parsed_seconds)
        return seconds

    def _min_delta_seconds(self, incident: dict, replay: dict) -> float | None:
        incident_seconds = timestamp_seconds(incident_row_time(incident))
        if incident_seconds is None:
            return None
        candidates = self._replay_seconds_candidates(replay)
        if not candidates:
            return None
        return min(abs(incident_seconds - replay_seconds) for replay_seconds in candidates)

    def _incident_match_summary(self, incident: dict, reason: str, delta_seconds: float | None) -> dict:
        return {
            "incident_id": incident.get("incident_id", ""),
            "at": incident_row_time(incident),
            "rule_id": incident.get("rule_id") or incident.get("event_type") or "",
            "status": incident.get("status", ""),
            "severity": incident.get("severity", ""),
            "summary": incident.get("summary", ""),
            "source_ref": incident.get("source_ref", ""),
            "match_reason": reason,
            "delta_seconds": round(delta_seconds, 1) if delta_seconds is not None else None,
        }

    def _replay_match_summary(self, replay: dict, reason: str, delta_seconds: float | None) -> dict:
        return {
            "replay_key": replay.get("replay_key") or replay_key(replay),
            "container": replay.get("container", ""),
            "path": replay.get("path", ""),
            "zip_path": replay.get("zip_path", ""),
            "member": replay.get("member", ""),
            "name": replay.get("name", ""),
            "kind": replay.get("kind", ""),
            "replay_at": replay.get("replay_at", ""),
            "saved_at": replay.get("saved_at", ""),
            "converted": bool(replay.get("converted")),
            "has_converted": bool(replay.get("has_converted")),
            "match_reason": reason,
            "delta_seconds": round(delta_seconds, 1) if delta_seconds is not None else None,
        }

    def to_summary(self) -> dict:
        students = [self._student_summary(student) for student in self.students.values()]
        students.sort(key=lambda item: (str(item.get("login_id") or "zzzz"), str(item.get("client_id") or "")))
        return {
            "data_root": str(self.data_root),
            "generated_at": self.generated_at,
            "students": students,
            "counts": {
                "students": len(students),
                "incidents": sum(item["incident_count"] for item in students),
                "retro_blacklist_matches": sum(item["retro_blacklist_match_count"] for item in students),
                "title_history_entries": sum(item["title_history_count"] for item in students),
                "replays": sum(item["replay_count"] for item in students),
                "submissions": sum(item["submission_count"] for item in students),
            },
            "blacklist": self.blacklist,
            "settings": {
                "process_definitions_count": len(self.process_definitions),
                "incident_rules_count": len(self.incident_rules),
                "focused_window": (self.exam_policy.get("rules") or {}).get("focused_window", {}),
            },
            "ffmpeg": {
                "available": bool(ffmpeg_path()),
                "path": ffmpeg_path() or "",
                "command_template": (
                    "ffmpeg -i input.mov -c:v libx264 -pix_fmt yuv420p -profile:v baseline "
                    "-level 3.0 -c:a aac -ac 2 -b:a 128k -movflags +faststart output.mp4"
                ),
            },
            "errors": self.errors[:80],
        }

    def student_detail(self, student_id: str) -> dict | None:
        student = self.students.get(student_id)
        if not student:
            for item in self.students.values():
                if student_id in {item.get("client_id"), item.get("login_id")}:
                    student = item
                    break
        if not student:
            return None
        user = student.get("user", {}) or {}
        return {
            "student": self._student_summary(student),
            "user": {
                "computer_name": user.get("computer_name", ""),
                "session_state": user.get("session_state", ""),
                "submitted_at": user.get("submitted_at", ""),
                "submission_name": user.get("submission_name", ""),
            },
            "incidents": [without_keys(row, {"pid"}) for row in student.get("incidents", [])],
            "title_history": [without_keys(row, {"source", "pid"}) for row in student.get("title_history", [])],
            "processes": [without_keys(row, {"sources", "pids"}) for row in student.get("processes", [])],
            "recent_process_events": [],
            "retro_blacklist_matches": [without_keys(row, {"source", "pid"}) for row in student.get("retro_blacklist_matches", [])],
            "replays": student.get("replays", []),
            "submissions": student.get("submissions", []),
            "blacklist": self.blacklist,
        }

    def _student_summary(self, student: dict) -> dict:
        incidents = student.get("incidents", [])
        statuses: dict[str, int] = {}
        rules: dict[str, int] = {}
        latest = ""
        for incident in incidents:
            status = str(incident.get("status") or "unknown")
            rule = str(incident.get("rule_id") or incident.get("event_type") or "unknown")
            statuses[status] = statuses.get(status, 0) + 1
            rules[rule] = rules.get(rule, 0) + 1
            timestamp = str(incident.get("at") or incident_time(incident))
            if timestamp > latest:
                latest = timestamp
        user = student.get("user") or {}
        return {
            "id": student.get("id"),
            "client_id": student.get("client_id"),
            "login_id": student.get("login_id"),
            "computer_name": user.get("computer_name", ""),
            "session_state": user.get("session_state", ""),
            "submitted_at": user.get("submitted_at", ""),
            "latest_incident_at": latest,
            "incident_count": len(incidents),
            "incident_status_counts": statuses,
            "incident_rule_counts": rules,
            "known_blacklist_incident_count": student.get("known_blacklist_incident_count", 0),
            "retro_blacklist_match_count": len(student.get("retro_blacklist_matches", [])),
            "title_history_count": len(student.get("title_history", [])),
            "title_policy_hit_count": student.get("title_policy_hit_count", 0),
            "process_count": len(student.get("processes", [])),
            "replay_count": len(student.get("replays", [])),
            "submission_count": len(student.get("submissions", [])),
        }

    def _file_size(self, path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def _mtime(self, path: Path) -> str:
        try:
            return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime))
        except OSError:
            return ""


def ffmpeg_path() -> str | None:
    return os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    configured = os.environ.get("FFPROBE_PATH")
    if configured:
        return configured
    ffmpeg = ffmpeg_path()
    if ffmpeg:
        candidate = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
        if candidate.exists():
            return str(candidate)
    return shutil.which("ffprobe")


def conversion_sidecar_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".conversion.json")


def read_conversion_metadata(output_path: Path) -> dict:
    return json_load_file(conversion_sidecar_path(output_path), {}) or {}


def write_conversion_metadata(
    *,
    data_root: Path,
    input_path: Path,
    output_path: Path,
    command: list[str],
    returncode: int,
    duration_seconds: float,
):
    metadata = {
        "converted": returncode == 0,
        "converted_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "original_path": rel_to_root(input_path, data_root),
        "converted_path": rel_to_root(output_path, data_root),
        "command": " ".join(command),
        "returncode": returncode,
        "duration_seconds": round(duration_seconds, 2),
    }
    try:
        conversion_sidecar_path(output_path).write_text(
            json.dumps(metadata, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
        return True
    except OSError:
        return False


def compatible_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_compatible.mp4")


def guessed_original_path(data_root: Path, converted_path: Path) -> str:
    if not converted_path.name.lower().endswith("_compatible.mp4"):
        return ""
    stem = converted_path.stem[:-len("_compatible")]
    for suffix in (".ts", ".mov", ".mp4", ".m4v", ".mkv", ".webm", ".avi"):
        candidate = converted_path.with_name(f"{stem}{suffix}")
        if candidate.exists():
            return rel_to_root(candidate, data_root)
    return ""


def video_duration_seconds(input_path: Path) -> float:
    ffprobe = ffprobe_path()
    if not ffprobe:
        return 0.0
    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(input_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode != 0:
            return 0.0
        return max(0.0, float(completed.stdout.strip() or 0))
    except Exception:
        return 0.0


class AppState:
    def __init__(self, data_root: Path, cache_seconds: float = 60.0, convert_timeout: int = 1800):
        self.data_root = data_root.resolve()
        self.cache_seconds = cache_seconds
        self.convert_timeout = convert_timeout
        self._index: ServerDataIndex | None = None
        self._index_at = 0.0
        self._conversion_jobs: dict[str, dict] = {}
        self._conversion_lock = threading.Lock()

    def index(self, *, force: bool = False) -> ServerDataIndex:
        if force or self._index is None or time.time() - self._index_at > self.cache_seconds:
            index = ServerDataIndex(self.data_root)
            index.build()
            self._index = index
            self._index_at = time.time()
        return self._index

    def resolve_rel(self, rel: str) -> Path:
        clean = unquote(str(rel or "")).replace("\\", "/").lstrip("/")
        if not clean or Path(clean).is_absolute() or ".." in Path(clean).parts:
            raise ValueError("Invalid relative path.")
        target = (self.data_root / clean).resolve()
        root = self.data_root.resolve()
        if target != root and root not in target.parents:
            raise ValueError("Path is outside data root.")
        return target

    def start_conversion(self, rel: str) -> dict:
        input_path = self.resolve_rel(rel)
        if not input_path.is_file() or input_path.suffix.lower() not in VIDEO_SUFFIXES:
            raise ValueError("Select a replay/video file under data/server.")
        if input_path.name.lower().endswith("_compatible.mp4") or read_conversion_metadata(input_path).get("converted"):
            raise ValueError("Selected replay is already a converted MP4.")
        ffmpeg = ffmpeg_path()
        if not ffmpeg:
            raise RuntimeError("ffmpeg was not found on PATH. Install ffmpeg or set FFMPEG_PATH.")
        output_path = compatible_output_path(input_path)
        rel_input = rel_to_root(input_path, self.data_root)
        rel_output = rel_to_root(output_path, self.data_root)
        if output_path.exists():
            metadata = read_conversion_metadata(output_path)
            if not metadata:
                write_conversion_metadata(
                    data_root=self.data_root,
                    input_path=input_path,
                    output_path=output_path,
                    command=[],
                    returncode=0,
                    duration_seconds=0.0,
                )
            return {
                "id": "",
                "status": "done",
                "percent": 100,
                "input_path": rel_input,
                "output_path": rel_output,
                "media_url": f"/api/media?path={quote(rel_output)}",
                "download_url": f"/api/download?path={quote(rel_output)}",
                "message": "Already converted.",
            }

        job_id = uuid.uuid4().hex
        job = {
            "id": job_id,
            "status": "queued",
            "percent": 0,
            "input_path": rel_input,
            "output_path": rel_output,
            "media_url": f"/api/media?path={quote(rel_output)}",
            "download_url": f"/api/download?path={quote(rel_output)}",
            "message": "Queued.",
            "returncode": None,
            "seconds": 0.0,
            "stderr_tail": "",
        }
        with self._conversion_lock:
            self._conversion_jobs[job_id] = job
        thread = threading.Thread(
            target=self._run_conversion_job,
            args=(job_id, input_path, output_path, ffmpeg),
            daemon=True,
        )
        thread.start()
        return self.conversion_status(job_id)

    def conversion_status(self, job_id: str) -> dict | None:
        with self._conversion_lock:
            job = self._conversion_jobs.get(str(job_id or ""))
            return dict(job) if job else None

    def _update_conversion_job(self, job_id: str, **updates):
        with self._conversion_lock:
            if job_id in self._conversion_jobs:
                self._conversion_jobs[job_id].update(updates)

    def _run_conversion_job(self, job_id: str, input_path: Path, output_path: Path, ffmpeg: str):
        duration = video_duration_seconds(input_path)
        command = [
            ffmpeg,
            "-nostdin",
            "-y",
            "-i",
            str(input_path),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "baseline",
            "-level",
            "3.0",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_path),
        ]
        started = time.time()
        tail: list[str] = []
        self._update_conversion_job(job_id, status="running", message="Converting.", duration_seconds=duration)
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                if "=" in line:
                    key, value = line.split("=", 1)
                    if key in {"out_time_ms", "out_time_us"} and duration > 0:
                        try:
                            elapsed = float(value) / 1_000_000.0
                            percent = max(0, min(99, int((elapsed / duration) * 100)))
                            self._update_conversion_job(job_id, percent=percent, message=f"Converting {percent}%")
                        except ValueError:
                            pass
                    elif key == "progress" and value == "end":
                        self._update_conversion_job(job_id, percent=99, message="Finalizing.")
                    continue
                tail.append(line)
                tail = tail[-40:]
                self._update_conversion_job(job_id, stderr_tail="\n".join(tail))
            returncode = process.wait(timeout=self.convert_timeout)
        except Exception as exc:
            self._update_conversion_job(
                job_id,
                status="error",
                message=str(exc),
                percent=0,
                seconds=round(time.time() - started, 2),
            )
            return

        seconds = round(time.time() - started, 2)
        if returncode == 0:
            write_conversion_metadata(
                data_root=self.data_root,
                input_path=input_path,
                output_path=output_path,
                command=command,
                returncode=returncode,
                duration_seconds=seconds,
            )
            self._update_conversion_job(
                job_id,
                status="done",
                percent=100,
                message="Conversion complete.",
                returncode=returncode,
                seconds=seconds,
                stderr_tail="\n".join(tail),
            )
        else:
            self._update_conversion_job(
                job_id,
                status="error",
                percent=0,
                message="ffmpeg conversion failed.",
                returncode=returncode,
                seconds=seconds,
                stderr_tail="\n".join(tail),
            )


class ServerDataHandler(BaseHTTPRequestHandler):
    server_version = "ServerDataWebUI/1.0"

    @property
    def app(self) -> AppState:
        return self.server.app_state  # type: ignore[attr-defined]

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                self._serve_html()
            elif parsed.path.startswith("/web/"):
                self._serve_web_file(parsed.path)
            elif parsed.path == "/api/summary":
                refresh = params.get("refresh", ["0"])[0] == "1"
                self._json(self.app.index(force=refresh).to_summary())
            elif parsed.path == "/api/student":
                student_id = params.get("id", [""])[0]
                detail = self.app.index().student_detail(student_id)
                if detail is None:
                    self._json({"error": "student not found"}, status=404)
                else:
                    self._json(detail)
            elif parsed.path == "/api/source-json":
                self._serve_source_json(
                    params.get("ref", [""])[0],
                    download=params.get("download", ["0"])[0] == "1",
                )
            elif parsed.path == "/api/convert-status":
                job = self.app.conversion_status(params.get("id", [""])[0])
                if job is None:
                    self._json({"error": "conversion job not found"}, status=404)
                else:
                    self._json(job)
            elif parsed.path == "/api/export":
                student_id = params.get("id", [""])[0]
                self._serve_student_export(student_id)
            elif parsed.path == "/api/media":
                self._serve_file(params.get("path", [""])[0], attachment=False)
            elif parsed.path == "/api/download":
                self._serve_file(params.get("path", [""])[0], attachment=True)
            elif parsed.path == "/api/zip-media":
                self._serve_zip_member(
                    params.get("zip", [""])[0],
                    params.get("member", [""])[0],
                    attachment=params.get("download", ["0"])[0] == "1",
                )
            else:
                self._json({"error": "not found"}, status=404)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=400)
        except OSError as exc:
            if is_client_disconnect(exc):
                return
            self._json({"error": str(exc)}, status=500)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/convert":
                payload = self._read_json_body()
                self._json(self.app.start_conversion(str(payload.get("path") or "")))
            else:
                self._json({"error": "not found"}, status=404)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=400)
        except RuntimeError as exc:
            self._json({"error": str(exc)}, status=503)
        except subprocess.TimeoutExpired:
            self._json({"error": "ffmpeg conversion timed out"}, status=504)
        except OSError as exc:
            if is_client_disconnect(exc):
                return
            self._json({"error": str(exc)}, status=500)
        except Exception as exc:
            self._json({"error": str(exc)}, status=500)

    def log_message(self, fmt: str, *args):
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), fmt % args))

    def _serve_html(self):
        html_path = self._web_root() / "index.html"
        body = html_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def _serve_web_file(self, request_path: str):
        web_root = self._web_root()
        rel = unquote(request_path.removeprefix("/web/")).replace("\\", "/").lstrip("/")
        if not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise ValueError("Invalid static path.")
        target = (web_root / rel).resolve()
        if target != web_root and web_root not in target.parents:
            raise ValueError("Static path is outside web root.")
        if not target.is_file():
            self._json({"error": "static file not found"}, status=404)
            return
        body = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def _web_root(self) -> Path:
        return Path(__file__).resolve().parent / "web"

    def _json(self, payload: Any, *, status: int = 200):
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
        except OSError as exc:
            if is_client_disconnect(exc):
                return
            raise
        self._safe_write(body)

    def _safe_write(self, body: bytes) -> bool:
        try:
            self.wfile.write(body)
            return True
        except OSError as exc:
            if is_client_disconnect(exc):
                return False
            raise

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body.") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _serve_file(self, rel: str, *, attachment: bool):
        path = self.app.resolve_rel(rel)
        if not path.is_file():
            raise ValueError("File not found.")
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        size = path.stat().st_size
        range_header = self.headers.get("Range") if not attachment else ""
        start = 0
        end = size - 1
        status = 200
        if range_header:
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                if match.group(1):
                    start = int(match.group(1))
                if match.group(2):
                    end = min(size - 1, int(match.group(2)))
                if start > end or start >= size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                status = 206
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        if attachment:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(path.name)}")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        length = end - start + 1
        self.send_header("Content-Length", str(length))
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                if not self._safe_write(chunk):
                    return
                remaining -= len(chunk)

    def _serve_zip_member(self, zip_rel: str, member: str, *, attachment: bool):
        zip_path = self.app.resolve_rel(zip_rel)
        if zip_path.suffix.lower() != ".zip" or not zip_path.is_file():
            raise ValueError("ZIP file not found.")
        member = unquote(str(member or "")).replace("\\", "/").lstrip("/")
        if not member or ".." in Path(member).parts:
            raise ValueError("Invalid ZIP member.")
        suffix = Path(member).suffix.lower()
        if suffix not in VIDEO_SUFFIXES:
            raise ValueError("Only replay/video members can be opened.")
        with zipfile.ZipFile(zip_path) as archive:
            try:
                info = archive.getinfo(member)
            except KeyError as exc:
                raise ValueError("ZIP member not found.") from exc
            with archive.open(info) as raw:
                body = raw.read()
        ctype = mimetypes.guess_type(member)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if attachment:
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(Path(member).name)}")
        self.end_headers()
        self._safe_write(body)

    def _serve_source_json(self, ref: str, *, download: bool):
        source = self.app.index().source_json(ref)
        if source is None:
            self._json({"error": "source JSON not found"}, status=404)
            return
        payload = source.get("payload")
        body_payload = payload if download else {
            "ref": ref,
            "kind": source.get("kind", ""),
            "label": source.get("label", ""),
            "student": {
                "login_id": source.get("login_id", ""),
                "client_id": source.get("client_id", ""),
            },
            "payload": payload,
        }
        body = json.dumps(body_payload, indent=2, ensure_ascii=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if download:
            filename = str(source.get("filename") or f"{ref}.json")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def _serve_student_export(self, student_id: str):
        index = self.app.index()
        detail = index.student_detail(student_id)
        if detail is None:
            self._json({"error": "student not found"}, status=404)
            return
        student = detail["student"]
        label = str(student.get("login_id") or student.get("client_id") or "student")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("student_summary.json", json.dumps(detail, indent=2, ensure_ascii=True))
            archive.writestr("incidents.jsonl", "\n".join(json.dumps(item, ensure_ascii=True) for item in detail["incidents"]))
            self._write_csv(archive, "incidents.csv", detail["incidents"])
            self._write_csv(archive, "titlebar_history.csv", detail["title_history"])
            self._write_csv(archive, "processes.csv", detail["processes"])
            self._write_csv(archive, "recent_process_events.csv", detail["recent_process_events"])
            self._write_csv(archive, "retro_blacklist_matches.csv", detail["retro_blacklist_matches"])
            self._write_csv(archive, "replays.csv", detail["replays"])
            self._write_csv(archive, "submissions.csv", detail["submissions"])
            for name in ("process_blacklist.txt", "exam_policy.json", "process_definitions.json", "incident_rules.json"):
                path = self.app.data_root / name
                if path.is_file():
                    archive.write(path, f"settings/{name}")
        body = buffer.getvalue()
        filename = f"{label}_server_data_export_{now_stamp()}.zip"
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._safe_write(body)

    def _write_csv(self, archive: zipfile.ZipFile, name: str, rows: list[dict]):
        output = io.StringIO()
        flattened = [flatten_dict(row) for row in rows]
        columns: list[str] = []
        for row in flattened:
            for key in row:
                if key not in columns:
                    columns.append(key)
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flattened)
        archive.writestr(name, output.getvalue())


def flatten_dict(value: dict, prefix: str = "") -> dict:
    result: dict[str, Any] = {}
    for key, item in value.items():
        flat_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            result.update(flatten_dict(item, flat_key))
        elif isinstance(item, list):
            result[flat_key] = json.dumps(item, ensure_ascii=True)
        else:
            result[flat_key] = item
    return result


def without_keys(value: dict, keys: set[str]) -> dict:
    return {key: item for key, item in value.items() if key not in keys}


def make_server(host: str, port: int, state: AppState) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), ServerDataHandler)
    server.app_state = state  # type: ignore[attr-defined]
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve a simple web UI for data/server runtime files.")
    parser.add_argument("--data-root", default=str(default_data_root()), help="Path to a data/server folder.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cache-seconds", type=float, default=60.0)
    parser.add_argument("--convert-timeout", type=int, default=1800)
    args = parser.parse_args(argv)

    data_root = resolve_data_root(args.data_root)
    if not data_root.exists():
        print(f"[server-data-webui] data root does not exist: {data_root}", file=sys.stderr)
        return 2
    state = AppState(data_root, cache_seconds=args.cache_seconds, convert_timeout=args.convert_timeout)
    server = make_server(args.host, args.port, state)
    url = f"http://{args.host}:{args.port}/"
    print(f"[server-data-webui] data root: {data_root}")
    print(f"[server-data-webui] url: {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server-data-webui] stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
