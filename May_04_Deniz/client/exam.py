import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

import aiohttp

MANIFEST_NAME = ".exam_client_manifest.json"


def _desktop_root() -> Path:
    override = os.environ.get("EXAM_DESKTOP_ROOT")
    if override:
        return Path(override).expanduser()
    return Path.home() / "Desktop"


def _dated_exam_folder_name(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%d-%m-%Y")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _manifest_path(folder: Path) -> Path:
    return folder / MANIFEST_NAME


def _load_manifest(folder: Path) -> dict | None:
    try:
        with _manifest_path(folder).open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        return manifest if isinstance(manifest, dict) else None
    except Exception:
        return None


def _folder_has_user_content(folder: Path) -> bool:
    if not folder.exists():
        return False
    try:
        return any(child.name != MANIFEST_NAME for child in folder.iterdir())
    except OSError:
        return True


def _choose_target_folder(base_folder: Path, checksum: str) -> Path:
    base_folder.parent.mkdir(parents=True, exist_ok=True)
    if not base_folder.exists():
        return base_folder

    manifest = _load_manifest(base_folder)
    if manifest is not None:
        return base_folder

    if not _folder_has_user_content(base_folder):
        return base_folder

    for index in range(2, 100):
        candidate = base_folder.with_name(f"{base_folder.name}-{index}")
        if not candidate.exists():
            return candidate
        candidate_manifest = _load_manifest(candidate)
        if candidate_manifest and candidate_manifest.get("archive_sha256") == checksum:
            return candidate
    raise RuntimeError(f"Could not choose a safe exam folder under {base_folder.parent}")


def _safe_zip_member_path(member_name: str) -> Path:
    raw = str(member_name or "")
    if "\x00" in raw:
        raise ValueError(f"Unsafe ZIP member name: {member_name!r}")

    windows_path = PureWindowsPath(raw)
    if windows_path.drive or windows_path.root:
        raise ValueError(f"Unsafe absolute ZIP member: {member_name!r}")

    normalized = raw.replace("\\", "/")
    posix_path = PurePosixPath(normalized)
    if posix_path.is_absolute():
        raise ValueError(f"Unsafe absolute ZIP member: {member_name!r}")

    parts = [part for part in posix_path.parts if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"Unsafe ZIP member path traversal: {member_name!r}")
    return Path(*parts)


def _remove_previous_managed_files(folder: Path, previous_files: list[str]):
    for relative in sorted({str(path) for path in previous_files}, reverse=True):
        try:
            target = (folder / relative).resolve()
            folder_root = folder.resolve()
            if folder_root not in {target, *target.parents}:
                continue
            if target.is_file() or target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
        except OSError:
            continue

    for directory in sorted(
        [path for path in folder.rglob("*") if path.is_dir()],
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass


def _extract_zip_safely(zip_path: Path, target_folder: Path) -> list[str]:
    extracted: list[str] = []
    target_root = target_folder.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            relative_path = _safe_zip_member_path(info.filename)
            destination = (target_folder / relative_path).resolve()
            if target_root not in {destination, *destination.parents}:
                raise ValueError(f"Unsafe ZIP member destination: {info.filename!r}")
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
            extracted.append(str(relative_path))
    return extracted


def extract_exam_materials(zip_path: str | Path, *, now: datetime | None = None) -> dict:
    zip_file = Path(zip_path).expanduser().resolve()
    content = zip_file.read_bytes()
    checksum = _sha256_bytes(content)
    exam_root = _desktop_root() / "Exam"
    target = _choose_target_folder(exam_root / _dated_exam_folder_name(now), checksum)
    target.mkdir(parents=True, exist_ok=True)

    manifest = _load_manifest(target)
    if manifest and manifest.get("archive_sha256") == checksum:
        return {
            "has_files": True,
            "zip_path": str(zip_file),
            "extracted_dir": str(target),
            "archive_sha256": checksum,
            "reused": True,
        }

    previous_files = list(manifest.get("files", [])) if manifest else []
    if previous_files:
        _remove_previous_managed_files(target, previous_files)

    extracted_files = _extract_zip_safely(zip_file, target)
    manifest_payload = {
        "managed_by": "May_04_Deniz_client",
        "archive_path": str(zip_file),
        "archive_sha256": checksum,
        "extracted_at": datetime.now().isoformat(timespec="seconds"),
        "files": extracted_files,
    }
    _manifest_path(target).write_text(
        json.dumps(manifest_payload, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    return {
        "has_files": True,
        "zip_path": str(zip_file),
        "extracted_dir": str(target),
        "archive_sha256": checksum,
        "reused": False,
    }


async def fetch_exam_prep(base_url: str, session_uuid: str) -> dict:
    """Fetch exam configuration, download files, and extract them for the student."""
    result = {"has_files": False, "zip_path": "", "extracted_dir": ""}
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/exam/config") as resp:
            if resp.status == 200:
                config = await resp.json()
                mins = config.get("exam_duration_seconds", 0) // 60
                print(f"[EXAM] Config loaded: Exam duration is {mins} minutes.")
            else:
                print(f"[EXAM] Failed to load config: {resp.status}")

        async with session.get(f"{base_url}/exam/files") as resp:
            if resp.status == 200:
                print("[EXAM] Downloading exam files...")
                content = await resp.read()
                out_dir = Path("data") / "client" / session_uuid / "exam_files"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / "exam_materials.zip"
                out_path.write_bytes(content)
                print(f"[EXAM] Exam files saved to {out_path}.")
                try:
                    result = extract_exam_materials(out_path)
                    print(f"[EXAM] Exam files extracted to {result['extracted_dir']}.")
                except Exception as exc:
                    result = {"has_files": True, "zip_path": str(out_path), "extracted_dir": "", "error": str(exc)}
                    print(f"[EXAM] Failed to extract exam files: {exc}")
            elif resp.status == 404:
                print("[EXAM] No exam files provided by server.")
            else:
                body = await resp.text()
                print(f"[EXAM] Failed to download exam files ({resp.status}): {body}")
    return result
