from common import protocol


WAITING = "waiting"
RUNNING = "running"
ADMIN_PAUSED = "admin_paused"
DISCONNECTED_PAUSED = "disconnected_paused"
VIOLATION_PAUSED = "violation_paused"
AWAITING_SUBMISSION = "awaiting_submission"
SUBMITTED = "submitted"
BANNED = "banned"

PAUSED_STATES = {ADMIN_PAUSED, DISCONNECTED_PAUSED, VIOLATION_PAUSED}
ACTIVE_EXAM_STATES = {RUNNING, *PAUSED_STATES, AWAITING_SUBMISSION}
TERMINAL_STATES = {SUBMITTED, BANNED}


def derive_state(user: dict) -> str:
    state = str(user.get("session_state", "") or "").strip()
    if state:
        return state

    if user.get("banned", False):
        return BANNED
    if user.get("submitted_at"):
        return SUBMITTED
    if user.get("exam_started", False) and user.get("exam_finished", False):
        return AWAITING_SUBMISSION
    if user.get("admin_paused", False):
        return ADMIN_PAUSED
    if user.get("exam_started", False):
        return RUNNING
    return WAITING


def ensure_defaults(user: dict):
    state = derive_state(user)
    user.setdefault("session_state", state)
    user.setdefault("session_state_reason", "")
    user.setdefault("session_state_updated_at", "")
    user.setdefault("last_disconnect_at", "")
    user.setdefault("blocking_incident_id", "")
    user.setdefault("blocking_rule_id", "")
    user.setdefault("violation_forgiven_at", "")
    user.setdefault("violation_forgiven_by", "")
    user.setdefault("violation_forgiven_incident_id", "")
    _sync_legacy_flags(user, state)


def set_state(
    user: dict,
    state: str,
    *,
    reason: str = "",
    remaining_seconds: int | None = None,
    blocking_incident_id: str = "",
    blocking_rule_id: str = "",
    clear_blocking: bool = False,
):
    at = protocol.now_iso()
    user["session_state"] = state
    user["session_state_reason"] = reason
    user["session_state_updated_at"] = at

    if remaining_seconds is not None:
        user["paused_remaining_seconds"] = int(max(0, remaining_seconds))

    if state == ADMIN_PAUSED:
        user["admin_paused"] = True
        user["admin_pause_reason"] = reason
        user["admin_paused_at"] = at
    else:
        user["admin_paused"] = False
        if state != RUNNING:
            user["admin_pause_reason"] = user.get("admin_pause_reason", "")
        else:
            user["admin_pause_reason"] = ""
        if state != RUNNING:
            user["admin_paused_at"] = user.get("admin_paused_at", "")
        else:
            user["admin_paused_at"] = ""

    if state == DISCONNECTED_PAUSED:
        user["last_disconnect_at"] = at
    elif state != VIOLATION_PAUSED:
        user["last_disconnect_at"] = ""

    if clear_blocking or state != VIOLATION_PAUSED:
        user["blocking_incident_id"] = ""
        user["blocking_rule_id"] = ""

    if state == VIOLATION_PAUSED:
        user["blocking_incident_id"] = blocking_incident_id
        user["blocking_rule_id"] = blocking_rule_id

    _sync_legacy_flags(user, state)


def reconnect_resume_allowed(user: dict, session_policy: dict) -> bool:
    state = derive_state(user)
    auto_resume = bool(session_policy.get("auto_resume_on_reconnect", True))
    if state == DISCONNECTED_PAUSED:
        return auto_resume
    return state not in {VIOLATION_PAUSED, AWAITING_SUBMISSION, SUBMITTED, BANNED}


def running_timer(user: dict) -> bool:
    return derive_state(user) == RUNNING


def pause_source(user: dict) -> str:
    state = derive_state(user)
    if state == ADMIN_PAUSED:
        return "admin"
    if state == DISCONNECTED_PAUSED:
        return "disconnect"
    if state == VIOLATION_PAUSED:
        return "violation"
    return ""


def display_name(user: dict) -> str:
    state = derive_state(user)
    if state == WAITING:
        return "Waiting"
    if state == RUNNING:
        return "Running"
    if state == ADMIN_PAUSED:
        return "Admin Paused"
    if state == DISCONNECTED_PAUSED:
        return "Disconnected Paused"
    if state == VIOLATION_PAUSED:
        return "Violation Paused"
    if state == AWAITING_SUBMISSION:
        return "Awaiting Submission"
    if state == SUBMITTED:
        return "Submitted"
    if state == BANNED:
        return "Banned"
    return state.replace("_", " ").title()


def _sync_legacy_flags(user: dict, state: str):
    user["banned"] = state == BANNED or bool(user.get("banned", False) and state != WAITING)
    if state == WAITING:
        user["exam_started"] = False
        user["exam_finished"] = False
        user["banned"] = False
    elif state == RUNNING:
        user["exam_started"] = True
        user["exam_finished"] = False
        user["banned"] = False
    elif state in PAUSED_STATES:
        user["exam_started"] = True
        user["exam_finished"] = False
        user["banned"] = False
    elif state == AWAITING_SUBMISSION:
        user["exam_started"] = True
        user["exam_finished"] = True
        user["banned"] = False
    elif state == SUBMITTED:
        user["exam_started"] = True
        user["exam_finished"] = True
        user["banned"] = False
    elif state == BANNED:
        user["banned"] = True
        user["exam_started"] = bool(user.get("exam_started", False))
        user["exam_finished"] = bool(user.get("exam_finished", False))
