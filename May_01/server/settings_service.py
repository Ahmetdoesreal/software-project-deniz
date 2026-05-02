import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import protocol


LIST_ACTIONS = {"add", "remove", "replace"}


@dataclass
class SettingsResult:
    ok: bool
    changed: bool = False
    message: str = ""
    settings: dict = field(default_factory=dict)
    changed_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def get_settings_snapshot(state, app=None) -> dict:
    policy = state.current_exam_policy()
    snapshot = {
        "exam_policy": copy.deepcopy(state.exam_policy_config),
        "current_exam_policy": policy,
        "policy_version": policy.get("policy_version", ""),
        "process_blacklist": list(state.process_blacklist),
        "process_blacklist_version": state.process_blacklist_version,
        "operator_defaults": state.operator_defaults(),
        "session": state.session_policy(),
    }
    if app is not None:
        snapshot["runtime"] = {
            "exam_duration": app.get("exam_duration"),
            "exam_files": app.get("exam_files"),
        }
    return snapshot


def update_exam_policy(state, patch: dict, *, actor="admin", _audit_action="update_exam_policy") -> SettingsResult:
    if not isinstance(patch, dict):
        return _error_result("Exam policy patch must be an object.", state)

    before_config = copy.deepcopy(state.exam_policy_config)
    before_version = state.current_exam_policy().get("policy_version", "")
    merged = _deep_merge(copy.deepcopy(before_config), patch)
    normalized = state._normalize_exam_policy_config(merged)
    changed_paths = _changed_paths(before_config, normalized)

    if not changed_paths:
        return SettingsResult(
            ok=True,
            changed=False,
            message="No exam policy changes.",
            settings=get_settings_snapshot(state),
            changed_paths=[],
            errors=[],
        )

    state.exam_policy_config = normalized
    state.save_exam_policy()
    after_version = state.current_exam_policy().get("policy_version", "")
    _append_audit(
        state,
        actor=actor,
        action=_audit_action,
        changed_paths=changed_paths,
        before={"policy_version": before_version},
        after={"policy_version": after_version},
    )
    return SettingsResult(
        ok=True,
        changed=True,
        message="Exam policy updated.",
        settings=get_settings_snapshot(state),
        changed_paths=changed_paths,
        errors=[],
    )


def update_process_blacklist(state, action: str, entries: list[str], *, actor="admin") -> SettingsResult:
    action = str(action or "").strip().lower()
    if action not in LIST_ACTIONS:
        return _error_result(f"Unsupported process blacklist action: {action}", state)
    if not isinstance(entries, list):
        return _error_result("Process blacklist entries must be a list.", state)

    before_entries = list(state.process_blacklist)
    before_version = state.process_blacklist_version
    incoming = _dedupe_strings(entries)

    if action == "replace":
        next_entries = incoming
    elif action == "add":
        next_entries = _dedupe_strings(before_entries + incoming)
    else:
        remove_keys = {_key(entry) for entry in incoming}
        next_entries = [entry for entry in before_entries if _key(entry) not in remove_keys]

    if [_key(entry) for entry in next_entries] == [_key(entry) for entry in before_entries]:
        return SettingsResult(
            ok=True,
            changed=False,
            message="No process blacklist changes.",
            settings=get_settings_snapshot(state),
            changed_paths=[],
            errors=[],
        )

    state.process_blacklist = next_entries
    state.save_process_blacklist()
    _append_audit(
        state,
        actor=actor,
        action=f"process_blacklist_{action}",
        changed_paths=["process_blacklist"],
        before={"process_blacklist_version": before_version, "entries": before_entries},
        after={"process_blacklist_version": state.process_blacklist_version, "entries": next_entries},
    )
    return SettingsResult(
        ok=True,
        changed=True,
        message="Process blacklist updated.",
        settings=get_settings_snapshot(state),
        changed_paths=["process_blacklist"],
        errors=[],
    )


def update_known_processes(state, action: str, process_names: list[str], *, actor="admin") -> SettingsResult:
    return _update_policy_list(
        state,
        action,
        process_names,
        path=("rules", "unexpected_process", "known_process_names"),
        changed_path="rules.unexpected_process.known_process_names",
        normalizer=_normalize_process_name,
        actor=actor,
        action_name="known_processes",
    )


def update_known_directories(state, action: str, directory_paths: list[str], *, actor="admin") -> SettingsResult:
    return _update_policy_list(
        state,
        action,
        directory_paths,
        path=("rules", "unexpected_process", "known_directory_paths"),
        changed_path="rules.unexpected_process.known_directory_paths",
        normalizer=_normalize_directory_path,
        actor=actor,
        action_name="known_directories",
    )


def update_focused_window_rules(state, patch: dict, *, actor="admin") -> SettingsResult:
    if not isinstance(patch, dict):
        return _error_result("Focused-window rule patch must be an object.", state)
    return update_exam_policy(
        state,
        {"rules": {"focused_window": patch}},
        actor=actor,
        _audit_action="update_focused_window_rules",
    )


def apply_incident_policy_action(state, incident: dict, action: str, *, actor="admin") -> SettingsResult:
    if not isinstance(incident, dict):
        return _error_result("Incident must be an object.", state)

    action = str(action or "").strip().lower()
    process_name = _incident_process_name(incident)
    if action == "mark_known_process":
        if not process_name:
            return _error_result("Incident does not include a process name.", state)
        return update_known_processes(state, "add", [process_name], actor=actor)

    if action == "mark_known_directory":
        directory = _incident_process_directory(incident)
        if not directory:
            return _error_result("Incident does not include a process path or directory.", state)
        return update_known_directories(state, "add", [directory], actor=actor)

    if action == "add_process_blacklist":
        if not process_name:
            return _error_result("Incident does not include a process name.", state)
        return update_process_blacklist(state, "add", [process_name], actor=actor)

    return _error_result(f"Unsupported incident policy action: {action}", state)


def update_operator_defaults(state, patch: dict, *, actor="admin") -> SettingsResult:
    if not isinstance(patch, dict):
        return _error_result("Operator defaults patch must be an object.", state)
    return update_exam_policy(
        state,
        {"operator_defaults": patch},
        actor=actor,
        _audit_action="update_operator_defaults",
    )


def update_session_settings(state, patch: dict, *, actor="admin") -> SettingsResult:
    if not isinstance(patch, dict):
        return _error_result("Session settings patch must be an object.", state)
    return update_exam_policy(
        state,
        {"session": patch},
        actor=actor,
        _audit_action="update_session_settings",
    )


def update_runtime_settings(app, patch: dict, *, actor="admin") -> SettingsResult:
    if app is None:
        return SettingsResult(ok=False, message="Runtime app is required.", errors=["Runtime app is required."])
    if not isinstance(patch, dict):
        return SettingsResult(ok=False, message="Runtime patch must be an object.", errors=["Runtime patch must be an object."])

    errors: list[str] = []
    updates: dict[str, Any] = {}
    if "exam_duration" in patch:
        try:
            exam_duration = int(patch["exam_duration"])
        except (TypeError, ValueError):
            errors.append("exam_duration must be a positive integer.")
        else:
            if exam_duration <= 0:
                errors.append("exam_duration must be greater than 0.")
            else:
                updates["exam_duration"] = exam_duration

    if "exam_files" in patch:
        exam_files = patch.get("exam_files")
        if exam_files in {None, ""}:
            updates["exam_files"] = None
        else:
            exam_file = Path(str(exam_files)).expanduser()
            if exam_file.suffix.lower() != ".zip":
                errors.append("exam_files must be a .zip file.")
            elif not exam_file.exists() or not exam_file.is_file():
                errors.append(f"exam_files does not exist: {exam_file}")
            else:
                updates["exam_files"] = str(exam_file)

    unsupported = sorted(set(patch) - {"exam_duration", "exam_files"})
    if unsupported:
        errors.append(f"Unsupported runtime setting(s): {', '.join(unsupported)}")

    state = app.get("settings_state") or app.get("state")
    if errors:
        return SettingsResult(
            ok=False,
            changed=False,
            message="Runtime settings were not updated.",
            settings=get_settings_snapshot(state, app) if state else {"runtime": _runtime_snapshot(app)},
            errors=errors,
        )

    before = _runtime_snapshot(app)
    changed_paths = []
    for key, value in updates.items():
        if app.get(key) != value:
            app[key] = value
            changed_paths.append(f"runtime.{key}")

    if changed_paths and state:
        _append_audit(
            state,
            actor=actor,
            action="update_runtime_settings",
            changed_paths=changed_paths,
            before=before,
            after=_runtime_snapshot(app),
        )

    return SettingsResult(
        ok=True,
        changed=bool(changed_paths),
        message="Runtime settings updated." if changed_paths else "No runtime settings changes.",
        settings=get_settings_snapshot(state, app) if state else {"runtime": _runtime_snapshot(app)},
        changed_paths=changed_paths,
        errors=[],
    )


def _update_policy_list(
    state,
    action: str,
    values: list[str],
    *,
    path: tuple[str, ...],
    changed_path: str,
    normalizer,
    actor: str,
    action_name: str,
) -> SettingsResult:
    action = str(action or "").strip().lower()
    if action not in LIST_ACTIONS:
        return _error_result(f"Unsupported {action_name} action: {action}", state)
    if not isinstance(values, list):
        return _error_result(f"{action_name} values must be a list.", state)

    config = copy.deepcopy(state.exam_policy_config)
    current = list(_get_nested(config, path, []))
    incoming = [normalizer(value) for value in values]
    incoming = [value for value in incoming if value]

    if action == "replace":
        updated = _dedupe_strings(incoming)
    elif action == "add":
        updated = _dedupe_strings(current + incoming)
    else:
        remove_keys = {_key(value) for value in incoming}
        updated = [value for value in current if _key(value) not in remove_keys]

    _set_nested(config, path, updated)
    result = update_exam_policy(
        state,
        config,
        actor=actor,
        _audit_action=f"{action_name}_{action}",
    )
    if result.changed:
        result.message = f"{action_name.replace('_', ' ').title()} updated."
        result.changed_paths = [changed_path if item == changed_path or item.startswith(changed_path) else item for item in result.changed_paths]
        if changed_path not in result.changed_paths:
            result.changed_paths.append(changed_path)
    return result


def _error_result(message: str, state=None) -> SettingsResult:
    return SettingsResult(
        ok=False,
        changed=False,
        message=message,
        settings=get_settings_snapshot(state) if state else {},
        changed_paths=[],
        errors=[message],
    )


def _append_audit(state, *, actor: str, action: str, changed_paths: list[str], before: dict, after: dict):
    if not hasattr(state, "append_audit"):
        return
    state.append_audit(
        {
            "timestamp": protocol.now_iso(),
            "actor": str(actor or "admin"),
            "action": action,
            "changed_paths": list(changed_paths),
            "before": before,
            "after": after,
        }
    )


def _deep_merge(base: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(dict(base[key]), value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _changed_paths(before, after, prefix: str = "") -> list[str]:
    if before == after:
        return []
    if not isinstance(before, dict) or not isinstance(after, dict):
        return [prefix or "settings"]
    paths = []
    for key in sorted(set(before) | set(after)):
        child_prefix = f"{prefix}.{key}" if prefix else str(key)
        paths.extend(_changed_paths(before.get(key), after.get(key), child_prefix))
    return paths


def _get_nested(config: dict, path: tuple[str, ...], default):
    current = config
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _set_nested(config: dict, path: tuple[str, ...], value):
    current = config
    for part in path[:-1]:
        next_value = current.get(part)
        if not isinstance(next_value, dict):
            next_value = {}
            current[part] = next_value
        current = next_value
    current[path[-1]] = value


def _dedupe_strings(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        clean = str(value or "").strip()
        if not clean:
            continue
        key = _key(clean)
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def _normalize_process_name(value: str) -> str:
    clean = os.path.basename(str(value or "").strip())
    return clean.lower()


def _normalize_directory_path(value: str) -> str:
    clean = _expand_path_vars(str(value or "").strip())
    if not clean:
        return ""
    return os.path.normcase(os.path.normpath(os.path.expanduser(clean)))


def _expand_path_vars(value: str) -> str:
    def replace_percent_var(match):
        name = match.group(1)
        return os.environ.get(name, match.group(0))

    return os.path.expandvars(re.sub(r"%([^%]+)%", replace_percent_var, value))


def _incident_process_name(incident: dict) -> str:
    process_name = str(incident.get("normalized_process_name") or incident.get("process_name") or "").strip()
    if not process_name and incident.get("process_path"):
        process_name = os.path.basename(str(incident.get("process_path")))
    return _normalize_process_name(process_name)


def _incident_process_directory(incident: dict) -> str:
    process_dir = str(incident.get("process_dir") or "").strip()
    if process_dir:
        return _normalize_directory_path(process_dir)
    process_path = str(incident.get("process_path") or "").strip()
    if not process_path:
        return ""
    return _normalize_directory_path(os.path.dirname(process_path))


def _runtime_snapshot(app) -> dict:
    return {
        "exam_duration": app.get("exam_duration"),
        "exam_files": app.get("exam_files"),
    }


def _key(value: str) -> str:
    return str(value or "").strip().lower()
