"""
replay_recorder.py -- Screen recording module (runs on the client).

Continuously records the screen into rolling segments using FFmpeg.
When save_replay() is called, it stitches the last 60 seconds into a file.

Supports Windows (gdigrab), macOS (avfoundation), and Linux (x11grab).

Usage:
    recorder = ReplayRecorder()
    recorder.start()          # begins ffmpeg recording in background
    recorder.save_replay()    # saves the last ~60 seconds
    recorder.stop()           # stops ffmpeg & cleans up cache
"""

import subprocess
import os
import re
import sys
import time


class ReplayRecorder:
    def __init__(self, session_uuid, base_dir="recordings",
                 segment_time=5, total_duration=60):
        self.session_uuid = session_uuid
        self.base_dir = base_dir
        self.cache_dir = os.path.join("data", "client", session_uuid, base_dir, "cache")
        self.output_dir = os.path.join("data", "client", session_uuid, base_dir, "replays")
        self.segment_time = segment_time
        self.total_duration = total_duration
        self.max_segments = total_duration // segment_time
        self._process = None
        self._running = False

        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    # -- Platform-specific FFmpeg capture args -----------------------------

    @staticmethod
    def _get_linux_screen_size() -> str:
        """Query X11 display resolution, fallback to 1920x1080."""
        try:
            output = subprocess.check_output(
                ["xdpyinfo"], stderr=subprocess.DEVNULL, text=True
            )
            for line in output.splitlines():
                if "dimensions:" in line:
                    # e.g. "  dimensions:    1920x1080 pixels (...)"
                    return line.split()[1]
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass
        return "1920x1080"

    def _build_capture_args(self) -> list[str]:
        """
        Return the platform-specific FFmpeg input flags for screen capture.
        Raises RuntimeError if the platform is unsupported.
        """
        platform = sys.platform

        if platform == "win32":
            return ["-f", "gdigrab", "-framerate", "24", "-i", "desktop"]

        elif platform == "darwin":
            return [
                "-f", "avfoundation",
                "-framerate", "30",
                "-capture_cursor", "1",
                "-pix_fmt", "yuv420p",
                "-i", "Capture screen 0:none",
            ]

        elif platform.startswith("linux"):
            screen_size = self._get_linux_screen_size()
            display = os.environ.get("DISPLAY", ":0.0")
            return [
                "-f", "x11grab",
                "-framerate", "24",
                "-video_size", screen_size,
                "-i", display,
            ]

        else:
            raise RuntimeError(f"Unsupported platform for screen capture: {platform}")

    # -- Public API --------------------------------------------------------

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
            "ffmpeg", "-y",
            *capture_args,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            # Force a keyframe exactly every N frames to allow the segmenter to split
            "-x264opts", f"keyint={24 * self.segment_time}:min-keyint={24 * self.segment_time}",
            "-f", "segment",
            "-segment_time", str(self.segment_time),
            "-segment_list", os.path.join(self.cache_dir, "replay.m3u8"),
            "-segment_list_size", str(self.max_segments),
            "-segment_wrap", str(self.max_segments + 2),
            "-segment_format", "mpegts",
            "-reset_timestamps", "1",
            os.path.join(self.cache_dir, "cache_%03d.ts")
        ]

        # Write stderr to a log file so failures aren't silent
        self._log_path = os.path.join(self.cache_dir, "ffmpeg.log")

        try:
            log_file = open(self._log_path, "w")
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=log_file,
                # Detach from terminal to avoid tty suspension issues
                stdin=subprocess.DEVNULL,
            )
            self._log_file = log_file
            self._running = True
            print("[RECORDER] Started FFmpeg screen recording.")

            # Quick check: did FFmpeg die immediately?
            time.sleep(1)
            if self._process.poll() is not None:
                log_file.close()
                self._running = False
                with open(self._log_path, "r") as f:
                    tail = "(no output)"
                    if err:
                        # Show last 3 lines of error
                        tail = "\n".join(err[-3:])
                print(f"[RECORDER] ERROR: FFmpeg exited immediately:\n{tail}")
                self._process = None
        except FileNotFoundError:
            print("[RECORDER] ERROR: FFmpeg not found in PATH.")
            self._running = False

    def save_replay(self):
        """
        Stitch cached segments into a replay file.
        Returns the output file path, or None on failure.
        """
        if not self._running:
            print("[RECORDER] Not running, nothing to save.")
            return None

        # Check if FFmpeg is still alive
        if self._process and self._process.poll() is not None:
            print("[RECORDER] FFmpeg process has died. Cannot save replay.")
            self._running = False
            return None

        m3u8_path = os.path.join(self.cache_dir, "replay.m3u8")
        if not os.path.exists(m3u8_path):
            print("[RECORDER] No segments found yet. Wait a few seconds.")
            return None

        # Parse m3u8 to get current segments
        segments = []
        with open(m3u8_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    segments.append(os.path.join(self.cache_dir, line))

        if not segments:
            print("[RECORDER] No segments available to save.")
            return None

        # Build concat list
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(self.output_dir, f"replay_{timestamp}.mp4")
        concat_list_path = os.path.join(self.cache_dir, "concat_list.txt")

        with open(concat_list_path, "w") as f:
            for seg in segments:
                f.write(f"file '{os.path.abspath(seg)}'\n")

        merge_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            output_file
        ]

        subprocess.run(merge_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[RECORDER] Replay saved to: {output_file}")
        return output_file

    def stop(self):
        """Stop FFmpeg and clean up cache."""
        if self._process:
            self._process.terminate()
            self._process.wait()
            self._process = None
        if hasattr(self, '_log_file') and self._log_file:
            self._log_file.close()
            self._log_file = None
        self._running = False
        self._cleanup_cache()
        print("[RECORDER] Stopped.")

    def _cleanup_cache(self):
        """Remove all files in the cache directory."""
        for filename in os.listdir(self.cache_dir):
            file_path = os.path.join(self.cache_dir, filename)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
            except Exception as e:
                print(f"[RECORDER] Error deleting {file_path}: {e}")

    @property
    def is_running(self):
        return self._running
