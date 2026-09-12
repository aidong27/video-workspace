from __future__ import annotations

from dataclasses import dataclass
import os
import signal
import subprocess
from threading import Lock, Thread
import time
from typing import Any, BinaryIO, Mapping, Sequence


DEFAULT_OUTPUT_LIMIT = 16 * 1024
DEFAULT_TERMINATE_GRACE_SECONDS = 3.0


class LimitedStreamCapture:
    """Drain a pipe continuously while retaining only a bounded prefix."""

    def __init__(self, stream: BinaryIO | None, limit: int = DEFAULT_OUTPUT_LIMIT) -> None:
        self.stream = stream
        self.limit = max(0, limit)
        self._buffer = bytearray()
        self._discarded = 0
        self._lock = Lock()
        self._thread = Thread(target=self._drain, name="bounded-process-output", daemon=True)

    def start(self) -> "LimitedStreamCapture":
        self._thread.start()
        return self

    def _drain(self) -> None:
        if self.stream is None:
            return
        try:
            while True:
                chunk = self.stream.read(64 * 1024)
                if not chunk:
                    break
                with self._lock:
                    remaining = max(0, self.limit - len(self._buffer))
                    self._buffer.extend(chunk[:remaining])
                    self._discarded += max(0, len(chunk) - remaining)
        except (OSError, ValueError):
            return

    def finish(self, timeout: float = 2.0) -> None:
        if self._thread.ident is not None:
            self._thread.join(timeout)
        if self._thread.is_alive() and self.stream is not None:
            try:
                self.stream.close()
            except (AttributeError, OSError):
                pass
            self._thread.join(timeout)
        elif self.stream is not None:
            try:
                self.stream.close()
            except (AttributeError, OSError):
                pass

    def text(self) -> str:
        with self._lock:
            value = bytes(self._buffer).decode("utf-8", errors="replace")
            discarded = self._discarded
        if discarded:
            return f"{value}\n[output truncated: {discarded} bytes]"
        return value


@dataclass(frozen=True)
class ManagedProcessResult:
    returncode: int
    stdout: str
    stderr: str


class ManagedProcessTimeout(TimeoutError):
    def __init__(self, timeout: float, result: ManagedProcessResult) -> None:
        super().__init__(f"process timed out after {timeout:g} seconds")
        self.timeout = timeout
        self.result = result


def terminate_process(process: Any, grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS) -> None:
    """Terminate, then kill and reap a subprocess without leaving a zombie."""

    try:
        if process.poll() is not None:
            process.wait()
            return
    except (AttributeError, OSError):
        return
    try:
        process.terminate()
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=max(0.1, grace_seconds))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
    except (OSError, ProcessLookupError):
        pass
    process.wait()


def terminate_child_process(process: Any, grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS) -> None:
    """Terminate and reap a multiprocessing.Process-like child."""

    if process is None:
        return
    try:
        alive = process.is_alive()
    except (AttributeError, AssertionError):
        return
    if not alive:
        try:
            process.join(0)
        except (AssertionError, RuntimeError):
            pass
        return
    try:
        process.terminate()
    except (AttributeError, OSError):
        pass
    process.join(max(0.1, grace_seconds))
    if process.is_alive():
        try:
            process.kill()
        except (AttributeError, OSError):
            pass
        process.join(max(0.1, grace_seconds))


def terminate_process_id(pid: int, grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS) -> None:
    """Stop a known descendant by PID when its immediate parent is another worker."""

    if pid <= 1:
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        pass
    deadline = time.monotonic() + max(0.1, grace_seconds)
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except OSError:
            break
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def terminate_child_process_group(
    process: Any,
    group_owned: bool,
    grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
) -> None:
    """Stop a spawned worker and descendants in its dedicated process group."""

    if process is None:
        return
    try:
        if not process.is_alive():
            process.join(0)
            return
    except (AttributeError, AssertionError):
        return
    pid = getattr(process, "pid", None)
    if not group_owned and pid and hasattr(os, "getpgid"):
        try:
            group_owned = os.getpgid(pid) == pid
        except OSError:
            group_owned = False
    if not group_owned or not pid or not hasattr(os, "killpg"):
        terminate_child_process(process, grace_seconds)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        pass
    process.join(max(0.1, grace_seconds))
    if process.is_alive():
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass
        process.join(max(0.1, grace_seconds))


def run_managed_process(
    command: Sequence[str],
    *,
    timeout: float,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ManagedProcessResult:
    """Run a command with bounded output capture and deterministic timeout cleanup."""

    process = subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        env=dict(env) if env is not None else None,
    )
    stdout_capture = LimitedStreamCapture(process.stdout, output_limit)
    stderr_capture = LimitedStreamCapture(process.stderr, output_limit)
    timed_out = False
    try:
        stdout_capture.start()
        stderr_capture.start()
        process.wait(timeout=max(0.1, timeout))
    except subprocess.TimeoutExpired:
        timed_out = True
        terminate_process(process)
    except BaseException:
        terminate_process(process)
        raise
    finally:
        stdout_capture.finish()
        stderr_capture.finish()
    result = ManagedProcessResult(
        returncode=int(process.returncode if process.returncode is not None else -1),
        stdout=stdout_capture.text(),
        stderr=stderr_capture.text(),
    )
    if timed_out:
        raise ManagedProcessTimeout(timeout, result)
    return result
