from __future__ import annotations

import logging
from threading import Event, Lock, Thread
from typing import Callable


class MaintenanceLoop:
    """One sleeping thread for bounded housekeeping, independent of HTTP traffic."""

    def __init__(self, callbacks: tuple[Callable[[], object], ...], interval: float = 60) -> None:
        self.callbacks = callbacks
        self.interval = max(0.01, interval)
        self.stop_event = Event()
        self.lock = Lock()
        self.thread: Thread | None = None

    def run_once(self) -> None:
        for callback in self.callbacks:
            try:
                callback()
            except Exception as exc:
                logging.getLogger(__name__).error(
                    "retention cleanup failed error_type=%s", type(exc).__name__
                )

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            self.run_once()

    def start(self) -> None:
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = Thread(target=self._run, name="caption-maintenance", daemon=True)
            self.thread.start()

    def stop(self) -> None:
        with self.lock:
            self.stop_event.set()
            if self.thread is not None:
                self.thread.join(timeout=5)
