import psutil


PROCESS_FIELDS = ("pid", "name", "username")


def get_processes_via_psutil() -> set[tuple[int, str, str | None]]:
    processes = set()
    try:
        iterator = psutil.process_iter(PROCESS_FIELDS)
        for process in iterator:
            try:
                pid = process.info.get("pid")
                name = process.info.get("name")
                username = process.info.get("username")
                if pid is None or not name:
                    continue
                processes.add((int(pid), str(name), str(username) if username else None))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except (psutil.Error, PermissionError, OSError) as e:
            print(f"[PROCESS] psutil process listing failed: {e}")
    return processes


def _print_processes(processes: set[tuple[int, str, str | None]], limit: int) -> None:
    for pid, name, username in sorted(processes, key=lambda item: (str(item[1]).lower(), int(item[0])))[:limit]:
        print(f"{pid}\t{name}\t{username or ''}")
    print(f"[PROCESS] listed {min(len(processes), limit)} of {len(processes)} process(es)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="List running processes using psutil.")
    parser.add_argument("--limit", type=int, default=25, help="Maximum number of processes to print.")
    args = parser.parse_args()

    _print_processes(get_processes_via_psutil(), max(0, args.limit))
