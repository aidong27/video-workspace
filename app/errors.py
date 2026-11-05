"""Task failure type, public error catalog, and secret redaction.

Everything a browser can see about a failed task is derived here: internal
``reason`` values are normalized to a small set of stable ``code`` values,
each with a fixed Chinese message. Free-form exception text is redacted
before it is stored or logged so cookies, tokens, and local paths never leak.
"""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\bsk-[A-Za-z0-9._-]{8,}\b"),
    re.compile(r"(?i)\b(authorization|cookie)\s*:\s*[^\r\n]+"),
    re.compile(
        r"(?i)\b("
        r"authorization|cookie|token|access_token|password|passwd|secret|invite_code|qrcode_key|"
        r"sessdata|bili_jct|dedeuserid|dedeuserid__ckmd5|bili_cookie|mstoken|"
        r"x-bogus|x_bogus|a_bogus|auth_key|signature"
        r")([=:])([^;\s&]+)"
    ),
    re.compile(
        r"(?i)([?&]("
        r"authorization|cookie|token|access_token|password|passwd|secret|invite_code|qrcode_key|"
        r"sessdata|bili_jct|dedeuserid|dedeuserid__ckmd5|bili_cookie|mstoken|"
        r"x-bogus|x_bogus|a_bogus|auth_key|signature"
        r")=)[^&\s]+"
    ),
)
LOCAL_PATH_PATTERNS = (
    re.compile(r"(?i)\bfile:///[^\s\"'<>]+"),
    re.compile(r"(?<![A-Za-z0-9:/])/(?:[^\s\"'<>]+(?:/[^\s\"'<>]+)*)"),
    re.compile(r"(?i)\b[A-Z]:[\\/][^\s\"'<>]+"),
)


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact_sensitive(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    if not isinstance(value, str):
        return value
    redacted = value
    for pattern in SENSITIVE_PATTERNS:
        if pattern.groups >= 3:
            redacted = pattern.sub(lambda match: match.group(1) + match.group(2) + "<redacted>", redacted)
        elif pattern.groups == 2:
            redacted = pattern.sub(lambda match: match.group(1) + "<redacted>", redacted)
        else:
            redacted = pattern.sub("<redacted>", redacted)
    for pattern in LOCAL_PATH_PATTERNS:
        redacted = pattern.sub("<local-path>", redacted)
    return redacted


class ExtractionFailure(Exception):
    """A task-level failure with an internal reason and retry hints.

    ``terminal`` failures stop fallback chains (for example an invalid link),
    ``can_try_asr`` lets subtitle extraction continue with speech recognition,
    and ``retryable`` overrides the status-code based retry hint shown to users.
    """

    def __init__(
        self,
        status_code: int,
        detail: str,
        reason: str = "failed",
        can_try_asr: bool = False,
        terminal: bool = False,
        retryable: bool | None = None,
    ) -> None:
        detail = redact_sensitive(detail)
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.reason = reason
        self.can_try_asr = can_try_asr
        self.terminal = terminal
        self.retryable = retryable


def public_reason(reason: str) -> str:
    return {
        "not_found": "video_not_found",
        "timeout": "asr_timeout",
        "audio_extract_failed": "download_failed",
        "subtitle_download_failed": "download_failed",
        "short_link_request_failed": "download_failed",
        "douyin_api_failed": "platform_temporarily_unavailable",
        "douyin_cookie_refresh_failed": "platform_temporarily_unavailable",
        "douyin_media_missing": "download_failed",
        "api_request_failed": "platform_unreachable",
        "api_error": "platform_temporarily_unavailable",
        "api_bad_response": "platform_temporarily_unavailable",
    }.get(reason, reason)


def stable_error_code(reason: str) -> str:
    normalized = public_reason(reason)
    return {
        "invalid_input": "invalid_url",
        "input_too_long": "invalid_url",
        "invalid_page": "invalid_url",
        "invalid_bvid": "invalid_url",
        "short_link_unresolved": "invalid_url",
        "short_link_untrusted": "invalid_url",
        "short_link_loop": "invalid_url",
        "video_not_found": "video_unavailable",
        "no_official_subtitle": "subtitle_unavailable",
        "subtitle_empty": "subtitle_unavailable",
        "empty_subtitle": "subtitle_unavailable",
        "subtitle_parse_failed": "subtitle_unavailable",
        "unsupported_subtitle_format": "subtitle_unavailable",
        "asr_empty": "subtitle_unavailable",
        "ocr_empty": "subtitle_unavailable",
        "audio_stream_missing": "no_audio_stream",
        "upload_audio_missing": "no_audio_stream",
        "audio_extract_failed": "download_failed",
        "download_too_large": "media_too_large",
        "media_convert_failed": "ffmpeg_failed",
        "media_probe_timeout": "ffmpeg_failed",
        "upload_probe_timeout": "ffmpeg_failed",
        "invalid_downloaded_media": "download_failed",
        "queue_full": "job_queue_full",
        "job_not_found": "job_expired",
        "job_cancelled": "task_cancelled",
        "platform_risk_control": "platform_blocked",
        "asr_provider_not_configured": "asr_provider_not_configured",
        "asr_daily_limit_reached": "asr_daily_limit_reached",
        "asr_monthly_limit_reached": "asr_monthly_limit_reached",
        "asr_total_limit_reached": "asr_total_limit_reached",
        "asr_user_daily_limit_reached": "asr_user_daily_limit_reached",
    }.get(normalized, normalized)


USER_ERROR_MESSAGES = {
    "invalid_url": "请输入有效的 B站或抖音视频链接。",
    "unsupported_platform": "暂不支持这个视频平台。",
    "video_unavailable": "视频不存在、已下架或当前账号无权访问。",
    "subtitle_unavailable": "没有找到可读取的字幕或语音内容。",
    "cookie_expired": "B站登录态已失效，请刷新 Cookie 或关闭 Cookie 后重试。",
    "download_failed": "媒体下载或音轨准备失败，请稍后重试。",
    "media_too_large": "媒体文件超过服务器允许的大小。",
    "upload_too_large": "上传文件超过服务器允许的大小。",
    "disk_space_low": "服务器剩余磁盘空间不足，请稍后重试。",
    "no_audio_stream": "视频没有音轨，无法进行语音识别或生成 MP3。",
    "no_subtitle_stream": "视频没有可读取的文本字幕轨。",
    "asr_timeout": "语音识别超时，请缩短视频或稍后重试。",
    "asr_worker_crashed": "语音识别进程意外退出，可能是内存不足；请稍后重试。",
    "asr_model_download_failed": "语音识别模型不可用或下载失败，请检查模型缓存与网络。",
    "asr_failed": "本地语音识别失败，请稍后重试。",
    "asr_busy": "精确处理资源正忙，请稍后重试。",
    "asr_provider_not_configured": "云端语音识别尚未完成配置。",
    "asr_provider_auth_failed": "云端语音识别凭证无效或模型权限不足。",
    "asr_provider_unavailable": "云端语音识别服务暂时不可用，请稍后重试。",
    "asr_temp_upload_failed": "云端临时音频上传失败，请稍后重试。",
    "asr_provider_rejected": "云端语音识别无法处理这个音频。",
    "asr_provider_failed": "云端语音识别任务失败，请稍后重试。",
    "asr_provider_response_invalid": "云端语音识别返回的数据异常，请稍后重试。",
    "asr_result_download_failed": "云端识别已完成，但结果下载失败。",
    "asr_audio_fetch_failed": "云端语音识别无法读取临时音频，请稍后重试。",
    "asr_rate_limited": "云端语音识别请求过于频繁，请稍后重试。",
    "asr_quota_exhausted": "免费额度已用尽，系统未继续产生付费调用。",
    "asr_daily_limit_reached": "今日云端语音识别额度已用尽。",
    "asr_monthly_limit_reached": "本月云端语音识别额度已用尽。",
    "asr_total_limit_reached": "云端语音识别总免费额度保护线已达到。",
    "asr_user_daily_limit_reached": "你今天可使用的云端识别时长已用尽。",
    "ocr_timeout": "画面字幕识别超时，请缩短视频或稍后重试。",
    "ocr_failed": "画面字幕识别失败；有音轨时会自动尝试语音识别。",
    "ocr_missing": "服务器未安装画面字幕识别组件。",
    "ffmpeg_failed": "媒体探测或转换失败，请确认文件可正常播放。",
    "ffmpeg_missing": "服务器缺少 FFmpeg 或 ffprobe。",
    "job_queue_full": "任务队列已满，请稍后重试。",
    "job_expired": "服务可能已重启或任务已过期，请重新提交。",
    "task_cancelled": "任务已取消。",
    "invalid_upload_media": "上传文件不是可读取的视频媒体。",
    "upload_video_missing": "上传文件中没有视频轨。",
    "asr_duration_too_long": "视频时长超过当前服务器的处理限制。",
    "cookie_required": "此视频需要有效的 B站登录态。",
    "platform_temporarily_unavailable": "平台暂时拒绝了请求，请稍后重试。",
    "platform_unreachable": "暂时无法连接视频平台，请稍后重试。",
    "platform_blocked": "B站当前拒绝了本站的访问（平台风控）。可以改为上传本地视频，或稍后再试。",
    "douyin_browser_busy": "抖音浏览器资源正忙，请稍后重试。",
}


def error_retryable(status_code: int, code: str, override: bool | None = None) -> bool:
    if override is not None:
        return override
    if code in {"invalid_url", "unsupported_platform", "video_unavailable", "media_too_large", "upload_too_large"}:
        return False
    return status_code in {408, 409, 425, 429, 500, 502, 503, 504, 507}


def failure_user_message(exc: ExtractionFailure) -> str:
    return USER_ERROR_MESSAGES.get(stable_error_code(exc.reason), "平台字幕不可用。")
