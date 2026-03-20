import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
CLIENT_DATA_DIR = PROJECT_ROOT / "data" / "client"
SERVER_STATE_FILE = PROJECT_ROOT / "data" / "server" / "server_users.json"


def _is_inside_git_dir(path: Path) -> bool:
    return ".git" in path.parts


@dataclass(frozen=True)
class CleanupEntry:
    path: Path
    kind: str
    reason: str


def _collect_python_cache_entries(root: Path) -> list[CleanupEntry]:
    entries = []
    for pycache_dir in root.rglob("__pycache__"):
        if _is_inside_git_dir(pycache_dir):
            continue
        entries.append(
            CleanupEntry(
                path=pycache_dir,
                kind="dir",
                reason="python cache directory",
            )
        )

    for pattern in ("*.pyc", "*.pyo"):
        for file_path in root.rglob(pattern):
            if _is_inside_git_dir(file_path):
                continue
            if "__pycache__" in file_path.parts:
                continue
            entries.append(
                CleanupEntry(
                    path=file_path,
                    kind="file",
                    reason="compiled python artifact",
                )
            )
    return entries


def _collect_client_runtime_entries() -> list[CleanupEntry]:
    entries = []
    if not CLIENT_DATA_DIR.exists():
        return entries

    for session_dir in CLIENT_DATA_DIR.iterdir():
        if not session_dir.is_dir():
            if session_dir.name == ".DS_Store":
                entries.append(
                    CleanupEntry(
                        path=session_dir,
                        kind="file",
                        reason="Finder metadata",
                    )
                )
            continue

        entries.append(
            CleanupEntry(
                path=session_dir,
                kind="dir",
                reason="client runtime session data",
            )
        )
    return entries


def _collect_server_runtime_entries(include_server_state: bool) -> list[CleanupEntry]:
    if not include_server_state or not SERVER_STATE_FILE.exists():
        return []

    return [
        CleanupEntry(
            path=SERVER_STATE_FILE,
            kind="file",
            reason="server runtime state",
        )
    ]


def _collect_root_metadata_entries(root: Path) -> list[CleanupEntry]:
    entries = []
    for ds_store in root.rglob(".DS_Store"):
        if _is_inside_git_dir(ds_store):
            continue
        entries.append(
            CleanupEntry(
                path=ds_store,
                kind="file",
                reason="Finder metadata",
            )
        )
    return entries


def collect_cleanup_entries(root: Path, include_server_state: bool) -> list[CleanupEntry]:
    entries = []
    entries.extend(_collect_python_cache_entries(root))
    entries.extend(_collect_client_runtime_entries())
    entries.extend(_collect_server_runtime_entries(include_server_state))
    entries.extend(_collect_root_metadata_entries(root))

    unique_entries = {}
    for entry in entries:
        unique_entries[entry.path] = entry
    return sorted(unique_entries.values(), key=lambda entry: str(entry.path))


def remove_entry(entry: CleanupEntry):
    if entry.kind == "dir":
        shutil.rmtree(entry.path, ignore_errors=False)
        return
    entry.path.unlink(missing_ok=True)


def summarize(entries: list[CleanupEntry]):
    if not entries:
        print("No runtime files found.")
        return

    print("Runtime files selected for cleanup:")
    for entry in entries:
        relative_path = entry.path.relative_to(PROJECT_ROOT)
        print(f"  - {relative_path} [{entry.reason}]")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Remove generated runtime files, caches, and saved session data.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete the selected files. Without this flag, the script only shows a dry run.",
    )
    parser.add_argument(
        "--keep-server-state",
        action="store_true",
        help="Keep data/server/server_users.json instead of deleting it.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    entries = collect_cleanup_entries(
        PROJECT_ROOT,
        include_server_state=not args.keep_server_state,
    )
    summarize(entries)

    if not args.apply:
        print("\nDry run only. Re-run with --apply to delete these files.")
        return

    if not entries:
        return

    for entry in entries:
        remove_entry(entry)

    print(f"\nRemoved {len(entries)} runtime entries.")


if __name__ == "__main__":
    main()
