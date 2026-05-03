"""
replay_recorder.py -- Screen recording module (runs on the client).

Continuously records the Windows desktop into rolling segments using FFmpeg.
When save_replay() is called, it stitches the last 60 seconds into a file.

Usage:
    recorder = ReplayRecorder()
    recorder.start()          # begins ffmpeg recording in background
    recorder.save_replay()    # saves the last ~60 seconds
    recorder.stop()           # stops ffmpeg & cleans up cache
"""

import os
import shutil
import stat
import struct
import subprocess
import time
import uuid


FFMPEG_MERGE_TIMEOUT_SECONDS = 30
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

    def _build_capture_args(self) -> list[str]:
        return ["-f", "gdigrab", "-framerate", "24", "-i", "desktop"]

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
            temp_output_file = os.path.join(request_dir, f"replay_{safe_request_id}.partial.mp4")
            fallback_output_file = os.path.join(self.output_dir, f"replay_{safe_request_id}.ts")
            fallback_temp_file = os.path.join(request_dir, f"replay_{safe_request_id}.partial.ts")
            merge_log_path = os.path.join(self.output_dir, f"replay_{safe_request_id}.ffmpeg.log")
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
                temp_output_file,
            ]

            try:
                with open(merge_log_path, "w", encoding="utf-8", errors="replace") as merge_log:
                    result = subprocess.run(
                        merge_cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=merge_log,
                        timeout=FFMPEG_MERGE_TIMEOUT_SECONDS,
                    )
            except subprocess.TimeoutExpired:
                self._remove_file(temp_output_file)
                print("[RECORDER] ERROR: FFmpeg timed out while stitching replay.")
                return self._save_ts_fallback(copied_segments, fallback_temp_file, fallback_output_file)

            if result.returncode != 0:
                self._remove_file(temp_output_file)
                print("[RECORDER] ERROR: FFmpeg failed while stitching replay.")
                return self._save_ts_fallback(copied_segments, fallback_temp_file, fallback_output_file)

            if not self._mp4_has_moov(temp_output_file):
                self._remove_file(temp_output_file)
                print("[RECORDER] ERROR: FFmpeg wrote an incomplete MP4 without a moov atom.")
                return self._save_ts_fallback(copied_segments, fallback_temp_file, fallback_output_file)

            os.replace(temp_output_file, output_file)
            self._remove_file(merge_log_path)
        except subprocess.TimeoutExpired:
            print("[RECORDER] ERROR: FFmpeg timed out while stitching replay.")
            return None
        finally:
            self._remove_request_dir(request_dir)
        print(f"[RECORDER] Replay saved to: {output_file}")
        return output_file

    def _save_ts_fallback(self, copied_segments: list[str], temp_output_file: str, output_file: str) -> str | None:
        try:
            with open(temp_output_file, "wb") as output:
                for segment in copied_segments:
                    with open(segment, "rb") as source:
                        shutil.copyfileobj(source, output)
            os.replace(temp_output_file, output_file)
        except OSError as e:
            self._remove_file(temp_output_file)
            print(f"[RECORDER] ERROR: Could not write fallback TS replay: {e}")
            return None

        print(f"[RECORDER] Replay saved as MPEG-TS fallback to: {output_file}")
        return output_file

    @staticmethod
    def _mp4_has_moov(path: str) -> bool:
        try:
            file_size = os.path.getsize(path)
            with open(path, "rb") as mp4_file:
                position = 0
                while position + 8 <= file_size:
                    header = mp4_file.read(8)
                    if len(header) < 8:
                        return False
                    atom_size, atom_type = struct.unpack(">I4s", header)
                    header_size = 8
                    if atom_size == 1:
                        extended = mp4_file.read(8)
                        if len(extended) < 8:
                            return False
                        atom_size = struct.unpack(">Q", extended)[0]
                        header_size = 16
                    elif atom_size == 0:
                        atom_size = file_size - position
                    if atom_type == b"moov":
                        return True
                    if atom_size < header_size:
                        return False
                    position += atom_size
                    mp4_file.seek(position)
        except OSError:
            return False
        return False

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
