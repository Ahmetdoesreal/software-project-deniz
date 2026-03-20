import asyncio
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path


class TeeStream:
    def __init__(self, original_stream, log_stream):
        self.original_stream = original_stream
        self.log_stream = log_stream
        self.encoding = getattr(original_stream, "encoding", "utf-8")

    def write(self, data):
        if not data:
            return 0
        self.original_stream.write(data)
        self.log_stream.write(data)
        return len(data)

    def flush(self):
        self.original_stream.flush()
        self.log_stream.flush()

    def isatty(self):
        return getattr(self.original_stream, "isatty", lambda: False)()

    def fileno(self):
        return self.original_stream.fileno()


def _log_exception(prefix: str, exc_type, exc_value, exc_traceback):
    print(prefix, file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)


def setup_runtime_logging(
    process_name: str,
    log_dir: Path,
    *,
    capture_stdout: bool = True,
    capture_stderr: bool = True,
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{process_name}_{timestamp}.log"
    log_stream = open(log_path, "a", buffering=1, encoding="utf-8")

    if capture_stdout:
        sys.stdout = TeeStream(sys.stdout, log_stream)
    if capture_stderr:
        sys.stderr = TeeStream(sys.stderr, log_stream)

    def excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        _log_exception("[EXCEPTION] Unhandled exception", exc_type, exc_value, exc_traceback)

    def thread_excepthook(args):
        _log_exception(
            f"[EXCEPTION] Unhandled thread exception in {args.thread.name}",
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
        )

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook

    target_stream = sys.stdout if capture_stdout else sys.stderr
    print(f"[LOG] Writing runtime log to {log_path}", file=target_stream)
    return log_path


def install_asyncio_exception_logging(loop: asyncio.AbstractEventLoop):
    def handler(_loop, context):
        message = context.get("message", "Unhandled asyncio exception")
        print(f"[ASYNCIO] {message}", file=sys.stderr)

        exception = context.get("exception")
        if exception:
            traceback.print_exception(
                type(exception),
                exception,
                exception.__traceback__,
                file=sys.stderr,
            )

    loop.set_exception_handler(handler)
