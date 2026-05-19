#!/usr/bin/env python3
"""Analyze the Software dump folder without extracting archives.

Default use:
    cd Software
    python tools\\analyze_software_dump.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import zipfile
import zlib
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


REPLAY_SUFFIXES = {".ts", ".mp4", ".mkv", ".webm"}
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

SAFE_PROCESS_PATTERNS = (
    "adobearm.exe",
    "adobecollabsync.exe",
    "adnotificationmanager.exe",
    "backgrounddownload.exe",
    "chrome.exe",
    "cloudflare warp.exe",
    "cowork-svc.exe",
    "crossdeviceservice.exe",
    "elevation_service.exe",
    "filecoauth.exe",
    "fulltrustnotifier.exe",
    "gamebar.exe",
    "gamebarftserver.exe",
    "gup.exe",
    "identity_helper.exe",
    "m365copilot.exe",
    "microsoft.media.player.exe",
    "microsoftedgeupdate.exe",
    "msedge.exe",
    "onedrivestandaloneupdater.exe",
    "storedesktopextension.exe",
    "updater.exe",
    "widgets.exe",
    "windowspackagemanagerserver.exe",
    "xboxgamebarwidgets.exe",
    "xboxpcappft.exe",
)
SUSPICIOUS_PROCESS_PATTERNS = (
    "anydesk",
    "obs",
    "snippingtool",
    "solitaire",
    "teams.exe",
    "vbox",
    "virtualbox",
)
APP_RUNTIME_PROCESS_PATTERNS = (
    "ffmpeg.exe",
    "python.exe",
    "py.exe",
    "openconsole.exe",
)
OBS_EXACT_PROCESS_NAMES = {
    "obs32.exe",
    "obs64.exe",
    "obs-qsv-test.exe",
    "get-graphics-offsets64.exe",
}


@dataclass
class ArchiveParity:
    zip_path: str
    extracted_folder: str
    checked_files: int = 0
    missing: int = 0
    size_mismatch: int = 0
    crc_mismatch: int = 0
    extra_files: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ArchiveFileCheck:
    zip_path: str
    zip_member: str
    extracted_path: str
    status: str
    zip_size: int = 0
    file_size: int = 0
    zip_crc: str = ""
    file_crc: str = ""
    error: str = ""


@dataclass
class LogHit:
    path: str
    line: int
    category: str
    student_hint: str
    session_hint: str
    excerpt: str


@dataclass
class ReplayIssue:
    side: str
    path: str
    incident_id: str
    save_id: str
    issue: str
    detail: str = ""


@dataclass
class ObsClient:
    client_id: str
    login_id: str
    session_path: str
    sources: list[str] = field(default_factory=list)
    process_names: list[str] = field(default_factory=list)


def safe_rel(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except OSError:
        return str(path)
    except ValueError:
        return str(path)


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_process_name(value: Any) -> str:
    text = clean_text(value).replace("\\", "/")
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    return text.lower()


def is_obs_process(value: Any) -> bool:
    name = normalize_process_name(value)
    if not name:
        return False
    if name in OBS_EXACT_PROCESS_NAMES:
        return True
    if name.startswith("obs-studio") and name.endswith(".exe"):
        return True
    if name.startswith("obs-") and name.endswith(".exe"):
        return True
    return False


def read_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def read_zip_json(archive: zipfile.ZipFile, name: str) -> Any:
    try:
        with archive.open(name) as handle:
            return json.loads(handle.read().decode("utf-8", errors="replace"))
    except Exception:
        return None


def iter_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, raw in enumerate(handle, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield line_no, json.loads(raw), raw
            except json.JSONDecodeError:
                yield line_no, None, raw


def path_hint(path: Path) -> tuple[str, str]:
    student_hint = ""
    session_hint = ""
    for part in path.parts:
        if UUID_RE.match(part):
            session_hint = part
        match = re.match(r"^(\d{7,12})_data$", part)
        if match:
            student_hint = match.group(1)
    return student_hint, session_hint


def categorize_log_line(line: str) -> str:
    lower = line.lower()
    if "broken pipe" in lower:
        return "broken_pipe"
    if "500 internal server error" in lower or re.search(r"\b(status|http)[=:\s]+500\b|\(500\)", lower):
        return "http_500"
    if "traceback" in lower:
        return "traceback"
    if "timeoutexpired" in lower or "timed out after" in lower:
        return "subprocess_timeout"
    if "replay save timed out" in lower:
        return "replay_timeout"
    if "ffmpeg" in lower and any(term in lower for term in ("died", "cannot", "failed", "error", "invalid")):
        return "ffmpeg_failure"
    if "upload failed" in lower or "evidence upload failed" in lower:
        return "upload_failed"
    if "winerror" in lower:
        return "winerror"
    if "exception" in lower:
        return "exception"
    if "[fatal]" in lower or "failed" in lower:
        return "failure"
    if "crash" in lower:
        return "crash"
    return ""


def analyze_logs(root: Path) -> tuple[list[LogHit], dict[str, int], list[dict[str, Any]]]:
    hits: list[LogHit] = []
    counts: Counter[str] = Counter()
    crash_markers: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.log")):
        rel = safe_rel(path, root)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if "gui_crash" in path.name.lower():
            marker = {
                "path": rel,
                "size_bytes": size,
                "empty": size == 0,
            }
            crash_markers.append(marker)
            if size == 0:
                student, session = path_hint(path)
                hits.append(LogHit(rel, 0, "gui_crash_marker_empty", student, session, "empty GUI crash marker"))
                counts["gui_crash_marker_empty"] += 1
                continue
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_no, line in enumerate(handle, 1):
                    category = categorize_log_line(line)
                    if not category:
                        continue
                    student, session = path_hint(path)
                    excerpt = line.strip()
                    hits.append(LogHit(rel, line_no, category, student, session, excerpt[:600]))
                    counts[category] += 1
        except OSError as exc:
            student, session = path_hint(path)
            hits.append(LogHit(rel, 0, "log_read_error", student, session, str(exc)))
            counts["log_read_error"] += 1
    return hits, dict(counts), crash_markers


def top_level_archives(root: Path) -> list[Path]:
    archives: list[Path] = []
    server_zip = root / "server_data.zip"
    if server_zip.is_file():
        archives.append(server_zip)
    demo = root / "DEMO DATA FILES"
    if demo.is_dir():
        archives.extend(sorted(demo.glob("*_data.zip")))
    return archives


def zip_common_prefix(infos: list[zipfile.ZipInfo]) -> str:
    first_parts = set()
    for info in infos:
        name = info.filename.replace("\\", "/").strip("/")
        if "/" in name:
            first_parts.add(name.split("/", 1)[0])
    return next(iter(first_parts)) if len(first_parts) == 1 else ""


def extracted_target(extracted: Path, info: zipfile.ZipInfo, common_prefix: str) -> Path:
    normalized_name = info.filename.replace("\\", "/").strip("/")
    candidates = [normalized_name]
    if common_prefix and normalized_name.startswith(common_prefix + "/"):
        candidates.append(normalized_name[len(common_prefix) + 1 :])
    if normalized_name.startswith(extracted.name + "/"):
        candidates.append(normalized_name[len(extracted.name) + 1 :])
    for rel in candidates:
        if not rel:
            continue
        candidate = extracted / Path(*rel.split("/"))
        if candidate.exists():
            return candidate
    rel = candidates[-1] if candidates else normalized_name
    return extracted / Path(*rel.split("/"))


def file_crc32(path: Path, chunk_size: int = 4 * 1024 * 1024) -> int:
    crc = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
    return crc & 0xFFFFFFFF


def verify_archive_pair(root: Path, zip_path: Path, *, full_crc: bool) -> tuple[ArchiveParity, list[ArchiveFileCheck]]:
    extracted = zip_path.with_suffix("")
    result = ArchiveParity(safe_rel(zip_path, root), safe_rel(extracted, root))
    file_checks: list[ArchiveFileCheck] = []
    if not extracted.is_dir():
        result.errors.append("extracted folder missing")
        return result, file_checks
    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            common_prefix = zip_common_prefix(infos)
            expected_targets: set[Path] = set()
            for info in infos:
                target = extracted_target(extracted, info, common_prefix)
                file_check = ArchiveFileCheck(
                    zip_path=safe_rel(zip_path, root),
                    zip_member=info.filename,
                    extracted_path=safe_rel(target, root),
                    status="ok",
                    zip_size=int(info.file_size),
                    zip_crc=f"{int(info.CRC):08x}",
                )
                expected_targets.add(target.resolve() if target.exists() else target)
                if not target.is_file():
                    file_check.status = "missing"
                    result.missing += 1
                    file_checks.append(file_check)
                    continue
                try:
                    size = target.stat().st_size
                except OSError as exc:
                    message = f"{safe_rel(target, root)}: stat failed: {exc}"
                    result.errors.append(message)
                    file_check.status = "error"
                    file_check.error = str(exc)
                    file_checks.append(file_check)
                    continue
                file_check.file_size = int(size)
                if size != info.file_size:
                    file_check.status = "size_mismatch"
                    result.size_mismatch += 1
                    file_checks.append(file_check)
                    continue
                if full_crc:
                    try:
                        actual_crc = file_crc32(target)
                        file_check.file_crc = f"{int(actual_crc):08x}"
                        if actual_crc != info.CRC:
                            file_check.status = "crc_mismatch"
                            result.crc_mismatch += 1
                            file_checks.append(file_check)
                            continue
                    except OSError as exc:
                        message = f"{safe_rel(target, root)}: crc failed: {exc}"
                        result.errors.append(message)
                        file_check.status = "error"
                        file_check.error = str(exc)
                        file_checks.append(file_check)
                        continue
                result.checked_files += 1
                file_checks.append(file_check)
            try:
                actual_files = {p.resolve() for p in extracted.rglob("*") if p.is_file()}
                result.extra_files = len(actual_files - expected_targets)
            except OSError:
                pass
    except zipfile.BadZipFile as exc:
        result.errors.append(f"bad zip file: {exc}")
    except OSError as exc:
        result.errors.append(f"could not read zip: {exc}")
    return result, file_checks


def verify_archives(root: Path, *, full_crc: bool) -> tuple[list[ArchiveParity], list[ArchiveFileCheck]]:
    parity: list[ArchiveParity] = []
    file_checks: list[ArchiveFileCheck] = []
    for archive in top_level_archives(root):
        archive_parity, archive_file_checks = verify_archive_pair(root, archive, full_crc=full_crc)
        parity.append(archive_parity)
        file_checks.extend(archive_file_checks)
    return parity, file_checks


def find_server_root(root: Path) -> Path | None:
    candidates = [
        root / "server_data" / "data" / "server",
        root / "data" / "server",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    for candidate in root.rglob("server"):
        if candidate.is_dir() and (candidate / "incidents.jsonl").is_file():
            return candidate
    return None


def client_root_has_sessions(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(item.is_dir() and UUID_RE.match(item.name) for item in path.iterdir())


def find_client_roots(root: Path) -> list[Path]:
    roots: list[Path] = []
    for candidate in root.rglob("client"):
        if client_root_has_sessions(candidate):
            roots.append(candidate)
    seen = set()
    result = []
    for path in roots:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return sorted(result, key=lambda item: str(item).lower())


def resolve_server_reference(reference: str, server_root: Path | None) -> Path | None:
    if not reference or server_root is None:
        return None
    ref = reference.replace("\\", "/").lstrip("/")
    candidates = [
        Path(reference),
        server_root / ref,
        server_root.parent / ref,
    ]
    if ref.startswith("data/server/"):
        candidates.append(server_root / ref[len("data/server/") :])
    if ref.startswith("server/"):
        candidates.append(server_root / ref[len("server/") :])
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def manifest_entries(manifest: Any) -> list[dict[str, Any]]:
    if isinstance(manifest, dict) and isinstance(manifest.get("entries"), list):
        return [entry for entry in manifest["entries"] if isinstance(entry, dict)]
    if isinstance(manifest, list):
        return [entry for entry in manifest if isinstance(entry, dict)]
    return []


def replay_manifest_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for entry in entries:
        role = clean_text(entry.get("role")).lower()
        archive_path = clean_text(entry.get("archive_path") or entry.get("path"))
        if "replay" in role or "replay" in archive_path.lower() or Path(archive_path).suffix.lower() in REPLAY_SUFFIXES:
            results.append(entry)
    return results


def save_id_from_replay_name(path: Path | str) -> str:
    stem = Path(path).stem
    return stem[len("replay_") :] if stem.startswith("replay_") else stem


def validate_zip_bundle(
    zip_path: Path,
    root: Path,
    *,
    side: str,
    local_replay_save_ids: set[str] | None = None,
    server_root: Path | None = None,
) -> tuple[dict[str, Any], list[ReplayIssue], dict[str, Any] | None]:
    issues: list[ReplayIssue] = []
    result: dict[str, Any] = {
        "path": safe_rel(zip_path, root),
        "side": side,
        "size_bytes": 0,
        "incident_id": "",
        "rule_id": "",
        "status": "",
        "replay_save_id": "",
        "replay_artifact_path": "",
        "embedded_replays": [],
        "manifest_replay_entries": [],
        "issues": [],
    }
    incident: dict[str, Any] | None = None
    try:
        result["size_bytes"] = zip_path.stat().st_size
        if result["size_bytes"] <= 0:
            result["issues"].append("zero-byte zip")
        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
            result["embedded_replays"] = sorted(
                name for name in names if Path(name).suffix.lower() in REPLAY_SUFFIXES and "replay" in name.lower()
            )
            incident_obj = read_zip_json(archive, "incident.json")
            manifest_obj = read_zip_json(archive, "manifest.json")
            if isinstance(incident_obj, dict):
                incident = incident_obj
                result["incident_id"] = clean_text(incident_obj.get("incident_id"))
                result["rule_id"] = clean_text(incident_obj.get("rule_id"))
                result["status"] = clean_text(incident_obj.get("status"))
                result["replay_save_id"] = clean_text(incident_obj.get("replay_save_id"))
                result["replay_artifact_path"] = clean_text(incident_obj.get("replay_artifact_path"))
            entries = manifest_entries(manifest_obj)
            replay_entries = replay_manifest_entries(entries)
            result["manifest_replay_entries"] = replay_entries
            for entry in replay_entries:
                archive_path = clean_text(entry.get("archive_path") or entry.get("path"))
                if archive_path and archive_path not in names:
                    result["issues"].append(f"manifest replay entry missing from zip: {archive_path}")
            if not result["embedded_replays"] and not replay_entries and not result["replay_artifact_path"]:
                result["issues"].append("no replay evidence")
    except zipfile.BadZipFile as exc:
        result["issues"].append(f"bad zip file: {exc}")
    except OSError as exc:
        result["issues"].append(f"could not read zip: {exc}")

    save_id = clean_text(result["replay_save_id"])
    if local_replay_save_ids is not None and save_id and save_id not in local_replay_save_ids:
        result["issues"].append(f"missing local replay for save id: {save_id}")
    ref = clean_text(result["replay_artifact_path"])
    if ref:
        resolved = resolve_server_reference(ref, server_root)
        if not resolved or resolved.stat().st_size <= 0:
            result["issues"].append(f"missing server replay reference: {ref}")
    for issue in result["issues"]:
        issues.append(
            ReplayIssue(
                side=side,
                path=result["path"],
                incident_id=clean_text(result["incident_id"]),
                save_id=save_id,
                issue=issue,
            )
        )
    return result, issues, incident


def add_unknown_process(counter: dict[str, dict[str, Any]], incident: dict[str, Any]) -> None:
    name = clean_text(incident.get("process_name")).lower()
    if not name:
        return
    entry = counter.setdefault(
        name,
        {
            "process_name": name,
            "count": 0,
            "paths": Counter(),
            "dirs": Counter(),
            "students": Counter(),
            "statuses": Counter(),
            "first_seen": "",
            "last_seen": "",
        },
    )
    entry["count"] += 1
    path = clean_text(incident.get("process_path"))
    directory = clean_text(incident.get("process_dir")) or (os.path.dirname(path) if path else "")
    student = clean_text(incident.get("login_id") or incident.get("client_id"))
    status = clean_text(incident.get("status"))
    event_at = clean_text(
        incident.get("server_received_at")
        or incident.get("reported_at")
        or incident.get("event_at")
        or incident.get("timestamp")
    )
    if path:
        entry["paths"][path] += 1
    if directory:
        entry["dirs"][directory] += 1
    if student:
        entry["students"][student] += 1
    if status:
        entry["statuses"][status] += 1
    if event_at:
        if not entry["first_seen"] or event_at < entry["first_seen"]:
            entry["first_seen"] = event_at
        if not entry["last_seen"] or event_at > entry["last_seen"]:
            entry["last_seen"] = event_at


def suggested_process_action(name: str, paths: Counter[str], dirs: Counter[str]) -> str:
    lower = name.lower()
    if any(pattern in lower for pattern in SUSPICIOUS_PROCESS_PATTERNS):
        return "review_or_blacklist"
    if lower in APP_RUNTIME_PROCESS_PATTERNS:
        return "known_process_names"
    if lower in SAFE_PROCESS_PATTERNS:
        return "known_process_names"
    if paths and len(paths) <= 2:
        return "process_definition_whitelist_path"
    if dirs and len(dirs) <= 2:
        return "known_directory_paths"
    return "review"


def finalize_unknown_processes(counter: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name, entry in counter.items():
        paths: Counter[str] = entry["paths"]
        dirs: Counter[str] = entry["dirs"]
        rows.append(
            {
                "process_name": name,
                "count": entry["count"],
                "unique_paths": len(paths),
                "top_paths": "; ".join(f"{path} ({count})" for path, count in paths.most_common(5)),
                "top_dirs": "; ".join(f"{path} ({count})" for path, count in dirs.most_common(5)),
                "students": "; ".join(f"{student} ({count})" for student, count in entry["students"].most_common(8)),
                "statuses": dict(entry["statuses"].most_common()),
                "first_seen": entry["first_seen"],
                "last_seen": entry["last_seen"],
                "suggested_action": suggested_process_action(name, paths, dirs),
            }
        )
    return sorted(rows, key=lambda item: (item["count"], item["process_name"]), reverse=True)


def incident_obs_processes(incident: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("process_name", "process_path", "summary"):
        value = clean_text(incident.get(key))
        if is_obs_process(value):
            names.add(normalize_process_name(value))
    raw_processes = incident.get("raw_processes")
    if isinstance(raw_processes, list):
        for entry in raw_processes:
            if not isinstance(entry, dict):
                continue
            for key in ("process_name", "process_path"):
                value = clean_text(entry.get(key))
                if is_obs_process(value):
                    names.add(normalize_process_name(value))
    return names


def add_obs_client(
    clients: dict[str, ObsClient],
    *,
    client_id: str,
    login_id: str = "",
    session_path: str = "",
    source: str,
    process_names: set[str],
) -> None:
    if not client_id and not login_id and not session_path:
        return
    key = client_id or login_id or session_path
    entry = clients.setdefault(
        key,
        ObsClient(
            client_id=client_id,
            login_id=login_id,
            session_path=session_path,
        ),
    )
    if client_id and not entry.client_id:
        entry.client_id = client_id
    if login_id and not entry.login_id:
        entry.login_id = login_id
    if session_path and not entry.session_path:
        entry.session_path = session_path
    if source not in entry.sources:
        entry.sources.append(source)
    for name in sorted(process_names):
        if name and name not in entry.process_names:
            entry.process_names.append(name)


def detect_obs_clients(root: Path, server_root: Path | None, client_roots: list[Path]) -> dict[str, ObsClient]:
    clients: dict[str, ObsClient] = {}
    if server_root is not None:
        for _line_no, payload, _raw in iter_jsonl(server_root / "incidents.jsonl") or []:
            if not isinstance(payload, dict):
                continue
            names = incident_obs_processes(payload)
            if names:
                add_obs_client(
                    clients,
                    client_id=clean_text(payload.get("client_id")),
                    login_id=clean_text(payload.get("login_id")),
                    source="server_incidents",
                    process_names=names,
                )

    for client_root in client_roots:
        for session_dir in sorted(path for path in client_root.iterdir() if path.is_dir() and UUID_RE.match(path.name)):
            session_key = session_dir.name
            for bundle in sorted((session_dir / "incident_bundles").glob("*.zip")) if (session_dir / "incident_bundles").is_dir() else []:
                try:
                    with zipfile.ZipFile(bundle) as archive:
                        incident = read_zip_json(archive, "incident.json")
                except Exception:
                    continue
                if not isinstance(incident, dict):
                    continue
                names = incident_obs_processes(incident)
                if names:
                    add_obs_client(
                        clients,
                        client_id=clean_text(incident.get("client_id")) or session_key,
                        login_id=clean_text(incident.get("login_id")),
                        session_path=safe_rel(session_dir, root),
                        source="client_incident_bundles",
                        process_names=names,
                    )

            for report_path in sorted(session_dir.glob("process_report_requested_*.json")):
                report = read_json_file(report_path)
                if not isinstance(report, dict):
                    continue
                processes = report.get("processes")
                if not isinstance(processes, list):
                    continue
                names: set[str] = set()
                for process in processes:
                    if not isinstance(process, dict):
                        continue
                    for key in ("process_name", "name", "process_path", "path"):
                        value = clean_text(process.get(key))
                        if is_obs_process(value):
                            names.add(normalize_process_name(value))
                if names:
                    add_obs_client(
                        clients,
                        client_id=session_key,
                        session_path=safe_rel(session_dir, root),
                        source="client_process_reports",
                        process_names=names,
                    )
    return clients


def incident_matches_obs_client(incident: dict[str, Any], obs_client_keys: set[str]) -> bool:
    for key in ("client_id", "login_id"):
        value = clean_text(incident.get(key))
        if value and value in obs_client_keys:
            return True
    return False


def analyze_server(
    root: Path,
    server_root: Path | None,
    unknown_counter_all: dict[str, dict[str, Any]],
    unknown_counter_filtered: dict[str, dict[str, Any]],
    obs_client_keys: set[str],
) -> tuple[dict[str, Any], list[ReplayIssue]]:
    report: dict[str, Any] = {
        "root": safe_rel(server_root, root) if server_root else "",
        "incident_count": 0,
        "incident_status_counts": {},
        "incident_rule_counts": {},
        "replay_files": 0,
        "zero_byte_replay_files": 0,
        "incident_bundles": [],
        "submission_bundles": [],
    }
    issues: list[ReplayIssue] = []
    if server_root is None:
        return report, issues

    status_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    for _line_no, payload, _raw in iter_jsonl(server_root / "incidents.jsonl") or []:
        if not isinstance(payload, dict):
            continue
        report["incident_count"] += 1
        status_counts[clean_text(payload.get("status"))] += 1
        rule_id = clean_text(payload.get("rule_id") or payload.get("event_type"))
        rule_counts[rule_id] += 1
        if rule_id == "unexpected_process":
            add_unknown_process(unknown_counter_all, payload)
            if not incident_matches_obs_client(payload, obs_client_keys):
                add_unknown_process(unknown_counter_filtered, payload)
    report["incident_status_counts"] = dict(status_counts.most_common())
    report["incident_rule_counts"] = dict(rule_counts.most_common())

    artifacts = server_root / "artifacts"
    if artifacts.is_dir():
        for replay in sorted(path for path in artifacts.rglob("*") if path.suffix.lower() in REPLAY_SUFFIXES):
            report["replay_files"] += 1
            try:
                if replay.stat().st_size <= 0:
                    report["zero_byte_replay_files"] += 1
                    issues.append(ReplayIssue("server", safe_rel(replay, root), "", save_id_from_replay_name(replay), "zero-byte replay"))
            except OSError as exc:
                issues.append(ReplayIssue("server", safe_rel(replay, root), "", save_id_from_replay_name(replay), "replay stat failed", str(exc)))
        for bundle in sorted(artifacts.glob("*/*/*.zip")):
            if bundle.parent.name.lower() != "incident_bundle":
                continue
            bundle_report, bundle_issues, _incident = validate_zip_bundle(bundle, root, side="server", server_root=server_root)
            report["incident_bundles"].append(bundle_report)
            issues.extend(bundle_issues)

    submissions = server_root / "submissions"
    if submissions.is_dir():
        for bundle in sorted(submissions.glob("*/*.zip")):
            bundle_report, bundle_issues, _incident = validate_zip_bundle(bundle, root, side="server_submission", server_root=server_root)
            report["submission_bundles"].append(bundle_report)
            issues.extend(bundle_issues)
    return report, issues


def logs_root_for_client_root(client_root: Path) -> Path:
    if client_root.parent.name.lower() == "data":
        return client_root.parent / "logs" / "client"
    return client_root.parent / "logs" / "client"


def analyze_client_roots(
    root: Path,
    client_roots: list[Path],
    server_root: Path | None,
    unknown_counter_all: dict[str, dict[str, Any]],
    unknown_counter_filtered: dict[str, dict[str, Any]],
    obs_client_keys: set[str],
) -> tuple[list[dict[str, Any]], list[ReplayIssue]]:
    reports: list[dict[str, Any]] = []
    issues: list[ReplayIssue] = []
    for client_root in client_roots:
        root_report = {
            "root": safe_rel(client_root, root),
            "logs_root": safe_rel(logs_root_for_client_root(client_root), root),
            "sessions": [],
        }
        for session_dir in sorted(path for path in client_root.iterdir() if path.is_dir() and UUID_RE.match(path.name)):
            replay_files = sorted(
                path for path in (session_dir / "recordings" / "replays").rglob("*")
                if path.is_file() and path.suffix.lower() in REPLAY_SUFFIXES
            ) if (session_dir / "recordings" / "replays").is_dir() else []
            local_save_ids = {save_id_from_replay_name(path) for path in replay_files}
            session_report = {
                "session_uuid": session_dir.name,
                "path": safe_rel(session_dir, root),
                "replay_files": len(replay_files),
                "zero_byte_replay_files": 0,
                "incident_bundles": [],
                "submission_bundles": [],
                "process_report_count": len(list(session_dir.glob("process_report_requested_*.json"))),
            }
            for replay in replay_files:
                try:
                    if replay.stat().st_size <= 0:
                        session_report["zero_byte_replay_files"] += 1
                        issues.append(ReplayIssue("client", safe_rel(replay, root), "", save_id_from_replay_name(replay), "zero-byte replay"))
                except OSError as exc:
                    issues.append(ReplayIssue("client", safe_rel(replay, root), "", save_id_from_replay_name(replay), "replay stat failed", str(exc)))

            for bundle in sorted((session_dir / "incident_bundles").glob("*.zip")) if (session_dir / "incident_bundles").is_dir() else []:
                bundle_report, bundle_issues, incident = validate_zip_bundle(
                    bundle,
                    root,
                    side="client",
                    local_replay_save_ids=local_save_ids,
                    server_root=server_root,
                )
                session_report["incident_bundles"].append(bundle_report)
                issues.extend(bundle_issues)
                if isinstance(incident, dict) and clean_text(incident.get("rule_id")) == "unexpected_process":
                    add_unknown_process(unknown_counter_all, incident)
                    if not incident_matches_obs_client(incident, obs_client_keys):
                        add_unknown_process(unknown_counter_filtered, incident)

            for bundle in sorted((session_dir / "submission_bundle").glob("*.zip")) if (session_dir / "submission_bundle").is_dir() else []:
                bundle_report, bundle_issues, _incident = validate_zip_bundle(
                    bundle,
                    root,
                    side="client_submission",
                    local_replay_save_ids=local_save_ids,
                    server_root=server_root,
                )
                session_report["submission_bundles"].append(bundle_report)
                issues.extend(bundle_issues)
            root_report["sessions"].append(session_report)
        reports.append(root_report)
    return reports, issues


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_log_hits_csv(path: Path, hits: list[LogHit]) -> None:
    write_csv(path, [asdict(hit) for hit in hits], ["path", "line", "category", "student_hint", "session_hint", "excerpt"])


def write_replay_issues_csv(path: Path, issues: list[ReplayIssue]) -> None:
    write_csv(path, [asdict(issue) for issue in issues], ["side", "path", "incident_id", "save_id", "issue", "detail"])


def markdown_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Software Dump Analysis")
    lines.append("")
    lines.append(f"- Root: `{report['root']}`")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Server root: `{report['server'].get('root') or '-'}`")
    lines.append(f"- Client roots: `{len(report['clients'])}`")
    lines.append("")

    log_counts = report["logs"]["counts"]
    lines.append("## Crash And Error Signals")
    lines.append(f"- Log hits: `{len(report['logs']['hits'])}`")
    lines.append(f"- GUI crash markers: `{len(report['logs']['gui_crash_markers'])}`")
    if log_counts:
        lines.append("- Top categories: " + ", ".join(f"`{key}={value}`" for key, value in sorted(log_counts.items(), key=lambda item: item[1], reverse=True)))
    lines.append("")
    for hit in report["logs"]["hits"][:20]:
        lines.append(f"- `{hit['category']}` `{hit['path']}:{hit['line']}` {hit['excerpt'][:180]}")
    lines.append("")

    archive_rows = report["archive_parity"]
    bad_archives = [row for row in archive_rows if row["missing"] or row["size_mismatch"] or row["crc_mismatch"] or row["errors"]]
    lines.append("## Archive Parity")
    lines.append(f"- Top-level archive pairs checked: `{len(archive_rows)}`")
    lines.append(f"- Archive member file checks logged: `{len(report.get('archive_file_checks', []))}`")
    lines.append(f"- Archive pairs with issues: `{len(bad_archives)}`")
    for row in archive_rows:
        lines.append(
            f"- `{row['zip_path']}` checked={row['checked_files']} missing={row['missing']} "
            f"size_mismatch={row['size_mismatch']} crc_mismatch={row['crc_mismatch']} extra={row['extra_files']}"
        )
    lines.append("")

    server = report["server"]
    client_sessions = sum(len(client.get("sessions", [])) for client in report["clients"])
    client_replays = sum(session.get("replay_files", 0) for client in report["clients"] for session in client.get("sessions", []))
    client_incident_bundles = sum(len(session.get("incident_bundles", [])) for client in report["clients"] for session in client.get("sessions", []))
    lines.append("## Replay And File Integrity")
    lines.append(f"- Server incidents: `{server.get('incident_count', 0)}`")
    lines.append(f"- Server replay files: `{server.get('replay_files', 0)}`, zero-byte `{server.get('zero_byte_replay_files', 0)}`")
    lines.append(f"- Server incident bundles: `{len(server.get('incident_bundles', []))}`")
    lines.append(f"- Client sessions: `{client_sessions}`")
    lines.append(f"- Client replay files: `{client_replays}`")
    lines.append(f"- Client incident bundles: `{client_incident_bundles}`")
    lines.append(f"- Replay/file issues: `{len(report['replay_issues'])}`")
    for issue in report["replay_issues"][:30]:
        lines.append(f"- `{issue['issue']}` `{issue['side']}` `{issue['path']}`")
    lines.append("")

    lines.append("## Unknown Process Filter Candidates")
    unknowns = report["unknown_process_candidates"]
    all_unknowns = report.get("unknown_process_candidates_all", [])
    obs_clients = report.get("obs_clients", [])
    lines.append(f"- OBS clients detected: `{len(obs_clients)}`")
    lines.append(f"- OBS clients filtered from recommendations: `{bool(report.get('obs_clients_filtered'))}`")
    lines.append(f"- Unique unexpected process names after OBS-client filter: `{len(unknowns)}`")
    lines.append(f"- Unique unexpected process names before filter: `{len(all_unknowns)}`")
    known_names = [row["process_name"] for row in unknowns if row["suggested_action"] == "known_process_names"][:30]
    known_dirs = [row["top_dirs"].split("; ")[0] for row in unknowns if row["suggested_action"] == "known_directory_paths" and row["top_dirs"]][:20]
    review = [row["process_name"] for row in unknowns if row["suggested_action"] in {"review", "review_or_blacklist"}][:30]
    if known_names:
        lines.append("- Suggested `known_process_names`: " + ", ".join(f"`{name}`" for name in known_names))
    if known_dirs:
        lines.append("- Suggested `known_directory_paths`: " + ", ".join(f"`{item}`" for item in known_dirs))
    if review:
        lines.append("- Review before whitelisting: " + ", ".join(f"`{name}`" for name in review))
    lines.append("")
    for row in unknowns[:40]:
        lines.append(
            f"- `{row['process_name']}` count={row['count']} action=`{row['suggested_action']}` "
            f"paths={row['unique_paths']}"
        )
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze extracted Software server/client dumps and matching top-level archives.")
    parser.add_argument("--root", default="", help="Software folder root. Defaults to parent of this script's tools folder or current directory.")
    parser.add_argument("--reports-dir", default="", help="Output folder. Defaults to <root>/reports.")
    parser.add_argument("--fast-metadata", action="store_true", help="Skip extracted-file CRC and compare archive paths/sizes only.")
    parser.add_argument("--include-obs-clients", action="store_true", help="Do not filter OBS clients out of unknown-process recommendations.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script_path = Path(__file__).resolve()
    default_root = script_path.parent.parent if script_path.parent.name.lower() == "tools" else Path.cwd()
    root = Path(args.root or default_root).expanduser().resolve()
    reports_dir = Path(args.reports_dir).expanduser().resolve() if args.reports_dir else root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    server_root = find_server_root(root)
    client_roots = find_client_roots(root)
    unknown_counter_all: dict[str, dict[str, Any]] = {}
    unknown_counter_filtered: dict[str, dict[str, Any]] = {}

    print(f"[analysis] root: {root}")
    print(f"[analysis] server root: {server_root or '-'}")
    print(f"[analysis] client roots: {len(client_roots)}")
    print("[analysis] detecting OBS clients...")
    obs_clients = detect_obs_clients(root, server_root, client_roots)
    obs_client_keys = {
        value
        for client in obs_clients.values()
        for value in (client.client_id, client.login_id)
        if value
    }
    if args.include_obs_clients:
        obs_client_keys = set()
    print(f"[analysis] scanning logs...")
    log_hits, log_counts, crash_markers = analyze_logs(root)

    print(f"[analysis] checking top-level archives ({'metadata only' if args.fast_metadata else 'full CRC'})...")
    archive_parity, archive_file_checks = verify_archives(root, full_crc=not args.fast_metadata)

    print("[analysis] scanning server bundles and incidents...")
    server_report, server_replay_issues = analyze_server(
        root,
        server_root,
        unknown_counter_all,
        unknown_counter_filtered,
        obs_client_keys,
    )

    print("[analysis] scanning client bundles and incidents...")
    client_reports, client_replay_issues = analyze_client_roots(
        root,
        client_roots,
        server_root,
        unknown_counter_all,
        unknown_counter_filtered,
        obs_client_keys,
    )

    unknown_rows_all = finalize_unknown_processes(unknown_counter_all)
    unknown_rows = finalize_unknown_processes(unknown_counter_filtered if not args.include_obs_clients else unknown_counter_all)
    obs_client_rows = [
        {
            "client_id": client.client_id,
            "login_id": client.login_id,
            "session_path": client.session_path,
            "sources": "; ".join(sorted(client.sources)),
            "process_names": "; ".join(sorted(client.process_names)),
        }
        for client in sorted(obs_clients.values(), key=lambda item: (item.login_id, item.client_id, item.session_path))
    ]
    replay_issues = server_replay_issues + client_replay_issues
    archive_rows = [asdict(item) for item in archive_parity]
    archive_file_rows = [asdict(item) for item in archive_file_checks]
    log_hit_rows = [asdict(item) for item in log_hits]
    replay_issue_rows = [asdict(item) for item in replay_issues]
    report = {
        "root": str(root),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "crc_mode": not args.fast_metadata,
        "server": server_report,
        "clients": client_reports,
        "logs": {
            "counts": log_counts,
            "gui_crash_markers": crash_markers,
            "hits": log_hit_rows,
        },
        "archive_parity": archive_rows,
        "archive_file_checks": archive_file_rows,
        "replay_issues": replay_issue_rows,
        "unknown_process_candidates": unknown_rows,
        "unknown_process_candidates_all": unknown_rows_all,
        "obs_clients": obs_client_rows,
        "obs_clients_filtered": not args.include_obs_clients,
    }

    json_path = reports_dir / f"software_analysis_{stamp}.json"
    md_path = reports_dir / f"software_analysis_{stamp}.md"
    crash_csv = reports_dir / f"crash_log_hits_{stamp}.csv"
    replay_csv = reports_dir / f"replay_issues_{stamp}.csv"
    unknown_csv = reports_dir / f"unknown_process_candidates_{stamp}.csv"
    unknown_all_csv = reports_dir / f"unknown_process_candidates_all_{stamp}.csv"
    obs_clients_csv = reports_dir / f"obs_clients_{stamp}.csv"
    archive_csv = reports_dir / f"archive_parity_{stamp}.csv"
    archive_files_csv = reports_dir / f"archive_file_checks_{stamp}.csv"

    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(markdown_report(report), encoding="utf-8")
    write_log_hits_csv(crash_csv, log_hits)
    write_replay_issues_csv(replay_csv, replay_issues)
    write_csv(
        unknown_csv,
        unknown_rows,
        ["process_name", "count", "unique_paths", "top_paths", "top_dirs", "students", "statuses", "first_seen", "last_seen", "suggested_action"],
    )
    write_csv(
        unknown_all_csv,
        unknown_rows_all,
        ["process_name", "count", "unique_paths", "top_paths", "top_dirs", "students", "statuses", "first_seen", "last_seen", "suggested_action"],
    )
    write_csv(
        obs_clients_csv,
        obs_client_rows,
        ["client_id", "login_id", "session_path", "sources", "process_names"],
    )
    write_csv(
        archive_csv,
        archive_rows,
        ["zip_path", "extracted_folder", "checked_files", "missing", "size_mismatch", "crc_mismatch", "extra_files", "errors"],
    )
    write_csv(
        archive_files_csv,
        archive_file_rows,
        ["zip_path", "zip_member", "extracted_path", "status", "zip_size", "file_size", "zip_crc", "file_crc", "error"],
    )

    print(f"[analysis] wrote: {md_path}")
    print(f"[analysis] wrote: {json_path}")
    print(f"[analysis] wrote: {crash_csv}")
    print(f"[analysis] wrote: {replay_csv}")
    print(f"[analysis] wrote: {unknown_csv}")
    print(f"[analysis] wrote: {unknown_all_csv}")
    print(f"[analysis] wrote: {obs_clients_csv}")
    print(f"[analysis] wrote: {archive_csv}")
    print(f"[analysis] wrote: {archive_files_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
