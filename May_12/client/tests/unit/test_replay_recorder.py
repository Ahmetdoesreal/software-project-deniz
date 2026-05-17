import concurrent.futures
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from client.custommodules.replay_recorder import ReplayRecorder


class ReplayRecorderTsSaveTests(unittest.TestCase):
    def setUp(self):
        self.session_uuid = f"_test_recorder_{uuid4().hex}"
        self.recorder = ReplayRecorder(self.session_uuid)
        self.recorder._running = True
        self.client_dir = Path("data") / "client" / self.session_uuid

    def tearDown(self):
        shutil.rmtree(self.client_dir, ignore_errors=True)

    def _write_cache(self, playlist_entries: list[str], existing_segments: dict[str, bytes] | None = None):
        cache_dir = Path(self.recorder.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        existing_segments = existing_segments or {
            segment: f"segment:{segment}".encode("utf-8")
            for segment in playlist_entries
        }
        for segment, content in existing_segments.items():
            (cache_dir / segment).write_bytes(content)
        playlist = ["#EXTM3U", *playlist_entries]
        (cache_dir / "replay.m3u8").write_text("\n".join(playlist), encoding="utf-8")

    def test_save_replay_returns_ts_without_subprocess_merge(self):
        self._write_cache(
            ["cache_000.ts", "cache_001.ts"],
            {
                "cache_000.ts": b"first",
                "cache_001.ts": b"second",
            },
        )

        with patch("client.custommodules.replay_recorder.core.subprocess.run") as subprocess_run:
            replay_path = self.recorder.save_replay("request-A")

        subprocess_run.assert_not_called()
        replay_file = Path(replay_path)
        self.assertEqual(replay_file.name, "replay_request-A.ts")
        self.assertEqual(replay_file.read_bytes(), b"firstsecond")
        self.assertFalse((Path(self.recorder.requests_dir) / "request-A").exists())

    def test_save_replay_skips_missing_zero_byte_and_changing_segments(self):
        self._write_cache(
            ["cache_000.ts", "cache_empty.ts", "cache_missing.ts", "cache_changing.ts"],
            {
                "cache_000.ts": b"stable",
                "cache_empty.ts": b"",
                "cache_changing.ts": b"before",
            },
        )
        original_copy2 = shutil.copy2

        def mutate_during_copy(source, destination, *args, **kwargs):
            result = original_copy2(source, destination, *args, **kwargs)
            if Path(source).name == "cache_changing.ts":
                Path(source).write_bytes(b"after-change")
            return result

        with patch("client.custommodules.replay_recorder.core.shutil.copy2", side_effect=mutate_during_copy):
            replay_path = self.recorder.save_replay("request-race")

        replay_file = Path(replay_path)
        self.assertEqual(replay_file.name, "replay_request-race.ts")
        self.assertEqual(replay_file.read_bytes(), b"stable")
        self.assertFalse((Path(self.recorder.requests_dir) / "request-race").exists())

    def test_ffmpeg_resolver_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env_ffmpeg = root / "env_ffmpeg.exe"
            bundled_ffmpeg = root / "bundled_ffmpeg.exe"
            path_ffmpeg = root / "path_ffmpeg.exe"
            for candidate in (env_ffmpeg, bundled_ffmpeg, path_ffmpeg):
                candidate.write_bytes(b"fake")

            with patch.dict(os.environ, {"EXAM_FFMPEG_PATH": str(env_ffmpeg)}), patch.object(
                ReplayRecorder,
                "_bundled_ffmpeg_paths",
                return_value=[str(bundled_ffmpeg)],
            ), patch(
                "client.custommodules.replay_recorder.core.shutil.which",
                side_effect=lambda value: str(path_ffmpeg) if value == "ffmpeg" else None,
            ):
                self.assertEqual(ReplayRecorder._resolve_ffmpeg_executable(), str(env_ffmpeg))

            with patch.dict(os.environ, {}, clear=True), patch.object(
                ReplayRecorder,
                "_bundled_ffmpeg_paths",
                return_value=[str(bundled_ffmpeg)],
            ), patch(
                "client.custommodules.replay_recorder.core.shutil.which",
                side_effect=lambda value: str(path_ffmpeg) if value == "ffmpeg" else None,
            ):
                self.assertEqual(ReplayRecorder._resolve_ffmpeg_executable(), str(bundled_ffmpeg))

            bundled_ffmpeg.unlink()
            with patch.dict(os.environ, {}, clear=True), patch.object(
                ReplayRecorder,
                "_bundled_ffmpeg_paths",
                return_value=[str(bundled_ffmpeg)],
            ), patch(
                "client.custommodules.replay_recorder.core.shutil.which",
                side_effect=lambda value: str(path_ffmpeg) if value == "ffmpeg" else None,
            ):
                self.assertEqual(ReplayRecorder._resolve_ffmpeg_executable(), str(path_ffmpeg))

    def test_save_replay_lock_prevents_overlapping_direct_saves(self):
        active = 0
        max_active = 0
        active_lock = threading.Lock()

        def fake_save(request_id: str | None = None):
            nonlocal active, max_active
            with active_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with active_lock:
                active -= 1
            return f"{request_id}.ts"

        self.recorder._save_replay_locked = fake_save

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self.recorder.save_replay, ["one", "two"]))

        self.assertEqual(max_active, 1)
        self.assertEqual(results, ["one.ts", "two.ts"])


if __name__ == "__main__":
    unittest.main()
