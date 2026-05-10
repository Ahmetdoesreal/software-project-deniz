# LLM Implementation Notes

## Current Validation Notes

- The previous baseline failure in `tests.unit.test_client_incident_reporting` was fixed by making incident-buffer access tolerant of test-created `WebSocketSession.__new__` instances.
- New local IPC tests cover:
  - envelope fields
  - transport selection
  - loopback peer guard
  - missing token rejection
  - client-to-server and server-to-client WebSocket roundtrips
  - manager/dashboard/timer channel roundtrips using threaded wrappers

## Important Compatibility Detail

Do not delete stdin/stdout code paths yet. Managed process stdout is still used for log capture, and manual terminal operation still depends on stdin command support.

## Likely Future Integration Points

- Add structured `process.lifecycle` messages for child started/ready/exited.
- Add request/reply helpers using `reply_to` and `seq`.
- Add a higher-level command registry instead of passing legacy dashboard payloads as `data`.
- Consider replacing polling labels in manager consoles with local IPC health messages while keeping log files as source of truth.
