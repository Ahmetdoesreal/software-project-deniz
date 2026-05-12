import hashlib
import fnmatch
import os
import re
from copy import deepcopy
from pathlib import PureWindowsPath
from urllib.parse import urlencode

from common import protocol


PROCESS_DEFINITIONS_RULE_ID = "process_definitions"
PROCESS_PATH_CLARIFICATION_RULE_ID = "process_path_clarification"

PROCESS_DEFINITION_STATUSES = {"unknown", "whitelist", "blacklist", "warning"}
PROCESS_DEFINITION_SCOPES = {"path", "directory", "name"}
PROCESS_DEFINITION_ACTIONS = ("ban", "kick", "pause_exam", "kill_pid")
PROCESS_INCIDENT_RULE_IDS = {
    "unexpected_process",
    "process_blacklist",
    PROCESS_DEFINITIONS_RULE_ID,
    PROCESS_PATH_CLARIFICATION_RULE_ID,
}


def normalize_process_name(value: str | None) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if "\\" in clean:
        clean = PureWindowsPath(clean).name
    return os.path.basename(clean).lower()


def process_name_has_wildcard(value: str | None) -> bool:
    return any(marker in str(value or "") for marker in ("*", "?", "["))


def process_name_matches(pattern: str | None, process_name: str | None) -> bool:
    normalized_pattern = normalize_process_name(pattern)
    normalized_name = normalize_process_name(process_name)
    if not normalized_pattern or not normalized_name:
        return False
    if process_name_has_wildcard(normalized_pattern):
        return fnmatch.fnmatchcase(normalized_name, normalized_pattern)
    return normalized_name == normalized_pattern


def process_name_matches_any(process_name: str | None, patterns) -> bool:
    if not patterns:
        return False
    if isinstance(patterns, str):
        patterns = [patterns]
    return any(process_name_matches(pattern, process_name) for pattern in patterns)


def normalize_process_path(value: str | None) -> str:
    clean = expand_path_vars(str(value or "").strip())
    if not clean:
        return ""
    return os.path.normcase(os.path.normpath(os.path.expanduser(clean)))


def normalize_process_dir(value: str | None) -> str:
    normalized = normalize_process_path(value)
    if not normalized:
        return ""
    suffix = os.path.basename(normalized)
    if "." in suffix:
        return os.path.dirname(normalized)
    return normalized


def process_dir_from_path(value: str | None) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    return os.path.dirname(clean)


def process_display_name(process_name: str | None, process_path: str | None = None) -> str:
    clean = str(process_name or "").strip()
    if clean:
        return os.path.basename(clean)
    path = str(process_path or "").strip()
    if path:
        return os.path.basename(path)
    return ""


def expand_path_vars(value: str) -> str:
    def replace_percent_var(match):
        name = match.group(1)
        return os.environ.get(name, os.environ.get(name.upper(), os.environ.get(name.lower(), match.group(0))))

    return os.path.expandvars(re.sub(r"%([^%]+)%", replace_percent_var, str(value or "")))


def _path_has_windows_drive(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z]:[\\/]", str(value or "")))


def _path_basename(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if "\\" in clean or _path_has_windows_drive(clean):
        return PureWindowsPath(clean).name
    return os.path.basename(clean)


def _path_dirname(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if "\\" in clean or _path_has_windows_drive(clean):
        parent = PureWindowsPath(clean).parent
        if str(parent) == ".":
            return ""
        return str(parent)
    return os.path.dirname(clean)


def normalized_process_identity(process_name: str | None, process_path: str | None = None) -> dict:
    display_name = process_display_name(process_name, process_path)
    if not display_name and process_path:
        display_name = _path_basename(process_path)
    normalized_path = normalize_process_path(process_path)
    raw_dir = process_dir_from_path(process_path) or _path_dirname(process_path)
    return {
        "process_name": display_name,
        "normalized_process_name": normalize_process_name(display_name or process_path),
        "process_path": str(process_path or "").strip(),
        "normalized_process_path": normalized_path,
        "process_dir": raw_dir,
        "normalized_process_dir": normalize_process_dir(raw_dir),
    }


def normalize_actions(actions) -> dict:
    if not isinstance(actions, dict):
        actions = {}
    return {name: bool(actions.get(name, False)) for name in PROCESS_DEFINITION_ACTIONS}


def normalize_status(value: str | None) -> str:
    status = str(value or "unknown").strip().lower()
    if status not in PROCESS_DEFINITION_STATUSES:
        return "unknown"
    return status


def normalize_match_scope(value: str | None, *, process_path: str = "", process_dir: str = "") -> str:
    scope = str(value or "").strip().lower()
    if scope in PROCESS_DEFINITION_SCOPES:
        return scope
    if process_path:
        return "path"
    if process_dir:
        return "directory"
    return "name"


def stable_process_key(process_name: str | None, process_path: str | None = None, match_scope: str | None = None) -> str:
    identity = normalized_process_identity(process_name, process_path)
    scope = normalize_match_scope(
        match_scope,
        process_path=identity["normalized_process_path"],
        process_dir=identity["normalized_process_dir"],
    )
    if scope == "path":
        target = identity["normalized_process_path"] or identity["normalized_process_name"]
    elif scope == "directory":
        target = identity["normalized_process_dir"] or identity["normalized_process_name"]
    else:
        target = identity["normalized_process_name"]
    digest = hashlib.sha256(f"{scope}|{identity['normalized_process_name']}|{target}".encode("utf-8")).hexdigest()
    return digest[:24]


def normalize_definition(raw: dict | None, *, now: str | None = None) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    now = now or protocol.now_iso()
    identity = normalized_process_identity(
        raw.get("process_name") or raw.get("executable") or raw.get("name"),
        raw.get("process_path") or raw.get("path") or raw.get("executable_path"),
    )
    raw_dir = str(raw.get("process_dir") or raw.get("directory") or identity["process_dir"] or "").strip()
    normalized_dir = normalize_process_dir(raw.get("normalized_process_dir") or raw_dir)
    normalized_path = normalize_process_path(raw.get("normalized_process_path") or identity["process_path"])
    if normalized_path and not normalized_dir:
        normalized_dir = normalize_process_dir(os.path.dirname(normalized_path))
    scope = normalize_match_scope(
        raw.get("match_scope"),
        process_path=normalized_path,
        process_dir=normalized_dir,
    )
    process_name = process_display_name(identity["process_name"], identity["process_path"])
    normalized_name = normalize_process_name(raw.get("normalized_process_name") or process_name or normalized_path)
    process_key = stable_process_key(normalized_name, normalized_path, scope)
    definition_id = str(raw.get("definition_id") or raw.get("id") or process_key).strip()
    history = raw.get("matching_history", [])
    if not isinstance(history, list):
        history = []
    previous_entries = raw.get("previous_matching_entries", [])
    if not isinstance(previous_entries, list):
        previous_entries = []
    metadata = raw.get("admin_decision", {})
    if not isinstance(metadata, dict):
        metadata = {}

    return {
        "definition_id": definition_id,
        "process_key": process_key,
        "process_name": process_name,
        "normalized_process_name": normalized_name,
        "process_path": str(identity["process_path"] or raw.get("process_path") or "").strip(),
        "normalized_process_path": normalized_path,
        "process_dir": raw_dir or process_dir_from_path(identity["process_path"]),
        "normalized_process_dir": normalized_dir,
        "match_scope": scope,
        "status": normalize_status(raw.get("status")),
        "actions": normalize_actions(raw.get("actions") or raw.get("saved_actions")),
        "source_incident_id": str(raw.get("source_incident_id") or "").strip(),
        "source": str(raw.get("source") or "").strip(),
        "matching_history": [dict(entry) for entry in history if isinstance(entry, dict)],
        "previous_matching_entries": [dict(entry) for entry in previous_entries if isinstance(entry, dict)],
        "created_at": str(raw.get("created_at") or now),
        "updated_at": str(raw.get("updated_at") or now),
        "decided_at": str(raw.get("decided_at") or metadata.get("decided_at") or ""),
        "decided_by": str(raw.get("decided_by") or metadata.get("decided_by") or ""),
        "decision_reason": str(raw.get("decision_reason") or metadata.get("reason") or ""),
    }


def normalize_definitions(values) -> list[dict]:
    if not isinstance(values, list):
        return []
    normalized = []
    seen: set[str] = set()
    for value in values:
        definition = normalize_definition(value)
        key = str(definition.get("definition_id") or definition.get("process_key") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(definition)
    return normalized


def definition_matches_process(definition: dict, process_name: str | None, process_path: str | None = None) -> bool:
    definition = normalize_definition(definition)
    identity = normalized_process_identity(process_name, process_path)
    normalized_name = identity["normalized_process_name"]
    if not normalized_name or not process_name_matches(definition.get("normalized_process_name"), normalized_name):
        return False

    scope = definition.get("match_scope", "name")
    if scope == "name":
        return True
    if scope == "path":
        expected = definition.get("normalized_process_path", "")
        return bool(expected and identity["normalized_process_path"] == expected)
    if scope == "directory":
        expected = definition.get("normalized_process_dir", "")
        if not expected:
            return False
        process_dir = identity["normalized_process_dir"]
        return process_dir == expected
    return False


def find_matching_definitions(
    definitions: list[dict],
    process_name: str | None,
    process_path: str | None = None,
    *,
    statuses: set[str] | None = None,
) -> list[dict]:
    normalized_statuses = {normalize_status(status) for status in statuses} if statuses else None
    matches = []
    for raw_definition in definitions:
        definition = normalize_definition(raw_definition)
        if normalized_statuses is not None and definition.get("status") not in normalized_statuses:
            continue
        if definition_matches_process(definition, process_name, process_path):
            matches.append(definition)
    return matches


def find_saved_definition_for_path(definitions: list[dict], process_name: str | None, process_path: str | None = None) -> dict | None:
    for definition in find_matching_definitions(definitions, process_name, process_path):
        if definition.get("match_scope") == "name":
            continue
        return definition
    return None


def has_definition_for_same_executable(definitions: list[dict], process_name: str | None) -> bool:
    normalized_name = normalize_process_name(process_name)
    return any(
        process_name_matches(normalize_definition(definition).get("normalized_process_name"), normalized_name)
        for definition in definitions
    )


def process_incident_identity(incident: dict) -> dict:
    if not isinstance(incident, dict):
        incident = {}
    process_name = incident.get("process_name") or incident.get("normalized_process_name")
    process_path = incident.get("process_path") or incident.get("normalized_process_path")
    identity = normalized_process_identity(process_name, process_path)
    if not identity["process_dir"]:
        identity["process_dir"] = str(incident.get("process_dir") or "").strip()
        identity["normalized_process_dir"] = normalize_process_dir(identity["process_dir"])
    return identity


def incident_matches_definition(incident: dict, definition: dict) -> bool:
    identity = process_incident_identity(incident)
    return definition_matches_process(definition, identity["normalized_process_name"], identity["normalized_process_path"])


def definition_from_incident(incident: dict, *, status: str = "unknown", match_scope: str | None = None) -> dict:
    identity = process_incident_identity(incident)
    return normalize_definition(
        {
            "process_name": identity["process_name"] or incident.get("process_name"),
            "process_path": identity["process_path"] or incident.get("process_path"),
            "process_dir": identity["process_dir"] or incident.get("process_dir"),
            "match_scope": match_scope,
            "status": status,
            "source_incident_id": incident.get("incident_id", ""),
            "source": incident.get("source", ""),
        }
    )


def process_definition_patch(definition: dict) -> dict:
    return {
        "rules": {
            "process_definitions": {
                "definitions": [deepcopy(definition)],
            }
        }
    }


def build_google_search_url(process_name: str | None, process_path: str | None = None) -> str:
    terms = " ".join(part for part in [str(process_name or "").strip(), str(process_path or "").strip()] if part)
    if not terms:
        terms = "unknown process"
    return "https://www.google.com/search?" + urlencode({"q": terms})
