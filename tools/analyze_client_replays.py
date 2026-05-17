#!/usr/bin/env python3
"""Analyze May_12 client replay files, bundles, and matching upload references.

Default target:
    May_12/data/client

Examples:
    python tools/analyze_client_replays.py
    python tools/analyze_client_replays.py --session 043e2a30-a7df-4422-982d-c6b8b8626d5a
    python tools/analyze_client_replays.py --session all --json client_replay_report.json
    python tools/analyze_client_replays.py --data-root X:\\May_12\\data\\client
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


REPLAY_SUFFIXES = {".ts", ".mp4", ".mkv", ".webm"}
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
STATUS_500_RE = re.compile(
    r"(\bstatus[=:\s]+500\b|\bhttp[=:\s]+500\b|\(500\)|\b500 internal server error\b)",
    re.I,
)
ERROR_TERMS = (
    "internal server error",
    "traceback",
    "exception",
    "upload failed",
    "replay save timed out",
    "timed out after",
)


@dataclass
class LocalReplay:
    path: str
    save_id: str
    size_bytes: int
    issue: str = ""


@dataclass
class IncidentBundle:
    path: str
    size_bytes: int = 0
    incident_id: str = ""
    rule_id: str = ""
    status: str = ""
    replay_save_id: str = ""
    replay_artifact_path: str = ""
    replay_artifact_exists: bool | None = None
    local_replay_exists: bool | None = None
    embedded_replays: list[str] = field(default_factory=list)
    manifest_replay_entries: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    zip_error: str = ""


@dataclass
class SubmissionBundle:
    path: str
    size_bytes: int = 0
    embedded_replays: list[str] = field(default_factory=list)
    manifest_replay_entries: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    zip_error: str = ""


@dataclass
class ClientSessionReport:
    session_uuid: str
    local_replays: list[LocalReplay]
    incident_bundles: list[IncidentBundle]
    submission_bundles: list[SubmissionBundle]
    process_report_count: int
    log_counts: dict[str, int]
    log_hits: list[dict[str, Any]]
    issues: list[str]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_data_root() -> Path:
    direct_extract = repo_root() / "May_12" / "data" / "client"
    if direct_extract.is_dir():
        return direct_extract
    return repo_root() / "May_12" / "client" / "data" / "client"


def default_logs_root() -> Path:
    direct_extract = repo_root() / "May_12" / "data" / "logs" / "client"
    if direct_extract.is_dir():
        return direct_extract
    return repo_root() / "May_12" / "client" / "data" / "logs" / "client"


def default_server_data_root() -> Path:
    return repo_root() / "May_12" / "server" / "data" / "server"


def normalize_client_data_root(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    candidates = [
        root,
        root / "data" / "client",
        root / "client" / "data" / "client",
        root / "May_12" / "data" / "client",
        root / "May_12" / "client" / "data" / "client",
    ]
    for candidate in candidates:
        if has_session_dirs(candidate):
            return candidate
    return root


def has_session_dirs(path: Path) -> bool:
    return path.is_dir() and any(item.is_dir() and UUID_RE.match(item.name) for item in path.iterdir())


def server_bundle_root(data_root: Path) -> Path:
    if data_root.name == "server" and data_root.parent.name == "data":
        return data_root.parent.parent
    return data_root


def safe_rel(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


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


def session_dirs(data_root: Path) -> list[Path]:
    if not data_root.is_dir():
        return []
    dirs = [path for path in data_root.iterdir() if path.is_dir() and UUID_RE.match(path.name)]
    return sorted(dirs, key=lambda path: path.name.lower())


def summarize_session_dir(path: Path) -> str:
    replay_count = len(list((path / "recordings" / "replays").glob("*"))) if (path / "recordings" / "replays").is_dir() else 0
    incident_count = len(list((path / "incident_bundles").glob("*.zip"))) if (path / "incident_bundles").is_dir() else 0
    submission_count = len(list((path / "submission_bundle").glob("*.zip"))) if (path / "submission_bundle").is_dir() else 0
    return f"{replay_count} replay file(s), {incident_count} incident bundle(s), {submission_count} submission bundle(s)"


def choose_session(data_root: Path, requested: str) -> list[str]:
    dirs = session_dirs(data_root)
    names = [path.name for path in dirs]
    if requested:
        if requested.lower() == "all":
            return names
        return [requested]

    if not names:
        raise SystemExit(f"No client session UUID folders found under {data_root}")

    print("\nAvailable client session UUIDs:\n")
    for index, name in enumerate(names, start=1):
        print(f"  {index:>2}. {name}  {summarize_session_dir(data_root / name)}")
    print("\nSelect a number, paste a UUID, or type 'all'.")

    while True:
        choice = input("> ").strip()
        if not choice:
            continue
        if choice.lower() == "all":
            return names
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(names):
                return [names[index - 1]]
        if UUID_RE.match(choice):
            return [choice]
        print("Invalid selection.")


def save_id_from_replay_name(path: Path | str) -> str:
    stem = Path(path).stem
    if stem.startswith("replay_"):
        return stem[len("replay_") :]
    return stem


def iter_replay_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        [
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix.lower() in REPLAY_SUFFIXES
        ],
        key=lambda path: path.name.lower(),
    )


def resolve_server_reference(reference: str, server_data_root: Path | None) -> Path | None:
    if not reference or not server_data_root:
        return None
    text = str(reference).strip()
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate

    candidates = [
        server_bundle_root(server_data_root) / candidate,
        server_data_root / candidate,
        repo_root() / candidate,
    ]
    for item in candidates:
        if item.exists():
            return item
    return candidates[0]


def analyze_local_replays(session_dir: Path, data_root: Path) -> list[LocalReplay]:
    replays: list[LocalReplay] = []
    for path in iter_replay_files(session_dir / "recordings" / "replays"):
        size = path.stat().st_size
        issue = "zero-byte replay" if size <= 0 else ""
        replays.append(
            LocalReplay(
                path=safe_rel(path, data_root),
                save_id=save_id_from_replay_name(path),
                size_bytes=size,
                issue=issue,
            )
        )
    return replays


def manifest_entries(manifest: Any) -> list[dict[str, Any]]:
    if isinstance(manifest, dict) and isinstance(manifest.get("entries"), list):
        return [entry for entry in manifest["entries"] if isinstance(entry, dict)]
    return []


def replay_manifest_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in entries:
        role = str(entry.get("role", "")).lower()
        archive_path = str(entry.get("archive_path", ""))
        if "replay" in role or Path(archive_path).suffix.lower() in REPLAY_SUFFIXES:
            result.append(entry)
    return result


def validate_manifest_entries(
    archive: zipfile.ZipFile,
    entries: list[dict[str, Any]],
) -> list[str]:
    issues: list[str] = []
    zip_infos = {info.filename: info for info in archive.infolist()}
    for entry in entries:
        archive_path = str(entry.get("archive_path", "") or "")
        if not archive_path:
            continue
        info = zip_infos.get(archive_path)
        if info is None:
            issues.append(f"manifest entry missing from zip: {archive_path}")
            continue
        expected_size = entry.get("size_bytes")
        if isinstance(expected_size, int) and expected_size != info.file_size:
            issues.append(
                f"manifest size mismatch for {archive_path}: manifest={expected_size}, zip={info.file_size}"
            )
    return issues


def analyze_incident_bundle(
    zip_path: Path,
    *,
    session_dir: Path,
    data_root: Path,
    server_data_root: Path | None,
    local_save_ids: set[str],
) -> IncidentBundle:
    result = IncidentBundle(path=safe_rel(zip_path, data_root), size_bytes=zip_path.stat().st_size)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            entries_by_name = set(names)
            result.embedded_replays = [
                name for name in names if Path(name).suffix.lower() in REPLAY_SUFFIXES
            ]
            incident = read_zip_json(archive, "incident.json")
            manifest = read_zip_json(archive, "manifest.json")
            if not isinstance(incident, dict) and isinstance(manifest, dict):
                incident = manifest.get("incident")
            if isinstance(incident, dict):
                result.incident_id = str(incident.get("incident_id", "") or "")
                result.rule_id = str(incident.get("rule_id", "") or "")
                result.status = str(incident.get("status", "") or "")
                result.replay_save_id = str(incident.get("replay_save_id", "") or "")
                result.replay_artifact_path = str(incident.get("replay_artifact_path", "") or "")
            else:
                result.issues.append("incident.json missing or unreadable")

            entries = manifest_entries(manifest)
            result.manifest_replay_entries = replay_manifest_entries(entries)
            result.issues.extend(validate_manifest_entries(archive, entries))

            for replay_name in result.embedded_replays:
                if replay_name not in entries_by_name:
                    result.issues.append(f"embedded replay listed but not found: {replay_name}")
    except zipfile.BadZipFile as exc:
        result.zip_error = str(exc)
        result.issues.append(f"bad zip: {exc}")
        return result
    except Exception as exc:
        result.zip_error = str(exc)
        result.issues.append(f"zip read failed: {exc}")
        return result

    if result.replay_save_id:
        result.local_replay_exists = result.replay_save_id in local_save_ids
        if not result.local_replay_exists:
            result.issues.append(f"local replay missing for save id: {result.replay_save_id}")

    if result.replay_artifact_path:
        resolved = resolve_server_reference(result.replay_artifact_path, server_data_root)
        result.replay_artifact_exists = bool(resolved and resolved.is_file())
        if not result.replay_artifact_exists:
            result.issues.append(f"server replay artifact missing: {result.replay_artifact_path}")

    if not result.embedded_replays and not result.replay_artifact_path:
        result.issues.append("bundle has no embedded replay and no shared replay reference")
    return result


def analyze_submission_bundle(zip_path: Path, data_root: Path) -> SubmissionBundle:
    result = SubmissionBundle(path=safe_rel(zip_path, data_root), size_bytes=zip_path.stat().st_size)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            result.embedded_replays = [
                name for name in names if Path(name).suffix.lower() in REPLAY_SUFFIXES
            ]
            manifest = read_zip_json(archive, "manifest.json")
            entries = manifest_entries(manifest)
            result.manifest_replay_entries = replay_manifest_entries(entries)
            result.issues.extend(validate_manifest_entries(archive, entries))
    except zipfile.BadZipFile as exc:
        result.zip_error = str(exc)
        result.issues.append(f"bad zip: {exc}")
    except Exception as exc:
        result.zip_error = str(exc)
        result.issues.append(f"zip read failed: {exc}")
    if not result.embedded_replays:
        result.issues.append("submission bundle has no replay")
    return result


def iter_log_lines(logs_root: Path):
    if not logs_root.is_dir():
        return
    for path in sorted(logs_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".log", ".jsonl", ".txt"}:
            continue
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, start=1):
                text = line.rstrip("\n")
                message = text
                if path.suffix.lower() == ".jsonl":
                    try:
                        item = json.loads(text)
                        if isinstance(item, dict):
                            message = str(item.get("message") or item.get("msg") or text)
                    except json.JSONDecodeError:
                        pass
                yield path, line_no, message, text


def analyze_logs(logs_root: Path, session_uuid: str, log_limit: int) -> tuple[dict[str, int], list[dict[str, Any]]]:
    counts: Counter[str] = Counter()
    hits: list[dict[str, Any]] = []
    counted_signals: set[tuple[str, str]] = set()
    counted_errors: set[str] = set()
    for path, line_no, message, raw in iter_log_lines(logs_root) or []:
        has_session = session_uuid in message or session_uuid in raw
        lowered = message.lower()
        primary_client_log = path.suffix.lower() == ".jsonl" and "sessions" not in {
            part.lower() for part in path.parts
        }
        if primary_client_log:
            if "[savescreen]" in lowered and "server requested replay save" in lowered:
                counts["savescreen_requests"] += 1
            if "requested_replay uploaded to" in lowered:
                counts["requested_replay_uploaded"] += 1
            if "failed to upload requested_replay" in lowered:
                counts["requested_replay_upload_failed"] += 1

        signal_names: list[str] = []
        if "sharing replay save" in lowered:
            signal_names.append("sharing_replay_save")
        if "reusing replay save" in lowered:
            signal_names.append("reusing_replay_save")
        if "replay saved to:" in lowered:
            signal_names.append("replay_saved")
        if "shared replay" in lowered and "uploaded" in lowered:
            signal_names.append("shared_replay_uploaded")
        if "evidence uploaded for" in lowered:
            signal_names.append("evidence_uploaded")
        if "replay save timed out" in lowered or "timed out after" in lowered:
            signal_names.append("replay_save_timed_out")

        for signal_name in signal_names:
            key = (signal_name, message)
            if key not in counted_signals:
                counted_signals.add(key)
                counts[signal_name] += 1

        is_error = STATUS_500_RE.search(message) or any(term in lowered for term in ERROR_TERMS)
        if is_error and (has_session or signal_names or "500" in lowered):
            new_error = message not in counted_errors
            if new_error:
                counted_errors.add(message)
                counts["unique_error_messages"] += 1
            counts["error_lines"] += 1
            if new_error and len(hits) < log_limit:
                hits.append(
                    {
                        "path": str(path),
                        "line": line_no,
                        "message": message[:500],
                    }
                )
    return dict(counts), hits


def analyze_session(
    data_root: Path,
    session_uuid: str,
    *,
    logs_root: Path,
    server_data_root: Path | None,
    log_limit: int,
) -> ClientSessionReport:
    session_dir = data_root / session_uuid
    issues: list[str] = []
    if not session_dir.is_dir():
        issues.append(f"client session folder missing: {session_dir}")

    local_replays = analyze_local_replays(session_dir, data_root)
    local_save_ids = {item.save_id for item in local_replays}
    for save_id, count in Counter(item.save_id for item in local_replays).items():
        if count > 1:
            issues.append(f"duplicate local replay save id {save_id}: {count} file(s)")
    for replay in local_replays:
        if replay.issue:
            issues.append(f"{replay.path}: {replay.issue}")

    incident_bundles = [
        analyze_incident_bundle(
            path,
            session_dir=session_dir,
            data_root=data_root,
            server_data_root=server_data_root,
            local_save_ids=local_save_ids,
        )
        for path in sorted((session_dir / "incident_bundles").glob("*.zip"))
    ]
    submission_bundles = [
        analyze_submission_bundle(path, data_root)
        for path in sorted((session_dir / "submission_bundle").glob("*.zip"))
    ]

    for bundle in incident_bundles:
        for issue in bundle.issues:
            issues.append(f"{bundle.path}: {issue}")
    for bundle in submission_bundles:
        for issue in bundle.issues:
            issues.append(f"{bundle.path}: {issue}")

    process_report_count = len(list(session_dir.glob("process_report_requested_*.json")))
    log_counts, log_hits = analyze_logs(logs_root, session_uuid, log_limit)

    return ClientSessionReport(
        session_uuid=session_uuid,
        local_replays=local_replays,
        incident_bundles=incident_bundles,
        submission_bundles=submission_bundles,
        process_report_count=process_report_count,
        log_counts=log_counts,
        log_hits=log_hits,
        issues=issues,
    )


def print_session_report(report: ClientSessionReport, *, detail_limit: int):
    replay_bytes = sum(item.size_bytes for item in report.local_replays)
    zero_replays = sum(1 for item in report.local_replays if item.size_bytes <= 0)
    incident_bytes = sum(item.size_bytes for item in report.incident_bundles)
    submission_bytes = sum(item.size_bytes for item in report.submission_bundles)
    embedded_incident = sum(1 for item in report.incident_bundles if item.embedded_replays)
    referenced_incident = sum(1 for item in report.incident_bundles if item.replay_artifact_path)
    no_replay_incident = sum(
        1 for item in report.incident_bundles if not item.embedded_replays and not item.replay_artifact_path
    )
    missing_server_refs = sum(1 for item in report.incident_bundles if item.replay_artifact_exists is False)
    missing_local_refs = sum(1 for item in report.incident_bundles if item.local_replay_exists is False)
    save_id_counts = Counter(item.replay_save_id for item in report.incident_bundles if item.replay_save_id)

    print(f"\n=== Client Session {report.session_uuid} ===")
    print("Local replay files:")
    print(f"  total: {len(report.local_replays)} file(s), {replay_bytes:,} byte(s)")
    print(f"  zero-byte: {zero_replays}")
    print(f"  save ids: {len({item.save_id for item in report.local_replays})}")

    print("\nIncident bundles:")
    print(f"  total: {len(report.incident_bundles)} file(s), {incident_bytes:,} byte(s)")
    print(f"  embedded replay: {embedded_incident}")
    print(f"  shared replay reference: {referenced_incident}")
    print(f"  no replay evidence: {no_replay_incident}")
    print(f"  missing local replay by save id: {missing_local_refs}")
    print(f"  missing server replay reference: {missing_server_refs}")
    if save_id_counts:
        print("  top save ids:")
        for save_id, count in save_id_counts.most_common(8):
            print(f"    {save_id}: {count} bundle(s)")

    print("\nSubmission bundles:")
    print(f"  total: {len(report.submission_bundles)} file(s), {submission_bytes:,} byte(s)")
    print(f"  with replay: {sum(1 for item in report.submission_bundles if item.embedded_replays)}")

    print("\nRuntime snapshots:")
    print(f"  requested process reports: {report.process_report_count}")

    if report.log_counts:
        print("\nClient log signals:")
        for key in sorted(report.log_counts):
            print(f"  {key}: {report.log_counts[key]}")

    if report.local_replays:
        print("\nReplay files:")
        for replay in sorted(report.local_replays, key=lambda item: item.path)[:detail_limit]:
            suffix = f" issue={replay.issue}" if replay.issue else ""
            print(f"  - {replay.path} ({replay.size_bytes:,} bytes) save_id={replay.save_id}{suffix}")
        if len(report.local_replays) > detail_limit:
            print(f"  ... {len(report.local_replays) - detail_limit} more replay file(s)")

    if report.log_hits:
        print("\nLog hits:")
        for hit in report.log_hits:
            path = Path(hit["path"])
            print(f"  - {path.name}:{hit['line']}: {hit['message']}")

    print("\nIssues:")
    if report.issues:
        for issue in report.issues[:detail_limit]:
            print(f"  - {issue}")
        if len(report.issues) > detail_limit:
            print(f"  ... {len(report.issues) - detail_limit} more issue(s)")
    else:
        print("  none found")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", default=str(default_data_root()), help="Client data root.")
    parser.add_argument("--logs-root", default=str(default_logs_root()), help="Client logs root.")
    parser.add_argument("--server-data-root", default=str(default_server_data_root()), help="Server data root for replay reference checks.")
    parser.add_argument("--session", default="", help="Session UUID, or 'all'. Omit for interactive selection.")
    parser.add_argument("--detail-limit", type=int, default=12, help="Maximum detailed rows to print per section.")
    parser.add_argument("--log-lines", type=int, default=20, help="Maximum suspicious client log lines to show.")
    parser.add_argument("--json", default="", help="Optional JSON report output path.")
    parser.add_argument("--no-server-check", action="store_true", help="Do not check replay_artifact_path against server data.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    data_root = normalize_client_data_root(args.data_root)
    logs_root = Path(args.logs_root).expanduser().resolve()
    server_data_root = None if args.no_server_check else Path(args.server_data_root).expanduser().resolve()
    sessions = choose_session(data_root, args.session)

    print(f"\nClient data root: {data_root}")
    print(f"Client logs root: {logs_root}")
    if server_data_root:
        print(f"Server data root: {server_data_root}")

    reports = [
        analyze_session(
            data_root,
            session,
            logs_root=logs_root,
            server_data_root=server_data_root,
            log_limit=max(0, args.log_lines),
        )
        for session in sessions
    ]

    for report in reports:
        print_session_report(report, detail_limit=max(1, args.detail_limit))

    if args.json:
        output_path = Path(args.json).expanduser().resolve()
        output_path.write_text(
            json.dumps([asdict(report) for report in reports], indent=2),
            encoding="utf-8",
        )
        print(f"\nWrote JSON report: {output_path}")

    return 1 if any(report.issues for report in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
