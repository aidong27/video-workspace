import base64
import asyncio
import copy
from contextlib import contextmanager
from difflib import SequenceMatcher
import errno
import gc
import hashlib
from http.cookies import SimpleCookie
import importlib.util
from io import BytesIO
import json
import logging
import math
from multiprocessing import get_context
import os
from pathlib import Path
from queue import Empty, Full
import re
import resource
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
from threading import BoundedSemaphore, Lock, Thread, local
import time
import urllib.parse
import wave
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Literal
from urllib.parse import quote, urljoin

import httpx
import qrcode
import qrcode.image.svg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect
from yt_dlp import YoutubeDL

from app.asr.aliyun import (
    AliyunParaformerProvider,
    AliyunQwenFileTransProvider,
    AliyunTemporaryFileUploader,
)
from app.asr.base import AsrProvider, AsrProviderError, Transcript
from app.asr.postprocess import normalize_segments
from app.asr.signing import SignedAudioError, SignedAudioStore
from app.asr.usage import UsageLedger, UsageLimitExceeded
from app.auth import (
    AuthFailure,
    SESSION_COOKIE_NAME,
    account_summary,
    auth_error,
    change_password,
    clear_session_cookie,
    create_session,
    delete_session,
    delete_user_sessions,
    initialize_auth_db,
    invite_configured,
    max_sessions_per_user,
    register_user,
    require_auth_user,
    resolve_session,
    authenticate_user,
    session_ttl_seconds,
    set_session_cookie,
)

from app.douyin import (
    DOUYIN_ADAPTER_VERSION,
    DouyinAdapterError,
    DouyinVideo,
    adapter_status as douyin_adapter_status,
    download_douyin_media,
    fetch_douyin_subtitle,
    get_douyin_video,
    is_douyin_url,
    normalize_douyin_input,
)
from app.jobs import (
    JobIdempotencyConflict,
    JobManager,
    JobNotFound,
    JobQueueFull,
    job_request_fingerprint,
)
from app.network import validate_public_request
from app.processes import (
    LimitedStreamCapture,
    ManagedProcessTimeout,
    run_managed_process,
    terminate_child_process,
    terminate_child_process_group,
    terminate_process,
    terminate_process_id,
)


LOGGER = logging.getLogger(__name__)
load_dotenv()


@dataclass
class ResultKeyLockEntry:
    lock: Lock
    references: int = 0


APP_TITLE = os.getenv("APP_TITLE", "Video Workspace")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0-beta.4")
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_INPUT_LENGTH = 512
LOCAL_MEDIA_PROTOCOL_WHITELIST = "file,crypto,data"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

PUBLIC_RESULT_METADATA_FIELDS = frozenset(
    {
        "title",
        "id",
        "webpage_url",
        "source",
        "track_source_type",
        "language",
        "subtitle_format",
        "warning",
        "note",
        "duration",
        "platform",
        "author",
        "quality",
        "asr_mode",
        "requested_asr_mode",
        "requested_source",
        "requested_quality",
        "embedded_subtitles_requested",
        "ocr_fallback_to_asr",
        "subtitle_source",
        "subtitle_stream_language",
        "quality_warning",
        "cache_hit",
        "entry_count",
        "character_count",
        "elapsed_seconds",
        "processing_seconds",
        "force_refresh",
        "media_type",
        "media_bytes",
        "source_container",
        "artifact_ttl_seconds",
        "original_filename",
        "uploaded_bytes",
        "input_type",
    }
)
ASR_TMP_DIR = Path(os.getenv("ASR_TMP_DIR", "/opt/bili-subtitle-tool/var/tmp"))
ASR_MODEL_DIR = Path(os.getenv("ASR_MODEL_DIR", "/opt/bili-subtitle-tool/var/models"))
ASR_CACHE_DIR = Path(os.getenv("ASR_CACHE_DIR", "/opt/bili-subtitle-tool/var/cache"))
RESULT_CACHE_DIR = Path(os.getenv("RESULT_CACHE_DIR", str(ASR_CACHE_DIR / "results")))
BILI_COOKIE_PATH = Path(
    os.getenv("BILI_COOKIE_PATH", "/opt/bili-subtitle-tool/var/auth/bili-cookie.txt")
)
DEFAULT_ASR_MODEL = os.getenv("ASR_MODEL", "small").strip() or "small"
ASR_COMPUTE_TYPE = os.getenv("ASR_COMPUTE_TYPE", "int8").strip() or "int8"
ASR_DEVICE = os.getenv("ASR_DEVICE", "cpu").strip() or "cpu"
ASR_CPU_THREADS = max(1, int(os.getenv("ASR_CPU_THREADS", "3")))
ASR_TIMEOUT_SECONDS = max(30, int(os.getenv("ASR_TIMEOUT_SECONDS", "1800")))
ACCURATE_ASR_MODEL = os.getenv("ASR_ACCURATE_MODEL", DEFAULT_ASR_MODEL).strip() or DEFAULT_ASR_MODEL
ACCURATE_ASR_COMPUTE_TYPE = (
    os.getenv("ASR_ACCURATE_COMPUTE_TYPE", ASR_COMPUTE_TYPE).strip() or ASR_COMPUTE_TYPE
)
ACCURATE_ASR_DEVICE = os.getenv("ASR_ACCURATE_DEVICE", ASR_DEVICE).strip() or ASR_DEVICE
ACCURATE_ASR_CPU_THREADS = max(
    1,
    int(os.getenv("ASR_ACCURATE_CPU_THREADS", str(ASR_CPU_THREADS))),
)
ACCURATE_ASR_TIMEOUT_SECONDS = max(
    ASR_TIMEOUT_SECONDS,
    int(os.getenv("ASR_ACCURATE_TIMEOUT_SECONDS", "3600")),
)
ASR_FAST_BEAM_SIZE = min(10, max(1, int(os.getenv("ASR_FAST_BEAM_SIZE", "3"))))
ACCURATE_ASR_BEAM_SIZE = min(10, max(1, int(os.getenv("ASR_ACCURATE_BEAM_SIZE", "5"))))
ASR_DOWNLOAD_TIMEOUT_SECONDS = max(30, int(os.getenv("ASR_DOWNLOAD_TIMEOUT_SECONDS", "300")))
ASR_QUEUE_WAIT_SECONDS = max(30, int(os.getenv("ASR_QUEUE_WAIT_SECONDS", "1800")))
ASR_MAX_AUDIO_SECONDS = max(30, int(os.getenv("ASR_MAX_AUDIO_SECONDS", "3600")))
ASR_PROMPT_MAX_CHARS = min(1000, max(50, int(os.getenv("ASR_PROMPT_MAX_CHARS", "300"))))
try:
    ASR_VAD_THRESHOLD = min(0.95, max(0.05, float(os.getenv("ASR_VAD_THRESHOLD", "0.45"))))
except ValueError:
    ASR_VAD_THRESHOLD = 0.45
ASR_VAD_MIN_SILENCE_MS = max(100, int(os.getenv("ASR_VAD_MIN_SILENCE_MS", "700")))
ASR_VAD_SPEECH_PAD_MS = max(0, int(os.getenv("ASR_VAD_SPEECH_PAD_MS", "300")))
try:
    ASR_LOW_LOGPROB_THRESHOLD = float(os.getenv("ASR_LOW_LOGPROB_THRESHOLD", "-1.0"))
except ValueError:
    ASR_LOW_LOGPROB_THRESHOLD = -1.0
try:
    ASR_RETRY_REPETITION_RATIO = min(
        1.0,
        max(0.0, float(os.getenv("ASR_RETRY_REPETITION_RATIO", "0.25"))),
    )
except ValueError:
    ASR_RETRY_REPETITION_RATIO = 0.25
try:
    ASR_RETRY_LOW_CONFIDENCE_RATIO = min(
        1.0,
        max(0.0, float(os.getenv("ASR_RETRY_LOW_CONFIDENCE_RATIO", "0.65"))),
    )
except ValueError:
    ASR_RETRY_LOW_CONFIDENCE_RATIO = 0.65
BILI_MAX_DOWNLOAD_BYTES = max(10_000_000, int(os.getenv("BILI_MAX_DOWNLOAD_BYTES", "1000000000")))
UPLOAD_MAX_BYTES = max(1_000_000, int(os.getenv("UPLOAD_MAX_BYTES", "536870912")))
PUBLIC_UPLOAD_MAX_BYTES = min(
    UPLOAD_MAX_BYTES,
    max(1_000_000, int(os.getenv("PUBLIC_UPLOAD_MAX_BYTES", str(UPLOAD_MAX_BYTES)))),
)
UPLOAD_STAGING_MAX_BYTES = max(
    UPLOAD_MAX_BYTES,
    int(os.getenv("UPLOAD_STAGING_MAX_BYTES", "2147483648")),
)
MEDIA_ARTIFACT_DIR = Path(
    os.getenv("MEDIA_ARTIFACT_DIR", str(ASR_TMP_DIR / "media-artifacts"))
)
MEDIA_MAX_BYTES = max(10_000_000, int(os.getenv("MEDIA_MAX_BYTES", "1000000000")))
MEDIA_STAGING_MAX_BYTES = max(
    MEDIA_MAX_BYTES,
    int(os.getenv("MEDIA_STAGING_MAX_BYTES", "8000000000")),
)
ASR_CONCURRENCY_LIMIT = max(
    1,
    int(os.getenv("ASR_JOB_CONCURRENCY", os.getenv("ASR_CONCURRENCY_LIMIT", "1"))),
)
ASR_TMP_MAX_AGE_SECONDS = max(300, int(os.getenv("ASR_TMP_MAX_AGE_SECONDS", "86400")))
RESULT_CACHE_TTL_SECONDS = max(
    0,
    int(
        os.getenv(
            "RESULT_CACHE_TTL_SECONDS",
            str(max(1, int(os.getenv("TRANSCRIPT_RETENTION_DAYS", "7"))) * 86400),
        )
    ),
)
RESULT_CACHE_MAX_ITEMS = max(1, int(os.getenv("RESULT_CACHE_MAX_ITEMS", "100")))
JOB_QUEUE_MAX_PENDING = max(1, int(os.getenv("JOB_QUEUE_MAX_PENDING", "4")))
JOB_RESULT_TTL_SECONDS = max(60, int(os.getenv("JOB_RESULT_TTL_SECONDS", "3600")))
JOB_STATE_DB_PATH = Path(os.getenv("JOB_STATE_DB_PATH", str(ASR_CACHE_DIR / "jobs.db")))
MEDIA_ARTIFACT_TTL_SECONDS = max(
    60,
    int(os.getenv("MEDIA_ARTIFACT_TTL_SECONDS", str(JOB_RESULT_TTL_SECONDS))),
)
JOB_MAX_RECORDS = max(10, int(os.getenv("JOB_MAX_RECORDS", "100")))
JOB_WORKER_COUNT = max(1, int(os.getenv("JOB_WORKER_COUNT", "2")))
LEGACY_WAIT_TIMEOUT_SECONDS = max(30, int(os.getenv("LEGACY_WAIT_TIMEOUT_SECONDS", "1200")))
OCR_TIMEOUT_SECONDS = max(60, int(os.getenv("OCR_TIMEOUT_SECONDS", "1800")))
OCR_SAMPLE_FPS = min(5.0, max(0.5, float(os.getenv("OCR_SAMPLE_FPS", "1.5"))))
OCR_CROP_TOP_RATIO = min(0.75, max(0.2, float(os.getenv("OCR_CROP_TOP_RATIO", "0.45"))))
OCR_MIN_CONFIDENCE = min(0.95, max(0.1, float(os.getenv("OCR_MIN_CONFIDENCE", "0.55"))))
OCR_CPU_THREADS = max(1, int(os.getenv("OCR_CPU_THREADS", "1")))
OCR_MAX_FRAMES = max(100, int(os.getenv("OCR_MAX_FRAMES", "12000")))
MIN_FREE_DISK_BYTES = max(0, int(os.getenv("MIN_FREE_DISK_BYTES", "2147483648")))
try:
    MIN_FREE_DISK_RATIO = min(0.95, max(0.0, float(os.getenv("MIN_FREE_DISK_RATIO", "0.05"))))
except ValueError:
    MIN_FREE_DISK_RATIO = 0.05
PROCESS_ERROR_OUTPUT_BYTES = max(1024, int(os.getenv("PROCESS_ERROR_OUTPUT_BYTES", "16384")))
try:
    ASR_TIMEOUT_PER_AUDIO_SECOND = max(0.0, float(os.getenv("ASR_TIMEOUT_PER_AUDIO_SECOND", "0.5")))
except ValueError:
    ASR_TIMEOUT_PER_AUDIO_SECOND = 0.5
try:
    ACCURATE_ASR_TIMEOUT_PER_AUDIO_SECOND = max(
        0.0,
        float(os.getenv("ASR_ACCURATE_TIMEOUT_PER_AUDIO_SECOND", "1.5")),
    )
except ValueError:
    ACCURATE_ASR_TIMEOUT_PER_AUDIO_SECOND = 1.5
ASR_MAX_TIMEOUT_SECONDS = max(
    ACCURATE_ASR_TIMEOUT_SECONDS,
    int(os.getenv("ASR_MAX_TIMEOUT_SECONDS", "7200")),
)
CLOUD_ASR_DEFAULT_MODEL = (
    os.getenv("ASR_DEFAULT_MODEL", "qwen3-asr-flash-filetrans").strip()
    or "qwen3-asr-flash-filetrans"
)
CLOUD_ASR_ECONOMY_MODEL = (
    os.getenv("ASR_ECONOMY_MODEL", "paraformer-v2").strip()
    or "paraformer-v2"
)
CLOUD_ASR_TIMEOUT_SECONDS = max(
    60,
    int(os.getenv("CLOUD_ASR_TIMEOUT_SECONDS", "1800")),
)
CLOUD_ASR_HTTP_TIMEOUT_SECONDS = max(
    5,
    int(os.getenv("CLOUD_ASR_HTTP_TIMEOUT_SECONDS", "30")),
)
CLOUD_ASR_MAX_FILE_BYTES = max(
    1_000_000,
    int(os.getenv("CLOUD_ASR_MAX_FILE_BYTES", "268435456")),
)
CLOUD_ASR_AUDIO_DELIVERY = (
    os.getenv("CLOUD_ASR_AUDIO_DELIVERY", "signed_url").strip().lower()
    or "signed_url"
)
CLOUD_ASR_UPLOAD_TIMEOUT_SECONDS = max(
    30,
    int(os.getenv("CLOUD_ASR_UPLOAD_TIMEOUT_SECONDS", "300")),
)
CLOUD_TEMP_AUDIO_RETENTION_SECONDS = 48 * 60 * 60
CLOUD_ASR_USAGE_DB_PATH = Path(
    os.getenv("ASR_USAGE_DB_PATH", str(ASR_CACHE_DIR / "cloud-usage.db"))
)
CLOUD_ASR_MONTHLY_FREE_SECONDS = max(
    0,
    int(os.getenv("ASR_MONTHLY_FREE_SECONDS", "0")),
)
CLOUD_ASR_MONTHLY_HARD_LIMIT_SECONDS = max(
    0,
    int(os.getenv("ASR_MONTHLY_HARD_LIMIT_SECONDS", "0")),
)
CLOUD_ASR_TOTAL_HARD_LIMIT_SECONDS = max(
    0,
    int(os.getenv("ASR_TOTAL_HARD_LIMIT_SECONDS", "0")),
)
CLOUD_ASR_DAILY_HARD_LIMIT_SECONDS = max(
    0,
    int(os.getenv("ASR_DAILY_HARD_LIMIT_SECONDS", "0")),
)
CLOUD_ASR_USER_DAILY_HARD_LIMIT_SECONDS = max(
    0,
    int(os.getenv("ASR_USER_DAILY_HARD_LIMIT_SECONDS", "0")),
)
CLOUD_AUDIO_TTL_SECONDS = max(
    60,
    min(3600, int(os.getenv("TEMP_AUDIO_TTL_SECONDS", "1800"))),
)
try:
    CLOUD_ASR_QWEN_PRICE_PER_SECOND = max(
        0.0,
        float(os.getenv("ASR_QWEN_PRICE_PER_SECOND", "0.00022")),
    )
except ValueError:
    CLOUD_ASR_QWEN_PRICE_PER_SECOND = 0.00022
try:
    CLOUD_ASR_PARAFORMER_PRICE_PER_SECOND = max(
        0.0,
        float(os.getenv("ASR_PARAFORMER_PRICE_PER_SECOND", "0.00008")),
    )
except ValueError:
    CLOUD_ASR_PARAFORMER_PRICE_PER_SECOND = 0.00008
RESULT_CACHE_VERSION = 11
ASR_PIPELINE_VERSION = 2
CLOUD_ASR_PIPELINE_VERSION = 2
ASR_SELECTION_VERSION = 1
ASR_PROMPT_VERSION = 1
ASR_VAD_PROFILE_VERSION = 1
ASR_AUDIO_FILTER_VERSION = 1
ASR_QUALITY_METRICS_VERSION = 1
OCR_PIPELINE_VERSION = 1
ASR_SEMAPHORE = BoundedSemaphore(ASR_CONCURRENCY_LIMIT)
LEGACY_REQUEST_SEMAPHORE = BoundedSemaphore(max(1, min(2, JOB_WORKER_COUNT)))
RESULT_CACHE_LOCK = Lock()
RESULT_KEY_LOCKS: dict[str, ResultKeyLockEntry] = {}
ASR_WORKER_LOCK = Lock()
ASR_WORKER_PROCESS: Any = None
ASR_WORKER_REQUEST_QUEUE: Any = None
ASR_WORKER_RESULT_QUEUE: Any = None
ASR_WORKER_READY_EVENT: Any = None
ASR_WORKER_WARM = False
ASR_WORKER_START_COUNT = 0
ASR_WORKER_MODEL_KEY: tuple[str, str, str, int] | None = None
ASR_PREWARM_THREAD: Thread | None = None
_ASR_MODEL_KEY: tuple[str, str, str, int] | None = None
_ASR_MODEL_INSTANCE: Any = None
_ASR_MODEL_LOCK = Lock()
CLOUD_PROVIDER_LOCK = Lock()
CLOUD_PROVIDER_INSTANCES: dict[str, AsrProvider] = {}
CLOUD_SIGNED_AUDIO_STORE: SignedAudioStore | None = None
CLOUD_TEMP_FILE_UPLOADER: AliyunTemporaryFileUploader | None = None
CLOUD_USAGE_LEDGER: UsageLedger | None = None
CLOUD_ASR_INIT_ERROR: str | None = None
PROGRESS_CONTEXT = local()
JOB_OWNER_CONTEXT = local()
UPLOAD_RESERVATION_LOCK = Lock()
UPLOAD_RESERVATIONS: dict[str, int] = {}
MEDIA_RESERVATION_LOCK = Lock()
MEDIA_RESERVATIONS: dict[str, int] = {}
os.environ.setdefault("HF_HOME", str(ASR_CACHE_DIR / "hf"))
os.environ.setdefault("XDG_CACHE_HOME", str(ASR_CACHE_DIR))
os.environ.setdefault("OMP_NUM_THREADS", "3")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")
if os.getenv("HF_ENDPOINT"):
    os.environ.setdefault("HF_ENDPOINT", os.getenv("HF_ENDPOINT", ""))
if os.getenv("HF_HUB_DISABLE_XET"):
    os.environ.setdefault("HF_HUB_DISABLE_XET", os.getenv("HF_HUB_DISABLE_XET", ""))

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]
LOGIN_QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
LOGIN_QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
LOGIN_COOKIE_NAMES = (
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "sid",
    "buvid3",
    "buvid4",
)
QR_LOGIN_SESSIONS: dict[str, float] = {}
QR_LOGIN_LOCK = Lock()
BILI_URL_RE = re.compile(
    r"(https?://(?:www\.)?(?:bilibili\.com|b23\.tv)[^\s<>'\"]+|"
    r"(?:www\.)?(?:bilibili\.com|b23\.tv)/[^\s<>'\"]+)",
    re.IGNORECASE,
)
TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？、)]}）】》"
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
UPLOAD_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
MEDIA_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
UPLOAD_ALLOWED_EXTENSIONS = frozenset(
    {
        ".3gp",
        ".avi",
        ".flv",
        ".m2ts",
        ".m4v",
        ".mkv",
        ".mov",
        ".mp4",
        ".mpeg",
        ".mpg",
        ".mts",
        ".ts",
        ".webm",
        ".wmv",
    }
)


class ExtractRequest(BaseModel):
    input: str = Field(..., min_length=2, max_length=MAX_INPUT_LENGTH)
    source: Literal["auto", "official", "asr"] = "auto"
    use_cookie: bool = False
    format: Literal["txt", "srt", "json", "markdown", "md", "vtt"] = "txt"
    lang: str | None = Field(
        default="zh",
        max_length=35,
        pattern=r"^[A-Za-z]{2,8}(?:[-_][A-Za-z0-9]{1,8})*$",
    )
    hotwords: str | None = Field(default=None, max_length=ASR_PROMPT_MAX_CHARS)
    allow_platform_ai: bool = True
    quality: Literal["fast", "accurate"] = "accurate"
    asr_mode: Literal["auto", "high_accuracy", "economy"] = "auto"
    embedded_subtitles: bool = False
    force_refresh: bool = False


class UploadJobRequest(BaseModel):
    kind: Literal["upload"] = "upload"
    upload_token: str = Field(..., pattern=r"^[0-9a-f]{32}$")
    stored_name: str = Field(..., pattern=r"^source\.[A-Za-z0-9]{2,5}$", max_length=16)
    filename: str = Field(..., min_length=1, max_length=180)
    sha256: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    size: int = Field(..., gt=0)
    format: Literal["txt", "srt", "json", "markdown", "md", "vtt"] = "txt"
    lang: str | None = Field(
        default="zh",
        max_length=35,
        pattern=r"^[A-Za-z]{2,8}(?:[-_][A-Za-z0-9]{1,8})*$",
    )
    hotwords: str | None = Field(default=None, max_length=ASR_PROMPT_MAX_CHARS)
    quality: Literal["fast", "accurate"] = "accurate"
    asr_mode: Literal["auto", "high_accuracy", "economy"] = "auto"
    embedded_subtitles: bool = False
    force_refresh: bool = False


class MediaRequest(BaseModel):
    input: str = Field(..., min_length=2, max_length=MAX_INPUT_LENGTH)
    media_type: Literal["video", "audio"]
    use_cookie: bool = False
    force_refresh: bool = False


class MediaJobRequest(MediaRequest):
    kind: Literal["media"] = "media"
    artifact_token: str = Field(..., pattern=r"^[0-9a-f]{32}$")
    owner_id: int = Field(..., gt=0)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=8, max_length=128)
    invite_code: str = Field(..., min_length=4, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


@dataclass
class SubtitleTrack:
    source_type: str
    language: str
    ext: str
    url: str
    name: str | None = None
    provider: str = "bilibili"
    context: Any = None


@dataclass
class SubtitleEntry:
    start: float
    end: float
    text: str


@dataclass
class ExtractionSource:
    title: str | None
    video_id: str | None
    webpage_url: str
    tracks: list[SubtitleTrack]
    note: str | None = None
    duration: float | None = None
    platform: str = "bilibili"
    author: str | None = None


class ExtractionFailure(Exception):
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


@dataclass(frozen=True)
class DiskSpaceStatus:
    total_bytes: int
    free_bytes: int
    free_ratio: float
    minimum_free_bytes: int
    required_bytes: int
    available: bool


def disk_space_status(path: Path, required_bytes: int = 0) -> DiskSpaceStatus:
    anchor = path
    while not anchor.exists() and anchor != anchor.parent:
        anchor = anchor.parent
    usage = shutil.disk_usage(anchor)
    minimum = max(MIN_FREE_DISK_BYTES, math.ceil(usage.total * MIN_FREE_DISK_RATIO))
    required = max(0, int(required_bytes))
    return DiskSpaceStatus(
        total_bytes=usage.total,
        free_bytes=usage.free,
        free_ratio=usage.free / usage.total if usage.total else 0.0,
        minimum_free_bytes=minimum,
        required_bytes=required,
        available=usage.free >= minimum + required,
    )


def ensure_disk_space(path: Path, required_bytes: int = 0) -> DiskSpaceStatus:
    try:
        status = disk_space_status(path, required_bytes)
    except OSError as exc:
        raise ExtractionFailure(
            507,
            "无法确认服务器剩余磁盘空间，请稍后重试。",
            "disk_space_low",
            retryable=True,
        ) from exc
    if not status.available:
        raise ExtractionFailure(
            507,
            "服务器剩余磁盘空间不足，暂时不能开始这个任务。",
            "disk_space_low",
            retryable=True,
        )
    return status


def disk_space_http_error(path: Path, required_bytes: int = 0) -> None:
    try:
        ensure_disk_space(path, required_bytes)
    except ExtractionFailure as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "reason": exc.reason,
                "code": "disk_space_low",
                "message": exc.detail,
                "retryable": True,
            },
        ) from exc


class QuietYtdlpLogger:
    def debug(self, msg: str) -> None:
        return None

    def warning(self, msg: str) -> None:
        return None

    def error(self, msg: str) -> None:
        return None


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def local_asr_enabled() -> bool:
    return env_bool("LOCAL_ASR_ENABLED", env_bool("ASR_ENABLED", False))


def cloud_asr_enabled() -> bool:
    return env_bool("CLOUD_ASR_ENABLED", False)


def any_asr_enabled() -> bool:
    return cloud_asr_enabled() or local_asr_enabled()


def selected_asr_backend(mode: str) -> Literal["local", "cloud"] | None:
    if mode in {"high_accuracy", "economy"}:
        return "cloud" if cloud_asr_enabled() else None
    if local_asr_enabled():
        return "local"
    if cloud_asr_enabled():
        return "cloud"
    return None


def asr_unavailable_failure(mode: str) -> ExtractionFailure:
    if mode in {"high_accuracy", "economy"}:
        return ExtractionFailure(
            503,
            "The selected cloud ASR mode is not configured.",
            "asr_provider_not_configured",
            retryable=False,
        )
    return ExtractionFailure(
        503,
        "No ASR provider is enabled.",
        "asr_disabled",
        retryable=False,
    )


def ensure_selected_asr_ready(mode: str) -> Literal["local", "cloud"]:
    backend = selected_asr_backend(mode)
    if backend == "local":
        ensure_asr_ready()
        return backend
    if backend == "cloud":
        ensure_cloud_asr_ready()
        return backend
    raise asr_unavailable_failure(mode)


def cloud_model_for_mode(mode: str) -> str:
    return CLOUD_ASR_ECONOMY_MODEL if mode == "economy" else CLOUD_ASR_DEFAULT_MODEL


def cloud_model_price(model: str) -> float:
    if model == CLOUD_ASR_ECONOMY_MODEL:
        return CLOUD_ASR_PARAFORMER_PRICE_PER_SECOND
    return CLOUD_ASR_QWEN_PRICE_PER_SECOND


def close_cloud_providers() -> None:
    global CLOUD_TEMP_FILE_UPLOADER
    with CLOUD_PROVIDER_LOCK:
        providers = list(CLOUD_PROVIDER_INSTANCES.values())
        CLOUD_PROVIDER_INSTANCES.clear()
        uploader = CLOUD_TEMP_FILE_UPLOADER
        CLOUD_TEMP_FILE_UPLOADER = None
    for provider in providers:
        close = getattr(provider, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
    if uploader is not None:
        try:
            uploader.close()
        except Exception:
            pass


def cloud_audio_delivery_ready() -> bool:
    if CLOUD_ASR_AUDIO_DELIVERY == "signed_url":
        return CLOUD_SIGNED_AUDIO_STORE is not None
    if CLOUD_ASR_AUDIO_DELIVERY == "aliyun_temp":
        return CLOUD_TEMP_FILE_UPLOADER is not None
    return False


def initialize_cloud_services() -> None:
    global CLOUD_ASR_INIT_ERROR, CLOUD_SIGNED_AUDIO_STORE
    global CLOUD_TEMP_FILE_UPLOADER, CLOUD_USAGE_LEDGER
    close_cloud_providers()
    CLOUD_ASR_INIT_ERROR = None
    CLOUD_SIGNED_AUDIO_STORE = None
    CLOUD_TEMP_FILE_UPLOADER = None
    CLOUD_USAGE_LEDGER = None
    if not cloud_asr_enabled():
        return
    try:
        api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        base_url = os.getenv("DASHSCOPE_BASE_URL", "").strip()
        workspace_id = os.getenv("DASHSCOPE_WORKSPACE_ID", "").strip()
        signing_secret = os.getenv("AUDIO_SIGNING_SECRET", "")
        public_base_url = os.getenv("PUBLIC_BASE_URL", "").strip()
        if not api_key or not base_url or not workspace_id:
            raise ValueError("DashScope credentials are incomplete")
        if not env_bool("ASR_ALLOW_PAID", False):
            if not CLOUD_ASR_MONTHLY_FREE_SECONDS:
                raise ValueError("ASR_MONTHLY_FREE_SECONDS must be configured when paid calls are disabled")
            if CLOUD_ASR_MONTHLY_HARD_LIMIT_SECONDS > CLOUD_ASR_MONTHLY_FREE_SECONDS:
                raise ValueError("monthly hard limit exceeds the configured free allowance")
            if not CLOUD_ASR_TOTAL_HARD_LIMIT_SECONDS:
                raise ValueError("ASR_TOTAL_HARD_LIMIT_SECONDS must be configured when paid calls are disabled")
            if CLOUD_ASR_TOTAL_HARD_LIMIT_SECONDS > CLOUD_ASR_MONTHLY_FREE_SECONDS:
                raise ValueError("total hard limit exceeds the configured free allowance")
        if not CLOUD_ASR_MONTHLY_HARD_LIMIT_SECONDS:
            raise ValueError("ASR_MONTHLY_HARD_LIMIT_SECONDS must be configured")
        if not CLOUD_ASR_DAILY_HARD_LIMIT_SECONDS:
            raise ValueError("ASR_DAILY_HARD_LIMIT_SECONDS must be configured")
        if not CLOUD_ASR_USER_DAILY_HARD_LIMIT_SECONDS:
            raise ValueError("ASR_USER_DAILY_HARD_LIMIT_SECONDS must be configured")
        if CLOUD_ASR_AUDIO_DELIVERY == "signed_url":
            CLOUD_SIGNED_AUDIO_STORE = SignedAudioStore(
                root=ASR_TMP_DIR,
                public_base_url=public_base_url,
                secret=signing_secret,
                default_ttl_seconds=CLOUD_AUDIO_TTL_SECONDS,
            )
        elif CLOUD_ASR_AUDIO_DELIVERY == "aliyun_temp":
            CLOUD_TEMP_FILE_UPLOADER = AliyunTemporaryFileUploader(
                api_key=api_key,
                timeout_seconds=CLOUD_ASR_UPLOAD_TIMEOUT_SECONDS,
            )
        else:
            raise ValueError("CLOUD_ASR_AUDIO_DELIVERY is invalid")
        CLOUD_USAGE_LEDGER = UsageLedger(
            CLOUD_ASR_USAGE_DB_PATH,
            daily_limit_seconds=CLOUD_ASR_DAILY_HARD_LIMIT_SECONDS,
            monthly_limit_seconds=CLOUD_ASR_MONTHLY_HARD_LIMIT_SECONDS,
            user_daily_limit_seconds=CLOUD_ASR_USER_DAILY_HARD_LIMIT_SECONDS,
            total_limit_seconds=CLOUD_ASR_TOTAL_HARD_LIMIT_SECONDS,
            reservation_ttl_seconds=CLOUD_ASR_TIMEOUT_SECONDS + 900,
        )
        CLOUD_USAGE_LEDGER.initialize()
    except Exception as exc:
        close_cloud_providers()
        CLOUD_SIGNED_AUDIO_STORE = None
        CLOUD_USAGE_LEDGER = None
        CLOUD_ASR_INIT_ERROR = type(exc).__name__
        LOGGER.error("cloud ASR initialization failed error_type=%s", type(exc).__name__)


def ensure_cloud_asr_ready() -> None:
    if not cloud_asr_enabled():
        raise ExtractionFailure(
            503,
            "Cloud ASR is disabled.",
            "asr_disabled",
            retryable=False,
        )
    if (
        CLOUD_ASR_INIT_ERROR
        or not cloud_audio_delivery_ready()
        or CLOUD_USAGE_LEDGER is None
    ):
        raise ExtractionFailure(
            503,
            "Cloud ASR configuration is incomplete.",
            "asr_provider_not_configured",
            retryable=False,
        )
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ExtractionFailure(
            503,
            "Cloud ASR audio preparation requires ffmpeg and ffprobe.",
            "ffmpeg_missing",
            retryable=False,
        )


def cloud_provider_for_mode(mode: str) -> AsrProvider:
    ensure_cloud_asr_ready()
    model = cloud_model_for_mode(mode)
    with CLOUD_PROVIDER_LOCK:
        existing = CLOUD_PROVIDER_INSTANCES.get(model)
        if existing is not None:
            return existing
        options = {
            "api_key": os.getenv("DASHSCOPE_API_KEY", "").strip(),
            "base_url": os.getenv("DASHSCOPE_BASE_URL", "").strip(),
            "model": model,
            "timeout_seconds": CLOUD_ASR_HTTP_TIMEOUT_SECONDS,
            "max_retries": 2,
        }
        if mode == "economy":
            provider: AsrProvider = AliyunParaformerProvider(**options)
        else:
            provider = AliyunQwenFileTransProvider(**options)
        CLOUD_PROVIDER_INSTANCES[model] = provider
        return provider


def cloud_usage_stats() -> dict[str, Any]:
    if CLOUD_USAGE_LEDGER is None:
        return {
            "daily_seconds": 0,
            "monthly_seconds": 0,
            "total_seconds": 0,
            "reserved_seconds": 0,
            "daily_limit_seconds": CLOUD_ASR_DAILY_HARD_LIMIT_SECONDS,
            "monthly_limit_seconds": CLOUD_ASR_MONTHLY_HARD_LIMIT_SECONDS,
            "user_daily_limit_seconds": CLOUD_ASR_USER_DAILY_HARD_LIMIT_SECONDS,
            "total_limit_seconds": CLOUD_ASR_TOTAL_HARD_LIMIT_SECONDS,
            "by_model_seconds": {},
        }
    try:
        return CLOUD_USAGE_LEDGER.stats()
    except Exception as exc:
        LOGGER.error("cloud ASR usage status failed error_type=%s", type(exc).__name__)
        return {
            "daily_seconds": None,
            "monthly_seconds": None,
            "total_seconds": None,
            "reserved_seconds": None,
            "daily_limit_seconds": CLOUD_ASR_DAILY_HARD_LIMIT_SECONDS,
            "monthly_limit_seconds": CLOUD_ASR_MONTHLY_HARD_LIMIT_SECONDS,
            "user_daily_limit_seconds": CLOUD_ASR_USER_DAILY_HARD_LIMIT_SECONDS,
            "total_limit_seconds": CLOUD_ASR_TOTAL_HARD_LIMIT_SECONDS,
            "by_model_seconds": {},
        }


def sanitize_asr_context(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"https?://\S+", " ", str(value), flags=re.IGNORECASE)
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;，；")
    return cleaned[:ASR_PROMPT_MAX_CHARS] or None


def asr_context(
    title: str | None = None,
    author: str | None = None,
    hotwords: str | None = None,
) -> tuple[str | None, str | None]:
    cleaned_hotwords = sanitize_asr_context(hotwords)
    parts: list[str] = []
    for candidate in (title, author, cleaned_hotwords):
        cleaned = sanitize_asr_context(candidate)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
    initial_prompt = sanitize_asr_context("，".join(parts))
    return initial_prompt, cleaned_hotwords


def asr_context_hash(value: str | None) -> str:
    cleaned = sanitize_asr_context(value)
    if not cleaned:
        return "none"
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def stable_config_hash(value: str | None) -> str:
    if not value:
        return "none"
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


def asr_audio_filter() -> str:
    value = re.sub(r"[\x00-\x1f\x7f]+", "", os.getenv("ASR_AUDIO_FILTER", "").strip())
    return value[:500]


def effective_quality(quality: str, embedded_subtitles: bool = False) -> Literal["fast", "accurate"]:
    return "accurate" if embedded_subtitles or quality == "accurate" else "fast"


def asr_profile(quality: str) -> dict[str, Any]:
    vad_parameters = {
        "threshold": ASR_VAD_THRESHOLD,
        "min_silence_duration_ms": ASR_VAD_MIN_SILENCE_MS,
        "speech_pad_ms": ASR_VAD_SPEECH_PAD_MS,
    }
    if quality == "accurate":
        return {
            "quality": "accurate",
            "model": ACCURATE_ASR_MODEL,
            "compute_type": ACCURATE_ASR_COMPUTE_TYPE,
            "device": ACCURATE_ASR_DEVICE,
            "cpu_threads": ACCURATE_ASR_CPU_THREADS,
            "beam_size": ACCURATE_ASR_BEAM_SIZE,
            "vad_filter": env_bool("ASR_ACCURATE_VAD_FILTER", True),
            "vad_parameters": vad_parameters,
            "condition_on_previous_text": env_bool(
                "ASR_ACCURATE_CONDITION_ON_PREVIOUS_TEXT",
                True,
            ),
            "timeout_seconds": ACCURATE_ASR_TIMEOUT_SECONDS,
        }
    payload = {
        "quality": "fast",
        "model": DEFAULT_ASR_MODEL,
        "compute_type": ASR_COMPUTE_TYPE,
        "device": ASR_DEVICE,
        "cpu_threads": ASR_CPU_THREADS,
        "beam_size": ASR_FAST_BEAM_SIZE,
        "vad_filter": env_bool("ASR_VAD_FILTER", True),
        "vad_parameters": vad_parameters,
        "condition_on_previous_text": env_bool("ASR_CONDITION_ON_PREVIOUS_TEXT", False),
        "timeout_seconds": ASR_TIMEOUT_SECONDS,
    }
    return payload


def asr_task_timeout(audio_path: Path, quality: str) -> int:
    profile = asr_profile(quality)
    duration = 0.0
    try:
        with wave.open(str(audio_path), "rb") as source:
            frame_rate = source.getframerate()
            if frame_rate > 0:
                duration = source.getnframes() / frame_rate
    except (OSError, EOFError, wave.Error):
        pass
    per_second = (
        ACCURATE_ASR_TIMEOUT_PER_AUDIO_SECOND
        if profile["quality"] == "accurate"
        else ASR_TIMEOUT_PER_AUDIO_SECOND
    )
    dynamic = math.ceil(duration * per_second + 60) if duration > 0 else 0
    return min(ASR_MAX_TIMEOUT_SECONDS, max(int(profile["timeout_seconds"]), dynamic))


def safe_upload_filename(value: str) -> tuple[str, str]:
    filename = re.split(r"[\\/]", value or "")[-1]
    filename = re.sub(r"[\x00-\x1f\x7f]+", "", filename).strip().strip(".")
    if not filename:
        raise HTTPException(
            status_code=400,
            detail={"reason": "invalid_upload_filename", "message": "上传文件名无效。"},
        )
    extension = Path(filename).suffix.lower()
    if extension not in UPLOAD_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail={
                "reason": "unsupported_upload_format",
                "message": "暂不支持这种视频格式。",
            },
        )
    if len(filename) > 180:
        stem = Path(filename).stem[: 180 - len(extension)].rstrip(".")
        filename = f"{stem or 'video'}{extension}"
    return filename, extension


def upload_directory(upload_token: str) -> Path:
    if not UPLOAD_TOKEN_RE.fullmatch(upload_token):
        raise ExtractionFailure(400, "Invalid upload token.", "invalid_upload_token", terminal=True)
    return ASR_TMP_DIR / f"asr-upload-{upload_token}"


def reserve_upload(upload_token: str, requested_bytes: int | None) -> int:
    reservation = requested_bytes if requested_bytes and requested_bytes > 0 else UPLOAD_MAX_BYTES
    if reservation > UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "reason": "upload_too_large",
                "message": f"视频文件不能超过 {UPLOAD_MAX_BYTES // (1024 * 1024)} MB。",
            },
        )
    with UPLOAD_RESERVATION_LOCK:
        projected = sum(UPLOAD_RESERVATIONS.values()) + reservation
        if projected > UPLOAD_STAGING_MAX_BYTES:
            raise HTTPException(
                status_code=429,
                detail={
                    "reason": "upload_storage_busy",
                    "message": "服务器正在处理其他上传视频，请稍后再试。",
                },
            )
        disk_space_http_error(ASR_TMP_DIR, projected)
        UPLOAD_RESERVATIONS[upload_token] = reservation
    return reservation


def resize_upload_reservation(upload_token: str, required_bytes: int) -> None:
    if required_bytes > UPLOAD_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "reason": "upload_too_large",
                "message": f"视频文件不能超过 {UPLOAD_MAX_BYTES // (1024 * 1024)} MB。",
            },
        )
    with UPLOAD_RESERVATION_LOCK:
        current = UPLOAD_RESERVATIONS.get(upload_token)
        if current is None:
            raise HTTPException(
                status_code=409,
                detail={"reason": "upload_expired", "message": "上传会话已失效，请重新选择视频。"},
            )
        if required_bytes <= current:
            return
        if sum(UPLOAD_RESERVATIONS.values()) - current + required_bytes > UPLOAD_STAGING_MAX_BYTES:
            raise HTTPException(
                status_code=429,
                detail={
                    "reason": "upload_storage_busy",
                    "message": "服务器上传暂存空间已满，请稍后再试。",
                },
            )
        UPLOAD_RESERVATIONS[upload_token] = required_bytes


def release_upload_reservation(upload_token: str) -> None:
    with UPLOAD_RESERVATION_LOCK:
        UPLOAD_RESERVATIONS.pop(upload_token, None)


def upload_staging_bytes() -> int:
    with UPLOAD_RESERVATION_LOCK:
        return sum(UPLOAD_RESERVATIONS.values())


def discard_upload_payload(payload: dict[str, Any]) -> None:
    if payload.get("kind") != "upload":
        return
    upload_token = str(payload.get("upload_token") or "")
    if not UPLOAD_TOKEN_RE.fullmatch(upload_token):
        return
    directory = ASR_TMP_DIR / f"asr-upload-{upload_token}"
    try:
        shutil.rmtree(directory)
    except FileNotFoundError:
        pass
    except OSError as exc:
        LOGGER.error("failed to remove staged upload error_type=%s", type(exc).__name__)
        return
    release_upload_reservation(upload_token)


def media_artifact_directory(artifact_token: str) -> Path:
    if not MEDIA_TOKEN_RE.fullmatch(artifact_token):
        raise ExtractionFailure(400, "Invalid media artifact token.", "invalid_artifact_token", terminal=True)
    return MEDIA_ARTIFACT_DIR / f"media-artifact-{artifact_token}"


def reserve_media_artifact(artifact_token: str) -> int:
    reservation = MEDIA_MAX_BYTES
    with MEDIA_RESERVATION_LOCK:
        if artifact_token in MEDIA_RESERVATIONS:
            raise HTTPException(
                status_code=409,
                detail={"reason": "artifact_conflict", "message": "媒体任务令牌冲突，请重新提交。"},
            )
        projected = sum(MEDIA_RESERVATIONS.values()) + reservation
        if projected > MEDIA_STAGING_MAX_BYTES:
            raise HTTPException(
                status_code=429,
                detail={
                    "reason": "media_storage_busy",
                    "message": "服务器媒体暂存空间正忙，请稍后再试。",
                },
            )
        disk_space_http_error(MEDIA_ARTIFACT_DIR, projected)
        MEDIA_RESERVATIONS[artifact_token] = reservation
    return reservation


def resize_media_reservation(artifact_token: str, required_bytes: int) -> None:
    if required_bytes <= 0 or required_bytes > MEDIA_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "reason": "media_too_large",
                "message": f"媒体文件不能超过 {MEDIA_MAX_BYTES // (1024 * 1024)} MB。",
            },
        )
    with MEDIA_RESERVATION_LOCK:
        current = MEDIA_RESERVATIONS.get(artifact_token)
        if current is None:
            raise HTTPException(
                status_code=410,
                detail={"reason": "artifact_expired", "message": "媒体任务已失效，请重新提交。"},
            )
        if sum(MEDIA_RESERVATIONS.values()) - current + required_bytes > MEDIA_STAGING_MAX_BYTES:
            raise HTTPException(
                status_code=429,
                detail={
                    "reason": "media_storage_busy",
                    "message": "服务器媒体暂存空间正忙，请稍后再试。",
                },
            )
        MEDIA_RESERVATIONS[artifact_token] = required_bytes


def release_media_reservation(artifact_token: str) -> None:
    with MEDIA_RESERVATION_LOCK:
        MEDIA_RESERVATIONS.pop(artifact_token, None)


def media_staging_bytes() -> int:
    with MEDIA_RESERVATION_LOCK:
        return sum(MEDIA_RESERVATIONS.values())


def discard_media_payload(payload: dict[str, Any]) -> None:
    if payload.get("kind") != "media":
        return
    artifact_token = str(payload.get("artifact_token") or "")
    if not MEDIA_TOKEN_RE.fullmatch(artifact_token):
        return
    directory = MEDIA_ARTIFACT_DIR / f"media-artifact-{artifact_token}"
    try:
        shutil.rmtree(directory)
    except FileNotFoundError:
        pass
    except OSError as exc:
        LOGGER.error("failed to remove media artifact error_type=%s", type(exc).__name__)
        return
    release_media_reservation(artifact_token)


def discard_job_payload(payload: dict[str, Any]) -> None:
    discard_upload_payload(payload)
    discard_media_payload(payload)


def write_media_artifact_metadata(directory: Path, payload: dict[str, Any]) -> None:
    path = directory / "artifact.json"
    temporary = directory / f".artifact.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def cleanup_stale_media_artifacts(now: float | None = None, remove_all: bool = False) -> int:
    if not MEDIA_ARTIFACT_DIR.exists():
        return 0
    current = time.time() if now is None else now
    with MEDIA_RESERVATION_LOCK:
        active_tokens = set(MEDIA_RESERVATIONS)
    removed = 0
    for directory in MEDIA_ARTIFACT_DIR.glob("media-artifact-*"):
        if not directory.is_dir():
            continue
        artifact_token = directory.name.removeprefix("media-artifact-")
        if not MEDIA_TOKEN_RE.fullmatch(artifact_token):
            continue
        metadata_path = directory / "artifact.json"
        if not remove_all and artifact_token in active_tokens and not metadata_path.is_file():
            continue
        expired = remove_all
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            expired = expired or float(metadata.get("expires_at") or 0) <= current
        except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError):
            try:
                expired = expired or current - directory.stat().st_mtime > MEDIA_ARTIFACT_TTL_SECONDS
            except OSError:
                continue
        if not expired:
            continue
        try:
            shutil.rmtree(directory)
        except OSError:
            continue
        release_media_reservation(artifact_token)
        removed += 1
    return removed


@contextmanager
def extraction_progress(callback: Callable[[str, int, str], None] | None):
    previous = getattr(PROGRESS_CONTEXT, "callback", None)
    PROGRESS_CONTEXT.callback = callback
    try:
        yield
    finally:
        PROGRESS_CONTEXT.callback = previous


@contextmanager
def extraction_owner(owner_id: int | None):
    previous = getattr(JOB_OWNER_CONTEXT, "owner_id", None)
    JOB_OWNER_CONTEXT.owner_id = owner_id
    try:
        yield
    finally:
        JOB_OWNER_CONTEXT.owner_id = previous


def current_asr_owner_key() -> str:
    owner_id = getattr(JOB_OWNER_CONTEXT, "owner_id", None)
    return f"user:{owner_id}" if isinstance(owner_id, int) and owner_id > 0 else "system"


def report_progress(stage: str, progress: int, message: str) -> None:
    callback = getattr(PROGRESS_CONTEXT, "callback", None)
    if callback:
        callback(stage, progress, message)


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
    }.get(reason, reason)


def stable_error_code(reason: str) -> str:
    normalized = public_reason(reason)
    return {
        "invalid_input": "invalid_url",
        "input_too_long": "invalid_url",
        "invalid_page": "invalid_url",
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


def extraction_error_detail(
    source: str,
    exc: ExtractionFailure,
    failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    reason = public_reason(exc.reason)
    code = stable_error_code(reason)
    LOGGER.warning(
        "task failed source=%s reason=%s detail=%s",
        source,
        reason,
        redact_sensitive(exc.detail),
    )
    detail: dict[str, Any] = {
        "source": source,
        "reason": reason,
        "code": code,
        "message": USER_ERROR_MESSAGES.get(code, "任务处理失败，请稍后重试。"),
        "retryable": error_retryable(exc.status_code, code, exc.retryable),
    }
    if failures:
        detail["attempts"] = failures
    return detail


def result_cache_enabled() -> bool:
    return RESULT_CACHE_TTL_SECONDS > 0


def result_cache_key(req: ExtractRequest, canonical_input: str) -> str:
    effective_cookie = cookie_header(cookie_allowed(req.use_cookie))
    cookie_fingerprint = hashlib.sha256(effective_cookie.encode("utf-8")).hexdigest()[:16] if effective_cookie else "none"
    quality = effective_quality(req.quality, req.embedded_subtitles)
    profile = asr_profile(quality)
    payload = {
        "version": RESULT_CACHE_VERSION,
        "input": canonical_input,
        "platform": detect_platform(canonical_input),
        "douyin_adapter_version": DOUYIN_ADAPTER_VERSION,
        "source": req.source,
        "lang": (req.lang or "").strip().lower(),
        "allow_platform_ai": req.allow_platform_ai,
        "quality": quality,
        "asr_mode": req.asr_mode,
        "asr_backend": selected_asr_backend(req.asr_mode),
        "asr_selection_version": ASR_SELECTION_VERSION,
        "embedded_subtitles": req.embedded_subtitles,
        "cookie": cookie_fingerprint,
        "cloud_asr_pipeline_version": CLOUD_ASR_PIPELINE_VERSION,
        "cloud_asr_model": cloud_model_for_mode(req.asr_mode),
        "cloud_asr_enabled": cloud_asr_enabled(),
        "local_asr_enabled": local_asr_enabled(),
        "asr_model": profile["model"],
        "asr_pipeline_version": ASR_PIPELINE_VERSION,
        "asr_compute_type": profile["compute_type"],
        "asr_device": profile["device"],
        "asr_beam_size": profile["beam_size"],
        "asr_vad_filter": profile["vad_filter"],
        "asr_vad_parameters": profile["vad_parameters"] if profile["vad_filter"] else None,
        "asr_vad_profile_version": ASR_VAD_PROFILE_VERSION,
        "asr_condition_on_previous_text": profile["condition_on_previous_text"],
        "asr_context_retry_enabled": env_bool("ASR_CONTEXT_RETRY_ENABLED", True),
        "asr_low_logprob_threshold": ASR_LOW_LOGPROB_THRESHOLD,
        "asr_retry_repetition_ratio": ASR_RETRY_REPETITION_RATIO,
        "asr_retry_low_confidence_ratio": ASR_RETRY_LOW_CONFIDENCE_RATIO,
        "asr_prompt_version": ASR_PROMPT_VERSION,
        "hotwords_hash": asr_context_hash(req.hotwords),
        "asr_audio_quality": os.getenv("ASR_AUDIO_QUALITY", "best").strip().lower(),
        "asr_audio_filter_hash": stable_config_hash(asr_audio_filter()),
        "asr_audio_filter_version": ASR_AUDIO_FILTER_VERSION,
        "asr_quality_metrics_version": ASR_QUALITY_METRICS_VERSION,
        "ocr_sample_fps": OCR_SAMPLE_FPS if req.embedded_subtitles else None,
        "ocr_pipeline_version": OCR_PIPELINE_VERSION if req.embedded_subtitles else None,
        "ocr_crop_top_ratio": OCR_CROP_TOP_RATIO if req.embedded_subtitles else None,
        "ocr_min_confidence": OCR_MIN_CONFIDENCE if req.embedded_subtitles else None,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def upload_result_cache_key(req: UploadJobRequest) -> str:
    quality = effective_quality(req.quality, req.embedded_subtitles)
    profile = asr_profile(quality)
    payload = {
        "version": RESULT_CACHE_VERSION,
        "kind": "upload",
        "sha256": req.sha256,
        "lang": (req.lang or "").strip().lower(),
        "quality": quality,
        "asr_mode": req.asr_mode,
        "asr_backend": selected_asr_backend(req.asr_mode),
        "asr_selection_version": ASR_SELECTION_VERSION,
        "embedded_subtitles": req.embedded_subtitles,
        "cloud_asr_pipeline_version": CLOUD_ASR_PIPELINE_VERSION,
        "cloud_asr_model": cloud_model_for_mode(req.asr_mode),
        "cloud_asr_enabled": cloud_asr_enabled(),
        "local_asr_enabled": local_asr_enabled(),
        "asr_model": profile["model"],
        "asr_pipeline_version": ASR_PIPELINE_VERSION,
        "asr_compute_type": profile["compute_type"],
        "asr_device": profile["device"],
        "asr_beam_size": profile["beam_size"],
        "asr_vad_filter": profile["vad_filter"],
        "asr_vad_parameters": profile["vad_parameters"] if profile["vad_filter"] else None,
        "asr_vad_profile_version": ASR_VAD_PROFILE_VERSION,
        "asr_condition_on_previous_text": profile["condition_on_previous_text"],
        "asr_context_retry_enabled": env_bool("ASR_CONTEXT_RETRY_ENABLED", True),
        "asr_low_logprob_threshold": ASR_LOW_LOGPROB_THRESHOLD,
        "asr_retry_repetition_ratio": ASR_RETRY_REPETITION_RATIO,
        "asr_retry_low_confidence_ratio": ASR_RETRY_LOW_CONFIDENCE_RATIO,
        "asr_prompt_version": ASR_PROMPT_VERSION,
        "upload_prompt_hash": asr_context_hash(upload_display_title(req.filename)),
        "hotwords_hash": asr_context_hash(req.hotwords),
        "asr_audio_quality": os.getenv("ASR_AUDIO_QUALITY", "best").strip().lower(),
        "asr_audio_filter_hash": stable_config_hash(asr_audio_filter()),
        "asr_audio_filter_version": ASR_AUDIO_FILTER_VERSION,
        "asr_quality_metrics_version": ASR_QUALITY_METRICS_VERSION,
        "ocr_sample_fps": OCR_SAMPLE_FPS if req.embedded_subtitles else None,
        "ocr_pipeline_version": OCR_PIPELINE_VERSION if req.embedded_subtitles else None,
        "ocr_crop_top_ratio": OCR_CROP_TOP_RATIO if req.embedded_subtitles else None,
        "ocr_min_confidence": OCR_MIN_CONFIDENCE if req.embedded_subtitles else None,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def result_cache_path(key: str) -> Path:
    return RESULT_CACHE_DIR / f"{key}.json"


def cache_updated_since(key: str, timestamp: float) -> bool:
    try:
        return result_cache_path(key).stat().st_mtime >= timestamp
    except OSError:
        return False


@contextmanager
def result_key_guard(key: str, blocking: bool = True):
    with RESULT_CACHE_LOCK:
        entry = RESULT_KEY_LOCKS.get(key)
        if entry is None:
            entry = ResultKeyLockEntry(lock=Lock())
            RESULT_KEY_LOCKS[key] = entry
        entry.references += 1
    acquired = entry.lock.acquire(blocking=blocking)
    try:
        yield acquired
    finally:
        if acquired:
            entry.lock.release()
        with RESULT_CACHE_LOCK:
            entry.references -= 1
            if entry.references == 0:
                RESULT_KEY_LOCKS.pop(key, None)


def deserialize_entries(items: Any) -> list[SubtitleEntry]:
    if not isinstance(items, list):
        return []
    entries: list[SubtitleEntry] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            text = str(item.get("text") or "").strip()
            if text:
                entries.append(SubtitleEntry(float(item.get("start") or 0), float(item.get("end") or 0), text))
        except (TypeError, ValueError):
            continue
    return entries


def load_cached_result(key: str, now: float | None = None) -> tuple[list[SubtitleEntry], dict[str, Any], float] | None:
    if not result_cache_enabled():
        return None
    path = result_cache_path(key)
    current = time.time() if now is None else now
    try:
        stat = path.stat()
        age = max(0.0, current - stat.st_mtime)
        if age > RESULT_CACHE_TTL_SECONDS:
            path.unlink(missing_ok=True)
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        path.unlink(missing_ok=True)
        return None
    except OSError:
        return None
    if not isinstance(payload, dict) or payload.get("version") != RESULT_CACHE_VERSION:
        path.unlink(missing_ok=True)
        return None
    entries = deserialize_entries(payload.get("entries"))
    metadata = payload.get("metadata")
    if not entries or not isinstance(metadata, dict):
        path.unlink(missing_ok=True)
        return None
    try:
        os.utime(path, None)
    except OSError:
        pass
    return entries, copy.deepcopy(metadata), age


def save_cached_result(key: str, entries: list[SubtitleEntry], metadata: dict[str, Any]) -> None:
    if not result_cache_enabled():
        return
    RESULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = result_cache_path(key)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = {
        "version": RESULT_CACHE_VERSION,
        "created_at": int(time.time()),
        "entries": [{"start": entry.start, "end": entry.end, "text": entry.text} for entry in entries],
        "metadata": metadata,
    }
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temp_path, path)
    except OSError as exc:
        LOGGER.warning("result cache write failed: %s", redact_sensitive(str(exc)))
        return
    finally:
        temp_path.unlink(missing_ok=True)
    cleanup_result_cache()


def cleanup_result_cache(now: float | None = None) -> int:
    if not RESULT_CACHE_DIR.exists():
        return 0
    current = time.time() if now is None else now
    kept: list[tuple[float, Path]] = []
    removed = 0
    for path in RESULT_CACHE_DIR.glob("*.json"):
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if not result_cache_enabled() or current - modified > RESULT_CACHE_TTL_SECONDS:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict) or payload.get("version") != RESULT_CACHE_VERSION:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
            continue
        kept.append((modified, path))
    kept.sort(reverse=True)
    for _, path in kept[RESULT_CACHE_MAX_ITEMS:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def failure_record(source: str, exc: ExtractionFailure) -> dict[str, Any]:
    reason = public_reason(exc.reason)
    code = stable_error_code(reason)
    return {
        "source": source,
        "reason": reason,
        "code": code,
        "message": USER_ERROR_MESSAGES.get(code, "该字幕来源不可用。"),
        "retryable": error_retryable(exc.status_code, code, exc.retryable),
    }


def bili_page_number(value: str) -> int:
    candidate = extract_bili_url(value) or value.strip()
    raw_page = (urllib.parse.parse_qs(urllib.parse.urlparse(candidate).query).get("p") or ["1"])[0]
    try:
        page = int(raw_page)
    except (TypeError, ValueError) as exc:
        raise ExtractionFailure(400, "Bilibili page number must be an integer.", "invalid_page", terminal=True) from exc
    if page < 1 or page > 10_000:
        raise ExtractionFailure(400, "Bilibili page number is out of range.", "invalid_page", terminal=True)
    return page


def canonical_bili_url(bvid: str, value: str) -> str:
    page = bili_page_number(value)
    base = f"https://www.bilibili.com/video/{bvid}"
    return f"{base}?p={page}" if page > 1 else base


def normalize_input(value: str) -> str:
    value = value.strip()
    if len(value) > MAX_INPUT_LENGTH:
        raise ExtractionFailure(400, "Input is too long.", "input_too_long", terminal=True)
    bvid = extract_bvid(value)
    if bvid:
        return canonical_bili_url(bvid, value)
    if is_douyin_url(value):
        try:
            return normalize_douyin_input(value)
        except DouyinAdapterError as exc:
            raise ExtractionFailure(exc.status_code, exc.message, exc.reason, terminal=exc.status_code < 500) from exc
    url = extract_bili_url(value)
    if not url:
        raise ExtractionFailure(400, "请输入有效的 B站或抖音视频链接，也可以输入 BV 号。", "invalid_input", terminal=True)
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith("b23.tv"):
        return resolve_b23_url(url)
    if host.endswith("bilibili.com"):
        av_match = re.fullmatch(r"/video/(av\d+)/?", parsed.path, flags=re.IGNORECASE)
        if av_match:
            page = bili_page_number(url)
            canonical = f"https://www.bilibili.com/video/{av_match.group(1).lower()}"
            return f"{canonical}?p={page}" if page > 1 else canonical
        return url
    raise ExtractionFailure(400, "请输入有效的 B站或抖音视频链接，也可以输入 BV 号。", "invalid_input", terminal=True)


def detect_platform(value: str) -> str:
    return "douyin" if is_douyin_url(value) else "bilibili"


def extract_bvid(value: str) -> str | None:
    match = re.search(r"(BV[0-9A-Za-z]{8,})", value)
    return match.group(1) if match else None


def extract_bili_url(value: str) -> str | None:
    match = BILI_URL_RE.search(value)
    if not match:
        return None
    url = match.group(1).rstrip(TRAILING_URL_PUNCTUATION)
    if not re.match(r"https?://", url, flags=re.IGNORECASE):
        url = f"https://{url}"
    return url


def bili_redirect_host_allowed(host: str | None) -> bool:
    value = (host or "").lower().rstrip(".")
    return any(value == root or value.endswith(f".{root}") for root in ("b23.tv", "bilibili.com"))


@lru_cache(maxsize=128)
def resolve_b23_url(url: str) -> str:
    current = url
    visited: set[str] = set()
    try:
        with httpx.Client(
            timeout=10,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"},
            event_hooks={"request": [validate_public_request]},
        ) as client:
            for _ in range(6):
                if not bili_redirect_host_allowed(urllib.parse.urlparse(current).hostname):
                    raise ExtractionFailure(
                        400,
                        "B站短链接跳转到了不受信任的站点。",
                        "short_link_untrusted",
                        terminal=True,
                    )
                if current in visited:
                    raise ExtractionFailure(
                        508,
                        "B站短链接发生循环跳转，请更换原始链接。",
                        "short_link_loop",
                        terminal=True,
                    )
                visited.add(current)
                resp = client.get(current)
                if resp.status_code in {301, 302, 303, 307, 308}:
                    location = resp.headers.get("location")
                    if not location:
                        break
                    next_url = urljoin(current, location)
                    if not bili_redirect_host_allowed(urllib.parse.urlparse(next_url).hostname):
                        raise ExtractionFailure(
                            400,
                            "B站短链接跳转到了不受信任的站点。",
                            "short_link_untrusted",
                            terminal=True,
                        )
                    bvid = extract_bvid(next_url)
                    if bvid:
                        return canonical_bili_url(bvid, next_url)
                    current = next_url
                    continue
                resp.raise_for_status()
                bvid = extract_bvid(str(resp.url) or current)
                if bvid:
                    return canonical_bili_url(bvid, str(resp.url) or current)
                break
            else:
                raise ExtractionFailure(
                    508,
                    "B站短链接跳转次数过多，请更换原始链接。",
                    "short_link_loop",
                    terminal=True,
                )
    except ExtractionFailure:
        raise
    except httpx.HTTPError as exc:
        raise ExtractionFailure(502, f"Bilibili short link request failed: {exc}", "short_link_request_failed") from exc
    raise ExtractionFailure(
        400,
        "Bilibili short link could not be resolved to a video BV id.",
        "short_link_unresolved",
        terminal=True,
    )


def configured_cookie_header() -> str | None:
    try:
        persisted = BILI_COOKIE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        persisted = ""
    if persisted:
        return persisted
    raw = os.getenv("BILI_COOKIE", "").strip()
    if raw:
        return raw
    parts: list[str] = []
    for env_name, cookie_name in (
        ("BILI_SESSDATA", "SESSDATA"),
        ("BILI_JCT", "bili_jct"),
        ("BILI_BUVID3", "buvid3"),
    ):
        value = os.getenv(env_name, "").strip()
        if value:
            parts.append(f"{cookie_name}={value}")
    return "; ".join(parts) if parts else None


def cookie_enabled() -> bool:
    return env_bool("COOKIE_ENABLED", False) or (web_qr_login_enabled() and BILI_COOKIE_PATH.is_file())


def cookie_header(allow_cookie: bool) -> str | None:
    if not allow_cookie or not cookie_enabled():
        return None
    return configured_cookie_header()


def cookie_allowed(requested: bool) -> bool:
    return bool(requested and cookie_enabled() and configured_cookie_header())


def web_qr_login_enabled() -> bool:
    return env_bool("WEB_QR_LOGIN_ENABLED", False)


def save_bili_cookie(cookie: str) -> None:
    value = cookie.strip()
    if not value or len(value) > 16_384 or "\n" in value or "\r" in value:
        raise HTTPException(status_code=502, detail="Bilibili returned an invalid cookie.")
    parent = BILI_COOKIE_PATH.parent
    temporary = parent / f".{BILI_COOKIE_PATH.name}.{os.getpid()}.{secrets.token_hex(6)}.tmp"
    try:
        with QR_LOGIN_LOCK:
            parent.mkdir(parents=True, exist_ok=True)
            os.chmod(parent, 0o700)
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(value)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, BILI_COOKIE_PATH)
            os.chmod(BILI_COOKIE_PATH, 0o600)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        LOGGER.error("Bilibili cookie persistence failed: %s", redact_sensitive(str(exc)))
        raise HTTPException(
            status_code=500,
            detail={
                "reason": "cookie_persistence_failed",
                "message": "B站登录态保存失败，请检查服务日志。",
            },
        ) from exc
    os.environ.update({"BILI_COOKIE": value, "BILI_SESSDATA": "", "BILI_JCT": "", "BILI_BUVID3": ""})


def cookie_header_from_set_cookie(headers: list[str]) -> str:
    jar = SimpleCookie()
    for header in headers:
        try:
            jar.load(header)
        except Exception:
            continue
    parts: list[str] = []
    for name in LOGIN_COOKIE_NAMES:
        morsel = jar.get(name)
        if morsel and morsel.value:
            parts.append(f"{name}={morsel.value}")
    names = {part.split("=", 1)[0] for part in parts}
    if "SESSDATA" not in names or "bili_jct" not in names:
        raise HTTPException(status_code=502, detail="Login succeeded but Bilibili did not return the required cookies.")
    return "; ".join(parts)


def qr_svg_data_url(value: str) -> str:
    image = qrcode.make(value, image_factory=qrcode.image.svg.SvgPathImage)
    buffer = BytesIO()
    image.save(buffer)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def clean_qr_sessions(now: float | None = None) -> None:
    current = time.time() if now is None else now
    expired = [key for key, expires_at in QR_LOGIN_SESSIONS.items() if expires_at <= current]
    for key in expired:
        QR_LOGIN_SESSIONS.pop(key, None)


def headers_for(referer: str | None = None, allow_cookie: bool = False) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    cookie = cookie_header(allow_cookie)
    if cookie:
        headers["Cookie"] = cookie
    return headers


def remaining_before(deadline: float, label: str) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ExtractionFailure(504, f"{label} timed out.", "download_failed", can_try_asr=False)
    return max(1.0, remaining)


def api_get_json(url: str, referer: str, allow_cookie: bool = False) -> dict[str, Any]:
    try:
        with httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers=headers_for(referer, allow_cookie),
            event_hooks={"request": [validate_public_request]},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        raise ExtractionFailure(502, f"Bilibili API request failed: {exc}", "api_request_failed") from exc
    if not isinstance(data, dict):
        raise ExtractionFailure(502, "Bilibili API returned an unexpected response.", "api_bad_response")
    if data.get("code") != 0:
        code = data.get("code")
        message = data.get("message")
        if code in {-400, -404, 62002, 62004}:
            raise ExtractionFailure(404, f"Bilibili API error: {message}", "not_found", terminal=True)
        if allow_cookie and code in {-101, -111}:
            raise ExtractionFailure(
                401,
                "B站登录态已失效，请刷新 Cookie 或关闭 Cookie 后重试。",
                "cookie_expired",
                can_try_asr=True,
                retryable=True,
            )
        raise ExtractionFailure(502, f"Bilibili API error: {message}", "api_error")
    return data


def extract_info(url: str, allow_cookie: bool = False, skip_download: bool = True) -> dict[str, Any]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": skip_download,
        "socket_timeout": 20,
        "http_headers": headers_for(allow_cookie=allow_cookie),
        "logger": QuietYtdlpLogger(),
        "noplaylist": True,
    }
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise ExtractionFailure(502, f"yt-dlp extraction failed: {exc}", "ytdlp_failed") from exc
    if not isinstance(info, dict):
        raise ExtractionFailure(502, "yt-dlp returned an unexpected response.", "ytdlp_bad_response")
    return info


def wbi_mixin_key(allow_cookie: bool = False) -> str | None:
    try:
        with httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers=headers_for(allow_cookie=allow_cookie),
            event_hooks={"request": [validate_public_request]},
        ) as client:
            resp = client.get("https://api.bilibili.com/x/web-interface/nav")
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    wbi_img = ((data.get("data") or {}).get("wbi_img") or {}) if isinstance(data, dict) else {}
    img_key = str(wbi_img.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = str(wbi_img.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
    raw = img_key + sub_key
    if len(raw) < 64:
        return None
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def wbi_signed_url(base_url: str, params: dict[str, Any], allow_cookie: bool = False) -> str:
    mixin_key = wbi_mixin_key(allow_cookie)
    if not mixin_key:
        return base_url + "?" + urllib.parse.urlencode(params)
    signed = {
        key: "".join(ch for ch in str(value) if ch not in "!'()*")
        for key, value in params.items()
        if value is not None and value != ""
    }
    signed["wts"] = str(int(time.time()))
    query = urllib.parse.urlencode(sorted(signed.items()))
    signed["w_rid"] = hashlib.md5(
        (query + mixin_key).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return base_url + "?" + urllib.parse.urlencode(sorted(signed.items()))


def bili_view_context(
    url: str,
    allow_cookie: bool = False,
) -> tuple[str, str, dict[str, Any], dict[str, Any] | None, Any]:
    bvid = extract_bvid(url)
    if not bvid:
        raise ExtractionFailure(400, "Could not find a BV id in the input.", "invalid_bvid", terminal=True)
    canonical_url = canonical_bili_url(bvid, url)
    view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={quote(bvid)}"
    view = api_get_json(view_url, canonical_url, allow_cookie)
    data = view.get("data") or {}
    if not isinstance(data, dict):
        raise ExtractionFailure(502, "Bilibili view API returned no data.", "api_bad_response")
    pages = [item for item in (data.get("pages") or []) if isinstance(item, dict)]
    page_number = bili_page_number(canonical_url)
    if pages and page_number > len(pages):
        raise ExtractionFailure(
            400,
            f"Bilibili video has {len(pages)} pages; requested P{page_number}.",
            "invalid_page",
            terminal=True,
        )
    if not pages and page_number > 1:
        raise ExtractionFailure(400, "This Bilibili video has no requested page.", "invalid_page", terminal=True)
    selected_page = pages[page_number - 1] if pages else None
    cid = selected_page.get("cid") if selected_page else data.get("cid")
    if not cid:
        raise ExtractionFailure(502, "Bilibili API returned no cid for this video.", "api_no_cid")
    return bvid, canonical_url, data, selected_page, cid


def view_source(url: str, allow_cookie: bool = False) -> ExtractionSource:
    if not extract_bvid(url):
        info = extract_info(url, allow_cookie=allow_cookie)
        return ExtractionSource(
            title=info.get("title"),
            video_id=str(info.get("id") or "") or None,
            webpage_url=str(info.get("webpage_url") or url),
            tracks=[],
            duration=float(info.get("duration") or 0) or None,
            platform="bilibili",
            author=info.get("uploader"),
        )
    bvid, canonical_url, data, selected_page, _ = bili_view_context(url, allow_cookie)
    page_number = bili_page_number(canonical_url)
    title = data.get("title")
    if page_number > 1 and selected_page and selected_page.get("part"):
        title = f"{title} - P{page_number} {selected_page['part']}"
    return ExtractionSource(
        title=title,
        video_id=bvid,
        webpage_url=canonical_url,
        tracks=[],
        duration=float((selected_page or {}).get("duration") or data.get("duration") or 0) or None,
        platform="bilibili",
        author=(data.get("owner") or {}).get("name") if isinstance(data.get("owner"), dict) else None,
    )


def bili_api_source(url: str, allow_cookie: bool = False) -> ExtractionSource:
    bvid, canonical_url, data, selected_page, cid = bili_view_context(url, allow_cookie)
    page_number = bili_page_number(canonical_url)
    title = data.get("title")
    if page_number > 1 and selected_page and selected_page.get("part"):
        title = f"{title} - P{page_number} {selected_page['part']}"
    aid = data.get("aid")
    view_subtitles = ((data.get("subtitle") or {}).get("list") or []) if isinstance(data.get("subtitle"), dict) else []

    player_url = wbi_signed_url(
        "https://api.bilibili.com/x/player/wbi/v2",
        {"aid": aid, "bvid": bvid, "cid": cid},
        allow_cookie,
    )
    player = api_get_json(player_url, canonical_url, allow_cookie)
    player_data = player.get("data") or {}
    subtitles = ((player_data.get("subtitle") or {}).get("subtitles") or []) if isinstance(player_data, dict) else []
    tracks: list[SubtitleTrack] = []
    for item in subtitles:
        if not isinstance(item, dict) or not item.get("subtitle_url"):
            continue
        raw_url = str(item["subtitle_url"])
        track_url = urljoin("https:", raw_url) if raw_url.startswith("//") else raw_url
        source_type = "platform_ai" if item.get("ai_type") else "official"
        tracks.append(
            SubtitleTrack(
                source_type=source_type,
                language=str(item.get("lan") or "unknown"),
                ext="json",
                url=track_url,
                name=item.get("lan_doc") or item.get("id_str"),
            )
        )

    note = None
    if not tracks and view_subtitles:
        languages = ", ".join(
            str(item.get("lan_doc") or item.get("lan") or "unknown")
            for item in view_subtitles
            if isinstance(item, dict)
        )
        note = (
            "Bilibili lists subtitle metadata but did not expose subtitle URLs in this mode. "
            f"Available languages from metadata: {languages or 'unknown'}."
        )
    elif not tracks:
        note = "No official subtitle track was exposed by Bilibili API."
    return ExtractionSource(
        title=title,
        video_id=bvid,
        webpage_url=canonical_url,
        tracks=tracks,
        note=note,
        duration=float((selected_page or {}).get("duration") or data.get("duration") or 0) or None,
        platform="bilibili",
        author=(data.get("owner") or {}).get("name") if isinstance(data.get("owner"), dict) else None,
    )


def subtitle_tracks(info: dict[str, Any]) -> list[SubtitleTrack]:
    tracks: list[SubtitleTrack] = []
    for source_type, field_name in (("official", "subtitles"), ("platform_ai", "automatic_captions")):
        group = info.get(field_name) or {}
        if not isinstance(group, dict):
            continue
        for language, items in group.items():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict) or not item.get("url"):
                    continue
                tracks.append(
                    SubtitleTrack(
                        source_type=source_type,
                        language=str(language),
                        ext=str(item.get("ext") or "json").lower(),
                        url=str(item["url"]),
                        name=item.get("name") or item.get("format_id"),
                    )
                )
    return tracks


def normalized_language(value: str | None) -> str:
    tag = (value or "").strip().lower().replace("_", "-")
    if tag in {"zh", "zh-cn", "zh-sg", "zh-hans"}:
        return "zh-hans"
    if tag in {"zh-tw", "zh-hk", "zh-mo", "zh-hant"}:
        return "zh-hant"
    return tag.split("-", 1)[0]


def choose_track(tracks: list[SubtitleTrack], lang: str | None, allow_platform_ai: bool) -> SubtitleTrack:
    official = [t for t in tracks if t.source_type == "official"]
    candidates = list(official)
    if allow_platform_ai:
        candidates += [t for t in tracks if t.source_type == "platform_ai"]
    if not candidates:
        if tracks:
            raise ExtractionFailure(
                404,
                "No official subtitle track found. Platform AI subtitle tracks exist, but allow_platform_ai is false.",
                "no_official_subtitle",
                can_try_asr=True,
            )
        raise ExtractionFailure(
            404,
            "No official subtitle track found, and no platform AI subtitle track was exposed.",
            "no_official_subtitle",
            can_try_asr=True,
        )

    def score(track: SubtitleTrack) -> tuple[int, int, int]:
        track_language = normalized_language(track.language)
        if lang:
            lang_score = 0 if track_language == normalized_language(lang) else 5
        elif track_language in {"zh-hans", "zh-hant"}:
            lang_score = 0 if track_language == "zh-hans" else 1
        else:
            lang_score = 3
        ext_score = {"json": 0, "srt": 1, "vtt": 2, "ass": 3}.get(track.ext, 9)
        source_score = 0 if track.source_type == "official" else 1
        return (lang_score, source_score, ext_score)

    return sorted(candidates, key=score)[0]


def fetch_subtitle(track: SubtitleTrack, referer: str, allow_cookie: bool = False) -> str:
    if track.provider == "douyin":
        try:
            douyin_track, video = track.context
            return fetch_douyin_subtitle(douyin_track, video)
        except DouyinAdapterError as exc:
            raise ExtractionFailure(exc.status_code, exc.message, exc.reason) from exc
        except (TypeError, ValueError) as exc:
            raise ExtractionFailure(502, "抖音字幕上下文无效。", "subtitle_download_failed") from exc
    try:
        with httpx.Client(
            timeout=20,
            follow_redirects=True,
            headers=headers_for(referer, allow_cookie),
            event_hooks={"request": [validate_public_request]},
        ) as client:
            resp = client.get(track.url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:
        raise ExtractionFailure(502, f"Subtitle download failed: {exc}", "subtitle_download_failed") from exc


def parse_json_subtitle(text: str) -> list[SubtitleEntry]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ExtractionFailure(502, "Subtitle JSON could not be parsed.", "subtitle_parse_failed") from exc
    body: Any = None
    millisecond_times = False
    if isinstance(data, dict):
        body = data.get("body")
        if not isinstance(body, list):
            body = data.get("utterances")
            millisecond_times = isinstance(body, list)
        if not isinstance(body, list) and isinstance(data.get("data"), dict):
            body = data["data"].get("utterances") or data["data"].get("body")
            millisecond_times = isinstance(data["data"].get("utterances"), list)
    elif isinstance(data, list):
        body = data
    if not isinstance(body, list):
        raise ExtractionFailure(502, "字幕 JSON 中没有可识别的字幕列表。", "subtitle_parse_failed")
    entries: list[SubtitleEntry] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        start = item.get("from", item.get("start", item.get("start_time", 0)))
        end = item.get("to", item.get("end", item.get("end_time", start)))
        content = item.get("content", item.get("text", ""))
        try:
            start_value = float(start)
            end_value = float(end)
            if millisecond_times or "start_time" in item or "end_time" in item:
                start_value /= 1000
                end_value /= 1000
            entries.append(SubtitleEntry(start_value, end_value, str(content).strip()))
        except (TypeError, ValueError):
            continue
    return [e for e in entries if e.text]


def subtitle_time_to_seconds(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = "0", parts[0], parts[1]
    else:
        raise ValueError("invalid subtitle timecode")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


SUBTITLE_TIMING_RE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{1,3})(?:\s+.*)?$"
)


def parse_timed_subtitle(text: str) -> list[SubtitleEntry]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    entries: list[SubtitleEntry] = []
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if not lines or lines[0].upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing_index = next((index for index, line in enumerate(lines[:3]) if "-->" in line), -1)
        if timing_index < 0:
            continue
        match = SUBTITLE_TIMING_RE.search(lines[timing_index])
        if not match:
            continue
        caption = "\n".join(lines[timing_index + 1 :]).strip()
        if not caption:
            continue
        try:
            entries.append(
                SubtitleEntry(
                    subtitle_time_to_seconds(match.group("start")),
                    subtitle_time_to_seconds(match.group("end")),
                    caption,
                )
            )
        except ValueError:
            continue
    if not entries:
        raise ExtractionFailure(502, "字幕文件中没有可识别的时间轴。", "subtitle_parse_failed")
    return entries


def parse_subtitle_text(text: str, ext: str) -> list[SubtitleEntry]:
    normalized_ext = (ext or "").lower()
    if normalized_ext == "json":
        return parse_json_subtitle(text)
    if normalized_ext in {"srt", "vtt", "webvtt"}:
        return parse_timed_subtitle(text)
    raise ExtractionFailure(502, f"暂不支持转换 {normalized_ext or 'unknown'} 字幕格式。", "unsupported_subtitle_format")


def seconds_to_srt(value: float) -> str:
    ms_total = max(0, int(round(value * 1000)))
    hours, rem = divmod(ms_total, 3600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, ms = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{ms:03}"


def seconds_to_vtt(value: float) -> str:
    return seconds_to_srt(value).replace(",", ".")


def public_result_metadata(meta: Any) -> dict[str, Any]:
    if not isinstance(meta, dict):
        return {}
    return {
        key: copy.deepcopy(meta[key])
        for key in PUBLIC_RESULT_METADATA_FIELDS
        if key in meta and meta[key] is not None
    }


def render_entries(entries: list[SubtitleEntry], output_format: str, meta: dict[str, Any]) -> str:
    fmt = "markdown" if output_format == "md" else output_format
    if fmt == "json":
        payload = {
            "metadata": meta,
            "entries": [{"start": e.start, "end": e.end, "text": e.text} for e in entries],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if fmt == "txt":
        return "\n".join(e.text for e in entries) + "\n"
    if fmt == "markdown":
        lines = [f"# {meta.get('title') or 'Video Subtitle'}", ""]
        note = meta.get("note") or meta.get("warning")
        if note:
            lines.extend([f"> {note}", ""])
        for e in entries:
            lines.append(f"- `{seconds_to_vtt(e.start)}` {e.text}")
        return "\n".join(lines) + "\n"
    if fmt == "srt":
        blocks = []
        for i, e in enumerate(entries, 1):
            blocks.append(f"{i}\n{seconds_to_srt(e.start)} --> {seconds_to_srt(e.end)}\n{e.text}")
        return "\n\n".join(blocks) + "\n"
    if fmt == "vtt":
        blocks = ["WEBVTT", ""]
        for e in entries:
            blocks.append(f"{seconds_to_vtt(e.start)} --> {seconds_to_vtt(e.end)}\n{e.text}\n")
        return "\n".join(blocks)
    raise ExtractionFailure(400, "Unsupported output format.", "unsupported_format", terminal=True)


def rendered_raw_content(meta: dict[str, Any], output_format: str) -> str | None:
    raw_entries = deserialize_entries(meta.get("raw_entries"))
    if not raw_entries:
        return None
    return render_entries(raw_entries, output_format, meta)


def public_result_payload(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    payload = copy.deepcopy(result)
    metadata = public_result_metadata(payload.get("metadata"))
    if "metadata" in payload:
        payload["metadata"] = metadata
    if payload.get("format") == "json":
        for field in ("content", "raw_content"):
            content = payload.get(field)
            if not isinstance(content, str):
                continue
            try:
                document = json.loads(content)
            except (TypeError, ValueError):
                payload[field] = ""
                continue
            if not isinstance(document, dict):
                payload[field] = ""
                continue
            document["metadata"] = metadata
            payload[field] = json.dumps(document, ensure_ascii=False, indent=2)
    return payload


def public_error_payload(error: Any) -> dict[str, Any]:
    if not isinstance(error, dict):
        return {
            "reason": "task_failed",
            "code": "task_failed",
            "message": "任务处理失败，请稍后重试。",
            "retryable": True,
        }
    allowed = {"source", "reason", "code", "message", "retryable"}
    return {
        key: copy.deepcopy(error[key])
        for key in allowed
        if key in error and error[key] is not None
    }


def public_job_payload(job: Any) -> dict[str, Any]:
    if not isinstance(job, dict):
        return {}
    allowed = {
        "id",
        "status",
        "stage",
        "progress",
        "message",
        "queue_position",
        "created_at",
        "updated_at",
        "reused",
        "platform",
        "error_status",
    }
    payload = {
        key: copy.deepcopy(job[key])
        for key in allowed
        if key in job and job[key] is not None
    }
    if job.get("status") == "completed" and "result" in job:
        payload["result"] = public_result_payload(job["result"])
    elif job.get("status") == "failed" and "error" in job:
        payload["error"] = public_error_payload(job["error"])
    return payload


def official_subtitle(req: ExtractRequest, allow_cookie: bool, source_label: str) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    url = normalize_input(req.input)
    platform = detect_platform(url)
    attempts: list[str] = []
    source: ExtractionSource | None = None
    if platform == "douyin":
        report_progress("platform", 18, "正在建立抖音匿名会话")
        try:
            video = get_douyin_video(url, force_refresh=req.force_refresh)
        except DouyinAdapterError as exc:
            raise ExtractionFailure(exc.status_code, exc.message, exc.reason, can_try_asr=False) from exc
        tracks = [
            SubtitleTrack(
                source_type="platform_ai",
                language=track.language,
                ext=track.ext,
                url=track.url,
                name=track.name,
                provider="douyin",
                context=(track, video),
            )
            for track in video.tracks
        ]
        source = ExtractionSource(
            title=video.title,
            video_id=video.video_id,
            webpage_url=video.webpage_url,
            tracks=tracks,
            note="抖音没有提供可用的平台字幕。" if not tracks else None,
            duration=video.duration,
            platform="douyin",
            author=video.author,
        )
        attempts.append("douyin_signed_api")
    else:
        try:
            report_progress("platform", 18, "正在查询 B站字幕")
            info = extract_info(url, allow_cookie=allow_cookie)
            tracks = subtitle_tracks(info)
            source = ExtractionSource(
                title=info.get("title"),
                video_id=info.get("id") or extract_bvid(url),
                webpage_url=info.get("webpage_url") or url,
                tracks=tracks,
                duration=float(info.get("duration") or 0) or None,
                platform="bilibili",
                author=info.get("uploader"),
            )
            attempts.append("yt-dlp")
        except ExtractionFailure as exc:
            attempts.append(f"yt-dlp_failed:{exc.reason}")

        if source is None or not source.tracks:
            try:
                source = bili_api_source(url, allow_cookie=allow_cookie)
                attempts.append("bilibili_api")
            except ExtractionFailure as exc:
                if exc.terminal and (source is None or exc.reason != "invalid_bvid"):
                    raise exc
                if source is None:
                    raise exc
                attempts.append(f"bilibili_api_failed:{exc.reason}")

    tracks = source.tracks if source else []
    if not tracks and source and source.note:
        raise ExtractionFailure(404, source.note, "no_official_subtitle", can_try_asr=True)
    track = choose_track(tracks, req.lang, req.allow_platform_ai)
    report_progress("subtitle", 48, "正在下载并整理字幕轨道")
    raw = fetch_subtitle(track, source.webpage_url if source else url, allow_cookie=allow_cookie)
    entries = parse_subtitle_text(raw, track.ext)
    if not entries:
        raise ExtractionFailure(404, "Subtitle track was found but contained no entries.", "empty_subtitle", can_try_asr=True)
    warning = None
    if track.source_type != "official":
        warning = f"本次使用了{'抖音' if platform == 'douyin' else 'B站'}平台自动字幕。"
    meta = {
        "title": source.title,
        "id": source.video_id,
        "webpage_url": source.webpage_url,
        "source": source_label,
        "track_source_type": track.source_type,
        "cookie_used": allow_cookie and bool(cookie_header(True)),
        "language": track.language,
        "subtitle_format": track.ext,
        "warning": warning,
        "note": warning,
        "attempts": attempts,
        "duration": source.duration,
        "platform": source.platform,
        "author": source.author,
        "session_mode": "anonymous_browser" if platform == "douyin" else ("bilibili_cookie" if allow_cookie else "anonymous"),
        "available_tracks": [
            {"source_type": t.source_type, "language": t.language, "ext": t.ext, "name": t.name}
            for t in tracks
        ],
    }
    return entries, meta


def ensure_asr_ready() -> None:
    if not local_asr_enabled():
        raise ExtractionFailure(503, "Local ASR is disabled by ASR_ENABLED=false.", "asr_disabled")
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise ExtractionFailure(503, "Local ASR requires ffmpeg and ffprobe.", "ffmpeg_missing")
    ASR_TMP_DIR.mkdir(parents=True, exist_ok=True)
    ASR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    ASR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ensure_disk_space(ASR_MODEL_DIR, 512 * 1024 * 1024)


def cleanup_stale_asr_tmp(now: float | None = None) -> int:
    current = time.time() if now is None else now
    if not ASR_TMP_DIR.exists():
        return 0
    removed = 0
    for path in ASR_TMP_DIR.iterdir():
        if not path.is_dir() or not path.name.startswith(("asr-", "ocr-")):
            continue
        is_upload = path.name.startswith("asr-upload-")
        try:
            age = current - path.stat().st_mtime
        except OSError:
            continue
        if not is_upload and age < ASR_TMP_MAX_AGE_SECONDS:
            continue
        try:
            shutil.rmtree(path)
            removed += 1
            if is_upload:
                release_upload_reservation(path.name.removeprefix("asr-upload-"))
        except OSError:
            continue
    return removed


def uploaded_media_path(req: UploadJobRequest) -> Path:
    directory = upload_directory(req.upload_token)
    expected_name = f"source{Path(req.stored_name).suffix.lower()}"
    if req.stored_name != expected_name or Path(req.stored_name).suffix.lower() not in UPLOAD_ALLOWED_EXTENSIONS:
        raise ExtractionFailure(400, "Invalid staged upload name.", "invalid_upload_path", terminal=True)
    path = directory / expected_name
    try:
        stat = path.lstat()
    except OSError as exc:
        raise ExtractionFailure(410, "Uploaded video is no longer available.", "upload_expired", terminal=True) from exc
    if path.is_symlink() or not path.is_file() or stat.st_size != req.size:
        raise ExtractionFailure(400, "Uploaded video failed staging validation.", "invalid_upload_path", terminal=True)
    return path


def probe_uploaded_media(path: Path, require_audio: bool = True) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ExtractionFailure(503, "Local ASR requires ffprobe.", "ffmpeg_missing")
    try:
        proc = run_managed_process(
            [
                ffprobe,
                "-v",
                "error",
                "-protocol_whitelist",
                LOCAL_MEDIA_PROTOCOL_WHITELIST,
                "-probesize",
                "50000000",
                "-analyzeduration",
                "30000000",
                "-show_entries",
                "format=duration,format_name:stream=index,codec_type,codec_name,duration:stream_tags=language,title",
                "-of",
                "json",
                str(path),
            ],
            timeout=min(60, ASR_DOWNLOAD_TIMEOUT_SECONDS),
            output_limit=PROCESS_ERROR_OUTPUT_BYTES,
        )
    except ManagedProcessTimeout as exc:
        raise ExtractionFailure(408, "Uploaded video inspection timed out.", "upload_probe_timeout") from exc
    except OSError as exc:
        raise ExtractionFailure(503, "无法启动 ffprobe 媒体探测进程。", "ffmpeg_failed", retryable=True) from exc
    if proc.returncode != 0:
        raise ExtractionFailure(400, "The uploaded file is not a readable video.", "invalid_upload_media")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ExtractionFailure(400, "The uploaded file has invalid media metadata.", "invalid_upload_media") from exc
    streams = payload.get("streams") if isinstance(payload, dict) else None
    streams = streams if isinstance(streams, list) else []
    stream_types = {str(item.get("codec_type") or "") for item in streams if isinstance(item, dict)}
    if "video" not in stream_types:
        raise ExtractionFailure(400, "The uploaded file does not contain a video stream.", "upload_video_missing")
    if require_audio and "audio" not in stream_types:
        raise ExtractionFailure(422, "The uploaded video does not contain an audio track.", "upload_audio_missing")
    format_info = payload.get("format") if isinstance(payload, dict) else None
    duration_values = []
    if isinstance(format_info, dict):
        duration_values.append(format_info.get("duration"))
    duration_values.extend(item.get("duration") for item in streams if isinstance(item, dict))
    duration = 0.0
    for value in duration_values:
        try:
            candidate = float(value or 0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(candidate) and candidate > duration:
            duration = candidate
    if duration <= 0:
        raise ExtractionFailure(400, "The uploaded video duration could not be determined.", "invalid_upload_media")
    return {
        "duration": duration,
        "format_name": str((format_info or {}).get("format_name") or "")
        if isinstance(format_info, dict)
        else "",
        "has_audio": "audio" in stream_types,
        "subtitle_streams": [
            {
                "index": int(item.get("index")),
                "codec_name": str(item.get("codec_name") or "").lower(),
                "language": str((item.get("tags") or {}).get("language") or ""),
                "title": str((item.get("tags") or {}).get("title") or ""),
            }
            for item in streams
            if isinstance(item, dict)
            and item.get("codec_type") == "subtitle"
            and isinstance(item.get("index"), int)
        ],
    }


def normalize_audio_for_asr(
    input_path: Path,
    tmp_dir: Path,
    stem: str,
    timeout_seconds: float | None = None,
) -> Path:
    normalized_path = tmp_dir / f"{stem}.asr.wav"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ExtractionFailure(503, "Local ASR requires ffmpeg.", "ffmpeg_missing")
    try:
        source_bytes = input_path.stat().st_size
    except OSError:
        source_bytes = 0
    ensure_disk_space(tmp_dir, min(256 * 1024 * 1024, max(64 * 1024 * 1024, source_bytes // 2)))
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-protocol_whitelist",
        LOCAL_MEDIA_PROTOCOL_WHITELIST,
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-sample_fmt",
        "s16",
    ]
    audio_filter = asr_audio_filter()
    if audio_filter:
        command.extend(["-af", audio_filter])
    command.append(str(normalized_path))
    try:
        proc = run_managed_process(
            command,
            timeout=max(1.0, timeout_seconds or ASR_DOWNLOAD_TIMEOUT_SECONDS),
            output_limit=PROCESS_ERROR_OUTPUT_BYTES,
        )
    except ManagedProcessTimeout as exc:
        normalized_path.unlink(missing_ok=True)
        raise ExtractionFailure(504, "ffmpeg audio normalization timed out.", "download_failed") from exc
    except OSError as exc:
        normalized_path.unlink(missing_ok=True)
        raise ExtractionFailure(503, "无法启动 ffmpeg 音轨转换进程。", "ffmpeg_failed", retryable=True) from exc
    if proc.returncode != 0 or not normalized_path.exists():
        normalized_path.unlink(missing_ok=True)
        LOGGER.warning("ffmpeg audio normalization failed: %s", redact_sensitive(proc.stderr))
        raise ExtractionFailure(502, "ffmpeg 音轨转换失败。", "audio_extract_failed")
    return normalized_path


def prepare_audio_for_cloud(input_path: Path, tmp_dir: Path) -> tuple[Path, dict[str, Any]]:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise ExtractionFailure(503, "Cloud ASR requires ffmpeg and ffprobe.", "ffmpeg_missing")
    output_path = tmp_dir / "provider-audio.mp3"
    ensure_disk_space(tmp_dir, 128 * 1024 * 1024)
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-protocol_whitelist",
        LOCAL_MEDIA_PROTOCOL_WHITELIST,
        "-i",
        str(input_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "96k",
    ]
    audio_filter = asr_audio_filter()
    if audio_filter:
        command.extend(["-af", audio_filter])
    command.append(str(output_path))
    try:
        result = run_managed_process(
            command,
            timeout=ASR_DOWNLOAD_TIMEOUT_SECONDS,
            output_limit=PROCESS_ERROR_OUTPUT_BYTES,
        )
    except ManagedProcessTimeout as exc:
        output_path.unlink(missing_ok=True)
        raise ExtractionFailure(
            504,
            "Cloud ASR audio preparation timed out.",
            "download_failed",
            retryable=True,
        ) from exc
    except OSError as exc:
        output_path.unlink(missing_ok=True)
        raise ExtractionFailure(
            503,
            "Unable to start ffmpeg for cloud ASR.",
            "ffmpeg_failed",
            retryable=True,
        ) from exc
    if result.returncode != 0 or not output_path.is_file():
        output_path.unlink(missing_ok=True)
        LOGGER.warning("cloud ASR audio conversion failed: %s", redact_sensitive(result.stderr))
        raise ExtractionFailure(
            422,
            "The media does not contain a readable audio stream.",
            "no_audio_stream",
            terminal=True,
        )
    size = output_path.stat().st_size
    if size <= 0 or size > CLOUD_ASR_MAX_FILE_BYTES:
        output_path.unlink(missing_ok=True)
        raise ExtractionFailure(
            413,
            "Cloud ASR audio exceeds the configured file limit.",
            "media_too_large",
            terminal=True,
        )
    try:
        probe = run_managed_process(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration,format_name:stream=codec_type,codec_name,channels,sample_rate",
                "-of",
                "json",
                str(output_path),
            ],
            timeout=min(60, ASR_DOWNLOAD_TIMEOUT_SECONDS),
            output_limit=PROCESS_ERROR_OUTPUT_BYTES,
        )
    except ManagedProcessTimeout as exc:
        output_path.unlink(missing_ok=True)
        raise ExtractionFailure(408, "Cloud ASR audio inspection timed out.", "ffmpeg_failed") from exc
    if probe.returncode != 0:
        output_path.unlink(missing_ok=True)
        raise ExtractionFailure(422, "Cloud ASR audio inspection failed.", "ffmpeg_failed")
    try:
        payload = json.loads(probe.stdout)
        duration = float((payload.get("format") or {}).get("duration") or 0)
        streams = payload.get("streams") or []
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        output_path.unlink(missing_ok=True)
        raise ExtractionFailure(422, "Cloud ASR audio metadata is invalid.", "ffmpeg_failed") from exc
    if not math.isfinite(duration) or duration <= 0:
        output_path.unlink(missing_ok=True)
        raise ExtractionFailure(422, "Cloud ASR audio duration is invalid.", "no_audio_stream")
    if duration > ASR_MAX_AUDIO_SECONDS:
        output_path.unlink(missing_ok=True)
        raise ExtractionFailure(
            413,
            "Cloud ASR audio duration exceeds the configured limit.",
            "asr_duration_too_long",
            terminal=True,
        )
    audio_stream = next(
        (item for item in streams if isinstance(item, dict) and item.get("codec_type") == "audio"),
        {},
    )
    return output_path, {
        "duration": duration,
        "size": size,
        "format_name": str((payload.get("format") or {}).get("format_name") or ""),
        "codec_name": str(audio_stream.get("codec_name") or ""),
        "channels": int(audio_stream.get("channels") or 0) or None,
        "sample_rate": int(audio_stream.get("sample_rate") or 0) or None,
    }


TEXT_SUBTITLE_CODECS = frozenset({"ass", "mov_text", "ssa", "srt", "subrip", "text", "ttml", "webvtt"})


def extract_embedded_text_subtitle(
    media_path: Path,
    media_info: dict[str, Any],
    tmp_dir: Path,
    lang: str | None,
) -> tuple[list[SubtitleEntry], dict[str, Any]] | None:
    streams = [
        item
        for item in media_info.get("subtitle_streams", [])
        if isinstance(item, dict) and item.get("codec_name") in TEXT_SUBTITLE_CODECS
    ]
    if not streams:
        return None
    requested_language = normalized_language(lang)

    def language_score(item: dict[str, Any]) -> int:
        stream_language = normalized_language(str(item.get("language") or ""))
        if requested_language:
            return 0 if stream_language == requested_language else 3
        if stream_language == "zh-hans":
            return 0
        if stream_language == "zh-hant":
            return 1
        return 2 if not stream_language else 3

    streams.sort(
        key=lambda item: (
            language_score(item),
            int(item.get("index") or 0),
        )
    )
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ExtractionFailure(503, "Embedded subtitle extraction requires ffmpeg.", "ffmpeg_missing")
    ensure_disk_space(tmp_dir, 32 * 1024 * 1024)
    for stream in streams:
        target = tmp_dir / f"embedded-{int(stream['index'])}.srt"
        try:
            completed = run_managed_process(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-protocol_whitelist",
                    LOCAL_MEDIA_PROTOCOL_WHITELIST,
                    "-i",
                    str(media_path),
                    "-map",
                    f"0:{int(stream['index'])}",
                    "-c:s",
                    "srt",
                    "-f",
                    "srt",
                    str(target),
                ],
                timeout=min(120, OCR_TIMEOUT_SECONDS),
                output_limit=PROCESS_ERROR_OUTPUT_BYTES,
            )
        except ManagedProcessTimeout:
            target.unlink(missing_ok=True)
            continue
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise ExtractionFailure(503, "无法启动 ffmpeg 字幕提取进程。", "ffmpeg_failed", retryable=True) from exc
        if completed.returncode != 0 or not target.is_file():
            target.unlink(missing_ok=True)
            continue
        try:
            entries = parse_subtitle_text(target.read_text(encoding="utf-8", errors="replace"), "srt")
        finally:
            target.unlink(missing_ok=True)
        if entries:
            return entries, {
                "subtitle_source": "embedded_text_track",
                "subtitle_stream_index": int(stream["index"]),
                "subtitle_stream_codec": stream.get("codec_name"),
                "subtitle_stream_language": stream.get("language") or None,
            }
    return None


def normalized_ocr_key(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.lower(), flags=re.UNICODE)


def ocr_text_similarity(first: str, second: str) -> float:
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    return SequenceMatcher(None, first, second).ratio()


def ocr_lines_from_result(result: Any) -> list[dict[str, Any]]:
    raw_texts = getattr(result, "txts", None)
    raw_scores = getattr(result, "scores", None)
    raw_boxes = getattr(result, "boxes", None)
    texts = list(raw_texts) if raw_texts is not None else []
    scores = list(raw_scores) if raw_scores is not None else []
    boxes = list(raw_boxes) if raw_boxes is not None else []
    lines: list[dict[str, Any]] = []
    for index, raw_text in enumerate(texts):
        text = re.sub(r"\s+", " ", str(raw_text or "")).strip()
        if not text or not normalized_ocr_key(text):
            continue
        try:
            score = float(scores[index])
        except (IndexError, TypeError, ValueError):
            score = 0.0
        if score < OCR_MIN_CONFIDENCE:
            continue
        x = 0.0
        y = float(index)
        height = 0.0
        try:
            raw_box = boxes[index]
            points = raw_box.tolist() if hasattr(raw_box, "tolist") else raw_box
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            x = min(xs)
            y = min(ys)
            height = max(ys) - min(ys)
        except (IndexError, TypeError, ValueError):
            pass
        if boxes and height and height < 12:
            continue
        lines.append({"text": text, "score": score, "x": x, "y": y})
    lines.sort(key=lambda item: (round(float(item["y"]) / 18), float(item["x"])))
    return lines


def filter_static_ocr_lines(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(frames) < 12:
        return frames
    occurrences: dict[str, list[float]] = {}
    for frame in frames:
        seen: set[str] = set()
        for line in frame.get("lines", []):
            key = normalized_ocr_key(str(line.get("text") or ""))
            if key and key not in seen:
                occurrences.setdefault(key, []).append(float(frame["time"]))
                seen.add(key)
    duration = max(float(frame["time"]) for frame in frames) - min(float(frame["time"]) for frame in frames)
    threshold = max(12, int(len(frames) * 0.55))
    static_keys = {
        key
        for key, times in occurrences.items()
        if len(times) >= threshold and (duration <= 0 or max(times) - min(times) >= duration * 0.6)
    }
    if not static_keys:
        return frames
    filtered = [
        {
            **frame,
            "lines": [
                line
                for line in frame.get("lines", [])
                if normalized_ocr_key(str(line.get("text") or "")) not in static_keys
            ],
        }
        for frame in frames
    ]
    if any(frame.get("lines") for frame in filtered):
        return filtered
    return frames


def select_ocr_variant(variants: list[tuple[str, float]]) -> str:
    weighted: dict[str, float] = {}
    originals: dict[str, list[tuple[str, float]]] = {}
    for text, score in variants:
        key = normalized_ocr_key(text)
        if not key:
            continue
        weighted[key] = weighted.get(key, 0.0) + max(0.1, score)
        originals.setdefault(key, []).append((text, score))
    if not weighted:
        return ""
    winner = max(weighted, key=lambda key: (weighted[key], len(key)))
    return max(originals[winner], key=lambda item: (item[1], len(item[0])))[0]


def build_ocr_entries(frames: list[dict[str, Any]], sample_fps: float) -> list[SubtitleEntry]:
    interval = 1.0 / max(0.1, sample_fps)
    cleaned = filter_static_ocr_lines(frames)
    groups: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def close_current() -> None:
        nonlocal current
        if current is not None:
            groups.append(current)
            current = None

    for frame in cleaned:
        lines = frame.get("lines", [])
        text = "\n".join(str(line.get("text") or "").strip() for line in lines if line.get("text")).strip()
        score_values = [float(line.get("score") or 0) for line in lines]
        score = sum(score_values) / len(score_values) if score_values else 0.0
        key = normalized_ocr_key(text)
        timestamp = float(frame["time"])
        if not key:
            if current is not None and timestamp - float(current["last_time"]) > interval * 1.6:
                close_current()
            continue
        if current is not None and ocr_text_similarity(str(current["last_key"]), key) >= 0.92:
            current["last_time"] = timestamp
            current["last_key"] = key
            current["variants"].append((text, score))
            continue
        close_current()
        current = {
            "start_time": timestamp,
            "last_time": timestamp,
            "last_key": key,
            "variants": [(text, score)],
        }
    close_current()

    entries: list[SubtitleEntry] = []
    for group in groups:
        text = select_ocr_variant(group["variants"])
        if not text:
            continue
        start = max(0.0, float(group["start_time"]) - interval / 2)
        end = max(start + 0.35, float(group["last_time"]) + interval / 2)
        if entries and ocr_text_similarity(normalized_ocr_key(entries[-1].text), normalized_ocr_key(text)) >= 0.94:
            if start - entries[-1].end <= interval * 2:
                entries[-1].end = end
                continue
        if entries and start < entries[-1].end:
            start = entries[-1].end
        entries.append(SubtitleEntry(start, max(start + 0.35, end), text))
    return entries


def iter_mjpeg_images(stream: Any):
    buffer = bytearray()
    while True:
        chunk = stream.read(64 * 1024)
        if not chunk:
            break
        buffer.extend(chunk)
        while True:
            start = buffer.find(b"\xff\xd8")
            if start < 0:
                if len(buffer) > 1:
                    del buffer[:-1]
                break
            end = buffer.find(b"\xff\xd9", start + 2)
            if end < 0:
                if start:
                    del buffer[:start]
                if len(buffer) > 20 * 1024 * 1024:
                    raise RuntimeError("OCR frame exceeded the safety limit")
                break
            yield bytes(buffer[start : end + 2])
            del buffer[: end + 2]


def burned_subtitle_ocr_worker(
    media_path: str,
    duration: float,
    result_queue: Any,
) -> None:
    ffmpeg_process: subprocess.Popen[bytes] | None = None
    stderr_capture: LimitedStreamCapture | None = None
    try:
        from rapidocr import RapidOCR

        engine = RapidOCR(
            params={
                "Global.text_score": OCR_MIN_CONFIDENCE,
                "Global.log_level": "error",
                "Global.use_cls": False,
                "EngineConfig.onnxruntime.intra_op_num_threads": OCR_CPU_THREADS,
                "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            }
        )
        crop_height = 1.0 - OCR_CROP_TOP_RATIO
        video_filter = (
            f"fps={OCR_SAMPLE_FPS:g},"
            f"crop=iw:trunc(ih*{crop_height:.4f}/2)*2:0:trunc(ih*{OCR_CROP_TOP_RATIO:.4f}/2)*2"
        )
        total_frames = min(OCR_MAX_FRAMES, max(1, int(math.ceil(duration * OCR_SAMPLE_FPS))))
        ffmpeg_process = subprocess.Popen(
            [
                shutil.which("ffmpeg") or "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-protocol_whitelist",
                LOCAL_MEDIA_PROTOCOL_WHITELIST,
                "-i",
                media_path,
                "-an",
                "-vf",
                video_filter,
                "-frames:v",
                str(total_frames),
                "-q:v",
                "3",
                "-f",
                "image2pipe",
                "-vcodec",
                "mjpeg",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stderr_capture = LimitedStreamCapture(ffmpeg_process.stderr, PROCESS_ERROR_OUTPUT_BYTES).start()
        result_queue.put({"kind": "started", "ffmpeg_pid": ffmpeg_process.pid})
        frames: list[dict[str, Any]] = []
        if ffmpeg_process.stdout is None:
            raise RuntimeError("ffmpeg did not expose an OCR frame stream")
        for index, image in enumerate(iter_mjpeg_images(ffmpeg_process.stdout)):
            if index >= OCR_MAX_FRAMES:
                break
            try:
                result = engine(image)
                lines = ocr_lines_from_result(result)
            except Exception:
                lines = []
            frames.append({"time": index / OCR_SAMPLE_FPS, "lines": lines})
            if index % 20 == 0:
                result_queue.put({"kind": "progress", "processed": index + 1, "total": total_frames})
        try:
            return_code = ffmpeg_process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            terminate_process(ffmpeg_process)
            return_code = int(ffmpeg_process.returncode or -1)
        if return_code != 0 and not frames:
            error = stderr_capture.text() if stderr_capture is not None else ""
            raise RuntimeError(f"ffmpeg frame extraction failed with exit code {return_code}: {error}")
        entries = build_ocr_entries(frames, OCR_SAMPLE_FPS)
        result_queue.put(
            {
                "kind": "result",
                "ok": True,
                "entries": [(entry.start, entry.end, entry.text) for entry in entries],
                "meta": {
                    "ocr_frames": len(frames),
                    "ocr_sample_fps": OCR_SAMPLE_FPS,
                    "ocr_crop_top_ratio": OCR_CROP_TOP_RATIO,
                    "ocr_engine": "RapidOCR PP-OCRv6",
                },
            }
        )
    except Exception as exc:
        result_queue.put({"kind": "result", "ok": False, "error": redact_sensitive(str(exc))})
    finally:
        if ffmpeg_process is not None and ffmpeg_process.poll() is None:
            terminate_process(ffmpeg_process)
        if ffmpeg_process is not None and ffmpeg_process.stdout is not None:
            try:
                ffmpeg_process.stdout.close()
            except (AttributeError, OSError):
                pass
        if stderr_capture is not None:
            stderr_capture.finish()


def extract_burned_subtitles(media_path: Path, duration: float) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    if not shutil.which("ffmpeg"):
        raise ExtractionFailure(503, "Video subtitle OCR requires ffmpeg.", "ffmpeg_missing")
    if importlib.util.find_spec("rapidocr") is None or importlib.util.find_spec("onnxruntime") is None:
        raise ExtractionFailure(503, "Video subtitle OCR is not installed.", "ocr_missing")
    ensure_disk_space(ASR_TMP_DIR, 16 * 1024 * 1024)
    acquired = ASR_SEMAPHORE.acquire(blocking=False)
    if not acquired:
        report_progress("ocr_wait", 28, "正在等待精确解析资源")
        acquired = ASR_SEMAPHORE.acquire(timeout=ASR_QUEUE_WAIT_SECONDS)
    if not acquired:
        raise ExtractionFailure(429, "OCR wait exceeded the queue timeout.", "asr_busy")
    result_queue: Any = None
    process: Any = None
    ffmpeg_pid: int | None = None
    try:
        try:
            ctx = get_context("spawn")
            result_queue = ctx.Queue(maxsize=64)
            process = ctx.Process(
                target=burned_subtitle_ocr_worker,
                args=(str(media_path), duration, result_queue),
                name="video-subtitle-ocr",
            )
            process.start()
        except (OSError, RuntimeError) as exc:
            raise ExtractionFailure(
                503,
                "无法启动 OCR 隔离进程。",
                "ocr_failed",
                retryable=True,
            ) from exc
        deadline = time.monotonic() + OCR_TIMEOUT_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if ffmpeg_pid:
                    terminate_process_id(ffmpeg_pid)
                terminate_child_process(process)
                raise ExtractionFailure(504, f"Video subtitle OCR timed out after {OCR_TIMEOUT_SECONDS} seconds.", "ocr_timeout")
            try:
                message = result_queue.get(timeout=min(1.0, remaining))
            except Empty:
                if not process.is_alive():
                    raise ExtractionFailure(502, f"Video subtitle OCR exited without a result. exit_code={process.exitcode}", "ocr_failed")
                continue
            if message.get("kind") == "started":
                ffmpeg_pid = int(message.get("ffmpeg_pid") or 0) or None
                continue
            if message.get("kind") == "progress":
                processed = int(message.get("processed") or 0)
                total = max(1, int(message.get("total") or 1))
                progress = min(88, 42 + int(processed / total * 46))
                report_progress("ocr", progress, f"正在识别画面字幕 {processed}/{total}")
                continue
            if message.get("kind") != "result":
                continue
            process.join(5)
            if not message.get("ok"):
                LOGGER.warning("OCR worker failed: %s", redact_sensitive(str(message.get("error") or "unknown error")))
                raise ExtractionFailure(502, f"Video subtitle OCR failed: {message.get('error') or 'unknown error'}", "ocr_failed")
            entries = [
                SubtitleEntry(float(start), float(end), str(text))
                for start, end, text in message.get("entries", [])
                if str(text).strip()
            ]
            meta = message.get("meta") if isinstance(message.get("meta"), dict) else {}
            return entries, meta
    finally:
        terminate_child_process(process)
        if result_queue is not None:
            try:
                result_queue.close()
            except Exception:
                pass
        ASR_SEMAPHORE.release()


def extract_video_subtitle_pixels(
    media_path: Path,
    media_info: dict[str, Any],
    tmp_dir: Path,
    lang: str | None,
) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    report_progress("embedded_subtitle", 36, "正在检查视频内嵌字幕轨")
    embedded = extract_embedded_text_subtitle(media_path, media_info, tmp_dir, lang)
    if embedded is not None:
        return embedded
    report_progress("ocr", 42, "正在准备画面字幕识别")
    try:
        entries, meta = extract_burned_subtitles(media_path, float(media_info.get("duration") or 0))
    except ExtractionFailure as exc:
        if media_info.get("has_audio") and exc.reason in {"ocr_missing", "ocr_failed", "ocr_timeout"}:
            return [], {
                "subtitle_source": "burned_in_ocr",
                "ocr_failed": True,
                "ocr_failure_reason": public_reason(exc.reason),
            }
        raise
    meta["subtitle_source"] = "burned_in_ocr"
    return entries, meta


def ytdlp_download_worker(payload: dict[str, Any], result_queue: Any) -> None:
    group_owned = False
    try:
        if hasattr(os, "setsid"):
            os.setsid()
            group_owned = True
    except OSError:
        group_owned = False
    result_queue.put({"kind": "started", "group_owned": group_owned})
    deadline = time.monotonic() + max(30, int(payload.get("timeout_seconds") or 300))
    max_bytes = max(1, int(payload.get("max_bytes") or 1))
    too_large = False
    timed_out = False
    last_progress = -1

    def progress_hook(status: dict[str, Any]) -> None:
        nonlocal too_large, timed_out, last_progress
        if time.monotonic() >= deadline:
            timed_out = True
            raise RuntimeError("yt-dlp deadline exceeded")
        downloaded = int(status.get("downloaded_bytes") or 0)
        total = int(status.get("total_bytes") or status.get("total_bytes_estimate") or 0)
        if downloaded > max_bytes or total > max_bytes:
            too_large = True
            raise RuntimeError("yt-dlp size limit exceeded")
        if status.get("status") != "downloading" or total <= 0:
            return
        progress = min(100, int(downloaded / total * 100))
        if progress < last_progress + 2:
            return
        last_progress = progress
        try:
            result_queue.put_nowait({"kind": "progress", "progress": progress})
        except Full:
            pass

    target_dir = Path(str(payload["target_dir"]))
    mode = str(payload.get("mode") or "audio")
    media_type = str(payload.get("media_type") or "audio")
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": str(
            target_dir / ("%(id)s.%(ext)s" if mode == "audio" else "source.%(ext)s")
        ),
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "http_headers": dict(payload.get("http_headers") or {}),
        "logger": QuietYtdlpLogger(),
        "noplaylist": True,
        "cachedir": False,
        "continuedl": False,
        "overwrites": True,
        "max_filesize": max_bytes,
        "progress_hooks": [progress_hook],
    }
    if mode == "audio":
        options["format"] = "bestaudio/best"
    elif media_type == "video":
        options.update(
            {
                "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "merge_output_format": "mp4",
                "concurrent_fragment_downloads": max(
                    1,
                    min(8, int(payload.get("fragment_concurrency") or 4)),
                ),
            }
        )
    else:
        options["format"] = "bestaudio/best"

    try:
        with YoutubeDL(options) as ydl:
            raw_info = ydl.extract_info(str(payload["url"]), download=True)
        info = raw_info if isinstance(raw_info, dict) else {}
        summary = {
            key: info.get(key)
            for key in ("id", "title", "duration", "webpage_url", "uploader", "channel", "ext")
            if info.get(key) is not None
        }
        result_queue.put({"kind": "result", "ok": True, "info": summary}, timeout=5)
    except Exception as exc:
        reason = "media_too_large" if too_large else ("download_timeout" if timed_out else "download_failed")
        try:
            result_queue.put(
                {
                    "kind": "result",
                    "ok": False,
                    "reason": reason,
                    "error": redact_sensitive(str(exc)),
                },
                timeout=5,
            )
        except Exception:
            pass


def run_isolated_ytdlp_download(
    *,
    url: str,
    target_dir: Path,
    mode: Literal["audio", "media"],
    media_type: Literal["video", "audio"] = "audio",
    allow_cookie: bool,
    max_bytes: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    result_queue: Any = None
    process: Any = None
    group_owned = False
    try:
        try:
            ctx = get_context("spawn")
            result_queue = ctx.Queue(maxsize=64)
            process = ctx.Process(
                target=ytdlp_download_worker,
                args=(
                    {
                        "url": url,
                        "target_dir": str(target_dir),
                        "mode": mode,
                        "media_type": media_type,
                        "http_headers": headers_for(allow_cookie=allow_cookie),
                        "max_bytes": max_bytes,
                        "timeout_seconds": max(1, int(timeout_seconds)),
                        "fragment_concurrency": max(
                            1,
                            min(8, int(os.getenv("MEDIA_FRAGMENT_CONCURRENCY", "2"))),
                        ),
                    },
                    result_queue,
                ),
                name="isolated-ytdlp-download",
            )
            process.start()
        except (OSError, RuntimeError) as exc:
            raise ExtractionFailure(
                503,
                "无法启动 yt-dlp 隔离下载进程。",
                "download_failed",
                retryable=True,
            ) from exc
        deadline = time.monotonic() + max(1.0, timeout_seconds)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExtractionFailure(504, "yt-dlp 下载超时。", "download_failed", retryable=True)
            try:
                message = result_queue.get(timeout=min(1.0, remaining))
            except Empty:
                if not process.is_alive():
                    process.join(0)
                    raise ExtractionFailure(
                        502,
                        "yt-dlp 下载进程意外退出。",
                        "download_failed",
                        retryable=True,
                    )
                continue
            if not isinstance(message, dict):
                continue
            if message.get("kind") == "started":
                group_owned = bool(message.get("group_owned"))
                continue
            if message.get("kind") == "progress" and mode == "media":
                progress = min(78, 20 + int(int(message.get("progress") or 0) * 0.58))
                report_progress("media_download", progress, "正在下载媒体文件")
                continue
            if message.get("kind") != "result":
                continue
            process.join(5)
            if not message.get("ok"):
                reason = str(message.get("reason") or "download_failed")
                LOGGER.warning("isolated yt-dlp failed: %s", redact_sensitive(str(message.get("error") or reason)))
                if reason == "media_too_large":
                    raise ExtractionFailure(413, "下载媒体超过大小限制。", "media_too_large")
                if reason == "download_timeout":
                    raise ExtractionFailure(504, "yt-dlp 下载超时。", "download_failed", retryable=True)
                raise ExtractionFailure(502, "yt-dlp 下载失败。", "download_failed", retryable=True)
            info = message.get("info")
            return info if isinstance(info, dict) else {}
    finally:
        terminate_child_process_group(process, group_owned)
        if result_queue is not None:
            try:
                result_queue.cancel_join_thread()
                result_queue.close()
            except Exception:
                pass


def download_audio_for_asr(
    url: str,
    allow_cookie: bool,
    tmp_dir: Path,
    *,
    normalize: bool = True,
) -> tuple[Path, dict[str, Any]]:
    def do_api_download() -> tuple[Path, dict[str, Any]]:
        deadline = time.monotonic() + ASR_DOWNLOAD_TIMEOUT_SECONDS
        attempt_dir = tmp_dir / "bilibili-api"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        bvid, canonical_url, data, selected_page, cid = bili_view_context(url, allow_cookie)
        play = api_get_json(
            "https://api.bilibili.com/x/player/playurl?"
            + urllib.parse.urlencode({"bvid": bvid, "cid": cid, "fnval": 16, "qn": 64}),
            canonical_url,
            allow_cookie,
        )
        play_data = play.get("data") or {}
        audio_items = ((play_data.get("dash") or {}).get("audio") or []) if isinstance(play_data, dict) else []
        if not audio_items:
            raise ExtractionFailure(
                422,
                "B站视频没有音轨。",
                "no_audio_stream",
                terminal=True,
            )
        audio_items = [
            item
            for item in audio_items
            if isinstance(item, dict) and (item.get("baseUrl") or item.get("base_url"))
        ]
        if not audio_items:
            raise ExtractionFailure(
                422,
                "B站视频没有可读取的音轨。",
                "no_audio_stream",
                terminal=True,
            )
        audio_items.sort(key=lambda item: int(item.get("bandwidth") or 0))
        audio_quality = os.getenv("ASR_AUDIO_QUALITY", "best").strip().lower()
        if audio_quality == "best":
            selected_audio = audio_items[-1]
        elif audio_quality == "smallest":
            selected_audio = audio_items[0]
        else:
            speech_items = [item for item in audio_items if int(item.get("bandwidth") or 0) >= 80_000]
            selected_audio = speech_items[0] if speech_items else audio_items[-1]
        audio_url = str(selected_audio.get("baseUrl") or selected_audio.get("base_url") or "")
        if not audio_url:
            raise ExtractionFailure(502, "Bilibili playurl API returned an empty audio URL.", "audio_extract_failed")
        raw_path = attempt_dir / f"{bvid}.m4s"
        headers = headers_for(canonical_url, False)
        headers["Range"] = "bytes=0-"
        downloaded = 0
        with httpx.Client(
            timeout=remaining_before(deadline, "Bilibili API audio download"),
            follow_redirects=True,
            headers=headers,
            event_hooks={"request": [validate_public_request]},
        ) as client:
            with client.stream("GET", audio_url) as resp:
                resp.raise_for_status()
                try:
                    content_length = int(resp.headers.get("content-length") or 0)
                except ValueError:
                    content_length = 0
                if content_length > BILI_MAX_DOWNLOAD_BYTES:
                    raise ExtractionFailure(413, "Bilibili audio exceeds the download size limit.", "download_too_large")
                with raw_path.open("wb") as handle:
                    for chunk in resp.iter_bytes(1024 * 1024):
                        if chunk:
                            remaining_before(deadline, "Bilibili API audio download")
                            downloaded += len(chunk)
                            if downloaded > BILI_MAX_DOWNLOAD_BYTES:
                                raise ExtractionFailure(
                                    413,
                                    "Bilibili audio exceeds the download size limit.",
                                    "download_too_large",
                                )
                            handle.write(chunk)
        output_path = raw_path
        if normalize:
            output_path = normalize_audio_for_asr(
                raw_path,
                tmp_dir,
                bvid,
                remaining_before(deadline, "Bilibili audio normalization"),
            )
            raw_path.unlink(missing_ok=True)
        page_number = bili_page_number(canonical_url)
        title = data.get("title")
        if page_number > 1 and selected_page and selected_page.get("part"):
            title = f"{title} - P{page_number} {selected_page['part']}"
        return output_path, {
            "id": bvid,
            "title": title,
            "duration": (selected_page or {}).get("duration") or data.get("duration"),
            "webpage_url": canonical_url,
            "audio_download": "bilibili_playurl",
            "audio_bytes": downloaded,
            "audio_bandwidth": int(selected_audio.get("bandwidth") or 0) or None,
            "audio_quality_strategy": audio_quality,
            "audio_normalized_for_asr": normalize,
        }

    def do_download() -> tuple[Path, dict[str, Any]]:
        deadline = time.monotonic() + ASR_DOWNLOAD_TIMEOUT_SECONDS
        attempt_dir = tmp_dir / "yt-dlp"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        info = run_isolated_ytdlp_download(
            url=url,
            target_dir=attempt_dir,
            mode="audio",
            allow_cookie=allow_cookie,
            max_bytes=BILI_MAX_DOWNLOAD_BYTES,
            timeout_seconds=remaining_before(deadline, "yt-dlp audio download"),
        )
        candidates = sorted(
            (
                path
                for path in attempt_dir.iterdir()
                if path.is_file() and path.suffix not in {".part", ".ytdl"}
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise ExtractionFailure(502, "Audio download did not produce a media file.", "audio_extract_failed")
        source_path = candidates[0]
        if source_path.stat().st_size > BILI_MAX_DOWNLOAD_BYTES:
            raise ExtractionFailure(413, "Bilibili audio exceeds the download size limit.", "download_too_large")
        output_path = source_path
        if normalize:
            output_path = normalize_audio_for_asr(
                source_path,
                tmp_dir,
                f"{source_path.stem}.normalized",
                remaining_before(deadline, "yt-dlp audio normalization"),
            )
            source_path.unlink(missing_ok=True)
        if isinstance(info, dict):
            info["audio_normalized_for_asr"] = normalize
            info["audio_download"] = "yt-dlp_fallback"
        return output_path, info if isinstance(info, dict) else {"audio_normalized_for_asr": normalize}

    try:
        return do_api_download()
    except ExtractionFailure as first:
        if first.terminal and first.reason != "invalid_bvid":
            raise
        try:
            return do_download()
        except Exception as raw_second:
            second = raw_second if isinstance(raw_second, ExtractionFailure) else ExtractionFailure(
                502,
                f"yt-dlp audio download failed: {raw_second}",
                "audio_extract_failed",
            )
            raise ExtractionFailure(
                second.status_code,
                f"{second.detail} Bilibili API reason: {first.detail}",
                second.reason,
            ) from second
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise ExtractionFailure(
                507,
                "服务器下载目录剩余空间不足。",
                "disk_space_low",
                retryable=True,
            ) from exc
        try:
            return do_download()
        except Exception as raw_second:
            second = raw_second if isinstance(raw_second, ExtractionFailure) else ExtractionFailure(
                502,
                f"yt-dlp audio download failed: {raw_second}",
                "audio_extract_failed",
            )
            raise second from raw_second
    except Exception as exc:
        try:
            return do_download()
        except Exception as raw_second:
            second = raw_second if isinstance(raw_second, ExtractionFailure) else ExtractionFailure(
                502,
                f"yt-dlp audio download failed: {raw_second}",
                "audio_extract_failed",
            )
            raise ExtractionFailure(
                second.status_code,
                f"{second.detail} Bilibili API reason: {exc}",
                second.reason,
            ) from second


def probe_downloaded_media(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise ExtractionFailure(503, "Media extraction requires ffprobe.", "ffmpeg_missing")
    try:
        completed = run_managed_process(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type",
                "-of",
                "json",
                str(path),
            ],
            timeout=30,
            output_limit=PROCESS_ERROR_OUTPUT_BYTES,
        )
    except ManagedProcessTimeout as exc:
        raise ExtractionFailure(504, "Media inspection timed out.", "media_probe_timeout") from exc
    except OSError as exc:
        raise ExtractionFailure(503, "无法启动 ffprobe 媒体探测进程。", "ffmpeg_failed", retryable=True) from exc
    if completed.returncode != 0:
        raise ExtractionFailure(502, "Downloaded file is not readable media.", "invalid_downloaded_media")
    try:
        payload = json.loads(completed.stdout)
        streams = payload.get("streams") or []
        duration = float((payload.get("format") or {}).get("duration") or 0) or None
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ExtractionFailure(502, "Downloaded media metadata is invalid.", "invalid_downloaded_media") from exc
    return {
        "has_video": any(item.get("codec_type") == "video" for item in streams if isinstance(item, dict)),
        "has_audio": any(item.get("codec_type") == "audio" for item in streams if isinstance(item, dict)),
        "duration": duration,
    }


def select_downloaded_media(directory: Path, media_type: Literal["video", "audio"]) -> tuple[Path, dict[str, Any]]:
    candidates: list[tuple[tuple[int, int, int], Path, dict[str, Any]]] = []
    ignored_suffixes = {".part", ".ytdl", ".json", ".jpg", ".jpeg", ".png", ".webp"}
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() in ignored_suffixes:
            continue
        try:
            stat = path.lstat()
            if path.is_symlink() or stat.st_size <= 0:
                continue
            probe = probe_downloaded_media(path)
        except (OSError, ExtractionFailure):
            continue
        if media_type == "video" and not probe["has_video"]:
            continue
        if media_type == "audio" and not probe["has_audio"]:
            continue
        rank = (
            int(bool(probe["has_video"])),
            int(bool(probe["has_audio"])),
            stat.st_size,
        )
        candidates.append((rank, path, probe))
    if not candidates:
        reason = "video_stream_missing" if media_type == "video" else "audio_stream_missing"
        raise ExtractionFailure(502, "Media download did not produce the requested stream.", reason)
    _, path, probe = max(candidates, key=lambda item: item[0])
    if path.stat().st_size > MEDIA_MAX_BYTES:
        raise ExtractionFailure(413, "Downloaded media exceeds the size limit.", "media_too_large")
    return path, probe


def download_bilibili_media_ytdlp(
    req: MediaJobRequest,
    target_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    target_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + ASR_DOWNLOAD_TIMEOUT_SECONDS
    info = run_isolated_ytdlp_download(
        url=req.input,
        target_dir=target_dir,
        mode="media",
        media_type=req.media_type,
        allow_cookie=cookie_allowed(req.use_cookie),
        max_bytes=MEDIA_MAX_BYTES,
        timeout_seconds=remaining_before(deadline, "Bilibili yt-dlp media download"),
    )
    source_path, probe = select_downloaded_media(target_dir, req.media_type)
    return source_path, {
        "id": info.get("id"),
        "title": info.get("title"),
        "author": info.get("uploader") or info.get("channel"),
        "duration": info.get("duration") or probe.get("duration"),
        "webpage_url": info.get("webpage_url") or req.input,
        "source_container": source_path.suffix.lower().lstrip("."),
    }


def bili_stream_urls(item: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for value in (item.get("baseUrl"), item.get("base_url")):
        if isinstance(value, str) and value:
            candidates.append(value)
    for key in ("backupUrl", "backup_url"):
        values = item.get(key) or []
        if isinstance(values, str):
            values = [values]
        if isinstance(values, list):
            candidates.extend(str(value) for value in values if isinstance(value, str) and value)
    return list(dict.fromkeys(candidates))


def download_bilibili_stream(
    urls: list[str],
    target: Path,
    referer: str,
    deadline: float,
    remaining_limit: int,
    progress_start: int,
    progress_span: int,
    message: str,
) -> int:
    if not urls:
        raise ExtractionFailure(502, "Bilibili returned an empty media URL.", "download_failed")
    last_error: Exception | None = None
    for url in urls:
        downloaded = 0
        target.unlink(missing_ok=True)
        try:
            headers = headers_for(referer, False)
            headers["Range"] = "bytes=0-"
            with httpx.Client(
                timeout=remaining_before(deadline, message),
                follow_redirects=True,
                headers=headers,
                event_hooks={"request": [validate_public_request]},
            ) as client:
                with client.stream("GET", url) as response:
                    response.raise_for_status()
                    try:
                        content_length = int(response.headers.get("content-length") or 0)
                    except ValueError:
                        content_length = 0
                    if content_length > remaining_limit:
                        raise ExtractionFailure(413, "Downloaded media exceeds the size limit.", "media_too_large")
                    with target.open("xb") as handle:
                        for chunk in response.iter_bytes(1024 * 1024):
                            if not chunk:
                                continue
                            remaining_before(deadline, message)
                            downloaded += len(chunk)
                            if downloaded > remaining_limit:
                                raise ExtractionFailure(
                                    413,
                                    "Downloaded media exceeds the size limit.",
                                    "media_too_large",
                                )
                            handle.write(chunk)
                            if content_length:
                                progress = progress_start + int(downloaded / content_length * progress_span)
                                report_progress(
                                    "media_download",
                                    min(progress_start + progress_span, progress),
                                    message,
                                )
            if downloaded <= 0:
                raise ExtractionFailure(502, "Bilibili media stream was empty.", "download_failed")
            return downloaded
        except ExtractionFailure as exc:
            target.unlink(missing_ok=True)
            if exc.status_code == 413:
                raise
            last_error = exc
        except OSError as exc:
            target.unlink(missing_ok=True)
            if exc.errno == errno.ENOSPC:
                raise ExtractionFailure(
                    507,
                    "服务器下载目录剩余空间不足。",
                    "disk_space_low",
                    retryable=True,
                ) from exc
            last_error = exc
        except Exception as exc:
            target.unlink(missing_ok=True)
            last_error = exc
    raise ExtractionFailure(502, "Bilibili media stream download failed.", "download_failed") from last_error


def merge_bilibili_dash(
    video_path: Path,
    audio_path: Path | None,
    target: Path,
    deadline: float,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ExtractionFailure(503, "Video extraction requires ffmpeg.", "ffmpeg_missing")
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(video_path),
    ]
    if audio_path is not None:
        command.extend(["-i", str(audio_path), "-map", "0:v:0", "-map", "1:a:0"])
    else:
        command.extend(["-map", "0:v:0"])
    command.extend(["-c", "copy", "-movflags", "+faststart", str(target)])
    try:
        required_bytes = video_path.stat().st_size + (audio_path.stat().st_size if audio_path else 0)
    except OSError:
        required_bytes = 64 * 1024 * 1024
    ensure_disk_space(target.parent, required_bytes)
    report_progress("media_convert", 82, "正在合并视频和音频")
    try:
        completed = run_managed_process(
            command,
            timeout=remaining_before(deadline, "Bilibili media merge"),
            output_limit=PROCESS_ERROR_OUTPUT_BYTES,
        )
    except ManagedProcessTimeout as exc:
        target.unlink(missing_ok=True)
        raise ExtractionFailure(504, "Bilibili media merge timed out.", "media_convert_failed") from exc
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise ExtractionFailure(503, "无法启动 ffmpeg 媒体合并进程。", "ffmpeg_failed", retryable=True) from exc
    if completed.returncode != 0 or not target.is_file():
        target.unlink(missing_ok=True)
        raise ExtractionFailure(502, "Bilibili media merge failed.", "media_convert_failed")


def download_bilibili_media_api(
    req: MediaJobRequest,
    target_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    target_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + ASR_DOWNLOAD_TIMEOUT_SECONDS
    allow_cookie = cookie_allowed(req.use_cookie)
    bvid, canonical_url, data, selected_page, cid = bili_view_context(req.input, allow_cookie)
    play = api_get_json(
        "https://api.bilibili.com/x/player/playurl?"
        + urllib.parse.urlencode(
            {
                "bvid": bvid,
                "cid": cid,
                "fnval": 16,
                "fnver": 0,
                "qn": 80,
                "fourk": 0,
            }
        ),
        canonical_url,
        allow_cookie,
    )
    play_data = play.get("data") or {}
    dash = play_data.get("dash") or {}
    audio_items = [
        item
        for item in (dash.get("audio") or [])
        if isinstance(item, dict) and bili_stream_urls(item)
    ]
    audio_items.sort(key=lambda item: int(item.get("bandwidth") or 0), reverse=True)
    if req.media_type == "audio":
        if not audio_items:
            raise ExtractionFailure(502, "Bilibili returned no audio stream.", "audio_stream_missing")
        source_path = target_dir / "source.m4s"
        downloaded = download_bilibili_stream(
            bili_stream_urls(audio_items[0]),
            source_path,
            canonical_url,
            deadline,
            MEDIA_MAX_BYTES,
            20,
            58,
            "正在下载 B站音频",
        )
    else:
        video_items = [
            item
            for item in (dash.get("video") or [])
            if isinstance(item, dict) and bili_stream_urls(item)
        ]
        within_limit = [item for item in video_items if int(item.get("height") or 0) <= 1080]
        if within_limit:
            video_items = within_limit
        video_items.sort(
            key=lambda item: (
                int(item.get("height") or 0),
                int(item.get("codecid") == 7 or str(item.get("codecs") or "").startswith("avc")),
                int(item.get("bandwidth") or 0),
            ),
            reverse=True,
        )
        if not video_items:
            raise ExtractionFailure(502, "Bilibili returned no video stream.", "video_stream_missing")
        raw_audio: Path | None = None
        audio_bytes = 0
        if audio_items:
            raw_audio = target_dir / "source.audio.m4s"
            audio_bytes = download_bilibili_stream(
                bili_stream_urls(audio_items[0]),
                raw_audio,
                canonical_url,
                deadline,
                MEDIA_MAX_BYTES,
                20,
                8,
                "正在下载 B站音频",
            )
        source_path = target_dir / "source.mp4"
        raw_video = target_dir / "source.video.m4s"
        last_size_error: ExtractionFailure | None = None
        for video_item in video_items:
            raw_video.unlink(missing_ok=True)
            source_path.unlink(missing_ok=True)
            try:
                download_bilibili_stream(
                    bili_stream_urls(video_item),
                    raw_video,
                    canonical_url,
                    deadline,
                    MEDIA_MAX_BYTES - audio_bytes,
                    28,
                    50,
                    "正在下载 B站视频",
                )
                merge_bilibili_dash(raw_video, raw_audio, source_path, deadline)
                if source_path.stat().st_size > MEDIA_MAX_BYTES:
                    raise ExtractionFailure(413, "Downloaded media exceeds the size limit.", "media_too_large")
                last_size_error = None
                break
            except ExtractionFailure as exc:
                raw_video.unlink(missing_ok=True)
                source_path.unlink(missing_ok=True)
                if exc.status_code != 413:
                    raise
                last_size_error = exc
        if last_size_error is not None or not source_path.is_file():
            raise last_size_error or ExtractionFailure(
                413,
                "Downloaded media exceeds the size limit.",
                "media_too_large",
            )
        raw_video.unlink(missing_ok=True)
        if raw_audio is not None:
            raw_audio.unlink(missing_ok=True)
        downloaded = source_path.stat().st_size
    page_number = bili_page_number(canonical_url)
    title = data.get("title")
    if page_number > 1 and selected_page and selected_page.get("part"):
        title = f"{title} - P{page_number} {selected_page['part']}"
    return source_path, {
        "id": bvid,
        "title": title,
        "author": (data.get("owner") or {}).get("name"),
        "duration": (selected_page or {}).get("duration") or data.get("duration"),
        "webpage_url": canonical_url,
        "source_container": source_path.suffix.lower().lstrip("."),
        "media_bytes": downloaded,
        "media_download": "bilibili_playurl",
    }


def download_bilibili_media(
    req: MediaJobRequest,
    target_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    try:
        return download_bilibili_media_api(req, target_dir)
    except ExtractionFailure as first:
        if (first.terminal and first.reason != "invalid_bvid") or first.status_code in {404, 413}:
            raise
        LOGGER.warning(
            "Bilibili playurl media path failed; trying yt-dlp",
            extra={"reason": first.reason, "media_type": req.media_type},
        )
        try:
            return download_bilibili_media_ytdlp(req, target_dir)
        except ExtractionFailure as second:
            raise ExtractionFailure(
                second.status_code,
                "Bilibili media download failed.",
                second.reason,
            ) from second


def prepare_media_output(
    source_path: Path,
    media_type: Literal["video", "audio"],
    artifact_dir: Path,
) -> tuple[Path, str]:
    probe = probe_downloaded_media(source_path)
    if media_type == "audio":
        if not probe["has_audio"]:
            raise ExtractionFailure(422, "Downloaded media has no audio stream.", "audio_stream_missing")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ExtractionFailure(503, "Audio extraction requires ffmpeg.", "ffmpeg_missing")
        final_path = artifact_dir / "artifact.mp3"
        try:
            source_bytes = source_path.stat().st_size
        except OSError:
            source_bytes = 0
        ensure_disk_space(artifact_dir, min(MEDIA_MAX_BYTES, max(32 * 1024 * 1024, source_bytes // 2)))
        report_progress("media_convert", 86, "正在生成 MP3 音频")
        try:
            completed = run_managed_process(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-nostdin",
                    "-i",
                    str(source_path),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "192k",
                    "-id3v2_version",
                    "3",
                    str(final_path),
                ],
                timeout=ASR_DOWNLOAD_TIMEOUT_SECONDS,
                output_limit=PROCESS_ERROR_OUTPUT_BYTES,
            )
        except ManagedProcessTimeout as exc:
            final_path.unlink(missing_ok=True)
            raise ExtractionFailure(504, "Audio conversion timed out.", "media_convert_failed") from exc
        except OSError as exc:
            final_path.unlink(missing_ok=True)
            raise ExtractionFailure(503, "无法启动 ffmpeg 音频转换进程。", "ffmpeg_failed", retryable=True) from exc
        if completed.returncode != 0 or not final_path.is_file():
            final_path.unlink(missing_ok=True)
            raise ExtractionFailure(502, "Audio conversion failed.", "media_convert_failed")
        source_path.unlink(missing_ok=True)
        return final_path, "audio/mpeg"

    if not probe["has_video"]:
        raise ExtractionFailure(422, "Downloaded media has no video stream.", "video_stream_missing")
    content_types = {
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
    }
    suffix = source_path.suffix.lower()
    if suffix not in content_types:
        suffix = ".mp4"
    final_path = artifact_dir / f"artifact{suffix}"
    os.replace(source_path, final_path)
    return final_path, content_types.get(suffix, "video/mp4")


def finalize_media_artifact(
    req: MediaJobRequest,
    final_path: Path,
    content_type: str,
    info: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    try:
        stat = final_path.lstat()
    except OSError as exc:
        raise ExtractionFailure(502, "Media artifact was not created.", "artifact_missing") from exc
    if final_path.is_symlink() or not final_path.is_file() or stat.st_size <= 0:
        raise ExtractionFailure(502, "Media artifact is invalid.", "invalid_artifact")
    resize_media_reservation(req.artifact_token, stat.st_size)
    extension = final_path.suffix.lower().lstrip(".") or ("mp3" if req.media_type == "audio" else "mp4")
    title = str(info.get("title") or info.get("id") or "video").strip()[:160]
    filename = safe_filename(title, extension)
    now = time.time()
    expires_at = now + MEDIA_ARTIFACT_TTL_SECONDS
    metadata = {
        "version": 1,
        "artifact_token": req.artifact_token,
        "owner_id": req.owner_id,
        "stored_name": final_path.name,
        "filename": filename,
        "content_type": content_type,
        "size": stat.st_size,
        "created_at": now,
        "expires_at": expires_at,
    }
    try:
        write_media_artifact_metadata(final_path.parent, metadata)
    except OSError as exc:
        reason = "disk_space_low" if exc.errno == errno.ENOSPC else "artifact_write_failed"
        status_code = 507 if exc.errno == errno.ENOSPC else 502
        raise ExtractionFailure(
            status_code,
            "服务器无法保存媒体产物。",
            reason,
            retryable=True,
        ) from exc
    platform = detect_platform(req.input)
    result_metadata = {
        "title": title,
        "id": info.get("id"),
        "author": info.get("author"),
        "duration": info.get("duration"),
        "webpage_url": info.get("webpage_url") or req.input,
        "platform": platform,
        "source": "direct_media",
        "media_type": req.media_type,
        "media_bytes": stat.st_size,
        "source_container": info.get("source_container"),
        "cookie_used": platform == "bilibili" and cookie_allowed(req.use_cookie),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "artifact_ttl_seconds": MEDIA_ARTIFACT_TTL_SECONDS,
    }
    report_progress("media_finalize", 97, "正在准备下载文件")
    payload = {
        "ok": True,
        "kind": "media",
        "media_type": req.media_type,
        "filename": filename,
        "content_type": content_type,
        "size": stat.st_size,
        "download_url": f"/api/artifacts/{req.artifact_token}",
        "metadata": result_metadata,
    }
    return payload


def media_extraction_payload(req: MediaJobRequest) -> dict[str, Any]:
    started = time.monotonic()
    artifact_dir = media_artifact_directory(req.artifact_token)
    source_dir = artifact_dir / "source"
    ensure_disk_space(MEDIA_ARTIFACT_DIR, MEDIA_MAX_BYTES)
    MEDIA_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(MEDIA_ARTIFACT_DIR, 0o700)
    artifact_dir.mkdir(mode=0o700)
    source_dir.mkdir(mode=0o700)
    platform = detect_platform(req.input)
    report_progress("platform", 12, f"正在解析{'抖音' if platform == 'douyin' else 'B站'}视频信息")
    if platform == "douyin":
        try:
            video = get_douyin_video(req.input, force_refresh=req.force_refresh)
            report_progress("media_download", 20, "正在下载抖音媒体文件")
            source_path, info = download_douyin_media(
                video,
                source_dir,
                require_video=req.media_type == "video",
            )
        except DouyinAdapterError as exc:
            raise ExtractionFailure(exc.status_code, exc.message, exc.reason) from exc
        info["source_container"] = source_path.suffix.lower().lstrip(".")
    else:
        report_progress("media_download", 20, "正在下载 B站媒体文件")
        source_path, info = download_bilibili_media(req, source_dir)
    if source_path.stat().st_size > MEDIA_MAX_BYTES:
        raise ExtractionFailure(413, "Downloaded media exceeds the size limit.", "media_too_large")
    final_path, content_type = prepare_media_output(source_path, req.media_type, artifact_dir)
    shutil.rmtree(source_dir)
    return finalize_media_artifact(req, final_path, content_type, info, started)


def _release_whisper_model_locked() -> None:
    global _ASR_MODEL_KEY, _ASR_MODEL_INSTANCE
    instance = _ASR_MODEL_INSTANCE
    _ASR_MODEL_INSTANCE = None
    _ASR_MODEL_KEY = None
    if instance is not None:
        runtime_model = getattr(instance, "model", None)
        unload = getattr(runtime_model, "unload_model", None)
        if not callable(unload):
            unload = getattr(instance, "unload_model", None)
        if callable(unload):
            try:
                unload()
            except Exception as exc:
                LOGGER.warning("ASR model unload failed: %s", type(exc).__name__)
    gc.collect()


def clear_whisper_model() -> None:
    with _ASR_MODEL_LOCK:
        _release_whisper_model_locked()


def whisper_model(model_name: str, compute_type: str, device: str, cpu_threads: int) -> Any:
    global _ASR_MODEL_KEY, _ASR_MODEL_INSTANCE
    key = (model_name, compute_type, device, cpu_threads)
    with _ASR_MODEL_LOCK:
        if _ASR_MODEL_INSTANCE is not None and _ASR_MODEL_KEY == key:
            return _ASR_MODEL_INSTANCE
        if _ASR_MODEL_INSTANCE is not None:
            _release_whisper_model_locked()
        from faster_whisper import WhisperModel

        instance = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
            cpu_threads=cpu_threads,
            download_root=str(ASR_MODEL_DIR),
        )
        _ASR_MODEL_INSTANCE = instance
        _ASR_MODEL_KEY = key
        return instance


def classify_asr_worker_error(value: str) -> str:
    normalized = value.lower()
    if any(
        marker in normalized
        for marker in (
            "huggingface",
            "localentrynotfound",
            "couldn't reach",
            "failed to download",
            "download error",
            "model not found",
            "permission denied",
        )
    ):
        return "asr_model_download_failed"
    if any(marker in normalized for marker in ("out of memory", "memoryerror", "cannot allocate memory")):
        return "asr_worker_crashed"
    return "asr_failed"


def audio_duration_seconds(audio_path: str) -> float:
    try:
        with wave.open(audio_path, "rb") as source:
            frame_rate = source.getframerate()
            return source.getnframes() / frame_rate if frame_rate > 0 else 0.0
    except (OSError, EOFError, wave.Error):
        return 0.0


def peak_rss_mb() -> float | None:
    try:
        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (OSError, ValueError):
        return None
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(value / divisor, 1)


def parse_linux_memory_kib(value: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in value.splitlines():
        name, separator, raw = line.partition(":")
        if not separator:
            continue
        fields = raw.strip().split()
        try:
            result[name] = int(fields[0]) if fields else 0
        except ValueError:
            continue
    return result


def runtime_memory_status() -> dict[str, float | None]:
    process_values: dict[str, int] = {}
    system_values: dict[str, int] = {}
    if sys.platform.startswith("linux"):
        try:
            process_values = parse_linux_memory_kib(Path("/proc/self/status").read_text(encoding="utf-8"))
        except OSError:
            pass
        try:
            system_values = parse_linux_memory_kib(Path("/proc/meminfo").read_text(encoding="utf-8"))
        except OSError:
            pass
    swap_total = system_values.get("SwapTotal")
    swap_free = system_values.get("SwapFree")
    return {
        "process_rss_mb": round(process_values["VmRSS"] / 1024, 1)
        if "VmRSS" in process_values
        else None,
        "process_swap_mb": round(process_values["VmSwap"] / 1024, 1)
        if "VmSwap" in process_values
        else None,
        "system_available_mb": round(system_values["MemAvailable"] / 1024, 1)
        if "MemAvailable" in system_values
        else None,
        "swap_total_mb": round(swap_total / 1024, 1) if swap_total is not None else None,
        "swap_used_mb": round(max(0, swap_total - (swap_free or 0)) / 1024, 1)
        if swap_total is not None and swap_free is not None
        else None,
    }


def segment_metric(segment: Any, name: str) -> float | None:
    try:
        value = float(getattr(segment, name))
    except (AttributeError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def repeated_segment_ratio(texts: list[str]) -> float:
    normalized = [re.sub(r"\W+", "", text, flags=re.UNICODE).lower() for text in texts]
    normalized = [text for text in normalized if text]
    if len(normalized) < 2:
        return 0.0
    repeats = 0
    seen: list[str] = []
    for text in normalized:
        duplicate = text in seen
        if not duplicate and seen:
            duplicate = SequenceMatcher(None, seen[-1], text).ratio() >= 0.92
        if duplicate:
            repeats += 1
        else:
            seen.append(text)
    return repeats / len(normalized)


def run_whisper_transcription(
    model: Any,
    audio_path: str,
    options: dict[str, Any],
    audio_duration: float,
) -> tuple[list[tuple[float, float, str]], Any, dict[str, Any]]:
    started = time.monotonic()
    segments, info = model.transcribe(audio_path, **options)
    entries: list[tuple[float, float, str]] = []
    avg_logprobs: list[float] = []
    no_speech_probs: list[float] = []
    compression_ratios: list[float] = []
    texts: list[str] = []
    for segment in segments:
        text = str(segment.text or "").strip()
        if not text:
            continue
        entries.append((float(segment.start), float(segment.end), text))
        texts.append(text)
        avg_logprob = segment_metric(segment, "avg_logprob")
        no_speech_prob = segment_metric(segment, "no_speech_prob")
        compression_ratio = segment_metric(segment, "compression_ratio")
        if avg_logprob is not None:
            avg_logprobs.append(avg_logprob)
        if no_speech_prob is not None:
            no_speech_probs.append(no_speech_prob)
        if compression_ratio is not None:
            compression_ratios.append(compression_ratio)
    elapsed = max(0.0, time.monotonic() - started)
    low_confidence = sum(value < ASR_LOW_LOGPROB_THRESHOLD for value in avg_logprobs)
    duration_after_vad = getattr(info, "duration_after_vad", None)
    try:
        duration_after_vad = float(duration_after_vad) if duration_after_vad is not None else None
    except (TypeError, ValueError):
        duration_after_vad = None
    metrics = {
        "audio_duration_seconds": round(audio_duration, 3) if audio_duration > 0 else None,
        "duration_after_vad": round(duration_after_vad, 3) if duration_after_vad is not None else None,
        "transcribe_seconds": round(elapsed, 3),
        "realtime_factor": round(elapsed / audio_duration, 4) if audio_duration > 0 else None,
        "median_avg_logprob": round(statistics.median(avg_logprobs), 4) if avg_logprobs else None,
        "median_no_speech_prob": round(statistics.median(no_speech_probs), 4) if no_speech_probs else None,
        "median_compression_ratio": round(statistics.median(compression_ratios), 4)
        if compression_ratios
        else None,
        "low_confidence_segment_ratio": round(low_confidence / len(avg_logprobs), 4)
        if avg_logprobs
        else 0.0,
        "repeated_segment_ratio": round(repeated_segment_ratio(texts), 4),
        "peak_rss_mb": peak_rss_mb(),
    }
    return entries, info, metrics


def prefer_retry_result(first: dict[str, Any], retry: dict[str, Any]) -> bool:
    first_repeat = float(first.get("repeated_segment_ratio") or 0.0)
    retry_repeat = float(retry.get("repeated_segment_ratio") or 0.0)
    if retry_repeat + 0.01 < first_repeat:
        return True
    first_low = float(first.get("low_confidence_segment_ratio") or 0.0)
    retry_low = float(retry.get("low_confidence_segment_ratio") or 0.0)
    if retry_repeat <= first_repeat + 0.01 and retry_low + 0.05 < first_low:
        return True
    first_logprob = first.get("median_avg_logprob")
    retry_logprob = retry.get("median_avg_logprob")
    return bool(
        retry_repeat <= first_repeat + 0.01
        and retry_low <= first_low + 0.05
        and isinstance(first_logprob, (int, float))
        and isinstance(retry_logprob, (int, float))
        and retry_logprob > first_logprob + 0.1
    )


def transcribe_audio_payload(
    audio_path: str,
    lang: str | None,
    quality: str = "accurate",
    initial_prompt: str | None = None,
    hotwords: str | None = None,
) -> dict[str, Any]:
    cleaned_prompt = sanitize_asr_context(initial_prompt)
    cleaned_hotwords = sanitize_asr_context(hotwords)
    try:
        profile = asr_profile(quality)
        model = whisper_model(
            profile["model"],
            profile["compute_type"],
            profile["device"],
            profile["cpu_threads"],
        )
        options: dict[str, Any] = {
            "language": lang or None,
            "beam_size": profile["beam_size"],
            "vad_filter": profile["vad_filter"],
            "condition_on_previous_text": profile["condition_on_previous_text"],
        }
        if profile["vad_filter"]:
            options["vad_parameters"] = profile["vad_parameters"]
        if cleaned_prompt:
            options["initial_prompt"] = cleaned_prompt
        if cleaned_hotwords:
            options["hotwords"] = cleaned_hotwords
        duration = audio_duration_seconds(audio_path)
        entries, info, metrics = run_whisper_transcription(model, audio_path, options, duration)
        initial_seconds = float(metrics.get("transcribe_seconds") or 0.0)
        repeated_ratio = float(metrics.get("repeated_segment_ratio") or 0.0)
        low_confidence_ratio = float(metrics.get("low_confidence_segment_ratio") or 0.0)
        retry_reason: str | None = None
        if repeated_ratio >= ASR_RETRY_REPETITION_RATIO:
            retry_reason = "repetition"
        elif low_confidence_ratio >= ASR_RETRY_LOW_CONFIDENCE_RATIO:
            retry_reason = "low_confidence"
        retry_performed = bool(
            entries
            and retry_reason
            and profile["quality"] == "accurate"
            and profile["condition_on_previous_text"]
            and env_bool("ASR_CONTEXT_RETRY_ENABLED", True)
        )
        retry_selected = False
        if retry_performed:
            retry_options = dict(options)
            retry_options["condition_on_previous_text"] = False
            retry_entries, retry_info, retry_metrics = run_whisper_transcription(
                model,
                audio_path,
                retry_options,
                duration,
            )
            total_seconds = initial_seconds + float(retry_metrics.get("transcribe_seconds") or 0.0)
            if retry_entries and prefer_retry_result(metrics, retry_metrics):
                entries, info, metrics = retry_entries, retry_info, retry_metrics
                retry_selected = True
            metrics["transcribe_seconds"] = round(total_seconds, 3)
            metrics["realtime_factor"] = round(total_seconds / duration, 4) if duration > 0 else None
        metrics.update(
            {
                "asr_attempt_count": 2 if retry_performed else 1,
                "context_retry_performed": retry_performed,
                "context_retry_selected": retry_selected,
                "context_retry_reason": retry_reason if retry_performed else None,
                "quality_warning": (
                    "repetition"
                    if float(metrics.get("repeated_segment_ratio") or 0.0)
                    >= ASR_RETRY_REPETITION_RATIO
                    else "low_confidence"
                    if float(metrics.get("low_confidence_segment_ratio") or 0.0)
                    >= ASR_RETRY_LOW_CONFIDENCE_RATIO
                    else None
                ),
            }
        )
        return {
            "ok": True,
            "entries": entries,
            "meta": {
                "detected_language": getattr(info, "language", None),
                "language_probability": getattr(info, "language_probability", None),
                "quality": profile["quality"],
                "model": profile["model"],
                "compute_type": profile["compute_type"],
                "device": profile["device"],
                "cpu_threads": profile["cpu_threads"],
                "beam_size": profile["beam_size"],
                "vad_filter": profile["vad_filter"],
                "vad_parameters": profile["vad_parameters"] if profile["vad_filter"] else None,
                "condition_on_previous_text": (
                    False if retry_selected else profile["condition_on_previous_text"]
                ),
                "initial_prompt_used": bool(cleaned_prompt),
                "hotwords_used": bool(cleaned_hotwords),
                "initial_prompt_hash": asr_context_hash(cleaned_prompt),
                "hotwords_hash": asr_context_hash(cleaned_hotwords),
                "audio_filter_enabled": bool(asr_audio_filter()),
                "audio_filter_hash": stable_config_hash(asr_audio_filter()),
                **metrics,
            },
        }
    except Exception as exc:
        error = str(exc)
        for sensitive_value in (cleaned_prompt, cleaned_hotwords):
            if sensitive_value:
                error = error.replace(sensitive_value, "<redacted>")
        return {
            "ok": False,
            "error": redact_sensitive(error),
            "error_type": type(exc).__name__,
            "reason": classify_asr_worker_error(error),
        }


def transcribe_audio_worker(
    audio_path: str,
    lang: str | None,
    quality: str,
    initial_prompt: str | None,
    hotwords: str | None,
    result_queue: Any,
) -> None:
    result_queue.put(transcribe_audio_payload(audio_path, lang, quality, initial_prompt, hotwords))


def persistent_asr_worker(request_queue: Any, result_queue: Any, ready_event: Any) -> None:
    prewarm_quality = os.getenv("ASR_PREWARM_QUALITY", "accurate").strip().lower()
    if prewarm_quality not in {"fast", "accurate"}:
        prewarm_quality = "accurate"
    prewarm_profile = asr_profile(prewarm_quality)
    prewarmed = False
    try:
        whisper_model(
            prewarm_profile["model"],
            prewarm_profile["compute_type"],
            prewarm_profile["device"],
            prewarm_profile["cpu_threads"],
        )
        prewarmed = True
    except Exception:
        # Prewarming is opportunistic. The first real request retries initialization
        # and returns the model error through the normal task result path.
        clear_whisper_model()
    finally:
        result_queue.put(
            {
                "kind": "prewarm",
                "ok": prewarmed,
                "model_key": [
                    prewarm_profile["model"],
                    prewarm_profile["compute_type"],
                    prewarm_profile["device"],
                    prewarm_profile["cpu_threads"],
                ],
            }
        )
        ready_event.set()
    try:
        while True:
            task = request_queue.get()
            if task is None:
                return
            task_id = str(task.get("task_id") or "")
            result = transcribe_audio_payload(
                str(task.get("audio_path") or ""),
                task.get("lang"),
                str(task.get("quality") or "accurate"),
                task.get("initial_prompt"),
                task.get("hotwords"),
            )
            result["task_id"] = task_id
            result_queue.put(result)
    finally:
        clear_whisper_model()


def asr_worker_alive() -> bool:
    try:
        return bool(ASR_WORKER_PROCESS is not None and ASR_WORKER_PROCESS.is_alive())
    except (AssertionError, RuntimeError):
        return False


def stop_asr_worker_locked(graceful: bool = True) -> None:
    global ASR_WORKER_PROCESS, ASR_WORKER_REQUEST_QUEUE, ASR_WORKER_RESULT_QUEUE, ASR_WORKER_READY_EVENT, ASR_WORKER_WARM, ASR_WORKER_MODEL_KEY
    process = ASR_WORKER_PROCESS
    request_queue = ASR_WORKER_REQUEST_QUEUE
    if ASR_WORKER_READY_EVENT is not None:
        try:
            ASR_WORKER_READY_EVENT.set()
        except Exception:
            pass
    if asr_worker_alive() and graceful and request_queue is not None:
        try:
            request_queue.put_nowait(None)
            process.join(3)
        except Exception:
            pass
    terminate_child_process(process)
    for queue in (ASR_WORKER_REQUEST_QUEUE, ASR_WORKER_RESULT_QUEUE):
        if queue is None:
            continue
        try:
            queue.cancel_join_thread()
            queue.close()
        except Exception:
            pass
    ASR_WORKER_PROCESS = None
    ASR_WORKER_REQUEST_QUEUE = None
    ASR_WORKER_RESULT_QUEUE = None
    ASR_WORKER_READY_EVENT = None
    ASR_WORKER_WARM = False
    ASR_WORKER_MODEL_KEY = None


def stop_asr_worker() -> None:
    with ASR_WORKER_LOCK:
        stop_asr_worker_locked()


def ensure_persistent_asr_worker_locked() -> None:
    global ASR_WORKER_PROCESS, ASR_WORKER_REQUEST_QUEUE, ASR_WORKER_RESULT_QUEUE, ASR_WORKER_READY_EVENT, ASR_WORKER_START_COUNT
    if asr_worker_alive():
        return
    stop_asr_worker_locked(graceful=False)
    try:
        ctx = get_context("spawn")
        ASR_WORKER_REQUEST_QUEUE = ctx.Queue(maxsize=1)
        ASR_WORKER_RESULT_QUEUE = ctx.Queue(maxsize=1)
        ASR_WORKER_READY_EVENT = ctx.Event()
        ASR_WORKER_PROCESS = ctx.Process(
            target=persistent_asr_worker,
            args=(ASR_WORKER_REQUEST_QUEUE, ASR_WORKER_RESULT_QUEUE, ASR_WORKER_READY_EVENT),
            name="bili-subtitle-asr",
            daemon=True,
        )
        ASR_WORKER_PROCESS.start()
        ASR_WORKER_START_COUNT += 1
    except (OSError, RuntimeError) as exc:
        stop_asr_worker_locked(graceful=False)
        raise ExtractionFailure(
            503,
            "无法启动 ASR 常驻进程。",
            "asr_worker_crashed",
            retryable=True,
        ) from exc


def prewarm_asr_worker() -> None:
    global ASR_WORKER_WARM, ASR_WORKER_MODEL_KEY
    acquired = ASR_SEMAPHORE.acquire(timeout=ASR_QUEUE_WAIT_SECONDS)
    if not acquired:
        return
    try:
        try:
            ensure_asr_ready()
        except ExtractionFailure as exc:
            LOGGER.warning("ASR prewarm skipped: %s", public_reason(exc.reason))
            return
        with ASR_WORKER_LOCK:
            ensure_persistent_asr_worker_locked()
            ready_event = ASR_WORKER_READY_EVENT
            result_queue = ASR_WORKER_RESULT_QUEUE
        ready = False
        if ready_event is not None:
            deadline = time.monotonic() + ASR_DOWNLOAD_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if ready_event.wait(min(1.0, max(0.1, deadline - time.monotonic()))):
                    ready = True
                    break
                if not asr_worker_alive():
                    break
        if ready and result_queue is not None:
            try:
                status = result_queue.get(timeout=1.0)
            except Empty:
                status = None
            if isinstance(status, dict) and status.get("kind") == "prewarm":
                ASR_WORKER_WARM = bool(status.get("ok"))
                model_key = status.get("model_key")
                if isinstance(model_key, list) and len(model_key) == 4:
                    ASR_WORKER_MODEL_KEY = (
                        str(model_key[0]),
                        str(model_key[1]),
                        str(model_key[2]),
                        int(model_key[3]),
                    )
    finally:
        ASR_SEMAPHORE.release()


def start_asr_prewarm() -> None:
    global ASR_PREWARM_THREAD
    if ASR_PREWARM_THREAD is not None and ASR_PREWARM_THREAD.is_alive():
        return
    ASR_PREWARM_THREAD = Thread(target=prewarm_asr_worker, name="asr-prewarm", daemon=True)
    ASR_PREWARM_THREAD.start()


def parse_transcription_result(result: dict[str, Any]) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    if not result.get("ok"):
        reason = str(result.get("reason") or "asr_failed")
        error_type = re.sub(r"[^A-Za-z0-9_.-]", "", str(result.get("error_type") or "ASRWorkerError"))
        LOGGER.warning("ASR worker task failed reason=%s error_type=%s", reason, error_type)
        message = USER_ERROR_MESSAGES.get(reason, USER_ERROR_MESSAGES["asr_failed"])
        status_code = 503 if reason in {"asr_model_download_failed", "asr_worker_crashed"} else 502
        raise ExtractionFailure(status_code, message, reason, retryable=True)
    entries = [
        SubtitleEntry(float(start), float(end), str(text))
        for start, end, text in result.get("entries", [])
        if str(text).strip()
    ]
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    return entries, meta


def asr_public_diagnostics(meta: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "audio_duration_seconds",
        "duration_after_vad",
        "transcribe_seconds",
        "realtime_factor",
        "median_avg_logprob",
        "median_no_speech_prob",
        "median_compression_ratio",
        "low_confidence_segment_ratio",
        "repeated_segment_ratio",
        "peak_rss_mb",
        "asr_attempt_count",
        "context_retry_performed",
        "context_retry_selected",
        "context_retry_reason",
        "quality_warning",
        "initial_prompt_used",
        "hotwords_used",
        "initial_prompt_hash",
        "hotwords_hash",
        "audio_filter_enabled",
        "audio_filter_hash",
        "condition_on_previous_text",
        "vad_parameters",
        "asr_worker_restart_count",
    }
    return {key: meta[key] for key in allowed if key in meta}


def asr_quality_user_note(meta: dict[str, Any]) -> str | None:
    warning = meta.get("quality_warning")
    if warning == "repetition":
        return "识别结果仍检测到较多重复片段，建议核对原音频或补充专业词汇后重试。"
    if warning == "low_confidence":
        return "部分片段识别置信度偏低，建议核对原音频或补充专业词汇后重试。"
    return None


def transcribe_audio_once(
    audio_path: Path,
    lang: str | None,
    quality: str = "accurate",
    initial_prompt: str | None = None,
    hotwords: str | None = None,
) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    profile = asr_profile(quality)
    timeout_seconds = asr_task_timeout(audio_path, profile["quality"])
    result_queue: Any = None
    process: Any = None
    try:
        try:
            ctx = get_context("spawn")
            result_queue = ctx.Queue(maxsize=1)
            process = ctx.Process(
                target=transcribe_audio_worker,
                args=(
                    str(audio_path),
                    lang,
                    profile["quality"],
                    initial_prompt,
                    hotwords,
                    result_queue,
                ),
            )
            process.start()
        except (OSError, RuntimeError) as exc:
            raise ExtractionFailure(
                503,
                "无法启动 ASR 识别进程。",
                "asr_worker_crashed",
                retryable=True,
            ) from exc
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ExtractionFailure(
                    504,
                    f"Local ASR timed out after {timeout_seconds} seconds.",
                    "asr_timeout",
                )
            try:
                result = result_queue.get(timeout=min(1.0, remaining))
                break
            except Empty:
                if not process.is_alive():
                    process.join(1)
                    detail = (
                        "本地语音识别进程可能因内存不足被系统终止。"
                        if process.exitcode in {-9, 137}
                        else "本地语音识别进程意外退出。"
                    )
                    raise ExtractionFailure(
                        502,
                        detail,
                        "asr_worker_crashed",
                        retryable=True,
                    )
        process.join(5)
        terminate_child_process(process)
        if not isinstance(result, dict):
            raise ExtractionFailure(502, "Local ASR returned an invalid result.", "asr_failed")
        entries, meta = parse_transcription_result(result)
        meta["asr_worker_reused"] = False
        meta["asr_worker_restart_count"] = 0
        meta["timeout_seconds"] = timeout_seconds
        return entries, meta
    finally:
        terminate_child_process(process)
        if result_queue is not None:
            try:
                result_queue.close()
            except Exception:
                pass


def transcribe_audio(
    audio_path: Path,
    lang: str | None,
    quality: str = "accurate",
    initial_prompt: str | None = None,
    hotwords: str | None = None,
) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    global ASR_WORKER_WARM, ASR_WORKER_MODEL_KEY
    profile = asr_profile(quality)
    timeout_seconds = asr_task_timeout(audio_path, profile["quality"])
    if not env_bool("ASR_PERSISTENT_WORKER", True):
        return transcribe_audio_once(
            audio_path,
            lang,
            profile["quality"],
            initial_prompt,
            hotwords,
        )

    with ASR_WORKER_LOCK:
        worker_reused = asr_worker_alive()
        ensure_persistent_asr_worker_locked()
        process = ASR_WORKER_PROCESS
        request_queue = ASR_WORKER_REQUEST_QUEUE
        result_queue = ASR_WORKER_RESULT_QUEUE
        reused = ASR_WORKER_WARM or worker_reused
        task_id = f"{os.getpid()}-{time.time_ns()}"
        request_queue.put(
            {
                "task_id": task_id,
                "audio_path": str(audio_path),
                "lang": lang,
                "quality": profile["quality"],
                "initial_prompt": sanitize_asr_context(initial_prompt),
                "hotwords": sanitize_asr_context(hotwords),
            }
        )
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                stop_asr_worker_locked(graceful=False)
                raise ExtractionFailure(
                    504,
                    f"Local ASR timed out after {timeout_seconds} seconds.",
                    "asr_timeout",
                )
            if process is None or not process.is_alive():
                exit_code = process.exitcode if process is not None else None
                stop_asr_worker_locked(graceful=False)
                detail = (
                    "本地语音识别进程可能因内存不足被系统终止。"
                    if exit_code in {-9, 137}
                    else "本地语音识别进程意外退出，下一次任务会自动重建。"
                )
                raise ExtractionFailure(502, detail, "asr_worker_crashed", retryable=True)
            try:
                result = result_queue.get(timeout=min(1.0, remaining))
            except Empty:
                continue
            if isinstance(result, dict) and result.get("kind") == "prewarm":
                ASR_WORKER_WARM = bool(result.get("ok"))
                model_key = result.get("model_key")
                if isinstance(model_key, list) and len(model_key) == 4:
                    ASR_WORKER_MODEL_KEY = (
                        str(model_key[0]),
                        str(model_key[1]),
                        str(model_key[2]),
                        int(model_key[3]),
                    )
                continue
            if not isinstance(result, dict):
                continue
            if result.get("task_id") != task_id:
                continue
            entries, meta = parse_transcription_result(result)
            ASR_WORKER_WARM = True
            ASR_WORKER_MODEL_KEY = (
                str(meta.get("model") or profile["model"]),
                str(meta.get("compute_type") or profile["compute_type"]),
                str(meta.get("device") or profile["device"]),
                int(meta.get("cpu_threads") or profile["cpu_threads"]),
            )
            meta["asr_worker_reused"] = reused
            meta["asr_worker_restart_count"] = max(0, ASR_WORKER_START_COUNT - 1)
            meta["timeout_seconds"] = timeout_seconds
            return entries, meta


def video_pixel_subtitle(
    req: ExtractRequest,
    allow_cookie: bool,
) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    url = normalize_input(req.input)
    platform = detect_platform(url)
    started = time.monotonic()
    ensure_disk_space(ASR_TMP_DIR, min(MEDIA_MAX_BYTES, 512 * 1024 * 1024))
    with tempfile.TemporaryDirectory(prefix="ocr-", dir=str(ASR_TMP_DIR)) as tmp:
        tmp_path = Path(tmp)
        report_progress("platform", 16, "正在解析视频画面与字幕信息")
        if platform == "douyin":
            try:
                video = get_douyin_video(url, force_refresh=req.force_refresh)
                report_progress("media_download", 24, "正在下载抖音视频画面")
                media_path, info = download_douyin_media(video, tmp_path, require_video=True)
            except DouyinAdapterError as exc:
                raise ExtractionFailure(exc.status_code, exc.message, exc.reason) from exc
            info.setdefault("id", video.video_id)
            info.setdefault("title", video.title)
            info.setdefault("author", video.author)
            info.setdefault("webpage_url", video.webpage_url)
            info.setdefault("duration", video.duration)
        else:
            report_progress("media_download", 24, "正在下载 B站视频画面")
            media_request = MediaRequest(
                input=url,
                media_type="video",
                use_cookie=allow_cookie,
                force_refresh=req.force_refresh,
            )
            media_path, info = download_bilibili_media(media_request, tmp_path)

        media_info = probe_uploaded_media(media_path, require_audio=False)
        duration = float(media_info.get("duration") or info.get("duration") or 0)
        if duration > ASR_MAX_AUDIO_SECONDS:
            raise ExtractionFailure(
                413,
                f"Video duration {int(duration)}s exceeds the precise extraction limit.",
                "asr_duration_too_long",
            )
        entries, subtitle_info = extract_video_subtitle_pixels(media_path, media_info, tmp_path, req.lang)
        fallback_asr_info: dict[str, Any] = {}
        if not entries and media_info.get("has_audio"):
            report_progress("ocr_fallback", 70, "画面字幕不足，正在使用精确语音识别补救")
            backend = ensure_selected_asr_ready(req.asr_mode)
            acquired = ASR_SEMAPHORE.acquire(blocking=False)
            if not acquired:
                report_progress("asr_wait", 72, "正在等待精确语音识别资源")
                acquired = ASR_SEMAPHORE.acquire(timeout=ASR_QUEUE_WAIT_SECONDS)
            if not acquired:
                raise ExtractionFailure(429, "ASR wait exceeded the queue timeout.", "asr_busy")
            try:
                if backend == "cloud":
                    entries, fallback_asr_info = transcribe_media_with_cloud(
                        media_path,
                        tmp_path,
                        language=req.lang,
                        mode=req.asr_mode,
                    )
                else:
                    audio_path = normalize_audio_for_asr(media_path, tmp_path, "ocr-fallback")
                    initial_prompt, hotwords = asr_context(
                        str(info.get("title") or ""),
                        str(info.get("author") or ""),
                        req.hotwords,
                    )
                    entries, fallback_asr_info = transcribe_audio(
                        audio_path,
                        req.lang,
                        "accurate",
                        initial_prompt,
                        hotwords,
                    )
            finally:
                ASR_SEMAPHORE.release()
        if not entries:
            raise ExtractionFailure(404, "No readable embedded or burned-in subtitles were found.", "ocr_empty")

    subtitle_source = str(subtitle_info.get("subtitle_source") or "burned_in_ocr")
    used_asr_fallback = bool(fallback_asr_info)
    if used_asr_fallback:
        cloud_result = fallback_asr_info.get("provider") == "aliyun"
        source = "asr_aliyun" if cloud_result else "asr_local"
        track_source_type = source
        subtitle_format = "asr"
        note = (
            "未识别到稳定的画面字幕，已自动改用阿里云百炼语音识别。"
            if cloud_result
            else "未识别到稳定的画面字幕，已自动改用精确语音识别。"
        )
    elif subtitle_source == "embedded_text_track":
        source = "embedded_text"
        track_source_type = "embedded_text"
        subtitle_format = "srt"
        note = "已从视频文件内嵌字幕轨提取字幕。"
    else:
        source = "ocr_video"
        track_source_type = "burned_in_ocr"
        subtitle_format = "ocr"
        note = "已通过画面文字识别提取视频中的烧录字幕。"
    quality_note = asr_quality_user_note(fallback_asr_info)
    if quality_note:
        note = f"{note} {quality_note}"
    profile = asr_profile("accurate")
    meta = {
        "title": info.get("title"),
        "id": info.get("id"),
        "webpage_url": info.get("webpage_url") or url,
        "source": source,
        "track_source_type": track_source_type,
        "cookie_used": allow_cookie and bool(cookie_header(True)),
        "language": fallback_asr_info.get("detected_language") or subtitle_info.get("subtitle_stream_language") or req.lang,
        "subtitle_format": subtitle_format,
        "warning": note,
        "note": note,
        "duration": duration,
        "platform": platform,
        "author": info.get("author"),
        "session_mode": "anonymous_browser" if platform == "douyin" else ("bilibili_cookie" if allow_cookie else "anonymous"),
        "quality": "accurate",
        "asr_mode": fallback_asr_info.get("asr_mode") or req.asr_mode,
        "embedded_subtitles_requested": True,
        "ocr_fallback_to_asr": used_asr_fallback,
        "processing_seconds": round(time.monotonic() - started, 3),
        "available_tracks": [],
        **subtitle_info,
    }
    if used_asr_fallback:
        meta.update(
            {
                "asr_model": fallback_asr_info.get("model") or profile["model"],
                "asr_compute_type": fallback_asr_info.get("compute_type") or profile["compute_type"],
                "asr_device": fallback_asr_info.get("device") or profile["device"],
                "asr_cpu_threads": fallback_asr_info.get("cpu_threads") or profile["cpu_threads"],
                "asr_beam_size": fallback_asr_info.get("beam_size") or profile["beam_size"],
                "asr_vad_filter": fallback_asr_info.get("vad_filter", profile["vad_filter"]),
                "asr_worker_reused": bool(fallback_asr_info.get("asr_worker_reused")),
                "asr_language_probability": fallback_asr_info.get("language_probability"),
            }
        )
        meta.update(asr_public_diagnostics(fallback_asr_info))
        meta.update(fallback_asr_info)
    return entries, meta


def transcript_entries(transcript: Transcript) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    raw_entries = [
        {
            "start": round(segment.start_ms / 1000, 3),
            "end": round(segment.end_ms / 1000, 3),
            "text": segment.text,
            "speaker": segment.speaker,
            "emotion": segment.emotion,
            "words": [
                {
                    "start": round(word.start_ms / 1000, 3) if word.start_ms is not None else None,
                    "end": round(word.end_ms / 1000, 3) if word.end_ms is not None else None,
                    "text": word.text,
                }
                for word in segment.words
            ],
        }
        for segment in transcript.segments
    ]
    normalized = normalize_segments(transcript.segments)
    entries = [
        SubtitleEntry(
            start=segment.start_ms / 1000,
            end=segment.end_ms / 1000,
            text=segment.text,
        )
        for segment in normalized
    ]
    return entries, {
        "provider": transcript.provider,
        "model": transcript.model,
        "detected_language": transcript.language,
        "provider_task_id": transcript.provider_task_id,
        "provider_seconds": transcript.provider_seconds,
        "provider_latency_seconds": transcript.latency_seconds,
        "audio_duration_seconds": round(transcript.duration_ms / 1000, 3)
        if transcript.duration_ms
        else None,
        "raw_entries": raw_entries,
        "raw_metadata": transcript.raw_metadata,
        "raw_entry_count": len(raw_entries),
        "normalized_entry_count": len(entries),
    }


def cloud_provider_failure(exc: AsrProviderError) -> ExtractionFailure:
    return ExtractionFailure(
        exc.status_code,
        exc.message,
        exc.code,
        retryable=exc.retryable,
    )


def transcribe_media_with_cloud(
    media_path: Path,
    tmp_dir: Path,
    *,
    language: str | None,
    mode: str,
) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    ensure_cloud_asr_ready()
    assert CLOUD_USAGE_LEDGER is not None
    report_progress("preprocessing", 45, "正在准备云端识别音频")
    audio_path, audio_info = prepare_audio_for_cloud(media_path, tmp_dir)
    requested_mode = "economy" if mode == "economy" else "high_accuracy"
    modes = [requested_mode]
    if (
        requested_mode == "high_accuracy"
        and env_bool("ASR_ECONOMY_FALLBACK_ENABLED", False)
    ):
        modes.append("economy")
    token: str | None = None
    signed_url: str | None = None
    if CLOUD_ASR_AUDIO_DELIVERY == "signed_url":
        assert CLOUD_SIGNED_AUDIO_STORE is not None
        token, signed_url = CLOUD_SIGNED_AUDIO_STORE.register(
            audio_path,
            content_type="audio/mpeg",
            ttl_seconds=CLOUD_AUDIO_TTL_SECONDS,
        )
    failures: list[str] = []
    try:
        for index, current_mode in enumerate(modes):
            model = cloud_model_for_mode(current_mode)
            provider = cloud_provider_for_mode(current_mode)
            try:
                reservation = CLOUD_USAGE_LEDGER.reserve(
                    owner_key=current_asr_owner_key(),
                    model=model,
                    predicted_seconds=float(audio_info["duration"]),
                )
            except UsageLimitExceeded as exc:
                raise ExtractionFailure(
                    429,
                    exc.message,
                    exc.code,
                    retryable=False,
                ) from exc
            submission_started = False
            try:
                if CLOUD_ASR_AUDIO_DELIVERY == "aliyun_temp":
                    assert CLOUD_TEMP_FILE_UPLOADER is not None
                    report_progress("preprocessing", 52, "正在安全上传临时音频")
                    file_url = CLOUD_TEMP_FILE_UPLOADER.upload(
                        audio_path,
                        model=model,
                    )
                else:
                    assert signed_url is not None
                    file_url = signed_url
                submission_started = True
                transcript = provider.transcribe(
                    file_url,
                    language=language,
                    enable_words=True,
                    timeout_seconds=CLOUD_ASR_TIMEOUT_SECONDS,
                    poll_initial_seconds=3,
                    poll_max_seconds=5,
                    progress=report_progress,
                )
            except AsrProviderError as exc:
                submitted = bool(exc.task_id)
                estimated_seconds = float(audio_info["duration"])
                if submitted:
                    CLOUD_USAGE_LEDGER.commit(
                        reservation.reservation_id,
                        actual_seconds=estimated_seconds,
                        estimated_cost_cny=estimated_seconds * cloud_model_price(model),
                        outcome="provider_failed",
                        metadata={"provider": "aliyun", "model": model, "fallback": index > 0},
                    )
                else:
                    CLOUD_USAGE_LEDGER.release(reservation.reservation_id)
                failures.append(exc.code)
                can_fallback = (
                    index + 1 < len(modes)
                    and exc.retryable
                    and exc.code not in {
                        "asr_provider_auth_failed",
                        "asr_quota_exhausted",
                        "asr_rate_limited",
                    }
                )
                if can_fallback:
                    report_progress("waiting_for_provider", 62, "高精度服务暂不可用，正在切换经济模式")
                    continue
                raise cloud_provider_failure(exc) from exc
            except Exception:
                estimated_seconds = float(audio_info["duration"])
                if submission_started:
                    CLOUD_USAGE_LEDGER.commit(
                        reservation.reservation_id,
                        actual_seconds=estimated_seconds,
                        estimated_cost_cny=estimated_seconds * cloud_model_price(model),
                        outcome="provider_internal_error",
                        metadata={"provider": "aliyun", "model": model, "fallback": index > 0},
                    )
                else:
                    CLOUD_USAGE_LEDGER.release(reservation.reservation_id)
                raise
            actual_seconds = float(
                transcript.provider_seconds
                if transcript.provider_seconds is not None
                else audio_info["duration"]
            )
            estimated_cost = actual_seconds * cloud_model_price(model)
            CLOUD_USAGE_LEDGER.commit(
                reservation.reservation_id,
                actual_seconds=actual_seconds,
                estimated_cost_cny=estimated_cost,
                outcome="completed",
                metadata={"provider": transcript.provider, "model": model, "fallback": index > 0},
            )
            entries, transcript_info = transcript_entries(transcript)
            if not entries:
                raise ExtractionFailure(
                    404,
                    "Cloud ASR completed but returned no text.",
                    "asr_empty",
                )
            transcript_info.update(
                {
                    "asr_mode": current_mode,
                    "requested_asr_mode": mode,
                    "fallback_used": index > 0,
                    "fallback_failures": failures,
                    "estimated_cost_cny": round(estimated_cost, 6),
                    "audio_file_bytes": audio_info["size"],
                    "audio_format": audio_info["format_name"],
                    "audio_codec": audio_info["codec_name"],
                    "audio_channels": audio_info["channels"],
                    "audio_sample_rate": audio_info["sample_rate"],
                    "audio_delivery": CLOUD_ASR_AUDIO_DELIVERY,
                    "provider_temporary_retention_seconds": (
                        CLOUD_TEMP_AUDIO_RETENTION_SECONDS
                        if CLOUD_ASR_AUDIO_DELIVERY == "aliyun_temp"
                        else 0
                    ),
                }
            )
            return entries, transcript_info
    finally:
        if token is not None and CLOUD_SIGNED_AUDIO_STORE is not None:
            CLOUD_SIGNED_AUDIO_STORE.revoke(token)

    raise ExtractionFailure(
        502,
        "Cloud ASR did not produce a result.",
        "asr_provider_failed",
        retryable=True,
    )


def cloud_asr_subtitle(
    req: ExtractRequest,
    allow_cookie: bool,
    prior_note: str | None = None,
) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    ensure_cloud_asr_ready()
    ensure_disk_space(ASR_TMP_DIR, min(BILI_MAX_DOWNLOAD_BYTES, 512 * 1024 * 1024))
    url = normalize_input(req.input)
    platform = detect_platform(url)
    douyin_video: DouyinVideo | None = None
    if platform == "douyin":
        report_progress("checking_existing_subtitle", 18, "正在解析抖音视频信息")
        try:
            douyin_video = get_douyin_video(
                url,
                force_refresh=req.force_refresh and req.source == "asr",
            )
        except DouyinAdapterError as exc:
            raise ExtractionFailure(exc.status_code, exc.message, exc.reason) from exc
        view = ExtractionSource(
            title=douyin_video.title,
            video_id=douyin_video.video_id,
            webpage_url=douyin_video.webpage_url,
            tracks=[],
            duration=douyin_video.duration,
            platform="douyin",
            author=douyin_video.author,
        )
    else:
        report_progress("checking_existing_subtitle", 18, "正在解析 B站视频信息")
        view = view_source(url, allow_cookie=allow_cookie)
    duration = float(view.duration or 0)
    if duration and duration > ASR_MAX_AUDIO_SECONDS:
        raise ExtractionFailure(
            413,
            "Video duration exceeds the cloud ASR limit.",
            "asr_duration_too_long",
            terminal=True,
        )
    acquired = ASR_SEMAPHORE.acquire(blocking=False)
    if not acquired:
        report_progress("asr_wait", 28, "正在等待语音识别资源")
        acquired = ASR_SEMAPHORE.acquire(timeout=ASR_QUEUE_WAIT_SECONDS)
    if not acquired:
        raise ExtractionFailure(
            429,
            "Cloud ASR queue wait timed out.",
            "asr_busy",
            retryable=True,
        )
    try:
        with tempfile.TemporaryDirectory(prefix="asr-cloud-", dir=str(ASR_TMP_DIR)) as tmp:
            tmp_path = Path(tmp)
            report_progress("downloading_audio", 35, "正在下载音轨")
            if platform == "douyin" and douyin_video is not None:
                try:
                    media_path, info = download_douyin_media(douyin_video, tmp_path)
                except DouyinAdapterError as exc:
                    raise ExtractionFailure(exc.status_code, exc.message, exc.reason) from exc
            else:
                media_path, info = download_audio_for_asr(
                    url,
                    allow_cookie=allow_cookie,
                    tmp_dir=tmp_path,
                    normalize=False,
                )
            entries, asr_info = transcribe_media_with_cloud(
                media_path,
                tmp_path,
                language=req.lang,
                mode=req.asr_mode,
            )
    finally:
        ASR_SEMAPHORE.release()
    note = "未找到可用的平台字幕，本次已使用阿里云百炼语音识别。"
    if prior_note:
        note = f"{redact_sensitive(prior_note)} 已改用阿里云百炼语音识别。"
    meta = {
        "title": view.title or info.get("title"),
        "id": view.video_id or info.get("id"),
        "webpage_url": view.webpage_url,
        "source": "asr_aliyun",
        "track_source_type": "asr_aliyun",
        "cookie_used": allow_cookie and bool(cookie_header(True)),
        "language": asr_info.get("detected_language") or req.lang,
        "subtitle_format": "asr",
        "warning": note,
        "note": note,
        "duration": duration or info.get("duration") or asr_info.get("audio_duration_seconds"),
        "platform": platform,
        "author": view.author or info.get("author"),
        "session_mode": "anonymous_browser"
        if platform == "douyin"
        else ("bilibili_cookie" if allow_cookie else "anonymous"),
        "quality": req.quality,
        "asr_mode": asr_info.get("asr_mode"),
        "requested_asr_mode": req.asr_mode,
        "asr_provider": asr_info.get("provider"),
        "asr_model": asr_info.get("model"),
        "asr_task_id": asr_info.get("provider_task_id"),
        "asr_provider_seconds": asr_info.get("provider_seconds"),
        "asr_provider_latency_seconds": asr_info.get("provider_latency_seconds"),
        "estimated_cost_cny": asr_info.get("estimated_cost_cny"),
        "asr_fallback_used": asr_info.get("fallback_used", False),
        "audio_download": info.get("audio_download"),
        "audio_bandwidth": info.get("audio_bandwidth"),
        "audio_quality_strategy": info.get("audio_quality_strategy"),
        "audio_normalized_for_asr": True,
        "available_tracks": [],
        **asr_info,
    }
    return entries, meta


def local_asr_subtitle(req: ExtractRequest, allow_cookie: bool, prior_note: str | None = None) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    ensure_asr_ready()
    ensure_disk_space(ASR_TMP_DIR, min(BILI_MAX_DOWNLOAD_BYTES, 512 * 1024 * 1024))
    quality = effective_quality(req.quality, req.embedded_subtitles)
    profile = asr_profile(quality)
    url = normalize_input(req.input)
    platform = detect_platform(url)
    douyin_video: DouyinVideo | None = None
    if platform == "douyin":
        report_progress("platform", 18, "正在解析抖音视频信息")
        try:
            douyin_video = get_douyin_video(url, force_refresh=req.force_refresh and req.source == "asr")
        except DouyinAdapterError as exc:
            raise ExtractionFailure(exc.status_code, exc.message, exc.reason) from exc
        view = ExtractionSource(
            title=douyin_video.title,
            video_id=douyin_video.video_id,
            webpage_url=douyin_video.webpage_url,
            tracks=[],
            duration=douyin_video.duration,
            platform="douyin",
            author=douyin_video.author,
        )
    else:
        report_progress("platform", 18, "正在解析 B站视频信息")
        view = view_source(url, allow_cookie=allow_cookie)
    duration = view.duration or 0
    if duration and duration > ASR_MAX_AUDIO_SECONDS:
        raise ExtractionFailure(
            413,
            f"Video duration {int(duration)}s exceeds ASR_MAX_AUDIO_SECONDS={ASR_MAX_AUDIO_SECONDS}.",
            "asr_duration_too_long",
        )
    acquired_asr = ASR_SEMAPHORE.acquire(blocking=False)
    if not acquired_asr:
        report_progress("asr_wait", 28, "正在等待语音识别资源")
        acquired_asr = ASR_SEMAPHORE.acquire(timeout=ASR_QUEUE_WAIT_SECONDS)
    if not acquired_asr:
        raise ExtractionFailure(
            429,
            f"Local ASR wait exceeded {ASR_QUEUE_WAIT_SECONDS} seconds. Retry later.",
            "asr_busy",
        )
    try:
        with tempfile.TemporaryDirectory(prefix="asr-", dir=str(ASR_TMP_DIR)) as tmp:
            tmp_path = Path(tmp)
            report_progress("download", 35, "正在下载并准备音频")
            if platform == "douyin" and douyin_video is not None:
                try:
                    media_path, info = download_douyin_media(douyin_video, tmp_path)
                except DouyinAdapterError as exc:
                    raise ExtractionFailure(exc.status_code, exc.message, exc.reason) from exc
                audio_path = normalize_audio_for_asr(media_path, tmp_path, douyin_video.video_id)
                media_path.unlink(missing_ok=True)
                info["audio_normalized_for_asr"] = True
            else:
                audio_path, info = download_audio_for_asr(url, allow_cookie=allow_cookie, tmp_dir=tmp_path)
            report_progress(
                "transcribe",
                68,
                "正在进行精确语音识别" if quality == "accurate" else "正在进行快速语音识别",
            )
            initial_prompt, hotwords = asr_context(view.title, view.author, req.hotwords)
            entries, asr_info = transcribe_audio(
                audio_path,
                req.lang,
                quality,
                initial_prompt,
                hotwords,
            )
    finally:
        ASR_SEMAPHORE.release()
    if not entries:
        raise ExtractionFailure(404, "Local ASR completed but returned no text.", "asr_empty")
    note = "未找到可用的平台字幕，本次使用本地语音识别。"
    if prior_note:
        note = f"{redact_sensitive(prior_note)} 已改用本地语音识别。"
    quality_note = asr_quality_user_note(asr_info)
    if quality_note:
        note = f"{note} {quality_note}"
    meta = {
        "title": view.title or info.get("title"),
        "id": view.video_id or info.get("id"),
        "webpage_url": view.webpage_url,
        "source": "asr_local",
        "track_source_type": "asr_local",
        "cookie_used": allow_cookie and bool(cookie_header(True)),
        "language": asr_info.get("detected_language") or req.lang,
        "subtitle_format": "asr",
        "warning": note,
        "note": note,
        "duration": duration or info.get("duration"),
        "platform": platform,
        "author": view.author or info.get("author"),
        "session_mode": "anonymous_browser" if platform == "douyin" else ("bilibili_cookie" if allow_cookie else "anonymous"),
        "quality": quality,
        "asr_mode": req.asr_mode,
        "embedded_subtitles_requested": req.embedded_subtitles,
        "asr_model": asr_info.get("model") or profile["model"],
        "asr_compute_type": asr_info.get("compute_type") or profile["compute_type"],
        "asr_device": asr_info.get("device") or profile["device"],
        "asr_cpu_threads": asr_info.get("cpu_threads") or profile["cpu_threads"],
        "asr_beam_size": asr_info.get("beam_size") or profile["beam_size"],
        "asr_vad_filter": asr_info.get("vad_filter", profile["vad_filter"]),
        "asr_timeout_seconds": asr_info.get("timeout_seconds") or profile["timeout_seconds"],
        "asr_concurrency_limit": ASR_CONCURRENCY_LIMIT,
        "asr_queue_wait_seconds": ASR_QUEUE_WAIT_SECONDS,
        "asr_worker_reused": bool(asr_info.get("asr_worker_reused")),
        "audio_normalized_for_asr": bool(info.get("audio_normalized_for_asr")),
        "audio_download": info.get("audio_download"),
        "audio_bandwidth": info.get("audio_bandwidth"),
        "audio_quality_strategy": info.get("audio_quality_strategy"),
        "asr_language_probability": asr_info.get("language_probability"),
        "available_tracks": [],
        **asr_public_diagnostics(asr_info),
    }
    return entries, meta


def asr_subtitle(
    req: ExtractRequest,
    allow_cookie: bool,
    prior_note: str | None = None,
) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    backend = selected_asr_backend(req.asr_mode)
    if backend == "cloud":
        return cloud_asr_subtitle(req, allow_cookie, prior_note)
    if backend == "local":
        return local_asr_subtitle(req, allow_cookie, prior_note)
    raise asr_unavailable_failure(req.asr_mode)


def upload_display_title(filename: str) -> str:
    title = Path(filename).stem.strip()
    return title[:120] or "uploaded_video"


def apply_upload_metadata(meta: dict[str, Any], req: UploadJobRequest) -> None:
    meta["title"] = upload_display_title(req.filename)
    meta["id"] = f"upload-{req.sha256[:12]}"
    meta["original_filename"] = req.filename
    meta["uploaded_bytes"] = req.size
    meta["platform"] = "upload"
    meta["input_type"] = "upload"
    meta["requested_source"] = "embedded" if req.embedded_subtitles else "asr"
    meta["requested_use_cookie"] = False
    meta["requested_quality"] = req.quality
    meta["requested_asr_mode"] = req.asr_mode
    meta["quality"] = effective_quality(req.quality, req.embedded_subtitles)
    meta["embedded_subtitles_requested"] = req.embedded_subtitles
    meta["cookie_enabled"] = cookie_enabled()


def extract_uploaded_subtitle_data(req: UploadJobRequest) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    started = time.monotonic()
    request_started_at = time.time()
    report_progress("validating", 7, "正在校验上传视频")
    key = upload_result_cache_key(req)

    with result_key_guard(key):
        report_progress("cache", 10, "正在检查已有识别结果")
        cached = load_cached_result(key)
        if req.force_refresh and not cache_updated_since(key, request_started_at):
            cached = None
        if cached is not None:
            entries, meta, cache_age = cached
            meta["cache_hit"] = True
            meta["cache_age_seconds"] = round(cache_age, 1)
            report_progress("cache_hit", 92, "已找到相同视频的字幕")
        else:
            media_path = uploaded_media_path(req)
            report_progress("platform", 18, "正在检查视频与音轨")
            media_info = probe_uploaded_media(media_path, require_audio=not req.embedded_subtitles)
            duration = float(media_info["duration"])
            if duration > ASR_MAX_AUDIO_SECONDS:
                raise ExtractionFailure(
                    413,
                    f"Video duration {int(duration)}s exceeds ASR_MAX_AUDIO_SECONDS={ASR_MAX_AUDIO_SECONDS}.",
                    "asr_duration_too_long",
                )

            processing_started = time.monotonic()
            quality = effective_quality(req.quality, req.embedded_subtitles)
            profile = asr_profile(quality)
            asr_info: dict[str, Any] = {}
            subtitle_info: dict[str, Any] = {}

            def transcribe_uploaded_video() -> tuple[list[SubtitleEntry], dict[str, Any]]:
                backend = ensure_selected_asr_ready(req.asr_mode)
                acquired_asr = ASR_SEMAPHORE.acquire(blocking=False)
                if not acquired_asr:
                    report_progress("asr_wait", 28, "正在等待语音识别资源")
                    acquired_asr = ASR_SEMAPHORE.acquire(timeout=ASR_QUEUE_WAIT_SECONDS)
                if not acquired_asr:
                    raise ExtractionFailure(
                        429,
                        f"Local ASR wait exceeded {ASR_QUEUE_WAIT_SECONDS} seconds. Retry later.",
                        "asr_busy",
                    )
                try:
                    if backend == "cloud":
                        return transcribe_media_with_cloud(
                            media_path,
                            media_path.parent,
                            language=req.lang,
                            mode=req.asr_mode,
                        )
                    report_progress("download", 38, "正在提取并标准化音轨")
                    normalized_path = normalize_audio_for_asr(
                        media_path,
                        media_path.parent,
                        "upload",
                        ASR_DOWNLOAD_TIMEOUT_SECONDS,
                    )
                    report_progress(
                        "transcribe",
                        68,
                        "正在进行精确语音识别" if quality == "accurate" else "正在进行快速语音识别",
                    )
                    initial_prompt, hotwords = asr_context(
                        upload_display_title(req.filename),
                        None,
                        req.hotwords,
                    )
                    return transcribe_audio(
                        normalized_path,
                        req.lang,
                        quality,
                        initial_prompt,
                        hotwords,
                    )
                finally:
                    ASR_SEMAPHORE.release()

            if req.embedded_subtitles:
                entries, subtitle_info = extract_video_subtitle_pixels(
                    media_path,
                    media_info,
                    media_path.parent,
                    req.lang,
                )
                if not entries and media_info.get("has_audio"):
                    report_progress("ocr_fallback", 70, "画面字幕不足，正在使用精确语音识别补救")
                    entries, asr_info = transcribe_uploaded_video()
            else:
                entries, asr_info = transcribe_uploaded_video()
            if not entries:
                reason = "ocr_empty" if req.embedded_subtitles else "asr_empty"
                raise ExtractionFailure(404, "The video did not produce readable subtitles.", reason)

            if asr_info:
                cloud_result = asr_info.get("provider") == "aliyun"
                source = "asr_aliyun" if cloud_result else "asr_local"
                track_source_type = source
                subtitle_format = "asr"
                note = (
                    "未识别到稳定的画面字幕，已自动改用云端语音识别。"
                    if req.embedded_subtitles
                    else (
                        "上传视频已使用阿里云百炼语音识别生成字幕。"
                        if cloud_result
                        else "本地上传视频已使用服务器语音识别生成字幕。"
                    )
                )
            elif subtitle_info.get("subtitle_source") == "embedded_text_track":
                source = "embedded_text"
                track_source_type = "embedded_text"
                subtitle_format = "srt"
                note = "已从上传视频的内嵌字幕轨提取字幕。"
            else:
                source = "ocr_video"
                track_source_type = "burned_in_ocr"
                subtitle_format = "ocr"
                note = "已通过画面文字识别提取上传视频中的烧录字幕。"
            quality_note = asr_quality_user_note(asr_info)
            if quality_note:
                note = f"{note} {quality_note}"
            meta = {
                "title": upload_display_title(req.filename),
                "id": f"upload-{req.sha256[:12]}",
                "webpage_url": None,
                "source": source,
                "track_source_type": track_source_type,
                "cookie_used": False,
                "language": asr_info.get("detected_language") or subtitle_info.get("subtitle_stream_language") or req.lang,
                "subtitle_format": subtitle_format,
                "warning": note,
                "note": note,
                "duration": duration,
                "platform": "upload",
                "author": None,
                "session_mode": "local_upload",
                "quality": quality,
                "asr_mode": asr_info.get("asr_mode") or req.asr_mode,
                "embedded_subtitles_requested": req.embedded_subtitles,
                "ocr_fallback_to_asr": bool(req.embedded_subtitles and asr_info),
                "asr_model": asr_info.get("model") or (profile["model"] if asr_info else None),
                "asr_compute_type": asr_info.get("compute_type") or (profile["compute_type"] if asr_info else None),
                "asr_device": asr_info.get("device") or (profile["device"] if asr_info else None),
                "asr_cpu_threads": asr_info.get("cpu_threads") or (profile["cpu_threads"] if asr_info else None),
                "asr_beam_size": asr_info.get("beam_size") or (profile["beam_size"] if asr_info else None),
                "asr_vad_filter": asr_info.get("vad_filter", profile["vad_filter"] if asr_info else None),
                "asr_timeout_seconds": (
                    asr_info.get("timeout_seconds") or profile["timeout_seconds"]
                    if asr_info
                    else None
                ),
                "asr_concurrency_limit": ASR_CONCURRENCY_LIMIT,
                "asr_queue_wait_seconds": ASR_QUEUE_WAIT_SECONDS,
                "asr_worker_reused": bool(asr_info.get("asr_worker_reused")),
                "asr_language_probability": asr_info.get("language_probability"),
                "audio_normalized_for_asr": bool(asr_info),
                "media_format": media_info.get("format_name"),
                "available_tracks": [],
                "processing_seconds": round(time.monotonic() - processing_started, 3),
                "cache_hit": False,
                "cache_age_seconds": 0,
                **subtitle_info,
                **asr_public_diagnostics(asr_info),
                **asr_info,
            }
            apply_upload_metadata(meta, req)
            meta["entry_count"] = len(entries)
            meta["character_count"] = sum(len(entry.text) for entry in entries)
            save_cached_result(key, entries, meta)

    apply_upload_metadata(meta, req)
    meta["entry_count"] = len(entries)
    meta["character_count"] = sum(len(entry.text) for entry in entries)
    meta["elapsed_seconds"] = round(time.monotonic() - started, 3)
    meta["force_refresh"] = req.force_refresh
    report_progress("render", 96, "正在生成字幕文件")
    return entries, meta


def upload_extraction_payload(req: UploadJobRequest) -> dict[str, Any]:
    entries, meta = extract_uploaded_subtitle_data(req)
    content = render_entries(entries, req.format, meta)
    payload = {
        "ok": True,
        "format": req.format,
        "filename": safe_filename(meta.get("title"), req.format),
        "content_type": content_type_for(req.format),
        "metadata": meta,
        "content": content,
    }
    raw_content = rendered_raw_content(meta, req.format)
    if raw_content is not None:
        payload["raw_content"] = raw_content
    return payload


def cached_upload_payload(req: UploadJobRequest) -> dict[str, Any] | None:
    if req.force_refresh or not result_cache_enabled():
        return None
    started = time.monotonic()
    key = upload_result_cache_key(req)
    with result_key_guard(key, blocking=False) as acquired:
        if not acquired:
            return None
        cached = load_cached_result(key)
    if cached is None:
        return None
    entries, meta, cache_age = cached
    meta["cache_hit"] = True
    meta["cache_age_seconds"] = round(cache_age, 1)
    meta["elapsed_seconds"] = round(time.monotonic() - started, 3)
    meta["force_refresh"] = False
    apply_upload_metadata(meta, req)
    meta["entry_count"] = len(entries)
    meta["character_count"] = sum(len(entry.text) for entry in entries)
    payload = {
        "ok": True,
        "format": req.format,
        "filename": safe_filename(meta.get("title"), req.format),
        "content_type": content_type_for(req.format),
        "metadata": meta,
        "content": render_entries(entries, req.format, meta),
    }
    raw_content = rendered_raw_content(meta, req.format)
    if raw_content is not None:
        payload["raw_content"] = raw_content
    return payload


def extraction_http_error(req: ExtractRequest, exc: ExtractionFailure, failures: list[dict[str, Any]]) -> HTTPException:
    detail = extraction_error_detail("failed", exc, failures)
    detail.update(
        {
            "cookie_enabled": cookie_enabled(),
            "cookie_requested": req.use_cookie,
            "cookie_used": False,
        }
    )
    return HTTPException(
        status_code=exc.status_code,
        detail=detail,
    )


def extract_subtitle_uncached(req: ExtractRequest) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    allow_cookie = cookie_allowed(req.use_cookie)
    failures: list[dict[str, Any]] = []
    report_progress("discover", 12, "正在查找可用字幕来源")

    try:
        if req.embedded_subtitles:
            entries, meta = video_pixel_subtitle(req, allow_cookie=allow_cookie)
        elif req.source == "official":
            source_label = "official_with_cookie" if allow_cookie else "official_no_cookie"
            entries, meta = official_subtitle(req, allow_cookie=allow_cookie, source_label=source_label)
        elif req.source == "asr":
            entries, meta = asr_subtitle(req, allow_cookie=allow_cookie)
        else:
            try:
                entries, meta = official_subtitle(req, allow_cookie=False, source_label="official_no_cookie")
            except ExtractionFailure as first:
                failures.append(failure_record("official_no_cookie", first))
                if first.terminal:
                    raise first
                if allow_cookie:
                    try:
                        entries, meta = official_subtitle(req, allow_cookie=True, source_label="official_with_cookie")
                    except ExtractionFailure as second:
                        failures.append(failure_record("official_with_cookie", second))
                        if second.terminal:
                            raise second
                        entries, meta = asr_subtitle(
                            req,
                            allow_cookie=allow_cookie,
                            prior_note=failure_user_message(second),
                        )
                else:
                    entries, meta = asr_subtitle(
                        req,
                        allow_cookie=False,
                        prior_note=failure_user_message(first),
                    )
    except ExtractionFailure as exc:
        raise extraction_http_error(req, exc, failures) from exc

    meta["requested_source"] = req.source
    meta["requested_use_cookie"] = req.use_cookie
    meta["requested_quality"] = req.quality
    meta["requested_asr_mode"] = req.asr_mode
    meta["quality"] = effective_quality(req.quality, req.embedded_subtitles)
    meta["embedded_subtitles_requested"] = req.embedded_subtitles
    meta["cookie_enabled"] = cookie_enabled()
    meta["attempts"] = meta.get("attempts", []) + failures
    meta.setdefault("platform", detect_platform(req.input))
    return entries, meta


def extract_subtitle_data(req: ExtractRequest) -> tuple[list[SubtitleEntry], dict[str, Any]]:
    start = time.monotonic()
    request_started_at = time.time()
    report_progress("validating", 7, "正在校验视频链接")
    try:
        canonical_input = normalize_input(req.input)
    except ExtractionFailure as exc:
        raise extraction_http_error(req, exc, []) from exc
    canonical_req = req.model_copy(
        update={
            "input": canonical_input,
            "hotwords": sanitize_asr_context(req.hotwords),
        }
    )
    key = result_cache_key(canonical_req, canonical_input)

    with result_key_guard(key):
        report_progress("cache", 10, "正在检查已有结果")
        cached = load_cached_result(key)
        if req.force_refresh and not cache_updated_since(key, request_started_at):
            cached = None
        if cached is not None:
            entries, meta, cache_age = cached
            meta["cache_hit"] = True
            meta["cache_age_seconds"] = round(cache_age, 1)
            report_progress("cache_hit", 92, "已找到缓存结果")
        else:
            processing_start = time.monotonic()
            entries, meta = extract_subtitle_uncached(canonical_req)
            meta["processing_seconds"] = round(time.monotonic() - processing_start, 3)
            meta["cache_hit"] = False
            meta["cache_age_seconds"] = 0
            meta["entry_count"] = len(entries)
            meta["character_count"] = sum(len(entry.text) for entry in entries)
            save_cached_result(key, entries, meta)

    meta["entry_count"] = len(entries)
    meta["character_count"] = sum(len(entry.text) for entry in entries)
    meta["requested_source"] = req.source
    meta["requested_use_cookie"] = req.use_cookie
    meta["requested_quality"] = req.quality
    meta["requested_asr_mode"] = req.asr_mode
    meta["quality"] = effective_quality(req.quality, req.embedded_subtitles)
    meta["embedded_subtitles_requested"] = req.embedded_subtitles
    meta["cookie_enabled"] = cookie_enabled()
    meta["elapsed_seconds"] = round(time.monotonic() - start, 3)
    meta["force_refresh"] = req.force_refresh
    meta.setdefault("platform", detect_platform(canonical_input))
    report_progress("render", 96, "正在生成字幕文件")
    return entries, meta


def extract_subtitle(req: ExtractRequest) -> tuple[str, dict[str, Any], str]:
    entries, meta = extract_subtitle_data(req)
    return render_entries(entries, req.format, meta), meta, req.format


def content_type_for(fmt: str) -> str:
    return {
        "txt": "text/plain; charset=utf-8",
        "srt": "application/x-subrip; charset=utf-8",
        "vtt": "text/vtt; charset=utf-8",
        "markdown": "text/markdown; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "json": "application/json; charset=utf-8",
    }.get(fmt, "text/plain; charset=utf-8")


def safe_filename(title: str | None, fmt: str) -> str:
    ext = "md" if fmt == "markdown" else fmt
    base = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", title or "video_subtitle")
    base = re.sub(r"\s+", "_", base).strip("._")
    return f"{base[:80] or 'video_subtitle'}.{ext}"


def extraction_payload(req: ExtractRequest) -> dict[str, Any]:
    content, meta, fmt = extract_subtitle(req)
    payload = {
        "ok": True,
        "format": fmt,
        "filename": safe_filename(meta.get("title"), fmt),
        "content_type": content_type_for(fmt),
        "metadata": meta,
        "content": content,
    }
    raw_content = rendered_raw_content(meta, fmt)
    if raw_content is not None:
        payload["raw_content"] = raw_content
    return payload


def cached_extraction_payload(
    req: ExtractRequest,
    canonical_input: str | None = None,
) -> dict[str, Any] | None:
    if req.force_refresh or not result_cache_enabled():
        return None
    started = time.monotonic()
    canonical = canonical_input or normalize_input(req.input)
    canonical_req = req.model_copy(
        update={
            "input": canonical,
            "hotwords": sanitize_asr_context(req.hotwords),
        }
    )
    key = result_cache_key(canonical_req, canonical)
    with result_key_guard(key, blocking=False) as acquired:
        if not acquired:
            return None
        cached = load_cached_result(key)
    if cached is None:
        return None

    entries, meta, cache_age = cached
    meta["cache_hit"] = True
    meta["cache_age_seconds"] = round(cache_age, 1)
    meta["entry_count"] = len(entries)
    meta["character_count"] = sum(len(entry.text) for entry in entries)
    meta["requested_source"] = req.source
    meta["requested_use_cookie"] = req.use_cookie
    meta["requested_quality"] = req.quality
    meta["requested_asr_mode"] = req.asr_mode
    meta["quality"] = effective_quality(req.quality, req.embedded_subtitles)
    meta["embedded_subtitles_requested"] = req.embedded_subtitles
    meta["cookie_enabled"] = cookie_enabled()
    meta["elapsed_seconds"] = round(time.monotonic() - started, 3)
    meta["force_refresh"] = False
    meta.setdefault("platform", detect_platform(canonical))
    content = render_entries(entries, req.format, meta)
    payload = {
        "ok": True,
        "format": req.format,
        "filename": safe_filename(meta.get("title"), req.format),
        "content_type": content_type_for(req.format),
        "metadata": meta,
        "content": content,
    }
    raw_content = rendered_raw_content(meta, req.format)
    if raw_content is not None:
        payload["raw_content"] = raw_content
    return payload


def _process_queued_job(
    payload: dict[str, Any],
    update: Callable[[str, int, str], None],
) -> dict[str, Any]:
    if payload.get("kind") == "upload":
        try:
            req = UploadJobRequest.model_validate(payload)
            with extraction_progress(update):
                return upload_extraction_payload(req)
        except ExtractionFailure as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=extraction_error_detail("upload", exc),
            ) from exc
        finally:
            discard_upload_payload(payload)
    if payload.get("kind") == "media":
        completed = False
        try:
            req = MediaJobRequest.model_validate(payload)
            with extraction_progress(update):
                result = media_extraction_payload(req)
            completed = True
            return result
        except ExtractionFailure as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=extraction_error_detail("media", exc),
            ) from exc
        finally:
            if not completed:
                discard_media_payload(payload)
    req = ExtractRequest.model_validate(payload)
    with extraction_progress(update):
        return extraction_payload(req)


def process_queued_job(
    payload: dict[str, Any],
    update: Callable[[str, int, str], None],
) -> dict[str, Any]:
    try:
        owner_id = int(payload.get("_owner_id") or 0) or None
    except (TypeError, ValueError):
        owner_id = None
    with extraction_owner(owner_id):
        return _process_queued_job(payload, update)


JOB_MANAGER = JobManager(
    process_queued_job,
    max_pending=JOB_QUEUE_MAX_PENDING,
    result_ttl_seconds=JOB_RESULT_TTL_SECONDS,
    max_records=JOB_MAX_RECORDS,
    worker_count=JOB_WORKER_COUNT,
    discarder=discard_job_payload,
    state_path=JOB_STATE_DB_PATH,
)


def request_idempotency_key(request: Request) -> str | None:
    value = request.headers.get("idempotency-key", "").strip()
    if not value:
        return None
    if not re.fullmatch(r"[A-Za-z0-9._:-]{8,128}", value):
        raise HTTPException(
            status_code=400,
            detail={"reason": "invalid_idempotency_key", "message": "Idempotency-Key 格式无效。"},
        )
    return value


def idempotency_conflict_error() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "source": "queue",
            "reason": "idempotency_conflict",
            "message": "这个 Idempotency-Key 已用于另一个请求，请更换后重试。",
        },
    )


def submit_extraction_job(req: ExtractRequest, owner_id: int, idempotency_key: str | None) -> dict[str, Any]:
    try:
        canonical_input = normalize_input(req.input)
    except ExtractionFailure as exc:
        raise extraction_http_error(req, exc, []) from exc
    canonical_req = req.model_copy(
        update={
            "input": canonical_input,
            "hotwords": sanitize_asr_context(req.hotwords),
        }
    )
    cached_payload = cached_extraction_payload(canonical_req, canonical_input)
    job_payload = canonical_req.model_dump(mode="json")
    job_payload["_owner_id"] = owner_id
    try:
        if cached_payload is not None:
            job = JOB_MANAGER.submit_completed(
                job_payload,
                cached_payload,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
            )
        else:
            job = JOB_MANAGER.submit(
                job_payload,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
            )
    except JobIdempotencyConflict as exc:
        raise idempotency_conflict_error() from exc
    except JobQueueFull as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "source": "queue",
                "reason": "queue_full",
                "code": "job_queue_full",
                "message": f"任务队列已满，当前最多等待 {JOB_QUEUE_MAX_PENDING} 个任务，请稍后再试。",
                "retryable": True,
            },
        ) from exc
    job["platform"] = detect_platform(canonical_input)
    return job


def request_content_length(request: Request) -> int | None:
    raw = request.headers.get("content-length")
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"reason": "invalid_content_length", "message": "上传文件大小无效。"},
        ) from exc
    if value < 0:
        raise HTTPException(
            status_code=400,
            detail={"reason": "invalid_content_length", "message": "上传文件大小无效。"},
        )
    return value


def request_asr_hotwords(request: Request) -> str | None:
    encoded = request.headers.get("x-asr-hotwords", "").strip()
    if not encoded:
        return None
    if re.search(r"%(?![0-9A-Fa-f]{2})", encoded):
        raise HTTPException(
            status_code=422,
            detail={"reason": "invalid_hotwords", "message": "专业词汇编码无效。"},
        )
    if len(encoded) > ASR_PROMPT_MAX_CHARS * 12:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "hotwords_too_long",
                "message": f"专业词汇最多输入 {ASR_PROMPT_MAX_CHARS} 个字符。",
            },
        )
    try:
        decoded = urllib.parse.unquote(encoded, encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"reason": "invalid_hotwords", "message": "专业词汇编码无效。"},
        ) from exc
    if len(decoded) > ASR_PROMPT_MAX_CHARS:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "hotwords_too_long",
                "message": f"专业词汇最多输入 {ASR_PROMPT_MAX_CHARS} 个字符。",
            },
        )
    return sanitize_asr_context(decoded)


def upload_idempotency_fingerprint(
    filename: str,
    output_format: str,
    lang: str | None,
    hotwords: str | None,
    quality: str,
    asr_mode: str,
    embedded_subtitles: bool,
    force_refresh: bool,
    content_length: int | None,
) -> str:
    safe_name, _ = safe_upload_filename(filename)
    return job_request_fingerprint(
        {
            "kind": "upload",
            "filename": safe_name,
            "format": output_format,
            "lang": (lang or "").lower().replace("_", "-"),
            "hotwords_hash": asr_context_hash(hotwords),
            "quality": quality,
            "asr_mode": asr_mode,
            "embedded_subtitles": embedded_subtitles,
            "force_refresh": force_refresh,
            "content_length": content_length,
        }
    )


def media_idempotency_fingerprint(req: MediaRequest, canonical_input: str) -> str:
    return job_request_fingerprint(
        {
            "kind": "media",
            "input": canonical_input,
            "media_type": req.media_type,
            "use_cookie": req.use_cookie,
            "force_refresh": req.force_refresh,
        }
    )


def submit_media_job(req: MediaRequest, owner_id: int, idempotency_key: str | None) -> dict[str, Any]:
    try:
        canonical_input = normalize_input(req.input)
    except ExtractionFailure as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=extraction_error_detail("media", exc),
        ) from exc
    canonical_req = req.model_copy(update={"input": canonical_input})
    fingerprint = media_idempotency_fingerprint(canonical_req, canonical_input) if idempotency_key else None
    try:
        existing = JOB_MANAGER.get_by_idempotency(
            owner_id,
            idempotency_key,
            idempotency_fingerprint=fingerprint,
        )
    except JobIdempotencyConflict as exc:
        raise idempotency_conflict_error() from exc
    if existing is not None:
        existing["platform"] = detect_platform(canonical_input)
        existing["media_type"] = req.media_type
        return existing
    if JOB_MANAGER.stats()["queued"] >= JOB_QUEUE_MAX_PENDING:
        raise HTTPException(
            status_code=429,
            detail={
                "source": "queue",
                "reason": "queue_full",
                "code": "job_queue_full",
                "message": f"任务队列已满，当前最多等待 {JOB_QUEUE_MAX_PENDING} 个任务，请稍后再试。",
                "retryable": True,
            },
        )

    artifact_token = secrets.token_hex(16)
    reserve_media_artifact(artifact_token)
    media_req = MediaJobRequest(
        **canonical_req.model_dump(mode="json"),
        artifact_token=artifact_token,
        owner_id=owner_id,
    )
    payload = media_req.model_dump(mode="json")
    transferred = False
    try:
        try:
            job = JOB_MANAGER.submit(
                payload,
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                idempotency_fingerprint=fingerprint,
            )
        except JobQueueFull as exc:
            raise HTTPException(
                status_code=429,
                detail={
                    "source": "queue",
                    "reason": "queue_full",
                    "code": "job_queue_full",
                    "message": f"任务队列已满，当前最多等待 {JOB_QUEUE_MAX_PENDING} 个任务，请稍后再试。",
                    "retryable": True,
                },
            ) from exc
        transferred = not bool(job.get("reused"))
        job["platform"] = detect_platform(canonical_input)
        job["media_type"] = req.media_type
        return job
    except JobIdempotencyConflict as exc:
        raise idempotency_conflict_error() from exc
    finally:
        if not transferred:
            discard_media_payload(payload)


async def stage_uploaded_video(
    request: Request,
    filename: str,
    output_format: Literal["txt", "srt", "json", "markdown", "md", "vtt"],
    lang: str | None,
    quality: Literal["fast", "accurate"],
    embedded_subtitles: bool,
    force_refresh: bool,
    hotwords: str | None = None,
    asr_mode: Literal["auto", "high_accuracy", "economy"] = "auto",
) -> UploadJobRequest:
    safe_name, extension = safe_upload_filename(filename)
    content_length = request_content_length(request)
    upload_token = secrets.token_hex(16)
    reserve_upload(upload_token, content_length)
    directory = ASR_TMP_DIR / f"asr-upload-{upload_token}"
    stored_name = f"source{extension}"
    target = directory / stored_name
    payload: dict[str, Any] = {"kind": "upload", "upload_token": upload_token}
    try:
        ASR_TMP_DIR.mkdir(parents=True, exist_ok=True)
        directory.mkdir(mode=0o700)
        digest = hashlib.sha256()
        written = 0
        next_disk_check = 32 * 1024 * 1024
        try:
            with target.open("xb") as handle:
                os.chmod(target, 0o600)
                async for chunk in request.stream():
                    if not chunk:
                        continue
                    next_size = written + len(chunk)
                    resize_upload_reservation(upload_token, next_size)
                    if next_size >= next_disk_check:
                        disk_space_http_error(ASR_TMP_DIR)
                        next_disk_check = next_size + 32 * 1024 * 1024
                    handle.write(chunk)
                    digest.update(chunk)
                    written = next_size
        except ClientDisconnect as exc:
            raise HTTPException(
                status_code=400,
                detail={"reason": "upload_interrupted", "message": "视频上传中断，请重试。"},
            ) from exc
        if written <= 0:
            raise HTTPException(
                status_code=400,
                detail={"reason": "empty_upload", "message": "上传的视频文件为空。"},
            )
        if content_length is not None and written != content_length:
            raise HTTPException(
                status_code=400,
                detail={"reason": "upload_interrupted", "message": "视频上传不完整，请重试。"},
            )
        return UploadJobRequest(
            upload_token=upload_token,
            stored_name=stored_name,
            filename=safe_name,
            sha256=digest.hexdigest(),
            size=written,
            format=output_format,
            lang=lang,
            hotwords=sanitize_asr_context(hotwords),
            quality=quality,
            asr_mode=asr_mode,
            embedded_subtitles=embedded_subtitles,
            force_refresh=force_refresh,
        )
    except asyncio.CancelledError:
        discard_upload_payload(payload)
        raise
    except OSError as exc:
        discard_upload_payload(payload)
        if exc.errno == errno.ENOSPC:
            raise HTTPException(
                status_code=507,
                detail={
                    "reason": "disk_space_low",
                    "code": "disk_space_low",
                    "message": "服务器剩余磁盘空间不足，上传已安全停止。",
                    "retryable": True,
                },
            ) from exc
        raise HTTPException(
            status_code=500,
            detail={
                "reason": "upload_write_failed",
                "code": "upload_failed",
                "message": "服务器无法保存上传文件，请稍后重试。",
                "retryable": True,
            },
        ) from exc
    except Exception:
        discard_upload_payload(payload)
        raise


def load_media_artifact(
    artifact_token: str,
    owner_id: int,
) -> tuple[Path, dict[str, Any]]:
    if not MEDIA_TOKEN_RE.fullmatch(artifact_token):
        raise HTTPException(
            status_code=404,
            detail={"reason": "artifact_not_found", "message": "下载文件不存在或已过期。"},
        )
    directory = MEDIA_ARTIFACT_DIR / f"media-artifact-{artifact_token}"
    metadata_path = directory / "artifact.json"
    try:
        metadata_stat = metadata_path.lstat()
        if metadata_path.is_symlink() or not metadata_path.is_file() or metadata_stat.st_size > 64 * 1024:
            raise OSError("invalid artifact metadata")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise HTTPException(
            status_code=410,
            detail={"reason": "artifact_expired", "message": "下载文件不存在或已过期。"},
        )
    if not isinstance(metadata, dict) or metadata.get("artifact_token") != artifact_token:
        raise HTTPException(
            status_code=410,
            detail={"reason": "artifact_expired", "message": "下载文件不存在或已过期。"},
        )
    try:
        stored_owner_id = int(metadata.get("owner_id"))
    except (TypeError, ValueError):
        stored_owner_id = -1
    if stored_owner_id != owner_id:
        raise HTTPException(
            status_code=404,
            detail={"reason": "artifact_not_found", "message": "下载文件不存在或已过期。"},
        )
    try:
        expires_at = float(metadata.get("expires_at") or 0)
    except (TypeError, ValueError):
        expires_at = 0
    if expires_at <= time.time():
        discard_media_payload({"kind": "media", "artifact_token": artifact_token})
        raise HTTPException(
            status_code=410,
            detail={"reason": "artifact_expired", "message": "下载文件已过期，请重新提取。"},
        )
    stored_name = str(metadata.get("stored_name") or "")
    if not re.fullmatch(r"artifact\.(?:mp3|mp4|webm|mkv|mov)", stored_name):
        raise HTTPException(
            status_code=410,
            detail={"reason": "artifact_expired", "message": "下载文件不存在或已过期。"},
        )
    path = directory / stored_name
    try:
        stat = path.lstat()
        expected_size = int(metadata.get("size") or 0)
    except (OSError, TypeError, ValueError):
        raise HTTPException(
            status_code=410,
            detail={"reason": "artifact_expired", "message": "下载文件不存在或已过期。"},
        )
    if path.is_symlink() or not path.is_file() or stat.st_size <= 0 or stat.st_size != expected_size:
        raise HTTPException(
            status_code=410,
            detail={"reason": "artifact_expired", "message": "下载文件不存在或已过期。"},
        )
    return path, metadata


def wait_for_legacy_result(job: dict[str, Any], owner_id: int) -> dict[str, Any]:
    if job["status"] not in {"completed", "failed", "cancelled"}:
        job = JOB_MANAGER.wait(job["id"], owner_id=owner_id, timeout=LEGACY_WAIT_TIMEOUT_SECONDS)
    if job["status"] == "completed":
        return job["result"]
    if job["status"] == "failed":
        raise HTTPException(status_code=int(job.get("error_status") or 500), detail=job.get("error"))
    if job["status"] == "cancelled":
        raise HTTPException(status_code=409, detail={"reason": "job_cancelled", "message": "任务已取消。"})
    raise HTTPException(
        status_code=504,
        detail={
            "reason": "legacy_wait_timeout",
            "message": "同步接口等待超时，任务仍在后台处理。",
            "job_id": job["id"],
        },
    )


def run_legacy_extraction(req: ExtractRequest, request: Request) -> dict[str, Any]:
    user = require_auth_user(request)
    if not LEGACY_REQUEST_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=429,
            detail={"reason": "legacy_busy", "message": "同步接口正忙，请使用任务接口。"},
        )
    try:
        job = submit_extraction_job(req, user.user_id, request_idempotency_key(request))
        return wait_for_legacy_result(job, user.user_id)
    finally:
        LEGACY_REQUEST_SEMAPHORE.release()


app = FastAPI(title=APP_TITLE)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

PUBLIC_PATHS = {
    "/login",
    "/register",
    "/api/health",
    "/api/auth/config",
    "/api/auth/login",
    "/api/auth/register",
}


def request_origin_allowed(request: Request) -> bool:
    origin = request.headers.get("origin", "").rstrip("/")
    if not origin:
        return True
    expected = f"{request.url.scheme}://{request.headers.get('host', '')}".rstrip("/")
    return secrets.compare_digest(origin, expected)


@app.middleware("http")
async def account_session_middleware(request: Request, call_next: Callable[[Request], Any]) -> Response:
    path = request.url.path
    is_static = path.startswith("/static/")
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    user = None
    if session_token and not is_static:
        user = await run_in_threadpool(resolve_session, session_token)
    request.state.auth_user = user

    if request.method not in {"GET", "HEAD", "OPTIONS"} and not request_origin_allowed(request):
        return JSONResponse(
            status_code=403,
            content={"detail": {"reason": "invalid_origin", "message": "请求来源校验失败。"}},
        )

    if path in {"/login", "/register"} and user is not None:
        return RedirectResponse(url="/", status_code=303)
    is_provider_audio = path.startswith("/api/provider-audio/")
    if path not in PUBLIC_PATHS and not is_static and not is_provider_audio and user is None:
        if path.startswith("/api/"):
            return JSONResponse(
                status_code=401,
                content={"detail": {"reason": "authentication_required", "message": "请先登录。"}},
                headers={"Cache-Control": "no-store"},
            )
        return RedirectResponse(url="/login", status_code=303)
    return await call_next(request)


@app.on_event("startup")
def startup() -> None:
    initialize_auth_db()
    with UPLOAD_RESERVATION_LOCK:
        UPLOAD_RESERVATIONS.clear()
    with MEDIA_RESERVATION_LOCK:
        MEDIA_RESERVATIONS.clear()
    ASR_TMP_DIR.mkdir(parents=True, exist_ok=True)
    ASR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ASR_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(MEDIA_ARTIFACT_DIR, 0o700)
    cleanup_stale_asr_tmp()
    cleanup_stale_media_artifacts()
    cleanup_result_cache()
    initialize_cloud_services()
    JOB_MANAGER.start()
    if (
        local_asr_enabled()
        and env_bool("ASR_PERSISTENT_WORKER", True)
        and env_bool("ASR_PREWARM", True)
    ):
        start_asr_prewarm()


@app.on_event("shutdown")
def shutdown() -> None:
    JOB_MANAGER.stop()
    stop_asr_worker()
    close_cloud_providers()
    if CLOUD_SIGNED_AUDIO_STORE is not None:
        CLOUD_SIGNED_AUDIO_STORE.cleanup()


def cloud_asr_ready() -> bool:
    return bool(
        cloud_asr_enabled()
        and CLOUD_ASR_INIT_ERROR is None
        and cloud_audio_delivery_ready()
        and CLOUD_USAGE_LEDGER is not None
    )


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse(
        {"status": "ok"},
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/client-config")
def api_client_config(request: Request) -> JSONResponse:
    require_auth_user(request)
    JOB_MANAGER.cleanup()
    cleanup_stale_media_artifacts()
    ffmpeg_ready = bool(shutil.which("ffmpeg"))
    ffprobe_ready = bool(shutil.which("ffprobe"))
    local_ready = bool(local_asr_enabled() and ffmpeg_ready and ffprobe_ready)
    cloud_ready = cloud_asr_ready()
    processing_ready = local_ready or cloud_ready
    douyin = douyin_adapter_status()
    douyin_ready = bool(
        douyin["enabled"]
        and douyin["api_adapter_ready"]
        and douyin["playwright_ready"]
        and douyin["chromium_ready"]
    )
    auto_backend = selected_asr_backend("auto")
    auto_ready = local_ready if auto_backend == "local" else cloud_ready
    payload = {
        "status": "ok",
        "features": {
            "local_processing": local_ready,
            "cloud_enhancement": cloud_ready,
            "embedded_subtitles": ffmpeg_ready,
            "video_text_recognition": bool(
                ffmpeg_ready
                and importlib.util.find_spec("rapidocr") is not None
                and importlib.util.find_spec("onnxruntime") is not None
            ),
            "uploads": processing_ready,
            "media": ffmpeg_ready and ffprobe_ready,
            "bilibili_cookie": cookie_enabled() and bool(configured_cookie_header()),
            "bilibili_qr_login": web_qr_login_enabled(),
        },
        "platforms": {
            "bilibili": True,
            "douyin": douyin_ready,
            "upload": processing_ready,
        },
        "asr_modes": {
            "auto": {
                "available": auto_ready,
                "processing": auto_backend,
            },
            "high_accuracy": {
                "available": cloud_ready,
                "processing": "cloud",
            },
            "economy": {
                "available": cloud_ready,
                "processing": "cloud",
            },
        },
        "uploads": {
            "enabled": processing_ready,
            "max_bytes": PUBLIC_UPLOAD_MAX_BYTES,
            "allowed_extensions": sorted(UPLOAD_ALLOWED_EXTENSIONS),
        },
        "media": {
            "enabled": ffmpeg_ready and ffprobe_ready,
        },
    }
    return JSONResponse(payload, headers={"Cache-Control": "private, no-store"})


@app.api_route("/api/provider-audio/{token}", methods=["GET", "HEAD"])
def api_provider_audio(
    request: Request,
    token: str,
    expires: int = Query(..., gt=0),
    signature: str = Query(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
) -> FileResponse:
    if CLOUD_SIGNED_AUDIO_STORE is None:
        raise HTTPException(status_code=404, detail={"reason": "signed_audio_not_found"})
    try:
        record = CLOUD_SIGNED_AUDIO_STORE.resolve(token, expires, signature)
    except SignedAudioError as exc:
        raise HTTPException(
            status_code=410,
            detail={"reason": "signed_audio_expired", "message": "临时音频链接已失效。"},
        ) from exc
    LOGGER.info(
        "provider audio fetch method=%s range=%s",
        request.method,
        bool(request.headers.get("range")),
    )
    return FileResponse(
        record.path,
        media_type=record.content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/auth/config")
def api_auth_config() -> dict[str, Any]:
    return {
        "registration_enabled": invite_configured(),
        "username_pattern": "[A-Za-z0-9_.-]{3,32}",
        "password_min_length": 8,
    }


@app.post("/api/auth/register")
def api_auth_register(req: RegisterRequest) -> JSONResponse:
    try:
        user = register_user(req.username, req.password, req.invite_code)
        token, expires_at = create_session(user)
    except AuthFailure as exc:
        raise auth_error(exc) from exc
    response = JSONResponse(
        {"ok": True, "user": {"id": user.user_id, "username": user.username}},
        headers={"Cache-Control": "no-store"},
    )
    set_session_cookie(response, token, expires_at)
    return response


@app.post("/api/auth/login")
def api_auth_login(req: LoginRequest) -> JSONResponse:
    try:
        user = authenticate_user(req.username, req.password)
        token, expires_at = create_session(user)
    except AuthFailure as exc:
        raise auth_error(exc) from exc
    response = JSONResponse(
        {"ok": True, "user": {"id": user.user_id, "username": user.username}},
        headers={"Cache-Control": "no-store"},
    )
    set_session_cookie(response, token, expires_at)
    return response


@app.get("/api/auth/me")
def api_auth_me(request: Request) -> dict[str, Any]:
    user = require_auth_user(request)
    try:
        summary = account_summary(user.user_id)
    except AuthFailure as exc:
        raise auth_error(exc) from exc
    return {
        "ok": True,
        "user": {
            "id": user.user_id,
            "username": user.username,
            **summary,
        },
    }


@app.post("/api/auth/change-password")
def api_auth_change_password(req: ChangePasswordRequest, request: Request) -> JSONResponse:
    user = require_auth_user(request)
    try:
        updated_user = change_password(
            user.user_id,
            req.current_password,
            req.new_password,
        )
        token, expires_at = create_session(updated_user)
    except AuthFailure as exc:
        raise auth_error(exc) from exc
    response = JSONResponse(
        {
            "ok": True,
            "message": "密码已更新，其他设备上的登录已退出。",
            "user": {"id": updated_user.user_id, "username": updated_user.username},
        },
        headers={"Cache-Control": "no-store"},
    )
    set_session_cookie(response, token, expires_at)
    return response


@app.post("/api/auth/logout-all")
def api_auth_logout_all(request: Request) -> JSONResponse:
    user = require_auth_user(request)
    delete_user_sessions(user.user_id)
    response = JSONResponse(
        {"ok": True, "message": "所有设备均已退出登录。"},
        headers={"Cache-Control": "no-store"},
    )
    clear_session_cookie(response)
    return response


@app.get("/api/bilibili/pages")
def api_bilibili_pages(
    input: str = Query(..., min_length=2, max_length=MAX_INPUT_LENGTH),
    use_cookie: bool = Query(False),
) -> dict[str, Any]:
    try:
        canonical = normalize_input(input)
        if detect_platform(canonical) != "bilibili":
            raise ExtractionFailure(
                400,
                "Only Bilibili videos have selectable pages.",
                "unsupported_platform",
                terminal=True,
            )
        bvid, canonical_url, data, selected_page, _ = bili_view_context(
            canonical,
            cookie_allowed(use_cookie),
        )
    except ExtractionFailure as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=extraction_error_detail("bilibili_pages", exc),
        ) from exc
    pages = [
        {
            "page": int(item.get("page") or index),
            "cid": int(item.get("cid") or 0),
            "title": str(item.get("part") or f"P{index}")[:160],
            "duration": float(item.get("duration") or 0) or None,
        }
        for index, item in enumerate(data.get("pages") or [], 1)
        if isinstance(item, dict) and item.get("cid")
    ]
    if not pages and selected_page:
        pages = [
            {
                "page": 1,
                "cid": int(selected_page.get("cid") or 0),
                "title": str(selected_page.get("part") or data.get("title") or "P1")[:160],
                "duration": float(selected_page.get("duration") or 0) or None,
            }
        ]
    return {
        "ok": True,
        "bvid": bvid,
        "title": str(data.get("title") or "")[:200],
        "base_url": f"https://www.bilibili.com/video/{quote(bvid)}",
        "current_page": bili_page_number(canonical_url),
        "pages": pages,
    }


@app.post("/api/auth/logout")
def api_auth_logout(request: Request) -> JSONResponse:
    delete_session(request.cookies.get(SESSION_COOKIE_NAME))
    response = JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})
    clear_session_cookie(response)
    return response


@app.get("/login", response_class=FileResponse)
def login_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "auth.html", headers={"Cache-Control": "no-cache"})


@app.get("/register", response_class=FileResponse)
def register_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "auth.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/login/qrcode")
@app.post("/api/login/qrcode")
def api_login_qrcode() -> dict[str, Any]:
    if not web_qr_login_enabled():
        raise HTTPException(
            status_code=403,
            detail={"reason": "qr_login_disabled", "message": "网页扫码登录当前未启用。"},
        )
    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"}
    try:
        with httpx.Client(
            timeout=10,
            follow_redirects=True,
            headers=headers,
            event_hooks={"request": [validate_public_request]},
        ) as client:
            resp = client.get(LOGIN_QR_GENERATE_URL)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        LOGGER.warning("Bilibili QR login request failed: %s", redact_sensitive(str(exc)))
        raise HTTPException(status_code=502, detail="Bilibili QR login request failed.") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("qrcode_key") or not data.get("url"):
        raise HTTPException(status_code=502, detail="Bilibili QR login returned an unexpected response.")
    key = str(data["qrcode_key"])
    url = str(data["url"])
    with QR_LOGIN_LOCK:
        clean_qr_sessions()
        QR_LOGIN_SESSIONS[key] = time.time() + 180
    return {
        "ok": True,
        "qrcode_key": key,
        "url": url,
        "expires_in": 180,
        "qr_svg_data_url": qr_svg_data_url(url),
    }


@app.get("/api/login/poll")
def api_login_poll(qrcode_key: str = Query(..., min_length=8, max_length=128)) -> dict[str, Any]:
    if not web_qr_login_enabled():
        raise HTTPException(status_code=403, detail="Web QR login is disabled.")
    with QR_LOGIN_LOCK:
        clean_qr_sessions()
        expires_at = QR_LOGIN_SESSIONS.get(qrcode_key)
    if not expires_at:
        raise HTTPException(status_code=410, detail="QR login session expired. Generate a new QR code.")

    headers = {"User-Agent": USER_AGENT, "Referer": "https://www.bilibili.com/"}
    try:
        with httpx.Client(
            timeout=10,
            follow_redirects=False,
            headers=headers,
            event_hooks={"request": [validate_public_request]},
        ) as client:
            resp = client.get(LOGIN_QR_POLL_URL, params={"qrcode_key": qrcode_key})
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        LOGGER.warning("Bilibili QR login polling failed: %s", redact_sensitive(str(exc)))
        raise HTTPException(status_code=502, detail="Bilibili QR login polling failed.") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Bilibili QR login polling returned an unexpected response.")

    code = data.get("code")
    if code == 0:
        cookie = cookie_header_from_set_cookie(resp.headers.get_list("set-cookie"))
        save_bili_cookie(cookie)
        with QR_LOGIN_LOCK:
            QR_LOGIN_SESSIONS.pop(qrcode_key, None)
        return {"ok": True, "status": "success", "cookie_saved": True, "cookie_enabled": cookie_enabled()}
    if code == 86101:
        return {"ok": True, "status": "waiting_scan", "message": "Waiting for scan."}
    if code == 86090:
        return {"ok": True, "status": "waiting_confirm", "message": "Waiting for confirmation in the Bilibili app."}
    if code == 86038:
        with QR_LOGIN_LOCK:
            QR_LOGIN_SESSIONS.pop(qrcode_key, None)
        return {"ok": False, "status": "expired", "message": "QR code expired."}
    return {"ok": False, "status": "failed", "message": str(data.get("message") or payload.get("message") or code)}


@app.post("/api/extract")
def api_extract(req: ExtractRequest, request: Request) -> JSONResponse:
    return JSONResponse(
        public_result_payload(run_legacy_extraction(req, request)),
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/jobs", status_code=202)
def api_create_job(req: ExtractRequest, request: Request) -> JSONResponse:
    user = require_auth_user(request)
    job = submit_extraction_job(req, user.user_id, request_idempotency_key(request))
    return JSONResponse(
        public_job_payload(job),
        status_code=202,
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/media-jobs", status_code=202)
def api_create_media_job(req: MediaRequest, request: Request) -> JSONResponse:
    user = require_auth_user(request)
    job = submit_media_job(req, user.user_id, request_idempotency_key(request))
    return JSONResponse(
        public_job_payload(job),
        status_code=202,
        headers={"Cache-Control": "no-store"},
    )


@app.post("/api/upload-jobs", status_code=202)
async def api_create_upload_job(
    request: Request,
    filename: str = Query(..., min_length=1, max_length=255),
    output_format: Literal["txt", "srt", "json", "markdown", "md", "vtt"] = Query(
        "txt",
        alias="format",
    ),
    lang: str | None = Query(
        default="zh",
        max_length=35,
        pattern=r"^[A-Za-z]{2,8}(?:[-_][A-Za-z0-9]{1,8})*$",
    ),
    quality: Literal["fast", "accurate"] = Query("accurate"),
    asr_mode: Literal["auto", "high_accuracy", "economy"] = Query("auto"),
    embedded_subtitles: bool = Query(False),
    force_refresh: bool = Query(False),
) -> JSONResponse:
    user = require_auth_user(request)
    hotwords = request_asr_hotwords(request)
    idempotency_key = request_idempotency_key(request)
    content_length = request_content_length(request)
    idempotency_fingerprint = (
        upload_idempotency_fingerprint(
            filename,
            output_format,
            lang,
            hotwords,
            quality,
            asr_mode,
            embedded_subtitles,
            force_refresh,
            content_length,
        )
        if idempotency_key
        else None
    )
    try:
        existing = JOB_MANAGER.get_by_idempotency(
            user.user_id,
            idempotency_key,
            idempotency_fingerprint=idempotency_fingerprint,
        )
    except JobIdempotencyConflict as exc:
        raise idempotency_conflict_error() from exc
    if existing is not None:
        existing["platform"] = "upload"
        return JSONResponse(
            public_job_payload(existing),
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )
    if JOB_MANAGER.stats()["queued"] >= JOB_QUEUE_MAX_PENDING:
        raise HTTPException(
            status_code=429,
            detail={
                "source": "queue",
                "reason": "queue_full",
                "code": "job_queue_full",
                "message": f"任务队列已满，当前最多等待 {JOB_QUEUE_MAX_PENDING} 个任务，请稍后再试。",
                "retryable": True,
            },
        )

    upload_req = await stage_uploaded_video(
        request,
        filename=filename,
        output_format=output_format,
        lang=lang,
        hotwords=hotwords,
        quality=quality,
        asr_mode=asr_mode,
        embedded_subtitles=embedded_subtitles,
        force_refresh=force_refresh,
    )
    transferred = False
    payload = upload_req.model_dump(mode="json")
    payload["_owner_id"] = user.user_id
    try:
        cached_payload = cached_upload_payload(upload_req)
        if cached_payload is not None:
            job = JOB_MANAGER.submit_completed(
                payload,
                cached_payload,
                owner_id=user.user_id,
                idempotency_key=idempotency_key,
                idempotency_fingerprint=idempotency_fingerprint,
            )
        else:
            try:
                job = JOB_MANAGER.submit(
                    payload,
                    owner_id=user.user_id,
                    idempotency_key=idempotency_key,
                    idempotency_fingerprint=idempotency_fingerprint,
                )
            except JobQueueFull as exc:
                raise HTTPException(
                    status_code=429,
                    detail={
                        "source": "queue",
                        "reason": "queue_full",
                        "code": "job_queue_full",
                        "message": f"任务队列已满，当前最多等待 {JOB_QUEUE_MAX_PENDING} 个任务，请稍后再试。",
                        "retryable": True,
                    },
                ) from exc
            transferred = not bool(job.get("reused"))
        job["platform"] = "upload"
        return JSONResponse(
            public_job_payload(job),
            status_code=202,
            headers={"Cache-Control": "no-store"},
        )
    except JobIdempotencyConflict as exc:
        raise idempotency_conflict_error() from exc
    finally:
        if not transferred:
            discard_upload_payload(payload)


@app.get("/api/jobs/{job_id}")
def api_get_job(job_id: str, request: Request) -> JSONResponse:
    user = require_auth_user(request)
    try:
        job = JOB_MANAGER.get(job_id, owner_id=user.user_id)
    except JobNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "job_not_found",
                "code": "job_expired",
                "message": "服务可能已重启或任务已过期，请重新提交。",
                "retryable": True,
            },
        ) from exc
    return JSONResponse(public_job_payload(job), headers={"Cache-Control": "no-store"})


@app.get("/api/artifacts/{artifact_token}")
def api_download_artifact(artifact_token: str, request: Request) -> FileResponse:
    user = require_auth_user(request)
    path, metadata = load_media_artifact(artifact_token, user.user_id)
    filename = str(metadata.get("filename") or path.name)
    content_type = str(metadata.get("content_type") or "application/octet-stream")
    return FileResponse(
        path,
        media_type=content_type,
        filename=filename,
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.delete("/api/jobs/{job_id}")
def api_cancel_job(job_id: str, request: Request) -> JSONResponse:
    user = require_auth_user(request)
    try:
        job = JOB_MANAGER.cancel(job_id, owner_id=user.user_id)
    except JobNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "job_not_found",
                "code": "job_expired",
                "message": "服务可能已重启或任务已过期，请重新提交。",
                "retryable": True,
            },
        ) from exc
    if job["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "job_running",
                "code": "task_not_interruptible",
                "message": "当前阶段不可立即中断，任务仍在安全处理资源。",
                "retryable": False,
            },
        )
    return JSONResponse(public_job_payload(job), headers={"Cache-Control": "no-store"})


@app.post("/api/download")
def api_download(req: ExtractRequest, request: Request) -> Response:
    payload = public_result_payload(run_legacy_extraction(req, request))
    filename = str(payload["filename"])
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
        "Cache-Control": "no-store",
    }
    return Response(payload["content"], media_type=payload["content_type"], headers=headers)


@app.get("/api/download")
def api_download_get_disabled() -> None:
    raise HTTPException(
        status_code=410,
        detail={
            "reason": "download_get_retired",
            "message": "GET 下载接口已停用，请改用 POST /api/download 或网页任务流。",
        },
    )


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-cache"},
    )
