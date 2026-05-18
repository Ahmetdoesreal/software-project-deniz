#!/usr/bin/env python3
"""Small HTTP syncer for May_12 client/server bundles.

Run this on the VM from the folder that should receive the bundles:

    python sync_bundles.py --serve

Run this on the dev machine from the repo root:

    python tools/sync_bundles.py --url http://VM_IP:8765 --delete

The receiver always writes into the folder where `--serve` was started:

    current-folder/client
    current-folder/server
"""

from __future__ import annotations

import argparse
import fnmatch
import http.client
import json
import os
import sys
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse


TARGETS = ("client", "server")
DEFAULT_PORT = 8765

SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "__pycache__",
    "env",
    "venv",
    ".venv",
}

SKIP_FILE_PATTERNS = (
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "*.temp",
    "*.bak",
    "*.log",
)

RUNTIME_EXCLUDE_PREFIXES = {
    "client": (
        "data/client/",
        "data/logs/",
        "offline-packages/",
    ),
    "server": (
        "data/logs/",
        "data/server/artifacts/",
        "data/server/submissions/",
        "offline-packages/",
    ),
}


@dataclass
class Stats:
    scanned: int = 0
    uploaded: int = 0
    current: int = 0
    deleted: int = 0
    bytes_uploaded: int = 0


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def may12_root() -> Path:
    return repo_root() / "May_12"


def selected_targets(target: str) -> list[str]:
    return list(TARGETS) if target == "all" else [target]


def source_root(target: str) -> Path:
    root = may12_root() / target
    if not root.is_dir():
        raise SystemExit(f"Source bundle not found: {root}")
    return root.resolve()


def normalize_rel(path: Path | str) -> str:
    return Path(path).as_posix().replace("//", "/")


def safe_rel_path(text: str) -> Path:
    raw = str(text or "").replace("\\", "/")
    if "\x00" in raw:
        raise ValueError("Path contains NUL byte.")
    path = Path(raw)
    if path.is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {text}")
    parts = [part for part in raw.split("/") if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"Unsafe relative path: {text}")
    if ":" in parts[0]:
        raise ValueError(f"Drive paths are not allowed: {text}")
    return Path(*parts)


def resolve_inside(root: Path, rel_path: Path) -> Path:
    root_resolved = root.resolve()
    target = (root / rel_path).resolve()
    if root_resolved not in {target, *target.parents}:
        raise ValueError(f"Path escapes sync root: {rel_path}")
    return target


def is_runtime_excluded(target: str, rel_text: str) -> bool:
    lowered = rel_text.lower()
    if lowered and not lowered.endswith("/"):
        lowered_dir = lowered + "/"
    else:
        lowered_dir = lowered
    return any(lowered_dir.startswith(prefix.lower()) for prefix in RUNTIME_EXCLUDE_PREFIXES[target])


def should_skip_dir(target: str, rel_dir: Path, dirname: str) -> bool:
    if dirname in SKIP_DIR_NAMES:
        return True
    rel_text = normalize_rel(rel_dir).rstrip("/") + "/"
    return is_runtime_excluded(target, rel_text)


def should_skip_file(target: str, rel_file: Path) -> bool:
    rel_text = normalize_rel(rel_file)
    if is_runtime_excluded(target, rel_text):
        return True
    name = rel_file.name.lower()
    return any(fnmatch.fnmatch(name, pattern.lower()) for pattern in SKIP_FILE_PATTERNS)


def iter_bundle_files(target: str):
    root = source_root(target)
    for dirpath, dirs, files in os.walk(root):
        base = Path(dirpath)
        dirs[:] = [
            dirname
            for dirname in dirs
            if not should_skip_dir(target, (base / dirname).relative_to(root), dirname)
        ]
        for filename in files:
            path = base / filename
            rel = path.relative_to(root)
            if not should_skip_file(target, rel):
                yield path, rel


def build_manifest(target: str) -> tuple[list[dict], dict[str, Path]]:
    manifest: list[dict] = []
    files: dict[str, Path] = {}
    for path, rel in iter_bundle_files(target):
        stat = path.stat()
        rel_text = normalize_rel(rel)
        manifest.append(
            {
                "path": rel_text,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
        files[rel_text] = path
    return manifest, files


def file_needs_upload(destination: Path, item: dict) -> bool:
    if not destination.is_file():
        return True
    try:
        stat = destination.stat()
    except OSError:
        return True
    if int(item.get("size", -1)) != stat.st_size:
        return True
    expected_mtime = int(item.get("mtime_ns", 0) or 0)
    return abs(stat.st_mtime_ns - expected_mtime) > 2_000_000_000


def destination_root(receiver_root: Path, target: str) -> Path:
    if target not in TARGETS:
        raise ValueError(f"Invalid target: {target}")
    return receiver_root / target


def stale_files(root: Path, target: str, expected: set[str]) -> list[str]:
    if not root.is_dir():
        return []
    stale: list[str] = []
    for dirpath, dirs, files in os.walk(root):
        base = Path(dirpath)
        dirs[:] = [
            dirname
            for dirname in dirs
            if not should_skip_dir(target, (base / dirname).relative_to(root), dirname)
        ]
        for filename in files:
            path = base / filename
            rel = path.relative_to(root)
            if should_skip_file(target, rel):
                continue
            rel_text = normalize_rel(rel)
            if rel_text not in expected:
                stale.append(rel_text)
    return stale


def plan_sync(receiver_root: Path, payload: dict) -> dict:
    target = str(payload.get("target", "") or "")
    files = payload.get("files", [])
    delete = bool(payload.get("delete"))
    if target not in TARGETS:
        raise ValueError(f"Invalid target: {target}")
    if not isinstance(files, list):
        raise ValueError("files must be a list")

    root = destination_root(receiver_root, target)
    upload: list[str] = []
    expected: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            continue
        rel = safe_rel_path(str(item.get("path", "") or ""))
        rel_text = normalize_rel(rel)
        expected.add(rel_text)
        destination = resolve_inside(root, rel)
        if file_needs_upload(destination, item):
            upload.append(rel_text)

    return {
        "ok": True,
        "root": str(root),
        "upload": upload,
        "delete": stale_files(root, target, expected) if delete else [],
    }


def delete_remote_files(receiver_root: Path, payload: dict) -> dict:
    target = str(payload.get("target", "") or "")
    paths = payload.get("paths", [])
    if target not in TARGETS:
        raise ValueError(f"Invalid target: {target}")
    if not isinstance(paths, list):
        raise ValueError("paths must be a list")

    root = destination_root(receiver_root, target)
    deleted = 0
    for text in paths:
        rel = safe_rel_path(str(text))
        path = resolve_inside(root, rel)
        if path.is_file():
            path.unlink()
            deleted += 1

    for dirpath, _dirs, _files in os.walk(root, topdown=False):
        path = Path(dirpath)
        if path == root:
            continue
        try:
            path.rmdir()
        except OSError:
            pass
    return {"ok": True, "deleted": deleted}


class SyncHandler(BaseHTTPRequestHandler):
    server_version = "May12SimpleSync/1.0"

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self.send_json({"ok": True, "root": str(self.server.receiver_root)})
            return
        self.send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        try:
            if not self.authorized():
                self.send_json({"ok": False, "error": "forbidden"}, status=403)
                return
            parsed = urlparse(self.path)
            if parsed.path == "/plan":
                self.send_json(plan_sync(self.server.receiver_root, self.read_json()))
                return
            if parsed.path == "/file":
                self.receive_file(parsed)
                return
            if parsed.path == "/delete":
                self.send_json(delete_remote_files(self.server.receiver_root, self.read_json()))
                return
            self.send_json({"ok": False, "error": "not found"}, status=404)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[HTTP] {self.address_string()} - {fmt % args}")

    def authorized(self) -> bool:
        token = getattr(self.server, "token", "")
        if not token:
            return True
        return self.headers.get("X-Sync-Token", "") == token

    def read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length)

    def read_json(self) -> dict:
        body = self.read_body()
        if not body:
            return {}
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def send_json(self, payload: dict, *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def receive_file(self, parsed) -> None:
        query = parse_qs(parsed.query)
        target = str(query.get("target", [""])[0])
        rel = safe_rel_path(str(query.get("path", [""])[0]))
        mtime_ns = int(query.get("mtime_ns", ["0"])[0] or "0")
        expected_size = int(query.get("size", ["0"])[0] or "0")
        root = destination_root(self.server.receiver_root, target)
        destination = resolve_inside(root, rel)
        destination.parent.mkdir(parents=True, exist_ok=True)

        length = int(self.headers.get("Content-Length", "0") or "0")
        if expected_size and length != expected_size:
            raise ValueError(f"Content-Length mismatch: {length} != {expected_size}")

        temp = destination.with_name(f".{destination.name}.sync-{os.getpid()}-{uuid.uuid4().hex}.tmp")
        written = 0
        with temp.open("wb") as handle:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                handle.write(chunk)
                written += len(chunk)
                remaining -= len(chunk)
        if written != length:
            try:
                temp.unlink()
            except OSError:
                pass
            raise ValueError(f"Incomplete upload: wrote {written}, expected {length}")

        os.replace(temp, destination)
        if mtime_ns:
            os.utime(destination, ns=(mtime_ns, mtime_ns))
        self.send_json({"ok": True, "path": normalize_rel(rel), "bytes": written})


class SyncServer(HTTPServer):
    receiver_root: Path
    token: str


def run_server(args: argparse.Namespace) -> int:
    root = Path.cwd().resolve()
    server = SyncServer((args.host, args.port), SyncHandler)
    server.receiver_root = root
    server.token = args.token or ""
    print(f"Serving sync receiver on http://{args.host}:{args.port}")
    print(f"Writing into current folder: {root}")
    if not server.token:
        print("WARNING: no --token set.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping receiver.")
    finally:
        server.server_close()
    return 0


def http_json(base_url: str, path: str, payload: dict, token: str, timeout: float) -> dict:
    parsed = urlparse(base_url.rstrip("/") + path)
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    if token:
        headers["X-Sync-Token"] = token
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or DEFAULT_PORT, timeout=timeout)
    try:
        conn.request("POST", parsed.path, body=body, headers=headers)
        response = conn.getresponse()
        data = response.read()
    finally:
        conn.close()
    result = json.loads(data.decode("utf-8") or "{}")
    if response.status >= 400 or not result.get("ok", False):
        raise RuntimeError(result.get("error") or f"HTTP {response.status}")
    return result


def upload_file(base_url: str, target: str, rel_path: str, source: Path, token: str, timeout: float) -> None:
    parsed = urlparse(base_url.rstrip("/"))
    query = urlencode(
        {
            "target": target,
            "path": rel_path,
            "mtime_ns": str(source.stat().st_mtime_ns),
            "size": str(source.stat().st_size),
        },
        quote_via=quote,
    )
    headers = {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(source.stat().st_size),
    }
    if token:
        headers["X-Sync-Token"] = token
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or DEFAULT_PORT, timeout=timeout)
    try:
        conn.putrequest("POST", f"/file?{query}")
        for key, value in headers.items():
            conn.putheader(key, value)
        conn.endheaders()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                conn.send(chunk)
        response = conn.getresponse()
        data = response.read()
    finally:
        conn.close()
    result = json.loads(data.decode("utf-8") or "{}")
    if response.status >= 400 or not result.get("ok", False):
        raise RuntimeError(result.get("error") or f"HTTP {response.status}")


def push_target(args: argparse.Namespace, target: str) -> Stats:
    manifest, files = build_manifest(target)
    plan = http_json(
        args.url,
        "/plan",
        {"target": target, "delete": args.delete, "files": manifest},
        args.token,
        args.timeout,
    )
    uploads = [str(item) for item in plan.get("upload", [])]
    deletes = [str(item) for item in plan.get("delete", [])]

    print(f"\n== {target} ==")
    print(f"Receiver folder: {plan.get('root')}")
    print(f"Files scanned:   {len(manifest)}")
    print(f"Need upload:     {len(uploads)}")
    if args.delete:
        print(f"Need delete:     {len(deletes)}")

    stats = Stats(scanned=len(manifest), current=len(manifest) - len(uploads))
    for rel_path in uploads:
        source = files.get(rel_path)
        if source is None:
            raise RuntimeError(f"Receiver requested unknown file: {rel_path}")
        if args.dry_run:
            print(f"UPLOAD {target}/{rel_path}")
        else:
            upload_file(args.url, target, rel_path, source, args.token, args.timeout)
            print(f"UPLOADED {target}/{rel_path}")
        stats.uploaded += 1
        stats.bytes_uploaded += source.stat().st_size

    if args.delete and deletes:
        if args.dry_run:
            for rel_path in deletes:
                print(f"DELETE {target}/{rel_path}")
        else:
            http_json(args.url, "/delete", {"target": target, "paths": deletes}, args.token, args.timeout)
            print(f"Deleted {len(deletes)} stale file(s).")
        stats.deleted = len(deletes)

    print(
        f"Done {target}: uploaded={stats.uploaded}, current={stats.current}, "
        f"deleted={stats.deleted}, bytes={stats.bytes_uploaded:,}"
    )
    return stats


def push(args: argparse.Namespace) -> int:
    totals = Stats()
    for target in selected_targets(args.target):
        stats = push_target(args, target)
        totals.scanned += stats.scanned
        totals.uploaded += stats.uploaded
        totals.current += stats.current
        totals.deleted += stats.deleted
        totals.bytes_uploaded += stats.bytes_uploaded
    print(
        f"\nTotal: scanned={totals.scanned}, uploaded={totals.uploaded}, "
        f"current={totals.current}, deleted={totals.deleted}, bytes={totals.bytes_uploaded:,}"
    )
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HTTP sync May_12 client/server into the receiver's current folder.")
    parser.add_argument("--serve", action="store_true", help="Run receiver. Files are written under the current folder.")
    parser.add_argument("--url", "--http-url", default="", help="Receiver URL, for example http://VM_IP:8765.")
    parser.add_argument("--host", default="0.0.0.0", help="Receiver bind host.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Receiver port.")
    parser.add_argument("--token", default="", help="Optional shared token.")
    parser.add_argument("--target", choices=("all", "client", "server"), default="all")
    parser.add_argument("--delete", action="store_true", help="Delete stale non-runtime files on the receiver.")
    parser.add_argument("--dry-run", action="store_true", help="Plan without uploading/deleting.")
    parser.add_argument("--timeout", type=float, default=120.0)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.serve:
        return run_server(args)
    if not args.url:
        raise SystemExit("Use --serve on the receiver, or pass --url http://HOST:8765 on the sender.")
    return push(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
