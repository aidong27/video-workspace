import json
from pathlib import Path
import tempfile
import unittest

import httpx

from app.asr.aliyun import (
    AliyunParaformerProvider,
    AliyunQwenFileTransProvider,
    AliyunTemporaryFileUploader,
    normalize_transcript_payload,
    validate_dashscope_base_url,
)
from app.asr.base import AsrProviderError, ProviderStatus


BASE_URL = "https://ws-test.cn-beijing.maas.aliyuncs.com/api/v1"


def json_response(request: httpx.Request, payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=request,
        headers={"Content-Type": "application/json"},
    )


class AliyunProviderTests(unittest.TestCase):
    def test_qwen_request_and_result_are_normalized(self) -> None:
        requests: list[httpx.Request] = []

        def api_handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "POST":
                return json_response(
                    request,
                    {"request_id": "req-1", "output": {"task_id": "task-1", "task_status": "PENDING"}},
                )
            return json_response(
                request,
                {
                    "request_id": "req-2",
                    "output": {
                        "task_id": "task-1",
                        "task_status": "SUCCEEDED",
                        "result": {"transcription_url": "https://result.example.test/qwen.json"},
                    },
                    "usage": {"seconds": 12.5},
                },
            )

        result_payload = {
            "request_id": "result-1",
            "properties": {"original_duration_in_milliseconds": 12500},
            "transcripts": [
                {
                    "language": "zh",
                    "text": "你好世界",
                    "sentences": [
                        {
                            "begin_time": 0,
                            "end_time": 1200,
                            "text": "你好世界",
                            "emotion": "neutral",
                            "words": [
                                {"begin_time": 0, "end_time": 400, "text": "你好"},
                                {"begin_time": 400, "end_time": 1200, "text": "世界"},
                            ],
                        }
                    ],
                }
            ],
        }
        result_client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=result_payload, request=request)
            )
        )
        provider = AliyunQwenFileTransProvider(
            api_key="sk-test",
            base_url=BASE_URL,
            model="qwen3-asr-flash-filetrans",
            client=httpx.Client(transport=httpx.MockTransport(api_handler)),
            result_client=result_client,
            result_url_validator=lambda _: None,
            sleep=lambda _: None,
        )

        transcript = provider.transcribe(
            "https://caption.example.test/api/provider-audio/token?signature=hidden",
            language="zh",
            sleep=lambda _: None,
        )

        body = json.loads(requests[0].content)
        self.assertIn("Bearer sk-test", requests[0].headers["authorization"])
        self.assertEqual(requests[0].headers["x-dashscope-async"], "enable")
        self.assertNotIn("x-dashscope-ossresourceresolve", requests[0].headers)
        self.assertNotIn("x-dashscope-async", requests[1].headers)
        self.assertEqual(body["input"], {"file_url": body["input"]["file_url"]})
        self.assertEqual(body["parameters"]["language"], "zh")
        self.assertTrue(body["parameters"]["enable_words"])
        self.assertEqual(transcript.provider_seconds, 12.5)
        self.assertEqual(transcript.language, "zh")
        self.assertEqual(transcript.segments[0].text, "你好世界")
        self.assertEqual(transcript.segments[0].words[1].start_ms, 400)

    def test_paraformer_uses_file_urls_and_distinct_result_shape(self) -> None:
        requests: list[httpx.Request] = []

        def api_handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.method == "POST":
                return json_response(request, {"output": {"task_id": "para-task"}})
            return json_response(
                request,
                {
                    "output": {
                        "task_status": "SUCCEEDED",
                        "results": [
                            {
                                "subtask_status": "SUCCEEDED",
                                "transcription_url": "https://result.example.test/para.json",
                            }
                        ],
                    },
                    "usage": {"duration": 8},
                },
            )

        result_client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "properties": {"original_duration_in_milliseconds": 8000},
                        "transcripts": [{"text": "经济模式结果", "sentences": []}],
                    },
                    request=request,
                )
            )
        )
        provider = AliyunParaformerProvider(
            api_key="sk-test",
            base_url=BASE_URL,
            model="paraformer-v2",
            client=httpx.Client(transport=httpx.MockTransport(api_handler)),
            result_client=result_client,
            result_url_validator=lambda _: None,
            sleep=lambda _: None,
        )

        transcript = provider.transcribe(
            "oss://dashscope-instant/test/audio.mp3",
            language="zh",
            sleep=lambda _: None,
        )

        body = json.loads(requests[0].content)
        self.assertEqual(
            body["input"],
            {"file_urls": ["oss://dashscope-instant/test/audio.mp3"]},
        )
        self.assertEqual(
            requests[0].headers["x-dashscope-ossresourceresolve"],
            "enable",
        )
        self.assertEqual(body["parameters"]["language_hints"], ["zh", "en"])
        self.assertNotIn("enable_words", body["parameters"])
        self.assertEqual(transcript.provider_seconds, 8)
        self.assertEqual(transcript.segments[0].text, "经济模式结果")

    def test_retry_is_limited_and_auth_error_is_stable(self) -> None:
        attempts = 0

        def retry_handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return json_response(request, {"code": "InternalError"}, 500)
            return json_response(
                request,
                {"output": {"task_id": "task-ok", "task_status": "PENDING"}},
            )

        provider = AliyunQwenFileTransProvider(
            api_key="sk-test",
            base_url=BASE_URL,
            model="qwen3-asr-flash-filetrans",
            client=httpx.Client(transport=httpx.MockTransport(retry_handler)),
            result_client=httpx.Client(transport=httpx.MockTransport(lambda request: json_response(request, {}))),
            sleep=lambda _: None,
            max_retries=2,
        )
        self.assertEqual(provider.query("task-ok").status, "PENDING")
        self.assertEqual(attempts, 3)

        submit_attempts = 0

        def submit_handler(request: httpx.Request) -> httpx.Response:
            nonlocal submit_attempts
            submit_attempts += 1
            return json_response(request, {"code": "InternalError"}, 500)

        submit_provider = AliyunQwenFileTransProvider(
            api_key="test-key",
            base_url=BASE_URL,
            model="qwen3-asr-flash-filetrans",
            client=httpx.Client(transport=httpx.MockTransport(submit_handler)),
            result_client=httpx.Client(transport=httpx.MockTransport(lambda request: json_response(request, {}))),
            sleep=lambda _: None,
            max_retries=2,
        )
        with self.assertRaises(AsrProviderError):
            submit_provider.submit("https://caption.example.test/audio")
        self.assertEqual(submit_attempts, 1)

        auth_provider = AliyunQwenFileTransProvider(
            api_key="sk-test",
            base_url=BASE_URL,
            model="qwen3-asr-flash-filetrans",
            client=httpx.Client(
                transport=httpx.MockTransport(
                    lambda request: json_response(request, {"code": "InvalidApiKey"}, 401)
                )
            ),
            result_client=httpx.Client(transport=httpx.MockTransport(lambda request: json_response(request, {}))),
            sleep=lambda _: None,
        )
        with self.assertRaises(AsrProviderError) as raised:
            auth_provider.submit("https://caption.example.test/audio")
        self.assertEqual(raised.exception.code, "asr_provider_auth_failed")
        self.assertFalse(raised.exception.retryable)

    def test_invalid_base_and_result_payload_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_dashscope_base_url("http://127.0.0.1/api/v1")
        with self.assertRaises(ValueError):
            validate_dashscope_base_url("https://example.com/api/v1")
        with self.assertRaises(ValueError):
            validate_dashscope_base_url(f"{BASE_URL}/compatible-mode")
        self.assertEqual(
            validate_dashscope_base_url("https://dashscope.aliyuncs.com"),
            "https://dashscope.aliyuncs.com/api/v1",
        )

        transcript = normalize_transcript_payload(
            {
                "properties": {"original_duration_in_milliseconds": 1000},
                "transcripts": [
                    {
                        "sentences": [
                            {"begin_time": -50, "end_time": 0, "text": " 文本 "},
                            {"begin_time": 5, "end_time": 10, "text": " "},
                        ]
                    }
                ],
            },
            provider="aliyun",
            model="test",
            task_id="task",
            usage_seconds=None,
        )
        self.assertEqual(len(transcript.segments), 1)
        self.assertEqual(transcript.segments[0].start_ms, 0)
        self.assertGreater(transcript.segments[0].end_ms, 0)

        status = ProviderStatus("SUCCEEDED", "task")
        provider = AliyunQwenFileTransProvider(
            api_key="sk-test",
            base_url=BASE_URL,
            model="qwen3-asr-flash-filetrans",
            client=httpx.Client(transport=httpx.MockTransport(lambda request: json_response(request, {}))),
            result_client=httpx.Client(transport=httpx.MockTransport(lambda request: json_response(request, {}))),
        )
        with self.assertRaises(AsrProviderError) as raised:
            provider.download_result(status)
        self.assertEqual(raised.exception.code, "asr_provider_response_invalid")

        unsafe_status = ProviderStatus(
            "SUCCEEDED",
            "unsafe-task",
            result_urls=("https://unsafe.example.test/result.json",),
        )

        def reject_result_url(_: str) -> None:
            raise ValueError("unsafe")

        unsafe_provider = AliyunQwenFileTransProvider(
            api_key="sk-test",
            base_url=BASE_URL,
            model="qwen3-asr-flash-filetrans",
            client=httpx.Client(
                transport=httpx.MockTransport(lambda request: json_response(request, {}))
            ),
            result_client=httpx.Client(
                transport=httpx.MockTransport(lambda request: json_response(request, {}))
            ),
            result_url_validator=reject_result_url,
        )
        with self.assertRaises(AsrProviderError) as unsafe:
            unsafe_provider.download_result(unsafe_status)
        self.assertEqual(unsafe.exception.code, "asr_provider_response_invalid")
        self.assertEqual(unsafe.exception.task_id, "unsafe-task")

    def test_quota_and_audio_fetch_task_failures_are_normalized(self) -> None:
        provider = AliyunQwenFileTransProvider(
            api_key="test-key",
            base_url=BASE_URL,
            model="qwen3-asr-flash-filetrans",
            client=httpx.Client(transport=httpx.MockTransport(lambda request: json_response(request, {}))),
            result_client=httpx.Client(transport=httpx.MockTransport(lambda request: json_response(request, {}))),
        )

        quota = provider.failure_from_status(
            ProviderStatus(
                "FAILED",
                "task-quota",
                error_code="AllocationQuota.FreeTierOnly",
                error_message="free tier exhausted",
            )
        )
        self.assertEqual(quota.code, "asr_quota_exhausted")
        self.assertEqual(quota.status_code, 429)
        self.assertNotIn("free tier exhausted", quota.message)

        fetch = provider.failure_from_status(
            ProviderStatus(
                "FAILED",
                "task-fetch",
                error_code="FILE_DOWNLOAD_FAILED",
                error_message="signed URL was unavailable",
            )
        )
        self.assertEqual(fetch.code, "asr_audio_fetch_failed")
        self.assertTrue(fetch.retryable)

    def test_temporary_uploader_streams_random_named_audio_to_trusted_oss(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.host == "dashscope.aliyuncs.com":
                self.assertEqual(request.url.params["action"], "getPolicy")
                self.assertEqual(request.url.params["model"], "qwen3-asr-flash-filetrans")
                return json_response(
                    request,
                    {
                        "data": {
                            "policy": "policy-value",
                            "signature": "signature-value",
                            "upload_dir": "dashscope-instant/account/session",
                            "upload_host": (
                                "https://dashscope-file-upload."
                                "oss-cn-beijing.aliyuncs.com"
                            ),
                            "oss_access_key_id": "temporary-access-key",
                            "x_oss_object_acl": "private",
                            "x_oss_forbid_overwrite": "true",
                            "max_file_size_mb": 10,
                        }
                    },
                )
            body = request.read()
            self.assertNotIn("authorization", request.headers)
            self.assertIn(b"audio-test-bytes", body)
            self.assertNotIn(b"user-supplied-name.mp3", body)
            self.assertIn(b"dashscope-instant/account/session/", body)
            return httpx.Response(200, request=request)

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "user-supplied-name.mp3"
            audio.write_bytes(b"audio-test-bytes")
            uploader = AliyunTemporaryFileUploader(
                api_key="sk-test",
                client=httpx.Client(transport=httpx.MockTransport(handler)),
                sleep=lambda _: None,
            )
            file_url = uploader.upload(
                audio,
                model="qwen3-asr-flash-filetrans",
            )

        self.assertRegex(
            file_url,
            r"^oss://dashscope-instant/account/session/[0-9a-f]{48}\.mp3$",
        )
        self.assertEqual(len(requests), 2)

    def test_temporary_uploader_rejects_untrusted_upload_host(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return json_response(
                request,
                {
                    "data": {
                        "policy": "policy-value",
                        "signature": "signature-value",
                        "upload_dir": "dashscope-instant/account/session",
                        "upload_host": "https://evil.example.test",
                        "oss_access_key_id": "temporary-access-key",
                        "x_oss_object_acl": "private",
                        "x_oss_forbid_overwrite": "true",
                    }
                },
            )

        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "audio.mp3"
            audio.write_bytes(b"audio")
            uploader = AliyunTemporaryFileUploader(
                api_key="sk-test",
                client=httpx.Client(transport=httpx.MockTransport(handler)),
                sleep=lambda _: None,
            )
            with self.assertRaises(AsrProviderError) as raised:
                uploader.upload(audio, model="qwen3-asr-flash-filetrans")

        self.assertEqual(raised.exception.code, "asr_provider_response_invalid")


if __name__ == "__main__":
    unittest.main()
