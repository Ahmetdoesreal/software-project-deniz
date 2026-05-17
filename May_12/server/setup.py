"""
Simple setup entry point for the May_12 server bundle.

Usage:
    python setup.py
    python setup.py --offline
    python setup.py --offline --source X:\\offline-packages
"""

from __future__ import annotations

import argparse
import hashlib
import os
import site
import subprocess
import sys
from pathlib import Path


TARGET_PYTHON = (3, 13)
OK = "[OK]"
FAIL = "[FAIL]"
INFO = "[>>]"


def bundle_root() -> Path:
    return Path(__file__).resolve().parent


def run(command: list[str], *, dry_run: bool = False) -> None:
    print(f"  {INFO} RUN {' '.join(command)}")
    if dry_run:
        return
    subprocess.run(command, check=True)


def check_python_version() -> None:
    if sys.version_info[:2] != TARGET_PYTHON:
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise SystemExit(
            f"{FAIL} Python {TARGET_PYTHON[0]}.{TARGET_PYTHON[1]} is required; current Python is {version}. "
            "Install Python manually, then rerun setup.py."
        )
    print(f"  {OK} Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")


def check_user_python() -> None:
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        raise SystemExit(
            f"{FAIL} setup.py must be run with the user-wide Python, not from a virtual environment. "
            "Deactivate it, then rerun setup.py."
        )


def read_manifest(manifest_path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    if not manifest_path.exists():
        return expected
    for raw_line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        digest, marker, relative = line.partition(" *")
        if marker and len(digest) == 64:
            expected[relative.replace("/", os.sep)] = digest.lower()
    return expected


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_manifest(source: Path) -> None:
    manifest = read_manifest(source / "manifest.sha256")
    if not manifest:
        print(f"  {INFO} No manifest.sha256 found; skipping offline package hash verification.")
        return
    checked = 0
    for relative, expected_hash in manifest.items():
        target = source / relative
        if not target.is_file():
            raise SystemExit(f"{FAIL} Manifest file is missing: {relative}")
        actual_hash = sha256(target)
        if actual_hash != expected_hash:
            raise SystemExit(f"{FAIL} Manifest hash mismatch: {relative}")
        checked += 1
    print(f"  {OK} Verified {checked} offline package file(s)")


def validate_offline_source(source: Path) -> Path:
    if not source.exists():
        raise SystemExit(f"{FAIL} Offline package folder not found: {source}")
    wheelhouse = source / "wheelhouse"
    if not wheelhouse.is_dir():
        raise SystemExit(f"{FAIL} Offline wheelhouse folder not found: {wheelhouse}")
    if not any(wheelhouse.glob("*.whl")):
        raise SystemExit(f"{FAIL} Offline wheelhouse is empty: {wheelhouse}")
    verify_manifest(source)
    return wheelhouse


def install_dependencies(args: argparse.Namespace) -> None:
    root = bundle_root()
    requirements = root / "requirements.txt"
    if not requirements.is_file():
        raise SystemExit(f"{FAIL} requirements.txt not found: {requirements}")

    pip_python = sys.executable
    pip_command = [pip_python, "-m", "pip", "install", "--user"]
    if args.offline:
        source = Path(args.source).expanduser().resolve() if args.source else root / "offline-packages"
        wheelhouse = validate_offline_source(source)
        pip_command.extend(["--no-index", "--find-links", str(wheelhouse)])
    pip_command.extend(["-r", str(requirements)])

    run(pip_command, dry_run=args.dry_run)
    run([pip_python, "-m", "pip", "check"], dry_run=args.dry_run)
    if args.dry_run:
        print(f"  {OK} Server setup dry run completed; no dependencies were installed.")
    else:
        print(f"  {OK} Server dependencies are installed for the current user.")
        print(f"  {INFO} User site-packages: {site.getusersitepackages()}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set up the May_12 server bundle.")
    parser.add_argument("--offline", action="store_true", help="Install from offline-packages instead of package indexes.")
    parser.add_argument("--source", default="", help="Offline package folder. Defaults to ./offline-packages when --offline is used.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print commands without installing packages.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print("\n  May_12 Server Setup\n")
    check_python_version()
    check_user_python()
    install_dependencies(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
