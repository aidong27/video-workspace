from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import logging
from queue import Empty, Queue
from threading import Event, Lock, Thread
import time
from typing import Any, Callable
import uuid

from fastapi import HTTPException


JobProcessor = Callable[[dict[str, Any], Callable[[str, int, str], None]], dict[str, Any]]
JobDiscarder = Callable[[dict[str, Any]], None]
LOGGER = logging.getLogger(__name__)


@dataclass
class JobRecord:
    job_id: str
    request: dict[str, Any]
    owner_id: int | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "queued"
    stage: str = "queued"
    progress: int = 2
    message: str = "任务已加入队列"
    result: dict[str, Any] | None = None
    error: Any = None
    error_status: int = 500
    idempotency_key: str | None = None
    idempotency_fingerprint: str | None = None
    done_event: Event = field(default_factory=Event, repr=False)


class JobQueueFull(Exception):
    pass


class JobNotFound(Exception):
    pass


class JobIdempotencyConflict(Exception):
    pass


def job_request_fingerprint(request: dict[str, Any]) -> str:
    encoded = json.dumps(
        request,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class JobManager:
    def __init__(
        self,
        processor: JobProcessor,
        max_pending: int = 8,
        result_ttl_seconds: int = 3600,
        max_records: int = 100,
        worker_count: int = 1,
        discarder: JobDiscarder | None = None,
    ) -> None:
        self.processor = processor
        self.max_pending = max(1, max_pending)
        self.result_ttl_seconds = max(60, result_ttl_seconds)
        self.max_records = max(10, max_records)
        self.worker_count = max(1, worker_count)
        self.discarder = discarder
        # Capacity is enforced against live queued records under self.lock. An
        # unbounded transport queue prevents cancelled IDs from causing false
        # queue-full responses before workers have consumed those stale IDs.
        self.queue: Queue[str] = Queue()
        self.records: dict[str, JobRecord] = {}
        self.lock = Lock()
        self.stop_event = Event()
        self.workers: list[Thread] = []

    def start(self) -> None:
        with self.lock:
            if any(worker.is_alive() for worker in self.workers):
                return
            self.stop_event.clear()
            self.workers = [
                Thread(target=self._run, name=f"caption-job-worker-{index + 1}", daemon=True)
                for index in range(self.worker_count)
            ]
            for worker in self.workers:
                worker.start()

    def stop(self, timeout: float = 3.0) -> None:
        self.stop_event.set()
        workers = list(self.workers)
        deadline = time.monotonic() + timeout
        for worker in workers:
            if worker.is_alive():
                worker.join(max(0.0, deadline - time.monotonic()))
        with self.lock:
            abandoned = []
            for item in self.records.values():
                if item.status != "queued":
                    continue
                item.status = "cancelled"
                item.stage = "cancelled"
                item.progress = 0
                item.message = "服务停止，排队任务已取消"
                item.updated_at = time.time()
                item.done_event.set()
                abandoned.append(dict(item.request))
        for request in abandoned:
            self._discard(request)

    def submit(
        self,
        request: dict[str, Any],
        owner_id: int | None = None,
        idempotency_key: str | None = None,
        idempotency_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        self.cleanup()
        fingerprint = (
            idempotency_fingerprint or job_request_fingerprint(request)
            if idempotency_key
            else None
        )
        record = JobRecord(
            job_id=uuid.uuid4().hex,
            request=dict(request),
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint,
        )
        with self.lock:
            existing = self._find_idempotent_locked(owner_id, idempotency_key)
            if existing is not None:
                self._ensure_idempotent_match(existing, fingerprint)
                payload = self._public_locked(existing)
                payload["reused"] = True
                return payload
            queued = sum(item.status == "queued" for item in self.records.values())
            if queued >= self.max_pending:
                raise JobQueueFull
            self.records[record.job_id] = record
        self.queue.put_nowait(record.job_id)
        payload = self.get(record.job_id, owner_id=owner_id)
        payload["reused"] = False
        return payload

    def submit_completed(
        self,
        request: dict[str, Any],
        result: dict[str, Any],
        owner_id: int | None = None,
        idempotency_key: str | None = None,
        idempotency_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        self.cleanup()
        now = time.time()
        fingerprint = (
            idempotency_fingerprint or job_request_fingerprint(request)
            if idempotency_key
            else None
        )
        record = JobRecord(
            job_id=uuid.uuid4().hex,
            request=dict(request),
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
            status="completed",
            stage="cache_hit",
            progress=100,
            message="已从缓存载入结果",
            result=result,
            idempotency_key=idempotency_key,
            idempotency_fingerprint=fingerprint,
        )
        record.done_event.set()
        with self.lock:
            existing = self._find_idempotent_locked(owner_id, idempotency_key)
            if existing is not None:
                self._ensure_idempotent_match(existing, fingerprint)
                payload = self._public_locked(existing)
                payload["reused"] = True
                return payload
            self.records[record.job_id] = record
            payload = self._public_locked(record)
            payload["reused"] = False
            return payload

    def get_by_idempotency(
        self,
        owner_id: int | None,
        idempotency_key: str | None,
        idempotency_fingerprint: str | None = None,
    ) -> dict[str, Any] | None:
        if not idempotency_key:
            return None
        self.cleanup()
        with self.lock:
            record = self._find_idempotent_locked(owner_id, idempotency_key)
            if record is None:
                return None
            self._ensure_idempotent_match(record, idempotency_fingerprint)
            payload = self._public_locked(record)
            payload["reused"] = True
            return payload

    def wait(self, job_id: str, owner_id: int | None = None, timeout: float | None = None) -> dict[str, Any]:
        with self.lock:
            record = self.records.get(job_id)
            if record is None or (owner_id is not None and record.owner_id != owner_id):
                raise JobNotFound
            done_event = record.done_event
        done_event.wait(timeout)
        return self.get(job_id, owner_id=owner_id)

    def get(self, job_id: str, owner_id: int | None = None) -> dict[str, Any]:
        self.cleanup()
        with self.lock:
            record = self.records.get(job_id)
            if record is None or (owner_id is not None and record.owner_id != owner_id):
                raise JobNotFound
            return self._public_locked(record)

    def cancel(self, job_id: str, owner_id: int | None = None) -> dict[str, Any]:
        discarded_request: dict[str, Any] | None = None
        with self.lock:
            record = self.records.get(job_id)
            if record is None or (owner_id is not None and record.owner_id != owner_id):
                raise JobNotFound
            if record.status == "queued":
                record.status = "cancelled"
                record.stage = "cancelled"
                record.progress = 0
                record.message = "任务已取消"
                record.updated_at = time.time()
                record.done_event.set()
                discarded_request = dict(record.request)
            payload = self._public_locked(record)
        if discarded_request is not None:
            self._discard(discarded_request)
        return payload

    def stats(self) -> dict[str, int | bool]:
        with self.lock:
            workers_alive = sum(worker.is_alive() for worker in self.workers)
            return {
                "worker_alive": workers_alive > 0,
                "workers_alive": workers_alive,
                "worker_count": self.worker_count,
                "queued": sum(item.status == "queued" for item in self.records.values()),
                "running": sum(item.status == "running" for item in self.records.values()),
                "max_pending": self.max_pending,
            }

    def cleanup(self) -> int:
        now = time.time()
        removed = 0
        discarded: list[dict[str, Any]] = []
        with self.lock:
            finished = [
                item
                for item in self.records.values()
                if item.status in {"completed", "failed", "cancelled"}
            ]
            for item in finished:
                if now - item.updated_at > self.result_ttl_seconds:
                    self.records.pop(item.job_id, None)
                    discarded.append(dict(item.request))
                    removed += 1
            if len(self.records) > self.max_records:
                removable = sorted(
                    (
                        item
                        for item in self.records.values()
                        if item.status in {"completed", "failed", "cancelled"}
                    ),
                    key=lambda item: item.updated_at,
                )
                for item in removable[: max(0, len(self.records) - self.max_records)]:
                    self.records.pop(item.job_id, None)
                    discarded.append(dict(item.request))
                    removed += 1
        for request in discarded:
            self._discard(request)
        return removed

    def _discard(self, request: dict[str, Any]) -> None:
        if self.discarder is None:
            return
        try:
            self.discarder(dict(request))
        except Exception:
            LOGGER.exception("caption job resource cleanup failed")

    def _public_locked(self, record: JobRecord) -> dict[str, Any]:
        queued_ids = [
            item.job_id
            for item in sorted(self.records.values(), key=lambda item: item.created_at)
            if item.status == "queued"
        ]
        position = queued_ids.index(record.job_id) + 1 if record.job_id in queued_ids else 0
        payload: dict[str, Any] = {
            "id": record.job_id,
            "status": record.status,
            "stage": record.stage,
            "progress": record.progress,
            "message": record.message,
            "queue_position": position,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        if record.status == "completed":
            payload["result"] = record.result
        elif record.status == "failed":
            payload["error"] = record.error
            payload["error_status"] = record.error_status
        return payload

    def _find_idempotent_locked(
        self,
        owner_id: int | None,
        idempotency_key: str | None,
    ) -> JobRecord | None:
        if not idempotency_key:
            return None
        return next(
            (
                item
                for item in self.records.values()
                if item.owner_id == owner_id and item.idempotency_key == idempotency_key
            ),
            None,
        )

    @staticmethod
    def _ensure_idempotent_match(record: JobRecord, fingerprint: str | None) -> None:
        if fingerprint is None or record.idempotency_fingerprint == fingerprint:
            return
        raise JobIdempotencyConflict

    def _update(self, job_id: str, stage: str, progress: int, message: str) -> None:
        with self.lock:
            record = self.records.get(job_id)
            if record is None or record.status != "running":
                return
            record.stage = stage
            record.progress = max(record.progress, min(99, max(1, int(progress))))
            record.message = message
            record.updated_at = time.time()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                job_id = self.queue.get(timeout=0.5)
            except Empty:
                continue
            with self.lock:
                record = self.records.get(job_id)
                if record is None or record.status == "cancelled":
                    self.queue.task_done()
                    continue
                record.status = "running"
                record.stage = "starting"
                record.progress = 5
                record.message = "正在启动任务"
                record.updated_at = time.time()
                request = dict(record.request)
            try:
                result = self.processor(
                    request,
                    lambda stage, progress, message: self._update(job_id, stage, progress, message),
                )
            except HTTPException as exc:
                with self.lock:
                    record = self.records.get(job_id)
                    if record:
                        record.status = "failed"
                        record.stage = "failed"
                        record.progress = 100
                        record.message = "任务处理失败"
                        record.error = exc.detail
                        record.error_status = exc.status_code
                        record.updated_at = time.time()
                        record.done_event.set()
            except Exception:
                LOGGER.exception("caption job failed", extra={"job_id": job_id})
                with self.lock:
                    record = self.records.get(job_id)
                    if record:
                        record.status = "failed"
                        record.stage = "failed"
                        record.progress = 100
                        record.message = "任务处理失败"
                        record.error = {"reason": "internal_error", "message": "服务处理任务时发生内部错误。"}
                        record.error_status = 500
                        record.updated_at = time.time()
                        record.done_event.set()
            else:
                with self.lock:
                    record = self.records.get(job_id)
                    if record:
                        record.status = "completed"
                        record.stage = "completed"
                        record.progress = 100
                        record.message = "任务处理完成"
                        record.result = result
                        record.updated_at = time.time()
                        record.done_event.set()
            finally:
                self.queue.task_done()
