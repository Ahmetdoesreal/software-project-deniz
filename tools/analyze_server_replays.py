#!/usr/bin/env python3
"""Analyze May_12 server replay artifacts and incident bundles.

Default target is auto-detected. The script can be run from repo-root/tools,
copied into May_12, or copied into May_12/server beside the data folder.

Examples:
    python tools/analyze_server_replays.py
    python tools/analyze_server_replays.py --session ecd1144d-49f2-405e-9466-5c7742c0d108
    python tools/analyze_server_replays.py --data-root X:\\May_12\\server\\data\\server
    python tools/analyze_server_replays.py --session all --json report.json
    cd May_12\\server && python analyze_server_replays.py
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
ERROR_TERMS = (
    "internal server error",
    "traceback",
    "exception",
    "permissionerror",
    "winerror",
    "upload failed",
    "failed to finalize artifact",
    "failed to save artifact",
    "checksum mismatch",
)
STATUS_500_RE = re.compile(r"(\bstatus[=:\s]+500\b|\bhttp[=:\s]+500\b|\(500\)|\b500 internal server error\b)", re.I)


@dataclass
class ReplayArtifact:
    path: str
    kind: str
    size_bytes: int
    sidecar_json: str = ""
    save_id: str = ""
    sha256: str = ""
    issue: str = ""


@dataclass
class BundleAnalysis:
    path: str
    size_bytes: int = 0
    incident_id: str = ""
    rule_id: str = ""
    status: str = ""
    event_type: str = ""
    summary: str = ""
    replay_save_id: str = ""
    replay_artifact_path: str = ""
    replay_artifact_exists: bool | None = None
    embedded_replays: list[str] = field(default_factory=list)
    manifest_replay_entries: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    zip_error: str = ""


@dataclass
class SessionAnalysis:
    session_uuid: str
    artifact_counts: dict[str, int]
    artifact_bytes: dict[str, int]
    replay_artifacts: list[ReplayArtifact]
    bundles: list[BundleAnalysis]
    incident_log_count: int
    incident_status_counts: dict[str, int]
    incident_rule_counts: dict[str, int]
    log_hits: list[dict[str, Any]]
    issues: list[str]


def script_dir() -> Path:
    return Path(__file__).resolve().parent


def repo_root() -> Path:
    path = script_dir()
    if path.name.lower() == "tools":
        return path.parent
    for parent in [path, *path.parents]:
        if (parent / "May_12").is_dir():
            return parent
    return path


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            key = str(path.expanduser().resolve())
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def location_roots() -> list[Path]:
    roots: list[Path] = []
    for base in [Path.cwd(), script_dir()]:
        roots.append(base)
        roots.extend(base.parents)
    return _unique_paths(roots)


def local_roots() -> list[Path]:
    return _unique_paths([Path.cwd(), script_dir()])


def _server_data_candidates_for_roots(roots: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    for root in roots:
        candidates.extend(
            [
                root / "data" / "server",
                root / "server" / "data" / "server",
                root / "May_12" / "server" / "data" / "server",
            ]
        )
    return _unique_paths(candidates)


def server_data_candidates() -> list[Path]:
    return _server_data_candidates_for_roots(location_roots())


def default_data_root() -> Path:
    local_candidates = _server_data_candidates_for_roots(local_roots())
    for candidate in local_candidates:
        if (candidate / "artifacts").is_dir():
            return candidate
    for candidate in local_candidates:
        if candidate.is_dir():
            return candidate

    candidates = server_data_candidates()
    for candidate in candidates:
        if (candidate / "artifacts").is_dir():
            return candidate
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def logs_root_for_data_root(data_root: Path) -> Path:
    if data_root.name == "server" and data_root.parent.name == "data":
        return data_root.parent / "logs" / "server"
    return data_root / "logs" / "server"


def normalize_data_root(path: str | Path) -> Path:
    root = Path(path).expanduser().resolve()
    candidates = [
        root,
        root / "data" / "server",
        root / "server" / "data" / "server",
        root / "May_12" / "server" / "data" / "server",
    ]
    for candidate in candidates:
        if (candidate / "artifacts").is_dir():
            return candidate
    return root


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


def iter_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                yield line_no, json.loads(text), text
            except json.JSONDecodeError:
                yield line_no, None, text


def value_contains(value: Any, needle: str) -> bool:
    if isinstance(value, dict):
        return any(value_contains(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(value_contains(item, needle) for item in value)
    return needle in str(value)


def resolve_server_reference(reference: str, data_root: Path) -> Path | None:
    text = str(reference or "").strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute():
        return candidate

    bundle_root = server_bundle_root(data_root)
    candidates = [
        bundle_root / candidate,
        data_root / candidate,
        repo_root() / candidate,
    ]
    for item in candidates:
        if item.exists():
            return item
    return candidates[0]


def session_dirs(data_root: Path) -> list[Path]:
    artifacts = data_root / "artifacts"
    if not artifacts.is_dir():
        return []
    dirs = [path for path in artifacts.iterdir() if path.is_dir()]
    return sorted(dirs, key=lambda path: path.name.lower())


def choose_session(data_root: Path, requested: str) -> list[str]:
    dirs = session_dirs(data_root)
    names = [path.name for path in dirs]
    if requested:
        if requested.lower() == "all":
            return names
        return [requested]

    if not names:
        raise SystemExit(f"No session UUID folders found under {data_root / 'artifacts'}")

    print("\nAvailable artifact session UUIDs:\n")
    for index, name in enumerate(names, start=1):
        summary = summarize_session_dir(data_root / "artifacts" / name)
        print(f"  {index:>2}. {name}  {summary}")
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


def summarize_session_dir(session_dir: Path) -> str:
    parts = []
    for child in sorted(session_dir.iterdir()) if session_dir.is_dir() else []:
        if child.is_dir():
            count = sum(1 for item in child.iterdir() if item.is_file() and not item.name.endswith(".json"))
            parts.append(f"{child.name}:{count}")
    return ", ".join(parts) or "no artifacts"


def analyze_replay_artifacts(session_dir: Path, data_root: Path) -> tuple[list[ReplayArtifact], Counter, Counter]:
    replay_artifacts: list[ReplayArtifact] = []
    counts: Counter = Counter()
    bytes_by_kind: Counter = Counter()
    if not session_dir.is_dir():
        return replay_artifacts, counts, bytes_by_kind

    for kind_dir in sorted(path for path in session_dir.iterdir() if path.is_dir()):
        kind = kind_dir.name
        for path in sorted(item for item in kind_dir.iterdir() if item.is_file()):
            if path.name.endswith(".json"):
                continue
            size = path.stat().st_size
            counts[kind] += 1
            bytes_by_kind[kind] += size
            if path.suffix.lower() not in REPLAY_SUFFIXES:
                continue

            sidecar = path.with_suffix(path.suffix + ".json")
            metadata = read_json_file(sidecar) if sidecar.is_file() else {}
            metadata_payload = metadata.get("metadata", {}) if isinstance(metadata, dict) else {}
            save_id = ""
            if isinstance(metadata_payload, dict):
                save_id = str(metadata_payload.get("save_id", "") or "")
            replay_artifacts.append(
                ReplayArtifact(
                    path=safe_rel(path, data_root),
                    kind=kind,
                    size_bytes=size,
                    sidecar_json=safe_rel(sidecar, data_root) if sidecar.is_file() else "",
                    save_id=save_id,
                    sha256=str(metadata.get("sha256", "") if isinstance(metadata, dict) else ""),
                    issue="zero-byte replay artifact" if size <= 0 else "",
                )
            )
    return replay_artifacts, counts, bytes_by_kind


def analyze_bundle(path: Path, data_root: Path) -> BundleAnalysis:
    result = BundleAnalysis(path=safe_rel(path, data_root), size_bytes=path.stat().st_size)
    if path.stat().st_size <= 0:
        result.issues.append("zero-byte incident bundle")

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            result.embedded_replays = sorted(
                name
                for name in names
                if Path(name).suffix.lower() in REPLAY_SUFFIXES and "replay" in name.lower()
            )
            manifest = read_zip_json(archive, "manifest.json") or {}
            incident = read_zip_json(archive, "incident.json") or {}
    except zipfile.BadZipFile as exc:
        result.zip_error = str(exc)
        result.issues.append("bad zip file")
        return result
    except Exception as exc:
        result.zip_error = str(exc)
        result.issues.append("could not read zip")
        return result

    if isinstance(incident, dict):
        result.incident_id = str(incident.get("incident_id", "") or "")
        result.rule_id = str(incident.get("rule_id", "") or "")
        result.status = str(incident.get("status", "") or "")
        result.event_type = str(incident.get("event_type", "") or "")
        result.summary = str(incident.get("summary", "") or "")
        result.replay_save_id = str(incident.get("replay_save_id", "") or "")
        result.replay_artifact_path = str(incident.get("replay_artifact_path", "") or "")

    entries = manifest.get("entries", []) if isinstance(manifest, dict) else []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            role = str(entry.get("role", "") or "").lower()
            archive_path = str(entry.get("archive_path", "") or "")
            if "replay" in role or "replay" in archive_path.lower() or Path(archive_path).suffix.lower() in REPLAY_SUFFIXES:
                result.manifest_replay_entries.append(dict(entry))
                if archive_path and archive_path not in names:
                    result.issues.append(f"manifest replay entry missing from zip: {archive_path}")

    if result.replay_artifact_path:
        resolved = resolve_server_reference(result.replay_artifact_path, data_root)
        result.replay_artifact_exists = bool(resolved and resolved.is_file() and resolved.stat().st_size > 0)
        if not result.replay_artifact_exists:
            result.issues.append(f"referenced replay artifact missing: {result.replay_artifact_path}")
    elif not result.embedded_replays and not result.manifest_replay_entries:
        result.issues.append("no embedded replay and no replay artifact reference")

    return result


def analyze_bundles(session_dir: Path, data_root: Path) -> list[BundleAnalysis]:
    bundle_dir = session_dir / "incident_bundle"
    if not bundle_dir.is_dir():
        return []
    return [
        analyze_bundle(path, data_root)
        for path in sorted(bundle_dir.glob("*.zip"), key=lambda item: item.stat().st_mtime)
    ]


def analyze_incident_log(data_root: Path, session_uuid: str) -> tuple[int, Counter, Counter]:
    status_counts: Counter = Counter()
    rule_counts: Counter = Counter()
    count = 0
    for _line_no, payload, raw in iter_jsonl(data_root / "incidents.jsonl") or []:
        if payload is None:
            if session_uuid in raw:
                count += 1
            continue
        if not value_contains(payload, session_uuid):
            continue
        count += 1
        status_counts[str(payload.get("status", "") or "unknown")] += 1
        rule_counts[str(payload.get("rule_id", "") or payload.get("rule_name", "") or "unknown")] += 1
    return count, status_counts, rule_counts


def scan_logs(logs_root: Path, session_uuid: str, limit: int) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    if limit <= 0 or not logs_root.exists():
        return hits
    files = sorted(
        [path for path in logs_root.rglob("*") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in files:
        if len(hits) >= limit:
            break
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                for line_no, line in enumerate(handle, start=1):
                    text = line.rstrip()
                    lowered = text.lower()
                    is_error = STATUS_500_RE.search(text) or any(term in lowered for term in ERROR_TERMS)
                    if is_error and session_uuid in text:
                        hits.append(
                            {
                                "path": str(path),
                                "line": line_no,
                                "text": text[:500],
                            }
                        )
                        if len(hits) >= limit:
                            break
        except OSError:
            continue
    return hits


def analyze_session(data_root: Path, logs_root: Path, session_uuid: str, log_limit: int) -> SessionAnalysis:
    session_dir = data_root / "artifacts" / session_uuid
    replay_artifacts, artifact_counts, artifact_bytes = analyze_replay_artifacts(session_dir, data_root)
    bundles = analyze_bundles(session_dir, data_root)
    incident_log_count, status_counts, rule_counts = analyze_incident_log(data_root, session_uuid)

    issues: list[str] = []
    if not session_dir.is_dir():
        issues.append(f"artifact session directory missing: {session_dir}")
    for replay in replay_artifacts:
        if replay.issue:
            issues.append(f"{replay.path}: {replay.issue}")
    for bundle in bundles:
        for issue in bundle.issues:
            label = bundle.incident_id or Path(bundle.path).name
            issues.append(f"{label}: {issue}")

    return SessionAnalysis(
        session_uuid=session_uuid,
        artifact_counts=dict(artifact_counts),
        artifact_bytes=dict(artifact_bytes),
        replay_artifacts=replay_artifacts,
        bundles=bundles,
        incident_log_count=incident_log_count,
        incident_status_counts=dict(status_counts),
        incident_rule_counts=dict(rule_counts),
        log_hits=scan_logs(logs_root, session_uuid, log_limit),
        issues=issues,
    )


def print_session_report(report: SessionAnalysis, *, detail_limit: int) -> None:
    print(f"\n=== Session {report.session_uuid} ===")
    print("Artifacts by kind:")
    if report.artifact_counts:
        for kind, count in sorted(report.artifact_counts.items()):
            size = report.artifact_bytes.get(kind, 0)
            print(f"  {kind}: {count} file(s), {size:,} byte(s)")
    else:
        print("  none")

    embedded = sum(1 for bundle in report.bundles if bundle.embedded_replays)
    referenced = sum(1 for bundle in report.bundles if bundle.replay_artifact_path)
    no_replay = sum(
        1
        for bundle in report.bundles
        if not bundle.embedded_replays and not bundle.replay_artifact_path
    )
    missing_ref = sum(1 for bundle in report.bundles if bundle.replay_artifact_exists is False)

    print("\nIncident bundles:")
    print(f"  total: {len(report.bundles)}")
    print(f"  embedded replay: {embedded}")
    print(f"  shared replay reference: {referenced}")
    print(f"  no replay evidence: {no_replay}")
    print(f"  missing referenced replay: {missing_ref}")

    print("\nReplay artifacts:")
    if report.replay_artifacts:
        save_id_counts = Counter(item.save_id or "(no save_id)" for item in report.replay_artifacts)
        print(f"  total replay files: {len(report.replay_artifacts)}")
        print(f"  save ids: {len(save_id_counts)}")
        for replay in report.replay_artifacts[:detail_limit]:
            save_id = f" save_id={replay.save_id}" if replay.save_id else ""
            issue = f" ISSUE={replay.issue}" if replay.issue else ""
            print(f"  - {replay.kind}: {replay.path} ({replay.size_bytes:,} bytes){save_id}{issue}")
    else:
        print("  none")

    print("\nIncident log:")
    print(f"  matching incident log rows: {report.incident_log_count}")
    if report.incident_status_counts:
        print("  statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(report.incident_status_counts.items())))
    if report.incident_rule_counts:
        top_rules = sorted(report.incident_rule_counts.items(), key=lambda item: item[1], reverse=True)[:8]
        print("  top rules: " + ", ".join(f"{key}={value}" for key, value in top_rules))

    print("\nBundle details:")
    for bundle in report.bundles[:detail_limit]:
        replay_state = "none"
        if bundle.embedded_replays:
            replay_state = f"embedded:{len(bundle.embedded_replays)}"
        if bundle.replay_artifact_path:
            exists = "ok" if bundle.replay_artifact_exists else "missing"
            replay_state = f"ref:{exists}"
        issue_text = f" issues={len(bundle.issues)}" if bundle.issues else ""
        print(
            f"  - {Path(bundle.path).name} incident={bundle.incident_id or '-'} "
            f"status={bundle.status or '-'} rule={bundle.rule_id or '-'} replay={replay_state}{issue_text}"
        )
        for issue in bundle.issues[:3]:
            print(f"      ISSUE: {issue}")
    if len(report.bundles) > detail_limit:
        print(f"  ... {len(report.bundles) - detail_limit} more bundle(s)")

    print("\nLog hits:")
    if report.log_hits:
        for hit in report.log_hits[:detail_limit]:
            print(f"  - {Path(hit['path']).name}:{hit['line']}: {hit['text']}")
        if len(report.log_hits) > detail_limit:
            print(f"  ... {len(report.log_hits) - detail_limit} more log hit(s)")
    else:
        print("  none")

    print("\nIssues:")
    if report.issues:
        for issue in report.issues[:detail_limit]:
            print(f"  - {issue}")
        if len(report.issues) > detail_limit:
            print(f"  ... {len(report.issues) - detail_limit} more issue(s)")
    else:
        print("  none found")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze May_12 server replay and incident bundle artifacts.")
    parser.add_argument("--data-root", default="", help="Path to May_12/server/data/server or May_12/server. Defaults to auto-detection.")
    parser.add_argument("--logs-root", default="", help="Path to May_12/server/data/logs/server. Defaults beside the selected data root.")
    parser.add_argument("--session", default="", help="Session UUID to analyze, or 'all'. If omitted, asks interactively.")
    parser.add_argument("--log-lines", type=int, default=80, help="Maximum matching server log lines to collect per session.")
    parser.add_argument("--detail-limit", type=int, default=40, help="Maximum detail rows printed per section.")
    parser.add_argument("--json", default="", help="Optional path to write the full JSON report.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_root = normalize_data_root(args.data_root or default_data_root())
    logs_root = Path(args.logs_root).expanduser().resolve() if args.logs_root else logs_root_for_data_root(data_root)

    if not (data_root / "artifacts").is_dir():
        print(f"Server artifacts folder not found: {data_root / 'artifacts'}", file=sys.stderr)
        return 2

    sessions = choose_session(data_root, args.session)
    reports = [
        analyze_session(data_root, logs_root, session_uuid, args.log_lines)
        for session_uuid in sessions
    ]

    print(f"\nData root: {data_root}")
    print(f"Logs root: {logs_root}")
    for report in reports:
        print_session_report(report, detail_limit=max(1, args.detail_limit))

    if args.json:
        output_path = Path(args.json).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps([asdict(report) for report in reports], indent=2),
            encoding="utf-8",
        )
        print(f"\nWrote JSON report: {output_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
