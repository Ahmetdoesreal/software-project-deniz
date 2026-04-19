import getpass
import os


SYSTEM_USERS = {
    "admin",
    "administrator",
    "root",
    "system",
    "trustedinstaller",
}


def user_key(username: str | None) -> str:
    value = str(username or "").strip().lower().replace("/", "\\")
    if "\\" in value:
        value = value.rsplit("\\", 1)[-1]
    return value


def watched_users(extra_users=None) -> set[str]:
    users = set(SYSTEM_USERS)
    candidates = [
        os.environ.get("USERNAME"),
        os.environ.get("USER"),
        os.environ.get("LOGNAME"),
    ]
    try:
        candidates.append(getpass.getuser())
    except (KeyError, OSError):
        pass
    try:
        candidates.append(os.getlogin())
    except OSError:
        pass

    for candidate in candidates:
        cleaned = user_key(candidate)
        if cleaned:
            users.add(cleaned)

    for candidate in extra_users or []:
        cleaned = user_key(candidate)
        if cleaned:
            users.add(cleaned)

    return users
