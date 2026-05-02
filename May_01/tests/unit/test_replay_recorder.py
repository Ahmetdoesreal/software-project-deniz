import shutil
import stat
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from client.custommodules.replay_recorder import ReplayRecorder


class _FakeFfmpegStdin:
    def __init__(self):
        self.writes = []
        self.flushed = False
        self.closed = False

    def write(self, data):
        self.writes.append(data)

    def flush(self):
        self.flushed = True

    def close(self):
        self.closed = True


class _FakeFfmpegProcess:
    def __init__(self, wait_side_effects=None, stdin=None):
        self.stdin = stdin if stdin is not None else _FakeFfmpegStdin()
        self.wait_side_effects = list(wait_side_effects or [0])
        self.wait_timeouts = []
        self.terminated = False
        self.killed = False

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        result = self.wait_side_effects.pop(0) if self.wait_side_effects else 0
        if isinstance(result, Exception):
            raise result
        return result

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class ReplayRecorderSaveTests(unittest.TestCase):
    def setUp(self):
        self.session_uuid = f"_test_recorder_{uuid4().hex}"
        self.recorder = ReplayRecorder(self.session_uuid)
        self.recorder._running = True
        self.client_dir = Path("data") / "client" / self.session_uuid

    def tearDown(self):
        shutil.rmtree(self.client_dir, ignore_errors=True)

    def _write_cache(self, playlist_entries: list[str], existing_segments: list[str] | None = None):
        cache_dir = Path(self.recorder.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        existing_segments = existing_segments if existing_segments is not None else playlist_entries
        for segment in existing_segments:
            (cache_dir / segment).write_bytes(f"segment:{segment}".encode("utf-8"))
        playlist = ["#EXTM3U", *playlist_entries]
        (cache_dir / "replay.m3u8").write_text("\n".join(playlist), encoding="utf-8")

    def test_save_replay_merges_from_copied_request_folder(self):
        self._write_cache(["cache_000.ts", "cache_001.ts"])
        observed = {}

        def fake_run(cmd, **_kwargs):
            concat_path = Path(cmd[cmd.index("-i") + 1])
            copied_segments = sorted(concat_path.parent.glob("*.ts"))
            observed["concat_path"] = concat_path
            observed["concat_text"] = concat_path.read_text(encoding="utf-8")
            observed["copied_names"] = [path.name for path in copied_segments]
            observed["all_readonly"] = all(
                not (path.stat().st_mode & stat.S_IWRITE) for path in copied_segments
            )
            return subprocess.CompletedProcess(cmd, 0)

        with patch("client.custommodules.replay_recorder.core.subprocess.run", side_effect=fake_run):
            replay_path = self.recorder.save_replay("request-A")

        self.assertEqual(Path(replay_path).name, "replay_request-A.mp4")
        self.assertEqual(observed["concat_path"].parent.name, "request-A")
        self.assertIn("recordings/requests/request-A", observed["concat_text"].replace("\\", "/"))
        self.assertEqual(observed["copied_names"], ["000_cache_000.ts", "001_cache_001.ts"])
        self.assertTrue(observed["all_readonly"])
        self.assertFalse((Path(self.recorder.cache_dir) / "concat_list.txt").exists())
        self.assertFalse((Path(self.recorder.requests_dir) / "request-A").exists())

    def test_save_replay_cleans_request_folder_after_ffmpeg_failure(self):
        self._write_cache(["cache_000.ts"])

        with patch(
            "client.custommodules.replay_recorder.core.subprocess.run",
            return_value=subprocess.CompletedProcess(["ffmpeg"], 1),
        ):
            replay_path = self.recorder.save_replay("request-fail")

        self.assertIsNone(replay_path)
        self.assertFalse((Path(self.recorder.cache_dir) / "concat_list.txt").exists())
        self.assertFalse((Path(self.recorder.requests_dir) / "request-fail").exists())

    def test_save_replay_skips_segments_that_disappear_before_copy(self):
        self._write_cache(
            ["cache_000.ts", "cache_missing.ts"],
            existing_segments=["cache_000.ts"],
        )
        observed = {}

        def fake_run(cmd, **_kwargs):
            concat_path = Path(cmd[cmd.index("-i") + 1])
            observed["concat_text"] = concat_path.read_text(encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0)

        with patch("client.custommodules.replay_recorder.core.subprocess.run", side_effect=fake_run):
            replay_path = self.recorder.save_replay("request-skip")

        self.assertEqual(Path(replay_path).name, "replay_request-skip.mp4")
        self.assertIn("000_cache_000.ts", observed["concat_text"])
        self.assertNotIn("cache_missing.ts", observed["concat_text"])
        self.assertFalse((Path(self.recorder.requests_dir) / "request-skip").exists())

    def test_stop_requests_ffmpeg_quit_before_terminating(self):
        fake_process = _FakeFfmpegProcess()
        self.recorder._process = fake_process

        self.recorder.stop()

        self.assertEqual(fake_process.stdin.writes, [b"q\n"])
        self.assertTrue(fake_process.stdin.flushed)
        self.assertTrue(fake_process.stdin.closed)
        self.assertFalse(fake_process.terminated)
        self.assertFalse(fake_process.killed)
        self.assertIsNone(self.recorder._process)

    def test_stop_terminates_when_ffmpeg_ignores_quit(self):
        fake_process = _FakeFfmpegProcess(
            wait_side_effects=[
                subprocess.TimeoutExpired(["ffmpeg"], timeout=1.5),
                0,
            ]
        )
        self.recorder._process = fake_process

        self.recorder.stop()

        self.assertEqual(fake_process.stdin.writes, [b"q\n"])
        self.assertEqual(fake_process.wait_timeouts, [1.5, 2.0])
        self.assertTrue(fake_process.terminated)
        self.assertFalse(fake_process.killed)

    def test_stop_kills_when_ffmpeg_ignores_quit_and_terminate(self):
        fake_process = _FakeFfmpegProcess(
            wait_side_effects=[
                subprocess.TimeoutExpired(["ffmpeg"], timeout=1.5),
                subprocess.TimeoutExpired(["ffmpeg"], timeout=2.0),
                0,
            ]
        )
        self.recorder._process = fake_process

        self.recorder.stop()

        self.assertTrue(fake_process.terminated)
        self.assertTrue(fake_process.killed)
        self.assertEqual(fake_process.wait_timeouts, [1.5, 2.0, 2.0])

    def test_stop_returns_even_when_ffmpeg_ignores_kill(self):
        fake_process = _FakeFfmpegProcess(
            wait_side_effects=[
                subprocess.TimeoutExpired(["ffmpeg"], timeout=1.5),
                subprocess.TimeoutExpired(["ffmpeg"], timeout=2.0),
                subprocess.TimeoutExpired(["ffmpeg"], timeout=2.0),
            ]
        )
        self.recorder._process = fake_process

        self.recorder.stop()

        self.assertTrue(fake_process.terminated)
        self.assertTrue(fake_process.killed)
        self.assertIsNone(self.recorder._process)
        self.assertEqual(fake_process.wait_timeouts, [1.5, 2.0, 2.0])


if __name__ == "__main__":
    unittest.main()
