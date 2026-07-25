from __future__ import annotations

import logging
import math
from pathlib import Path
import secrets
import time
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from app.asr.base import (
    AsrProvider,
    AsrProviderError,
    ProviderStatus,
    ProviderSubmission,
    Transcript,
    TranscriptSegment,
    TranscriptWord,
)
from app.network import ensure_public_http_url, validate_public_request


TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED", "CANCELLED"}
ACTIVE_STATUSES = {"PENDING", "RUNNING", "QUEUED"}
LOGGER = logging.getLogger(__name__)
DASHSCOPE_UPLOAD_POLICY_URL = "https://dashscope.aliyuncs.com/api/v1/uploads"


def validate_dashscope_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    host = (parsed.hostname or "").lower().rstrip(".")
    path = parsed.path.rstrip("/")
    allowed = host == "dashscope.aliyuncs.com" or (
        host.endswith(".maas.aliyuncs.com") and ".cn-beijing." in host
    )
    if (
        parsed.scheme != "https"
        or not allowed
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or path not in {"", "/api/v1"}
    ):
        raise ValueError("DASHSCOPE_BASE_URL must be a trusted HTTPS DashScope endpoint")
    return f"{normalized}/api/v1" if not path else normalized


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _safe_ms(value: Any, default: int = 0) -> int:
    number = _safe_float(value)
    return max(0, int(round(number))) if number is not None else max(0, default)


def _language_hint(language: str | None) -> list[str] | None:
    tag = (language or "").strip().lower().replace("_", "-")
    if not tag:
        return None
    if tag.startswith("zh"):
        return ["zh", "en"]
    if tag.startswith("en"):
        return ["en", "zh"]
    return [tag.split("-", 1)[0]]


def normalize_transcript_payload(
    payload: dict[str, Any],
    *,
    provider: str,
    model: str,
    task_id: str,
    usage_seconds: float | None,
) -> Transcript:
    properties = payload.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    duration_ms = _safe_ms(properties.get("original_duration_in_milliseconds"))
    transcript_items = payload.get("transcripts")
    transcript_items = transcript_items if isinstance(transcript_items, list) else []
    segments: list[TranscriptSegment] = []
    language: str | None = None

    for transcript_item in transcript_items:
        if not isinstance(transcript_item, dict):
            continue
        if not language and transcript_item.get("language"):
            language = str(transcript_item["language"])
        sentences = transcript_item.get("sentences")
        sentences = sentences if isinstance(sentences, list) else []
        if not sentences:
            text = str(transcript_item.get("text") or "").strip()
            if text:
                segments.append(
                    TranscriptSegment(
                        start_ms=0,
                        end_ms=max(1, duration_ms),
                        text=text,
                    )
                )
            continue
        for sentence in sentences:
            if not isinstance(sentence, dict):
                continue
            text = str(sentence.get("text") or "").strip()
            if not text:
                continue
            start_ms = _safe_ms(sentence.get("begin_time"))
            end_ms = max(start_ms + 1, _safe_ms(sentence.get("end_time"), start_ms + 1))
            words_payload = sentence.get("words")
            words_payload = words_payload if isinstance(words_payload, list) else []
            words: list[TranscriptWord] = []
            for word in words_payload:
                if not isinstance(word, dict):
                    continue
                word_text = str(word.get("text") or "").strip()
                if not word_text:
                    continue
                word_start = _safe_ms(word.get("begin_time"))
                word_end = max(word_start + 1, _safe_ms(word.get("end_time"), word_start + 1))
                words.append(TranscriptWord(word_text, word_start, word_end))
            speaker_value = sentence.get("speaker_id")
            if speaker_value is None:
                speaker_value = sentence.get("speaker")
            segments.append(
                TranscriptSegment(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                    speaker=str(speaker_value) if speaker_value is not None else None,
                    emotion=str(sentence["emotion"]) if sentence.get("emotion") is not None else None,
                    words=tuple(words),
                )
            )
            duration_ms = max(duration_ms, end_ms)

    return Transcript(
        provider=provider,
        model=model,
        language=language,
        duration_ms=duration_ms,
        segments=segments,
        provider_task_id=task_id,
        provider_seconds=usage_seconds,
        raw_metadata={
            "request_id": payload.get("request_id"),
            "properties": properties,
            "transcript_count": len(transcript_items),
        },
    )


class AliyunTemporaryFileUploader:
    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 300,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DASHSCOPE_API_KEY is required")
        timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self.max_retries = max(0, max_retries)
        self.sleep = sleep
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    @staticmethod
    def _response_error(response: httpx.Response) -> AsrProviderError:
        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = {}
        code = str(payload.get("code") or payload.get("error_code") or "")
        marker = f"{code} {payload.get('message') or ''}".lower()
        if response.status_code in {401, 403}:
            return AsrProviderError(
                "asr_provider_auth_failed",
                "云端临时文件凭证无效或权限不足。",
                retryable=False,
                status_code=503,
            )
        if response.status_code == 429 or "throttl" in marker:
            return AsrProviderError(
                "asr_rate_limited",
                "云端临时文件上传请求过于频繁，请稍后重试。",
                retryable=True,
                status_code=429,
            )
        retryable = response.status_code >= 500
        return AsrProviderError(
            "asr_provider_unavailable" if retryable else "asr_temp_upload_failed",
            "云端临时文件服务暂时不可用。"
            if retryable
            else "云端临时音频上传失败。",
            retryable=retryable,
            status_code=503 if retryable else 502,
        )

    def _get_policy(self, model: str) -> dict[str, Any]:
        last_error: AsrProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.get(
                    DASHSCOPE_UPLOAD_POLICY_URL,
                    params={"action": "getPolicy", "model": model},
                    headers=self._headers,
                )
            except httpx.RequestError as exc:
                last_error = AsrProviderError(
                    "asr_provider_unavailable",
                    "无法连接云端临时文件服务。",
                    retryable=True,
                    status_code=503,
                )
                if attempt >= self.max_retries:
                    raise last_error from exc
            else:
                if 200 <= response.status_code < 300:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise AsrProviderError(
                            "asr_provider_response_invalid",
                            "云端临时文件服务返回了无法解析的数据。",
                            retryable=True,
                        ) from exc
                    data = payload.get("data") if isinstance(payload, dict) else None
                    if isinstance(data, dict):
                        return data
                    raise AsrProviderError(
                        "asr_provider_response_invalid",
                        "云端临时文件服务返回了异常数据结构。",
                        retryable=True,
                    )
                last_error = self._response_error(response)
                if not last_error.retryable or attempt >= self.max_retries:
                    raise last_error
            self.sleep(min(4.0, 0.5 * (2**attempt)))
        raise last_error or AsrProviderError(
            "asr_provider_unavailable",
            "云端临时文件服务暂时不可用。",
            retryable=True,
        )

    def upload(self, path: Path, *, model: str) -> str:
        try:
            if path.is_symlink():
                raise OSError("symbolic links are not accepted")
            resolved = path.resolve(strict=True)
            is_file = resolved.is_file()
            file_size = resolved.stat().st_size
        except OSError as exc:
            raise AsrProviderError(
                "asr_temp_upload_failed",
                "待上传的临时音频不可用。",
                retryable=False,
            ) from exc
        if not is_file:
            raise AsrProviderError(
                "asr_temp_upload_failed",
                "待上传的临时音频不可用。",
                retryable=False,
            )
        policy = self._get_policy(model)
        required = {
            "policy",
            "signature",
            "upload_dir",
            "upload_host",
            "oss_access_key_id",
            "x_oss_object_acl",
            "x_oss_forbid_overwrite",
        }
        if any(not str(policy.get(key) or "").strip() for key in required):
            raise AsrProviderError(
                "asr_provider_response_invalid",
                "云端临时文件凭证不完整。",
                retryable=True,
            )
        upload_host = str(policy["upload_host"]).strip()
        parsed_host = urlparse(upload_host)
        if (
            parsed_host.scheme != "https"
            or not (parsed_host.hostname or "").endswith(".oss-cn-beijing.aliyuncs.com")
            or parsed_host.username is not None
            or parsed_host.password is not None
            or parsed_host.query
            or parsed_host.fragment
            or parsed_host.path not in {"", "/"}
        ):
            raise AsrProviderError(
                "asr_provider_response_invalid",
                "云端临时文件上传地址无效。",
                retryable=False,
            )
        upload_dir = str(policy["upload_dir"]).strip().strip("/")
        if (
            not upload_dir.startswith("dashscope-instant/")
            or ".." in upload_dir.split("/")
            or "\\" in upload_dir
        ):
            raise AsrProviderError(
                "asr_provider_response_invalid",
                "云端临时文件路径无效。",
                retryable=False,
            )
        max_size_mb = _safe_float(policy.get("max_file_size_mb"))
        if max_size_mb is not None and file_size > max_size_mb * 1024 * 1024:
            raise AsrProviderError(
                "media_too_large",
                "音频文件超过云端临时上传限制。",
                retryable=False,
                status_code=413,
            )
        object_key = f"{upload_dir}/{secrets.token_hex(24)}.mp3"
        form = {
            "OSSAccessKeyId": str(policy["oss_access_key_id"]),
            "Signature": str(policy["signature"]),
            "policy": str(policy["policy"]),
            "x-oss-object-acl": str(policy["x_oss_object_acl"]),
            "x-oss-forbid-overwrite": str(policy["x_oss_forbid_overwrite"]),
            "key": object_key,
            "success_action_status": "200",
        }
        try:
            with resolved.open("rb") as source:
                response = self.client.post(
                    upload_host,
                    data=form,
                    files={"file": ("audio.mp3", source, "audio/mpeg")},
                )
        except (httpx.RequestError, OSError) as exc:
            raise AsrProviderError(
                "asr_provider_unavailable"
                if isinstance(exc, httpx.RequestError)
                else "asr_temp_upload_failed",
                "云端临时音频上传连接失败。"
                if isinstance(exc, httpx.RequestError)
                else "待上传的临时音频不可用。",
                retryable=isinstance(exc, httpx.RequestError),
                status_code=503 if isinstance(exc, httpx.RequestError) else 502,
            ) from exc
        if not 200 <= response.status_code < 300:
            raise self._response_error(response)
        return f"oss://{object_key}"


class _AliyunAsyncProvider(AsrProvider):
    provider_name = "aliyun"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 30,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        result_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        result_url_validator: Callable[[str], None] = ensure_public_http_url,
        max_result_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        if not api_key.strip():
            raise ValueError("DASHSCOPE_API_KEY is required")
        self._model = model.strip()
        if not self._model:
            raise ValueError("ASR model is required")
        self.base_url = validate_dashscope_base_url(base_url)
        self.max_retries = max(0, max_retries)
        self.sleep = sleep
        self.result_url_validator = result_url_validator
        self.max_result_bytes = max(1024, max_result_bytes)
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(timeout_seconds, connect=min(10.0, timeout_seconds))
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            headers=self._headers,
        )
        self._owns_result_client = result_client is None
        self.result_client = result_client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            event_hooks={"request": [validate_public_request]},
        )

    @property
    def model(self) -> str:
        return self._model

    def close(self) -> None:
        if self._owns_client:
            self.client.close()
        if self._owns_result_client:
            self.result_client.close()

    @staticmethod
    def _normalized_error(
        code: str,
        provider_message: str,
        *,
        http_status: int,
        task_id: str | None = None,
    ) -> AsrProviderError:
        marker = f"{code} {provider_message}".lower()
        if any(
            word in marker
            for word in (
                "quota",
                "free tier",
                "freetier",
                "insufficient balance",
                "arrearage",
                "allocation exhausted",
            )
        ):
            return AsrProviderError(
                "asr_quota_exhausted",
                "云端语音识别免费额度或本地限额已用尽，未继续产生付费调用。",
                retryable=False,
                status_code=429,
                task_id=task_id,
            )
        if http_status in {401, 403} or any(
            word in marker for word in ("invalidapikey", "invalid api key", "unauthorized")
        ):
            return AsrProviderError(
                "asr_provider_auth_failed",
                "云端语音识别凭证无效或无权访问当前模型。",
                retryable=False,
                status_code=503,
                task_id=task_id,
            )
        if http_status == 429 or any(word in marker for word in ("rate limit", "throttl")):
            return AsrProviderError(
                "asr_rate_limited",
                "云端语音识别请求过于频繁，请稍后重试。",
                retryable=True,
                status_code=429,
                task_id=task_id,
            )
        if http_status == 413 or any(
            word in marker for word in ("filetoolarge", "file too large", "durationtoolong")
        ):
            return AsrProviderError(
                "media_too_large",
                "音频文件超过云端语音识别限制。",
                retryable=False,
                status_code=413,
                task_id=task_id,
            )
        if any(
            word in marker
            for word in (
                "invalidfile.downloadfailed",
                "downloadfailed",
                "download failed",
                "file_download_failed",
                "filedownloadfailed",
            )
        ):
            return AsrProviderError(
                "asr_audio_fetch_failed",
                "云端语音识别无法读取临时音频，请稍后重试。",
                retryable=True,
                status_code=502,
                task_id=task_id,
            )
        retryable = http_status >= 500 or any(
            word in marker for word in ("internalerror", "serviceunavailable", "systemerror")
        )
        return AsrProviderError(
            "asr_provider_unavailable" if retryable else "asr_provider_rejected",
            "云端语音识别服务暂时不可用。" if retryable else "云端语音识别拒绝了这个任务。",
            retryable=retryable,
            status_code=503 if retryable else 422,
            task_id=task_id,
        )

    def _error_from_response(self, response: httpx.Response) -> AsrProviderError:
        try:
            payload = response.json()
        except (ValueError, TypeError):
            payload = {}
        code = str(payload.get("code") or payload.get("error_code") or response.status_code)
        provider_message = str(payload.get("message") or payload.get("error_message") or "")
        return self._normalized_error(
            code,
            provider_message,
            http_status=response.status_code,
        )

    def failure_from_status(self, status: ProviderStatus) -> AsrProviderError:
        safe_code = "".join(
            character
            for character in str(status.error_code or "unknown")
            if character.isalnum() or character in "._-"
        )[:80]
        LOGGER.warning(
            "Aliyun ASR task failed model=%s code=%s",
            self.model,
            safe_code or "unknown",
        )
        return self._normalized_error(
            status.error_code or "TaskFailed",
            status.error_message or "",
            http_status=200,
            task_id=status.task_id,
        )

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        resolve_oss: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        last_error: AsrProviderError | None = None
        normalized_method = method.upper()
        retry_count = self.max_retries if normalized_method in {"GET", "HEAD"} else 0
        request_headers = dict(self._headers)
        if normalized_method == "POST":
            request_headers["X-DashScope-Async"] = "enable"
        if resolve_oss:
            request_headers["X-DashScope-OssResourceResolve"] = "enable"
        for attempt in range(retry_count + 1):
            try:
                response = self.client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=request_headers,
                    **kwargs,
                )
            except httpx.RequestError as exc:
                last_error = AsrProviderError(
                    "asr_provider_unavailable",
                    "无法连接云端语音识别服务。",
                    retryable=True,
                    status_code=503,
                )
                if attempt >= retry_count:
                    raise last_error from exc
            else:
                if 200 <= response.status_code < 300:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise AsrProviderError(
                            "asr_provider_response_invalid",
                            "云端语音识别返回了无法解析的数据。",
                            retryable=True,
                        ) from exc
                    if not isinstance(payload, dict):
                        raise AsrProviderError(
                            "asr_provider_response_invalid",
                            "云端语音识别返回了异常数据结构。",
                            retryable=True,
                        )
                    return payload
                last_error = self._error_from_response(response)
                if not last_error.retryable or attempt >= retry_count:
                    raise last_error
            self.sleep(min(4.0, 0.5 * (2**attempt)))
        raise last_error or AsrProviderError(
            "asr_provider_unavailable",
            "云端语音识别服务暂时不可用。",
            retryable=True,
        )

    def query(self, task_id: str) -> ProviderStatus:
        if not task_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in task_id):
            raise AsrProviderError(
                "asr_provider_response_invalid",
                "云端语音识别任务编号无效。",
                retryable=False,
            )
        payload = self._request_json("GET", f"/tasks/{task_id}")
        return self._parse_status(payload, task_id)

    def download_result(self, status: ProviderStatus) -> Transcript:
        if not status.result_urls:
            raise AsrProviderError(
                "asr_provider_response_invalid",
                "云端语音识别完成但没有返回结果文件。",
                retryable=True,
                task_id=status.task_id,
            )
        transcripts: list[Transcript] = []
        for result_url in status.result_urls:
            try:
                self.result_url_validator(result_url)
            except Exception as exc:
                raise AsrProviderError(
                    "asr_provider_response_invalid",
                    "云端语音识别返回了不安全的结果地址。",
                    retryable=False,
                    task_id=status.task_id,
                ) from exc
            try:
                with self.result_client.stream("GET", result_url) as response:
                    response.raise_for_status()
                    try:
                        content_length = int(response.headers.get("content-length") or 0)
                    except ValueError:
                        content_length = 0
                    if content_length > self.max_result_bytes:
                        raise AsrProviderError(
                            "asr_provider_response_invalid",
                            "云端识别结果文件异常过大。",
                            retryable=False,
                            task_id=status.task_id,
                        )
                    data = bytearray()
                    for chunk in response.iter_bytes(64 * 1024):
                        data.extend(chunk)
                        if len(data) > self.max_result_bytes:
                            raise AsrProviderError(
                                "asr_provider_response_invalid",
                                "云端识别结果文件异常过大。",
                                retryable=False,
                                task_id=status.task_id,
                            )
                payload = httpx.Response(200, content=bytes(data)).json()
            except AsrProviderError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                raise AsrProviderError(
                    "asr_result_download_failed",
                    "云端识别已完成，但结果下载失败。",
                    retryable=True,
                    task_id=status.task_id,
                ) from exc
            if not isinstance(payload, dict):
                raise AsrProviderError(
                    "asr_provider_response_invalid",
                    "云端识别结果格式异常。",
                    retryable=True,
                    task_id=status.task_id,
                )
            transcripts.append(
                normalize_transcript_payload(
                    payload,
                    provider=self.provider_name,
                    model=self.model,
                    task_id=status.task_id,
                    usage_seconds=status.usage_seconds,
                )
            )
        combined = transcripts[0]
        for transcript in transcripts[1:]:
            combined.segments.extend(transcript.segments)
            combined.duration_ms = max(combined.duration_ms, transcript.duration_ms)
            if not combined.language:
                combined.language = transcript.language
        combined.raw_metadata.update(status.raw_metadata)
        return combined

    def _parse_status(self, payload: dict[str, Any], task_id: str) -> ProviderStatus:
        raise NotImplementedError


class AliyunQwenFileTransProvider(_AliyunAsyncProvider):
    def submit(
        self,
        file_url: str,
        *,
        language: str | None = None,
        enable_words: bool = True,
    ) -> ProviderSubmission:
        parameters: dict[str, Any] = {
            "channel_id": [0],
            "enable_itn": True,
            "enable_words": bool(enable_words),
        }
        hint = _language_hint(language)
        if hint:
            parameters["language"] = hint[0]
        payload = self._request_json(
            "POST",
            "/services/audio/asr/transcription",
            resolve_oss=file_url.startswith("oss://"),
            json={
                "model": self.model,
                "input": {"file_url": file_url},
                "parameters": parameters,
            },
        )
        output = payload.get("output")
        output = output if isinstance(output, dict) else {}
        task_id = str(output.get("task_id") or "").strip()
        if not task_id:
            raise AsrProviderError(
                "asr_provider_response_invalid",
                "云端语音识别未返回任务编号。",
                retryable=True,
            )
        return ProviderSubmission(self.provider_name, self.model, task_id, payload.get("request_id"))

    def _parse_status(self, payload: dict[str, Any], task_id: str) -> ProviderStatus:
        output = payload.get("output")
        output = output if isinstance(output, dict) else {}
        status = str(output.get("task_status") or "").upper()
        usage = output.get("usage")
        if not isinstance(usage, dict):
            usage = payload.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        result_url = output.get("result", {}).get("transcription_url") if isinstance(output.get("result"), dict) else None
        error_code = output.get("code") or payload.get("code")
        error_message = output.get("message") or payload.get("message")
        return ProviderStatus(
            status=status,
            task_id=task_id,
            result_urls=(str(result_url),) if result_url else (),
            usage_seconds=_safe_float(usage.get("seconds")),
            request_id=str(payload.get("request_id")) if payload.get("request_id") else None,
            error_code=str(error_code) if error_code else None,
            error_message=str(error_message) if error_message else None,
            raw_metadata={"request_id": payload.get("request_id")},
        )


class AliyunParaformerProvider(_AliyunAsyncProvider):
    def submit(
        self,
        file_url: str,
        *,
        language: str | None = None,
        enable_words: bool = True,
    ) -> ProviderSubmission:
        parameters: dict[str, Any] = {
            "channel_id": [0],
            "disfluency_removal_enabled": False,
            "timestamp_alignment_enabled": bool(enable_words),
            "diarization_enabled": False,
        }
        hints = _language_hint(language)
        if hints:
            parameters["language_hints"] = hints
        payload = self._request_json(
            "POST",
            "/services/audio/asr/transcription",
            resolve_oss=file_url.startswith("oss://"),
            json={
                "model": self.model,
                "input": {"file_urls": [file_url]},
                "parameters": parameters,
            },
        )
        output = payload.get("output")
        output = output if isinstance(output, dict) else {}
        task_id = str(output.get("task_id") or "").strip()
        if not task_id:
            raise AsrProviderError(
                "asr_provider_response_invalid",
                "云端语音识别未返回任务编号。",
                retryable=True,
            )
        return ProviderSubmission(self.provider_name, self.model, task_id, payload.get("request_id"))

    def _parse_status(self, payload: dict[str, Any], task_id: str) -> ProviderStatus:
        output = payload.get("output")
        output = output if isinstance(output, dict) else {}
        status = str(output.get("task_status") or "").upper()
        usage = output.get("usage")
        if not isinstance(usage, dict):
            usage = payload.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        results = output.get("results")
        results = results if isinstance(results, list) else []
        urls = tuple(
            str(item["transcription_url"])
            for item in results
            if isinstance(item, dict)
            and str(item.get("subtask_status") or "SUCCEEDED").upper() == "SUCCEEDED"
            and item.get("transcription_url")
        )
        failed = next(
            (
                item
                for item in results
                if isinstance(item, dict)
                and str(item.get("subtask_status") or "").upper() == "FAILED"
            ),
            None,
        )
        error_code = (failed or {}).get("code") or output.get("code") or payload.get("code")
        error_message = (failed or {}).get("message") or output.get("message") or payload.get("message")
        return ProviderStatus(
            status=status,
            task_id=task_id,
            result_urls=urls,
            usage_seconds=_safe_float(usage.get("duration")),
            request_id=str(payload.get("request_id")) if payload.get("request_id") else None,
            error_code=str(error_code) if error_code else None,
            error_message=str(error_message) if error_message else None,
            raw_metadata={
                "request_id": payload.get("request_id"),
                "subtask_count": len(results),
            },
        )
