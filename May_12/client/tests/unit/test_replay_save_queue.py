import asyncio
import threading
import time
import unittest

from client.ws_client import ReplaySaveQueue, ReplaySaveRequest, WebSocketSession


def _window_id(second: int) -> str:
    return f"window_20260502T1000{second:02d}Z"


def _requested_at(second: int) -> str:
    return f"2026-05-02T10:00:{second:02d}+00:00"


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
        return f"{request_id}.ts"


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
        if not self.started.is_set():
            self.started.set()
            self.release.wait(timeout=2)
        with self.lock:
            self.active -= 1
        return f"{request_id}.ts"


class ReplaySaveQueueTests(unittest.TestCase):
    def test_queue_processes_fifo_without_parallel_recorder_calls(self):
        async def run_scenario():
            recorder = _FakeRecorder()
            queue = ReplaySaveQueue(recorder, asyncio.get_running_loop())
            try:
                futures = [
                    queue.enqueue(request_id=request_id, requested_at=requested_at, source="test")[1]
                    for request_id, requested_at in [
                        ("one", _requested_at(0)),
                        ("two", _requested_at(5)),
                        ("three", _requested_at(10)),
                    ]
                ]
                results = await asyncio.gather(*futures)
            finally:
                queue.close()
                await asyncio.sleep(0)
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, [_window_id(0), _window_id(5), _window_id(10)])
        self.assertEqual(recorder.max_active, 1)
        self.assertEqual(results, [f"{_window_id(0)}.ts", f"{_window_id(5)}.ts", f"{_window_id(10)}.ts"])

    def test_same_window_requests_share_one_replay_save(self):
        async def run_scenario():
            recorder = _FakeRecorder(delay=0.03)
            queue = ReplaySaveQueue(recorder, asyncio.get_running_loop())
            try:
                futures = [
                    queue.enqueue(request_id=request_id, requested_at=_requested_at(second), source="incident_evidence")[1]
                    for request_id, second in [("one", 0), ("two", 1), ("three", 4)]
                ]
                results = await asyncio.gather(*futures)
            finally:
                await queue.aclose()
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, [_window_id(0)])
        self.assertEqual(results, [f"{_window_id(0)}.ts"] * 3)

    def test_final_submission_drops_queued_and_future_optional_saves(self):
        async def run_scenario():
            recorder = _GateRecorder()
            loop = asyncio.get_running_loop()
            queue = ReplaySaveQueue(recorder, loop)
            try:
                slow = queue.enqueue(request_id="slow", requested_at=_requested_at(0), source="admin_cli")[1]
                await loop.run_in_executor(None, recorder.started.wait, 1)
                queued_optional = queue.enqueue(request_id="optional", requested_at=_requested_at(5), source="admin_cli")[1]
                final = queue.enqueue(request_id="final", source="final_submission")[1]
                late_optional = queue.enqueue(request_id="late", requested_at=_requested_at(10), source="admin_cli")[1]
                recorder.release.set()
                results = await asyncio.gather(slow, final, queued_optional, late_optional)
            finally:
                await queue.aclose()
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, [_window_id(0), "final"])
        self.assertEqual(recorder.max_active, 1)
        self.assertEqual(results, [f"{_window_id(0)}.ts", "final.ts", None, None])

    def test_optional_saves_drop_when_queue_is_full(self):
        async def run_scenario():
            recorder = _FakeRecorder(delay=0)
            queue = ReplaySaveQueue(recorder, asyncio.get_running_loop(), optional_queue_limit=2)
            try:
                futures = [
                    queue.enqueue(request_id=request_id, requested_at=_requested_at(second), source="admin_cli")[1]
                    for request_id, second in [("one", 0), ("two", 5), ("three", 10)]
                ]
                results = await asyncio.gather(*futures)
            finally:
                await queue.aclose()
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, [_window_id(0), _window_id(5)])
        self.assertEqual(results, [f"{_window_id(0)}.ts", f"{_window_id(5)}.ts", None])

    def test_incident_replay_queue_is_bounded(self):
        async def run_scenario():
            recorder = _GateRecorder()
            loop = asyncio.get_running_loop()
            queue = ReplaySaveQueue(recorder, loop, incident_queue_limit=1)
            try:
                slow = queue.enqueue(request_id="slow", requested_at=_requested_at(0), source="incident_evidence")[1]
                await loop.run_in_executor(None, recorder.started.wait, 1)
                queued = queue.enqueue(request_id="queued", requested_at=_requested_at(5), source="incident_evidence")[1]
                overflow = queue.enqueue(request_id="overflow", requested_at=_requested_at(10), source="incident_evidence")[1]
                recorder.release.set()
                results = await asyncio.gather(slow, queued, overflow)
            finally:
                await queue.aclose()
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, [_window_id(0), _window_id(5)])
        self.assertEqual(recorder.max_active, 1)
        self.assertEqual(results, [f"{_window_id(0)}.ts", f"{_window_id(5)}.ts", None])

    def test_final_submission_drops_queued_and_future_incident_replays(self):
        async def run_scenario():
            recorder = _GateRecorder()
            loop = asyncio.get_running_loop()
            queue = ReplaySaveQueue(recorder, loop)
            try:
                slow = queue.enqueue(request_id="slow", requested_at=_requested_at(0), source="admin_cli")[1]
                await loop.run_in_executor(None, recorder.started.wait, 1)
                queued_incident = queue.enqueue(request_id="incident", requested_at=_requested_at(5), source="incident_evidence")[1]
                final = queue.enqueue(request_id="final", source="final_submission")[1]
                late_incident = queue.enqueue(request_id="late-incident", requested_at=_requested_at(10), source="incident_evidence")[1]
                recorder.release.set()
                results = await asyncio.gather(slow, final, queued_incident, late_incident)
            finally:
                await queue.aclose()
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, [_window_id(0), "final"])
        self.assertEqual(recorder.max_active, 1)
        self.assertEqual(results, [f"{_window_id(0)}.ts", "final.ts", None, None])

    def test_expired_queued_save_does_not_call_recorder(self):
        async def run_scenario():
            recorder = _GateRecorder()
            loop = asyncio.get_running_loop()
            queue = ReplaySaveQueue(recorder, loop)
            try:
                slow = queue.enqueue(request_id="slow", requested_at=_requested_at(0), source="admin_cli")[1]
                await loop.run_in_executor(None, recorder.started.wait, 1)
                expired = queue.enqueue(
                    request_id="expired",
                    requested_at=_requested_at(5),
                    source="admin_cli",
                    deadline_seconds=-0.01,
                )[1]
                recorder.release.set()
                results = await asyncio.gather(slow, expired)
            finally:
                await queue.aclose()
            return recorder, results

        recorder, results = asyncio.run(run_scenario())

        self.assertEqual(recorder.calls, [_window_id(0)])
        self.assertEqual(results, [f"{_window_id(0)}.ts", None])

    def test_close_does_not_leave_pending_futures_unresolved(self):
        async def run_scenario():
            recorder = _FakeRecorder(delay=0)
            queue = ReplaySaveQueue(recorder, asyncio.get_running_loop())
            futures = [
                queue.enqueue(request_id=request_id, requested_at=_requested_at(second), source="admin_cli")[1]
                for request_id, second in [("one", 0), ("two", 5), ("three", 10)]
            ]
            queue.close()
            await asyncio.sleep(0)
            return futures

        futures = asyncio.run(run_scenario())

        self.assertTrue(all(future.done() for future in futures))

    def test_requested_replay_uploads_are_shared_by_save_id(self):
        async def run_scenario():
            session = object.__new__(WebSocketSession)
            session._uploaded_requested_replays = {}
            session._requested_replay_upload_tasks = {}
            calls = []

            async def fake_upload(artifact_path: str, *, artifact_kind: str, metadata: dict | None = None):
                calls.append((artifact_path, artifact_kind, metadata))
                await asyncio.sleep(0.01)
                return "server/replay.ts"

            session._upload_runtime_artifact = fake_upload
            loop = asyncio.get_running_loop()
            requests = [
                ReplaySaveRequest(
                    request_id=request_id,
                    save_id="window_20260502T100000Z",
                    requested_at=_requested_at(0),
                    source="server_request",
                    future=loop.create_future(),
                    priority=2,
                    deadline_at=None,
                    optional=True,
                )
                for request_id in ("one", "two", "three")
            ]
            results = await asyncio.gather(
                *[
                    WebSocketSession._upload_requested_replay(session, "replay_window_20260502T100000Z.ts", request)
                    for request in requests
                ]
            )
            cached = await WebSocketSession._upload_requested_replay(
                session,
                "replay_window_20260502T100000Z.ts",
                requests[0],
            )
            return calls, results, cached

        calls, results, cached = asyncio.run(run_scenario())

        self.assertEqual(len(calls), 1)
        self.assertEqual(results, ["server/replay.ts"] * 3)
        self.assertEqual(cached, "server/replay.ts")


if __name__ == "__main__":
    unittest.main()
