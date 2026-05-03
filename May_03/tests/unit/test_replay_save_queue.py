import asyncio
import threading
import time
import unittest

from client.ws_client import ReplaySaveQueue


class _FakeRecorder:
    def __init__(self):
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def save_replay(self, request_id: str | None = None):
        with self.lock:
            self.calls.append(str(request_id))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.02)
        with self.lock:
            self.active -= 1
        return f"{request_id}.mp4"


class ReplaySaveQueueTests(unittest.TestCase):
    def test_queue_processes_fifo_without_parallel_recorder_calls(self):
        async def run_scenario():
            recorder = _FakeRecorder()
            queue = ReplaySaveQueue(recorder, asyncio.get_running_loop())
            try:
                futures = [
                    queue.enqueue(request_id=request_id, requested_at="2026-05-02T10:00:00+00:00", source="test")[1]
                    for request_id in ["one", "two", "three"]
                ]
                results = await asyncio.gather(*futures)
            finally:
                queue.close()
                await asyncio.sleep(0)
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, ["one", "two", "three"])
        self.assertEqual(recorder.max_active, 1)
        self.assertEqual(results, ["one.mp4", "two.mp4", "three.mp4"])


if __name__ == "__main__":
    unittest.main()
