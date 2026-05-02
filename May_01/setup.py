#!/usr/bin/env python3
"""
setup.py -- Windows setup script.

Checks for and installs:
  1. Python packages from requirements.txt (via pip)
  2. FFmpeg (via winget)

Run:  python setup.py
"""

import os
import platform
import shutil
import subprocess
import sys


OK = "[OK]"
WARN = "[!!]"
FAIL = "[FAIL]"
INFO = "[>>]"


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
    """Return the Windows package manager install command prefix."""
    if shutil.which("winget"):
        return "winget", [
            "winget",
            "install",
            "--accept-source-agreements",
            "--accept-package-agreements",
        ]
    return None, None


def check_windows():
    """Verify this setup script is running on the supported OS."""
    system = platform.system()
    if system == "Windows":
        print(f"  {OK} Windows target detected")
        return True
    print(f"  {FAIL} Unsupported OS: {system}. This delivery targets Windows only.")
    return False


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
    """Check for FFmpeg and install it with winget when available."""
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
        print(f"\n  {WARN} winget was not found.")
        print("     Install FFmpeg manually or install winget and rerun setup.py.")
        return False

    ffmpeg_pkg = "Gyan.FFmpeg"
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
    print(f"\n  Setup - Windows target ({system} {arch})\n")

    print("  Operating System")
    windows_ok = check_windows()
    if not windows_ok:
        print("\n  Fix the issue above and run this script on Windows.\n")
        return 1

    print("\n  Python")
    check_python()

    print("\n  Python Packages")
    pip_ok = check_pip_packages()
    if pip_ok:
        print(f"  {INFO} Protected websocket messaging requires 'cryptography' at runtime.")

    print("\n  FFmpeg")
    ffmpeg_ok = check_ffmpeg()

    print("\n  Summary")
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

