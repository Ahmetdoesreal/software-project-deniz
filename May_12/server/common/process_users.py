import getpass
import os


WELL_KNOWN_PROCESS_USERS = {
    "admin",
    "administrator",
    "root",
    "system",
    "trustedinstaller",
}


def normalize_process_username(username: str | None) -> str:
    value = str(username or "").strip().lower().replace("/", "\\")
    if "\\" in value:
        value = value.rsplit("\\", 1)[-1]
    return value


def current_process_usernames(extra_usernames: list[str] | tuple[str, ...] | set[str] | None = None) -> set[str]:
    usernames = set(WELL_KNOWN_PROCESS_USERS)
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
        normalized = normalize_process_username(candidate)
        if normalized:
            usernames.add(normalized)

    if extra_usernames:
        for username in extra_usernames:
            normalized = normalize_process_username(username)
            if normalized:
                usernames.add(normalized)

    return usernames
