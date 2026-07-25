from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from typing import Any, Callable


ProgressCallback = Callable[[str, int, str], None]


class AsrProviderError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int = 502,
        task_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code
        self.task_id = task_id


@dataclass(frozen=True)
class TranscriptWord:
    text: str
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(frozen=True)
class TranscriptSegment:
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    emotion: str | None = None
    words: tuple[TranscriptWord, ...] = ()


@dataclass
class Transcript:
    provider: str
    model: str
    language: str | None
    duration_ms: int
    segments: list[TranscriptSegment]
    provider_task_id: str | None = None
    provider_seconds: float | None = None
    latency_seconds: float | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderSubmission:
    provider: str
    model: str
    task_id: str
    request_id: str | None = None


@dataclass(frozen=True)
class ProviderStatus:
    status: str
    task_id: str
    result_urls: tuple[str, ...] = ()
    usage_seconds: float | None = None
    request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class AsrProvider(ABC):
    provider_name = "unknown"

    @property
    @abstractmethod
    def model(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def submit(
        self,
        file_url: str,
        *,
        language: str | None = None,
        enable_words: bool = True,
    ) -> ProviderSubmission:
        raise NotImplementedError

    @abstractmethod
    def query(self, task_id: str) -> ProviderStatus:
        raise NotImplementedError

    @abstractmethod
    def download_result(self, status: ProviderStatus) -> Transcript:
        raise NotImplementedError

    def abandon(self, task_id: str) -> bool:
        return False

    def failure_from_status(self, status: ProviderStatus) -> AsrProviderError:
        return AsrProviderError(
            "asr_provider_failed",
            "云端语音识别任务失败。",
            retryable=False,
            task_id=status.task_id,
        )

    def transcribe(
        self,
        file_url: str,
        *,
        language: str | None = None,
        enable_words: bool = True,
        timeout_seconds: float = 1800,
        poll_initial_seconds: float = 3,
        poll_max_seconds: float = 5,
        progress: ProgressCallback | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Transcript:
        started = time.monotonic()
        if progress:
            progress("waiting_for_provider", 58, "正在提交云端语音识别任务")
        submission = self.submit(file_url, language=language, enable_words=enable_words)
        deadline = started + max(1.0, timeout_seconds)
        interval = max(0.1, poll_initial_seconds)
        status: ProviderStatus | None = None
        try:
            while time.monotonic() < deadline:
                status = self.query(submission.task_id)
                normalized = status.status.upper()
                if normalized == "SUCCEEDED":
                    if progress:
                        progress("postprocessing", 88, "正在整理云端识别结果")
                    transcript = self.download_result(status)
                    transcript.provider_task_id = submission.task_id
                    transcript.provider_seconds = (
                        status.usage_seconds
                        if status.usage_seconds is not None
                        else transcript.provider_seconds
                    )
                    transcript.latency_seconds = round(time.monotonic() - started, 3)
                    return transcript
                if normalized in {"FAILED", "CANCELED", "CANCELLED"}:
                    raise self.failure_from_status(status)
                if normalized not in {"PENDING", "RUNNING", "QUEUED"}:
                    raise AsrProviderError(
                        "asr_provider_response_invalid",
                        "云端语音识别返回了未知任务状态。",
                        retryable=True,
                        task_id=submission.task_id,
                    )
                if progress:
                    progress("transcribing", 70, "云端正在识别音频")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sleep(min(interval, remaining))
                interval = min(max(interval * 1.35, interval + 0.25), poll_max_seconds)
        except AsrProviderError as exc:
            if exc.task_id is None:
                exc.task_id = submission.task_id
            raise
        self.abandon(submission.task_id)
        raise AsrProviderError(
            "asr_timeout",
            "云端语音识别等待超时，请稍后重试。",
            retryable=True,
            status_code=504,
            task_id=submission.task_id,
        )
