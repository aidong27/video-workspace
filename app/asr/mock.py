from __future__ import annotations

from app.asr.base import AsrProvider, ProviderStatus, ProviderSubmission, Transcript


class MockAsrProvider(AsrProvider):
    provider_name = "mock"

    def __init__(self, transcript: Transcript, model: str = "mock-asr") -> None:
        self.transcript = transcript
        self._model = model
        self.submissions: list[dict[str, object]] = []

    @property
    def model(self) -> str:
        return self._model

    def submit(
        self,
        file_url: str,
        *,
        language: str | None = None,
        enable_words: bool = True,
    ) -> ProviderSubmission:
        self.submissions.append(
            {"file_url": file_url, "language": language, "enable_words": enable_words}
        )
        return ProviderSubmission(self.provider_name, self.model, "mock-task")

    def query(self, task_id: str) -> ProviderStatus:
        return ProviderStatus(
            status="SUCCEEDED",
            task_id=task_id,
            result_urls=("https://example.test/result.json",),
            usage_seconds=self.transcript.provider_seconds,
        )

    def download_result(self, status: ProviderStatus) -> Transcript:
        self.transcript.provider_task_id = status.task_id
        return self.transcript
