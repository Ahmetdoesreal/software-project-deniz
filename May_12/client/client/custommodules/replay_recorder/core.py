"""
replay_recorder.py -- Screen recording module (runs on the client).

Continuously records the Windows desktop into rolling segments using FFmpeg.
When save_replay() is called, it stitches recent MPEG-TS segments into a file.

Usage:
    recorder = ReplayRecorder()
    recorder.start()          # begins ffmpeg recording in background
    recorder.save_replay()    # saves recent MPEG-TS replay fragments
    recorder.stop()           # stops ffmpeg & cleans up cache
"""

import os
import shutil
import stat
import subprocess
import threading
import time
import uuid


FFMPEG_ENV_PATH = "EXAM_FFMPEG_PATH"
FFMPEG_QUIT_TIMEOUT_SECONDS = 1.5
FFMPEG_TERMINATE_TIMEOUT_SECONDS = 2.0
FFMPEG_KILL_TIMEOUT_SECONDS = 2.0


class ReplayRecorder:
    def __init__(self, session_uuid, base_dir="recordings", segment_time=5, total_duration=60):
        self.session_uuid = session_uuid
        self.base_dir = base_dir
        self.cache_dir = os.path.join("data", "client", session_uuid, base_dir, "cache")
        self.output_dir = os.path.join("data", "client", session_uuid, base_dir, "replays")
        self.requests_dir = os.path.join("data", "client", session_uuid, base_dir, "requests")
        self.segment_time = segment_time
        self.total_duration = total_duration
        self.max_segments = total_duration // segment_time
        self._process = None
        self._running = False
        self._log_file = None
        self._log_path = None
        self._save_lock = threading.Lock()

        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.requests_dir, exist_ok=True)

    @staticmethod
    def _safe_request_id(request_id: str | None) -> str:
        raw = str(request_id or uuid.uuid4().hex).strip()
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in raw)
        safe = safe.strip("._")
        return safe[:120] or uuid.uuid4().hex

    def _build_capture_args(self) -> list[str]:
        return ["-f", "gdigrab", "-framerate", "24", "-i", "desktop"]

    @classmethod
    def _resolve_ffmpeg_executable(cls) -> str | None:
        candidates: list[str] = []
        configured_path = os.environ.get(FFMPEG_ENV_PATH, "").strip().strip('"')
        if configured_path:
            if os.path.isdir(configured_path):
                candidates.append(os.path.join(configured_path, "ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
            else:
                candidates.append(configured_path)

        candidates.extend(cls._bundled_ffmpeg_paths())

        path_ffmpeg = shutil.which("ffmpeg")
        if path_ffmpeg:
            candidates.append(path_ffmpeg)

        for candidate in candidates:
            if not candidate:
                continue
            resolved = shutil.which(candidate) or candidate
            if os.path.isfile(resolved):
                return resolved
        return None

    @staticmethod
    def _bundled_ffmpeg_paths() -> list[str]:
        module_dir = os.path.dirname(__file__)
        bundle_root = os.path.abspath(os.path.join(module_dir, "..", "..", ".."))
        executable = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        return [
            os.path.join(bundle_root, "offline-packages", "ffmpeg", "bin", executable),
        ]

    @staticmethod
    def _ffmpeg_creation_flags() -> int:
        return (
            int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            | int(getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0))
        )

    def start(self):
        """Start FFmpeg screen recording in the background."""
        if self._running:
            print("[RECORDER] Already running.")
            return

        self._cleanup_cache()

        try:
            capture_args = self._build_capture_args()
        except RuntimeError as e:
            print(f"[RECORDER] ERROR: {e}")
            return

        ffmpeg_executable = self._resolve_ffmpeg_executable()
        if not ffmpeg_executable:
            print(
                "[RECORDER] ERROR: FFmpeg not found. Set "
                f"{FFMPEG_ENV_PATH}, install the bundled setup assets, or add ffmpeg to PATH."
            )
            return

        cmd = [
            ffmpeg_executable,
            "-y",
            *capture_args,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-x264opts",
            f"keyint={24 * self.segment_time}:min-keyint={24 * self.segment_time}",
            "-f",
            "segment",
            "-segment_time",
            str(self.segment_time),
            "-segment_list",
            os.path.join(self.cache_dir, "replay.m3u8"),
            "-segment_list_size",
            str(self.max_segments),
            "-segment_wrap",
            str(self.max_segments + 2),
            "-segment_format",
            "mpegts",
            "-reset_timestamps",
            "0",
            os.path.join(self.cache_dir, "cache_%03d.ts"),
        ]

        self._log_path = os.path.join(self.cache_dir, "ffmpeg.log")

        log_file = None
        try:
            log_file = open(self._log_path, "w")
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=log_file,
                stdin=subprocess.PIPE,
                creationflags=self._ffmpeg_creation_flags(),
            )
            self._log_file = log_file
            self._running = True
            print("[RECORDER] Started FFmpeg screen recording.")

            time.sleep(1)
            if self._process.poll() is not None:
                self._running = False
                self._process = None
                self._log_file.close()
                self._log_file = None
                print("[RECORDER] ERROR: FFmpeg exited immediately.")
        except OSError as e:
            if log_file:
                log_file.close()
            print(f"[RECORDER] ERROR: Could not start FFmpeg: {e}")
            self._running = False

    def save_replay(self, request_id: str | None = None):
        """Stitch cached segments into a replay file."""
        with self._save_lock:
            return self._save_replay_locked(request_id)

    def _save_replay_locked(self, request_id: str | None = None):
        if not self._running:
            print("[RECORDER] Not running, nothing to save.")
            return None

        if self._process and self._process.poll() is not None:
            print("[RECORDER] FFmpeg process has died. Cannot save replay.")
            self._running = False
            return None

        m3u8_path = os.path.join(self.cache_dir, "replay.m3u8")
        if not os.path.exists(m3u8_path):
            print("[RECORDER] No segments found yet. Wait a few seconds.")
            return None

        segments = []
        with open(m3u8_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    segments.append(line)

        if not segments:
            print("[RECORDER] No segments available to save.")
            return None

        safe_request_id = self._safe_request_id(request_id)
        request_dir = os.path.join(self.requests_dir, safe_request_id)
        self._remove_request_dir(request_dir)
        os.makedirs(request_dir, exist_ok=True)
        try:
            copied_segments = self._copy_segments_to_request_dir(segments, request_dir)
            if not copied_segments:
                print("[RECORDER] No complete segments could be copied for replay save.")
                return None

            output_file = self._replay_output_path(safe_request_id)
            temp_output_file = os.path.join(request_dir, f"replay_{safe_request_id}.partial.ts")
            replay_path = self._write_ts_replay(copied_segments, temp_output_file, output_file)
        finally:
            self._remove_request_dir(request_dir)
        return replay_path

    def _replay_output_path(self, safe_request_id: str) -> str:
        preferred_path = os.path.join(self.output_dir, f"replay_{safe_request_id}.ts")
        if not os.path.exists(preferred_path):
            return preferred_path

        while True:
            candidate = os.path.join(self.output_dir, f"replay_{safe_request_id}_{time.time_ns()}.ts")
            if not os.path.exists(candidate):
                return candidate

    def _write_ts_replay(self, copied_segments: list[str], temp_output_file: str, output_file: str) -> str | None:
        try:
            with open(temp_output_file, "wb") as output:
                for segment in copied_segments:
                    with open(segment, "rb") as source:
                        shutil.copyfileobj(source, output)
            os.replace(temp_output_file, output_file)
        except OSError as e:
            self._remove_file(temp_output_file)
            print(f"[RECORDER] ERROR: Could not write TS replay: {e}")
            return None

        print(f"[RECORDER] Replay saved to: {output_file}")
        return output_file

    @staticmethod
    def _segment_signature(path: str) -> tuple[int, int] | None:
        try:
            info = os.stat(path)
        except OSError:
            return None
        if info.st_size <= 0:
            return None
        return info.st_size, getattr(info, "st_mtime_ns", int(info.st_mtime * 1_000_000_000))

    def _copy_segments_to_request_dir(self, segments: list[str], request_dir: str) -> list[str]:
        copied_segments = []
        for index, segment in enumerate(segments):
            source_path = segment if os.path.isabs(segment) else os.path.join(self.cache_dir, segment)
            before_signature = self._segment_signature(source_path)
            if before_signature is None:
                print(f"[RECORDER] Skipping missing cache segment: {source_path}")
                continue

            dest_name = f"{index:03d}_{os.path.basename(source_path)}"
            dest_path = os.path.join(request_dir, dest_name)
            try:
                shutil.copy2(source_path, dest_path)
                after_signature = self._segment_signature(source_path)
                if after_signature != before_signature or os.path.getsize(dest_path) != before_signature[0]:
                    self._remove_file(dest_path)
                    print(f"[RECORDER] Skipping changing cache segment: {source_path}")
                    continue
                os.chmod(dest_path, stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
            except OSError as e:
                print(f"[RECORDER] Error copying cache segment {source_path}: {e}")
                continue
            copied_segments.append(dest_path)
        return copied_segments

    def stop(self):
        """Stop FFmpeg and clean up cache."""
        if self._process:
            self._stop_ffmpeg_process(self._process)
            self._process = None
        if self._log_file:
            self._log_file.close()
            self._log_file = None
        self._running = False
        self._cleanup_cache()
        print("[RECORDER] Stopped.")

    def _stop_ffmpeg_process(self, process):
        if process.poll() is not None:
            return

        if self._request_ffmpeg_quit(process):
            if self._wait_for_process(process, FFMPEG_QUIT_TIMEOUT_SECONDS):
                return
            print("[RECORDER] FFmpeg did not exit after quit request; terminating it.")

        try:
            process.terminate()
        except OSError as e:
            print(f"[RECORDER] FFmpeg terminate request failed: {e}")
        if self._wait_for_process(process, FFMPEG_TERMINATE_TIMEOUT_SECONDS):
            return

        print("[RECORDER] FFmpeg did not exit after terminate; killing it.")
        try:
            process.kill()
        except OSError as e:
            print(f"[RECORDER] FFmpeg kill request failed: {e}")
            return

        if not self._wait_for_process(process, FFMPEG_KILL_TIMEOUT_SECONDS):
            print("[RECORDER] FFmpeg did not exit after kill request.")

    @staticmethod
    def _wait_for_process(process, timeout_seconds: float) -> bool:
        try:
            process.wait(timeout=timeout_seconds)
            return True
        except subprocess.TimeoutExpired:
            return False
        except OSError as e:
            print(f"[RECORDER] FFmpeg wait failed: {e}")
            return True

    @staticmethod
    def _request_ffmpeg_quit(process) -> bool:
        stdin = getattr(process, "stdin", None)
        if stdin is None:
            return False

        try:
            stdin.write(b"q\n")
            stdin.flush()
            stdin.close()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def _cleanup_cache(self):
        for filename in os.listdir(self.cache_dir):
            file_path = os.path.join(self.cache_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"[RECORDER] Error deleting {file_path}: {e}")

    @staticmethod
    def _handle_rmtree_error(func, path, _exc_info):
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            func(path)
        except Exception as e:
            print(f"[RECORDER] Error deleting request cache {path}: {e}")

    def _remove_request_dir(self, request_dir: str):
        if os.path.isdir(request_dir):
            shutil.rmtree(request_dir, onerror=self._handle_rmtree_error)

    @staticmethod
    def _remove_file(path: str):
        try:
            if path and os.path.isfile(path):
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
                os.remove(path)
        except OSError as e:
            print(f"[RECORDER] Error deleting partial replay {path}: {e}")

    @property
    def is_running(self):
        return self._running
