#!/usr/bin/env python3
"""
setup.py -- Cross-platform setup script.

Checks for and installs:
  1. Python packages from requirements.txt (via pip)
  2. FFmpeg (via winget when available)

Run:  python setup.py
"""

import os
import platform
import shutil
import subprocess
import sys


class Color:
    """ANSI colors, disabled automatically on Windows without VT support."""

    ENABLED = sys.stdout.isatty() and os.name != "nt"

    @staticmethod
    def green(s):
        if Color.ENABLED:
            return f"\033[92m{s}\033[0m"
        return s

    @staticmethod
    def yellow(s):
        if Color.ENABLED:
            return f"\033[93m{s}\033[0m"
        return s

    @staticmethod
    def red(s):
        if Color.ENABLED:
            return f"\033[91m{s}\033[0m"
        return s

    @staticmethod
    def cyan(s):
        if Color.ENABLED:
            return f"\033[96m{s}\033[0m"
        return s

    @staticmethod
    def bold(s):
        if Color.ENABLED:
            return f"\033[1m{s}\033[0m"
        return s


OK = Color.green("[OK]")
WARN = Color.yellow("[!!]")
FAIL = Color.red("[FAIL]")
INFO = Color.cyan("[>>]")


def run(cmd, capture=True):
    """Run a command and return (success, stdout)."""
    try:
        result = subprocess.run(cmd, capture_output=capture, text=True, timeout=60)
        stdout = result.stdout.strip() if capture and result.stdout else ""
        return result.returncode == 0, stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""


def get_version(binary):
    """Try to get a version string from a binary."""
    for flag in ["--version", "-version"]:
        ok, out = run([binary, flag])
        if ok and out:
            return out.splitlines()[0]
    return None


def detect_package_manager():
    """Return package manager install command prefix."""
    system = platform.system()
    if system == "Windows" and shutil.which("winget"):
        return "winget", [
            "winget",
            "install",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ]
    return None, None


def check_python():
    """Verify Python version."""
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 10):
        print(f"  {OK} Python {version_str}")
        return True
    print(f"  {WARN} Python {version_str} (3.10+ recommended)")
    return True


def check_pip_packages():
    """Check and install packages from requirements.txt."""
    req_path = os.path.join(os.path.dirname(__file__) or ".", "requirements.txt")
    if not os.path.exists(req_path):
        print(f"  {FAIL} requirements.txt not found")
        return False

    with open(req_path, encoding="utf-8") as f:
        packages = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if not packages:
        print(f"  {OK} No Python packages required")
        return True

    print(f"  {INFO} Using requirements file: {os.path.abspath(req_path)}")

    missing = []
    for pkg in packages:
        name = pkg.split(">=")[0].split("==")[0].split("<")[0].split(">")[0].strip()
        ok, out = run([sys.executable, "-m", "pip", "show", name])
        if ok:
            version = ""
            for line in out.splitlines():
                if line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
                    break
            print(f"  {OK} {name} {version}")
        else:
            print(f"  {FAIL} {name} - not installed")
            missing.append(pkg)

    if not missing:
        return True

    print(f"\n  {INFO} Installing missing packages: {', '.join(missing)}")
    ok, _ = run([sys.executable, "-m", "pip", "install", *missing], capture=False)
    if ok:
        print(f"  {OK} Packages installed successfully")
        return True
    print(f"  {FAIL} pip install failed")
    return False


def check_ffmpeg():
    """Check for FFmpeg and offer to install if missing."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        version = get_version("ffmpeg")
        print(f"  {OK} FFmpeg found: {ffmpeg_path}")
        if version:
            print(f"     {version}")
        return True

    print(f"  {FAIL} FFmpeg - not found in PATH")
    mgr_name, install_cmd = detect_package_manager()
    if not install_cmd:
        print(f"\n  {WARN} No supported package manager found.")
        print("     Download FFmpeg manually: https://ffmpeg.org/download.html")
        return False

    ffmpeg_pkg = "Gyan.FFmpeg" if mgr_name == "winget" else "ffmpeg"
    print(f"\n  {INFO} Installing FFmpeg via {mgr_name}...")
    ok, _ = run([*install_cmd, ffmpeg_pkg], capture=False)
    if ok and shutil.which("ffmpeg"):
        version = get_version("ffmpeg")
        print(f"  {OK} FFmpeg installed successfully")
        if version:
            print(f"     {version}")
        return True

    print(f"  {FAIL} FFmpeg installation failed. Please install manually.")
    return False


def main():
    system = platform.system()
    arch = platform.machine()
    print(Color.bold(f"\n  Setup - {system} {arch}\n"))
    print(Color.bold("  Python"))
    check_python()

    print(Color.bold("\n  Python Packages"))
    pip_ok = check_pip_packages()
    if pip_ok:
        print(f"  {INFO} Protected websocket messaging requires 'cryptography' at runtime.")

    print(Color.bold("\n  FFmpeg"))
    ffmpeg_ok = check_ffmpeg()

    print(Color.bold("\n  Summary"))
    if pip_ok and ffmpeg_ok:
        print(f"  {OK} Everything is set up. You are ready to go.\n")
        return 0

    if not pip_ok:
        print(f"  {FAIL} Some Python packages could not be installed.")
    if not ffmpeg_ok:
        print(f"  {FAIL} FFmpeg is not available.")
    print(f"\n  Fix the issues above and run this script again.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())

