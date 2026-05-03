"""
replay_recorder.py -- Screen recording module (runs on the client).

Continuously records the screen into rolling segments using FFmpeg.
When save_replay() is called, it stitches the last 60 seconds into a file.

Supports Windows (gdigrab) and Linux (x11grab).

Usage:
    recorder = ReplayRecorder()
    recorder.start()          # begins ffmpeg recording in background
    recorder.save_replay()    # saves the last ~60 seconds
    recorder.stop()           # stops ffmpeg & cleans up cache
"""

import os
import shutil
import stat
import subprocess
import sys
import time
import uuid


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

        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.requests_dir, exist_ok=True)

    @staticmethod
    def _safe_request_id(request_id: str | None) -> str:
        raw = str(request_id or uuid.uuid4().hex).strip()
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in raw)
        safe = safe.strip("._")
        return safe[:120] or uuid.uuid4().hex

    @staticmethod
    def _get_linux_screen_size() -> str:
        """Query X11 display resolution, fallback to 1920x1080."""
        try:
            output = subprocess.check_output(
                ["xdpyinfo"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for line in output.splitlines():
                if "dimensions:" in line:
                    return line.split()[1]
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        return "1920x1080"

    def _build_capture_args(self) -> list[str]:
        platform_name = sys.platform

        if platform_name == "win32":
            return ["-f", "gdigrab", "-framerate", "24", "-i", "desktop"]

        if platform_name == "darwin":
            return [
                "-f",
                "avfoundation",
                "-framerate",
                "30",
                "-capture_cursor",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-i",
                "Capture screen 0:none",
            ]

        if platform_name.startswith("linux"):
            screen_size = self._get_linux_screen_size()
            display = os.environ.get("DISPLAY", ":0.0")
            return [
                "-f",
                "x11grab",
                "-framerate",
                "24",
                "-video_size",
                screen_size,
                "-i",
                display,
            ]

        raise RuntimeError(f"Unsupported platform for screen capture: {platform_name}")

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

        cmd = [
            "ffmpeg",
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
            "1",
            os.path.join(self.cache_dir, "cache_%03d.ts"),
        ]

        self._log_path = os.path.join(self.cache_dir, "ffmpeg.log")

        try:
            log_file = open(self._log_path, "w")
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=log_file,
                stdin=subprocess.PIPE,
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
        except FileNotFoundError:
            print("[RECORDER] ERROR: FFmpeg not found in PATH.")
            self._running = False

    def save_replay(self, request_id: str | None = None):
        """Stitch cached segments into a replay file."""
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

            output_file = os.path.join(self.output_dir, f"replay_{safe_request_id}.mp4")
            concat_list_path = os.path.join(request_dir, "concat_list.txt")

            with open(concat_list_path, "w") as f:
                for seg in copied_segments:
                    f.write(f"file '{os.path.abspath(seg)}'\n")

            merge_cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list_path,
                "-c",
                "copy",
                output_file,
            ]

            result = subprocess.run(
                merge_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            print("[RECORDER] ERROR: FFmpeg timed out while stitching replay.")
            return None
        finally:
            self._remove_request_dir(request_dir)
        if result.returncode != 0:
            print("[RECORDER] ERROR: FFmpeg failed while stitching replay.")
            return None
        print(f"[RECORDER] Replay saved to: {output_file}")
        return output_file

    def _copy_segments_to_request_dir(self, segments: list[str], request_dir: str) -> list[str]:
        copied_segments = []
        for index, segment in enumerate(segments):
            source_path = segment if os.path.isabs(segment) else os.path.join(self.cache_dir, segment)
            if not os.path.isfile(source_path):
                print(f"[RECORDER] Skipping missing cache segment: {source_path}")
                continue

            dest_name = f"{index:03d}_{os.path.basename(source_path)}"
            dest_path = os.path.join(request_dir, dest_name)
            try:
                shutil.copy2(source_path, dest_path)
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

    @property
    def is_running(self):
        return self._running
