"""
replay_recorder.py -- Screen recording module (runs on the client).

Continuously records the screen into rolling segments using FFmpeg.
When save_replay() is called, it stitches the last 60 seconds into a file.

Usage:
    recorder = ReplayRecorder()
    recorder.start()          # begins ffmpeg recording in background
    recorder.save_replay()    # saves the last ~60 seconds
    recorder.stop()           # stops ffmpeg & cleans up cache
"""

import subprocess
import os
import time


class ReplayRecorder:
    def __init__(self, session_uuid, base_dir="recordings",
                 segment_time=5, total_duration=60):
        self.session_uuid = session_uuid
        self.base_dir = base_dir
        self.cache_dir = os.path.join(session_uuid, base_dir, "cache")
        self.output_dir = os.path.join(session_uuid, base_dir, "replays")
        self.segment_time = segment_time
        self.total_duration = total_duration
        self.max_segments = total_duration // segment_time
        self._process = None
        self._running = False

        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def start(self):
        """Start FFmpeg screen recording in the background."""
        if self._running:
            print("[RECORDER] Already running.")
            return

        self._cleanup_cache()

        cmd = [
            "ffmpeg", "-y",
            "-f", "gdigrab",
            "-framerate", "24",
            "-i", "desktop",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-g", str(24 * self.segment_time),
            "-force_key_frames", f"expr:gte(t,n_forced*{self.segment_time})",
            "-f", "segment",
            "-segment_time", str(self.segment_time),
            "-segment_list", os.path.join(self.cache_dir, "replay.m3u8"),
            "-segment_list_size", str(self.max_segments),
            "-segment_wrap", str(self.max_segments + 2),
            "-segment_format", "mpegts",
            os.path.join(self.cache_dir, "cache_%03d.ts")
        ]

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            self._running = True
            print("[RECORDER] Started FFmpeg screen recording.")
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
