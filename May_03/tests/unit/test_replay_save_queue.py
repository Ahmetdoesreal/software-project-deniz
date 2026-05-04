import asyncio
import threading
import time
import unittest

from client.ws_client import ReplaySaveQueue


class _FakeRecorder:
    def __init__(self, *, delay: float = 0.02):
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        self.delay = delay

    def save_replay(self, request_id: str | None = None):
        with self.lock:
            self.calls.append(str(request_id))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return f"{request_id}.mp4"


class _GateRecorder(_FakeRecorder):
    def __init__(self):
        super().__init__(delay=0)
        self.started = threading.Event()
        self.release = threading.Event()

    def save_replay(self, request_id: str | None = None):
        request_id = str(request_id)
        with self.lock:
            self.calls.append(request_id)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        if request_id == "slow":
            self.started.set()
            self.release.wait(timeout=2)
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

    def test_final_submission_bypasses_queued_optional_saves(self):
        async def run_scenario():
            recorder = _GateRecorder()
            loop = asyncio.get_running_loop()
            queue = ReplaySaveQueue(recorder, loop)
            try:
                slow = queue.enqueue(request_id="slow", source="admin_cli")[1]
                await loop.run_in_executor(None, recorder.started.wait, 1)
                optional = queue.enqueue(request_id="optional", source="admin_cli")[1]
                final = queue.enqueue(request_id="final", source="final_submission")[1]
                recorder.release.set()
                results = await asyncio.gather(slow, final, optional)
            finally:
                await queue.aclose()
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, ["slow", "final", "optional"])
        self.assertEqual(recorder.max_active, 1)
        self.assertEqual(results, ["slow.mp4", "final.mp4", "optional.mp4"])

    def test_optional_saves_drop_when_queue_is_full(self):
        async def run_scenario():
            recorder = _FakeRecorder(delay=0)
            queue = ReplaySaveQueue(recorder, asyncio.get_running_loop(), optional_queue_limit=2)
            try:
                futures = [
                    queue.enqueue(request_id=request_id, source="admin_cli")[1]
                    for request_id in ["one", "two", "three"]
                ]
                results = await asyncio.gather(*futures)
            finally:
                await queue.aclose()
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, ["one", "two"])
        self.assertEqual(results, ["one.mp4", "two.mp4", None])

    def test_expired_queued_save_does_not_call_recorder(self):
        async def run_scenario():
            recorder = _GateRecorder()
            loop = asyncio.get_running_loop()
            queue = ReplaySaveQueue(recorder, loop)
            try:
                slow = queue.enqueue(request_id="slow", source="admin_cli")[1]
                await loop.run_in_executor(None, recorder.started.wait, 1)
                expired = queue.enqueue(
                    request_id="expired",
                    source="admin_cli",
                    deadline_seconds=-0.01,
                )[1]
                recorder.release.set()
                results = await asyncio.gather(slow, expired)
            finally:
                await queue.aclose()
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, ["slow"])
        self.assertEqual(results, ["slow.mp4", None])

    def test_close_does_not_leave_pending_futures_unresolved(self):
        async def run_scenario():
            recorder = _FakeRecorder(delay=0)
            queue = ReplaySaveQueue(recorder, asyncio.get_running_loop())
            futures = [
                queue.enqueue(request_id=request_id, source="admin_cli")[1]
                for request_id in ["one", "two", "three"]
            ]
            queue.close()
            await asyncio.sleep(0)
            return futures

        futures = asyncio.run(run_scenario())

        self.assertTrue(all(future.done() for future in futures))


if __name__ == "__main__":
    unittest.main()
