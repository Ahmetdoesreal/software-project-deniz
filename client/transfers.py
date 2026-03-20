import asyncio
import hashlib
import json
import os
import time
import zipfile
from pathlib import Path

import aiohttp


UPLOAD_ATTEMPTS = 2


def build_submission_bundle(
    session_uuid: str,
    student_archive_path: str,
    process_report_path: str | None,
    replay_path: str | None,
) -> str:
    student_archive = Path(student_archive_path).expanduser().resolve()
    bundle_dir = Path("data") / "client" / session_uuid / "submission_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    bundle_path = bundle_dir / f"submission_bundle_{timestamp}.zip"
    manifest = _build_bundle_manifest(student_archive, process_report_path, replay_path)

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(student_archive, arcname=f"student_submission/{student_archive.name}")
        _write_manifest(archive, manifest)
        _add_optional_file(archive, process_report_path, "runtime/process_report_requested.json")
        _add_optional_file(archive, replay_path, _runtime_replay_name(replay_path))

    return str(bundle_path)


async def upload_runtime_artifact(
    base_url: str,
    session_uuid: str,
    artifact_path: str,
    artifact_kind: str,
    metadata: dict | None = None,
) -> dict:
    return await _upload_file(
        url=f"{base_url}/client/artifact",
        session_uuid=session_uuid,
        file_path=artifact_path,
        file_field_name="artifact",
        extra_fields={
            "kind": artifact_kind,
            "metadata": json.dumps(metadata or {}),
        },
    )


async def upload_submission_bundle(
    base_url: str,
    session_uuid: str,
    bundle_path: str,
) -> dict:
    return await _upload_file(
        url=f"{base_url}/exam/submission",
        session_uuid=session_uuid,
        file_path=bundle_path,
        file_field_name="archive",
    )


def file_sha256(file_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(file_path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _upload_file(
    *,
    url: str,
    session_uuid: str,
    file_path: str,
    file_field_name: str,
    extra_fields: dict[str, str] | None = None,
) -> dict:
    target_file = Path(file_path).expanduser().resolve()
    if not target_file.exists() or not target_file.is_file():
        raise ValueError(f"Upload file does not exist: {target_file}")

    last_error: Exception | None = None
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            return await _post_file(
                url=url,
                session_uuid=session_uuid,
                target_file=target_file,
                file_field_name=file_field_name,
                extra_fields=extra_fields or {},
            )
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as exc:
            last_error = exc
            if attempt >= UPLOAD_ATTEMPTS:
                break
            await asyncio.sleep(0.5 * attempt)

    raise ValueError(f"Upload failed after {UPLOAD_ATTEMPTS} attempt(s): {last_error}")


async def _post_file(
    *,
    url: str,
    session_uuid: str,
    target_file: Path,
    file_field_name: str,
    extra_fields: dict[str, str],
) -> dict:
    checksum = file_sha256(target_file)
    timeout = aiohttp.ClientTimeout(total=120)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        with target_file.open("rb") as file_handle:
            form = aiohttp.FormData()
            form.add_field(
                file_field_name,
                file_handle,
                filename=target_file.name,
                content_type="application/octet-stream",
            )
            form.add_field("sha256", checksum)
            for key, value in extra_fields.items():
                form.add_field(key, value)

            async with session.post(
                url,
                params={"id": session_uuid},
                data=form,
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    raise ValueError(f"Upload failed ({response.status}): {body}")
                return await response.json()


def _build_bundle_manifest(
    student_archive: Path,
    process_report_path: str | None,
    replay_path: str | None,
) -> dict:
    entries = [
        {
            "role": "student_submission",
            "name": student_archive.name,
            "size_bytes": student_archive.stat().st_size,
            "sha256": file_sha256(student_archive),
        }
    ]
    if process_report_path:
        process_file = Path(process_report_path)
        entries.append(
            {
                "role": "requested_process_report",
                "name": process_file.name,
                "size_bytes": process_file.stat().st_size,
                "sha256": file_sha256(process_file),
            }
        )
    if replay_path:
        replay_file = Path(replay_path)
        entries.append(
            {
                "role": "final_replay",
                "name": replay_file.name,
                "size_bytes": replay_file.stat().st_size,
                "sha256": file_sha256(replay_file),
            }
        )

    return {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "entries": entries,
    }


def _write_manifest(archive: zipfile.ZipFile, manifest: dict):
    archive.writestr("manifest.json", json.dumps(manifest, indent=2))


def _add_optional_file(archive: zipfile.ZipFile, file_path: str | None, arcname: str | None):
    if not file_path or not arcname:
        return
    source = Path(file_path)
    if not source.exists() or not source.is_file():
        return
    archive.write(source, arcname=arcname)


def _runtime_replay_name(replay_path: str | None) -> str | None:
    if not replay_path:
        return None
    replay_file = Path(replay_path)
    return f"runtime/{replay_file.name}"
