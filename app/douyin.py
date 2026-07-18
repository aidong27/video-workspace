from __future__ import annotations

import asyncio
from dataclasses import dataclass
import errno
import importlib.util
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import string
from threading import Lock
import time
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from app.network import validate_public_request
from app.processes import ManagedProcessTimeout, run_managed_process


DOUYIN_ADAPTER_VERSION = 3
DOUYIN_URL_RE = re.compile(
    r"(https?://(?:[A-Za-z0-9-]+\.)?(?:douyin\.com|iesdouyin\.com)[^\s<>'\"]+|"
    r"(?:[A-Za-z0-9-]+\.)?(?:douyin\.com|iesdouyin\.com)/[^\s<>'\"]+)",
    re.IGNORECASE,
)
DOUYIN_VIDEO_ID_RE = re.compile(r"/(?:video|note)/(\d{8,})", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？、)]}）】》"
DOUYIN_COOKIE_LOCK = Lock()
DOUYIN_DETAIL_LOCK = Lock()
DOUYIN_DETAIL_CACHE: dict[str, tuple[float, "DouyinVideo"]] = {}
LOGGER = logging.getLogger(__name__)


class DouyinAdapterError(Exception):
    def __init__(self, status_code: int, message: str, reason: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.reason = reason


@dataclass(frozen=True)
class DouyinTrack:
    language: str
    ext: str
    url: str
    name: str | None = None


@dataclass
class DouyinVideo:
    video_id: str
    title: str
    author: str | None
    webpage_url: str
    duration: float | None
    media_urls: list[str]
    tracks: list[DouyinTrack]
    cookies: dict[str, str]


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return max(minimum, default)


def _scoped_douyin_cookies(values: dict[str, str]) -> httpx.Cookies:
    cookies = httpx.Cookies()
    for key, value in values.items():
        cookies.set(key, value, domain=".douyin.com", path="/")
    return cookies


def _cookie_state_path() -> Path:
    return Path(
        os.getenv(
            "DOUYIN_COOKIE_STATE_PATH",
            "/opt/bili-subtitle-tool/var/douyin/cookies.json",
        )
    )


def _playwright_root() -> Path:
    return Path(
        os.getenv(
            "PLAYWRIGHT_BROWSERS_PATH",
            "/opt/bili-subtitle-tool/var/playwright",
        )
    )


def _host_allowed(host: str | None) -> bool:
    value = (host or "").lower().rstrip(".")
    return any(value == root or value.endswith(f".{root}") for root in ("douyin.com", "iesdouyin.com"))


def is_douyin_url(value: str) -> bool:
    match = DOUYIN_URL_RE.search(value or "")
    if not match:
        return False
    parsed = urlparse(match.group(1) if "://" in match.group(1) else f"https://{match.group(1)}")
    return _host_allowed(parsed.hostname)


def extract_douyin_url(value: str) -> str | None:
    match = DOUYIN_URL_RE.search(value or "")
    if not match:
        return None
    url = match.group(1).rstrip(TRAILING_URL_PUNCTUATION)
    if not re.match(r"https?://", url, flags=re.IGNORECASE):
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not _host_allowed(parsed.hostname):
        return None
    return url


def extract_douyin_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    match = DOUYIN_VIDEO_ID_RE.search(parsed.path)
    if match:
        return match.group(1)
    query = parse_qs(parsed.query)
    for key in ("modal_id", "aweme_id", "item_id"):
        value = (query.get(key) or [""])[0]
        if re.fullmatch(r"\d{8,}", value):
            return value
    return None


def _resolve_douyin_redirect(url: str) -> str:
    current = url
    visited: set[str] = set()
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
    }
    try:
        with httpx.Client(
            timeout=12,
            follow_redirects=False,
            headers=headers,
            event_hooks={"request": [validate_public_request]},
        ) as client:
            for _ in range(6):
                if not _host_allowed(urlparse(current).hostname):
                    raise DouyinAdapterError(400, "抖音短链接跳转到了不受信任的站点。", "short_link_untrusted")
                if current in visited:
                    raise DouyinAdapterError(508, "抖音短链接发生循环跳转。", "short_link_loop")
                visited.add(current)
                response = client.get(current)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    response.raise_for_status()
                    break
                location = response.headers.get("location")
                if not location:
                    break
                next_url = urljoin(current, location)
                if not _host_allowed(urlparse(next_url).hostname):
                    raise DouyinAdapterError(400, "抖音短链接跳转到了不受信任的站点。", "short_link_untrusted")
                current = next_url
            else:
                raise DouyinAdapterError(508, "抖音短链接跳转次数过多。", "short_link_loop")
    except DouyinAdapterError:
        raise
    except httpx.HTTPError as exc:
        raise DouyinAdapterError(502, f"抖音短链接解析失败：{exc}", "short_link_request_failed") from exc
    return current


def normalize_douyin_input(value: str) -> str:
    url = extract_douyin_url(value)
    if not url:
        raise DouyinAdapterError(400, "请输入有效的抖音视频链接。", "invalid_input")
    parsed = urlparse(url)
    video_id = extract_douyin_video_id(url)
    if not video_id and parsed.hostname and parsed.hostname.lower().startswith("v."):
        url = _resolve_douyin_redirect(url)
        video_id = extract_douyin_video_id(url)
    if not video_id:
        url = _resolve_douyin_redirect(url)
        video_id = extract_douyin_video_id(url)
    if not video_id:
        raise DouyinAdapterError(400, "链接中没有识别到抖音视频编号。", "invalid_input")
    return f"https://www.douyin.com/video/{video_id}"


def _chromium_executable() -> Path | None:
    configured = os.getenv("DOUYIN_CHROMIUM_EXECUTABLE", "").strip()
    if configured:
        path = Path(configured)
        return path if path.is_file() else None
    root = _playwright_root()
    try:
        matches = sorted(root.glob("chromium-*/chrome-linux*/chrome"), reverse=True)
    except OSError:
        return None
    return matches[0] if matches else None


def _dependency_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ModuleNotFoundError, AttributeError):
        return False


def adapter_status() -> dict[str, Any]:
    cookie_path = _cookie_state_path()
    cookie_age = None
    cookie_cached = False
    try:
        cookie_age = max(0, int(time.time() - cookie_path.stat().st_mtime))
        cookie_cached = cookie_path.is_file()
    except OSError:
        pass
    return {
        "enabled": os.getenv("DOUYIN_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"},
        "api_adapter_ready": _dependency_available("core.api_client"),
        "playwright_ready": _dependency_available("playwright.sync_api"),
        "chromium_ready": _chromium_executable() is not None,
        "cookie_cached": cookie_cached,
        "cookie_age_seconds": cookie_age,
        "adapter_version": DOUYIN_ADAPTER_VERSION,
    }


def _read_cached_cookies() -> dict[str, str] | None:
    path = _cookie_state_path()
    ttl = _env_int("DOUYIN_COOKIE_TTL_SECONDS", 1800, 60)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        created_at = float(payload.get("created_at") or 0)
        cookies = payload.get("cookies")
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if time.time() - created_at > ttl or not isinstance(cookies, dict):
        return None
    cleaned = {str(key): str(value) for key, value in cookies.items() if key and value is not None}
    return cleaned if len(cleaned) >= 6 else None


def _write_cached_cookies(cookies: dict[str, str]) -> None:
    path = _cookie_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = {"created_at": int(time.time()), "cookies": cookies}
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")), encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def refresh_douyin_cookies(target_url: str) -> dict[str, str]:
    executable = _chromium_executable()
    if executable is None:
        raise DouyinAdapterError(503, "抖音浏览器运行环境尚未安装。", "douyin_browser_missing")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DouyinAdapterError(503, "抖音浏览器依赖尚未安装。", "douyin_browser_missing") from exc

    wait_ms = _env_int("DOUYIN_BROWSER_WAIT_MS", 6000, 1500)
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
    )
    raw_cookies: list[dict[str, Any]] = []
    try:
        with sync_playwright() as playwright:
            browser = None
            context = None
            page = None
            try:
                browser = playwright.chromium.launch(
                    executable_path=str(executable),
                    headless=True,
                    timeout=60_000,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-crash-reporter",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                context = browser.new_context(
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    user_agent=user_agent,
                    viewport={"width": 1365, "height": 768},
                )
                page = context.new_page()
                page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(wait_ms)
                raw_cookies = context.cookies()
            finally:
                for resource in (page, context, browser):
                    if resource is None:
                        continue
                    try:
                        resource.close()
                    except Exception:
                        pass
    except Exception as exc:
        raise DouyinAdapterError(502, f"抖音匿名会话初始化失败：{exc}", "douyin_cookie_refresh_failed") from exc

    cookies = {
        str(item.get("name")): str(item.get("value"))
        for item in raw_cookies
        if item.get("name") and item.get("value") is not None and _host_allowed(str(item.get("domain") or ""))
    }
    if len(cookies) < 6:
        raise DouyinAdapterError(502, "抖音匿名会话没有返回足够的 Cookie。", "douyin_cookie_refresh_failed")
    _write_cached_cookies(cookies)
    return cookies


def douyin_cookies(target_url: str, force_refresh: bool = False) -> dict[str, str]:
    if not force_refresh:
        cached = _read_cached_cookies()
        if cached:
            return cached
    acquired = DOUYIN_COOKIE_LOCK.acquire(
        timeout=_env_int("DOUYIN_BROWSER_LOCK_TIMEOUT_SECONDS", 90, 10)
    )
    if not acquired:
        raise DouyinAdapterError(429, "抖音浏览器资源正忙，请稍后重试。", "douyin_browser_busy")
    try:
        if not force_refresh:
            cached = _read_cached_cookies()
            if cached:
                return cached
        return refresh_douyin_cookies(target_url)
    finally:
        DOUYIN_COOKIE_LOCK.release()


def _fake_ms_token() -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(182)) + "=="


async def _fetch_detail_async(video_id: str, cookies: dict[str, str]) -> dict[str, Any] | None:
    try:
        from core.api_client import DouyinAPIClient
    except ImportError as exc:
        raise DouyinAdapterError(503, "抖音签名适配器尚未安装。", "douyin_adapter_missing") from exc
    request_cookies = dict(cookies)
    request_cookies.setdefault("msToken", _fake_ms_token())
    client = DouyinAPIClient(request_cookies)
    try:
        detail = await client.get_video_detail(video_id, suppress_error=True)
        return detail if isinstance(detail, dict) else None
    finally:
        await client.close()


def _fetch_detail(video_id: str, cookies: dict[str, str]) -> dict[str, Any] | None:
    try:
        return asyncio.run(_fetch_detail_async(video_id, cookies))
    except DouyinAdapterError:
        raise
    except Exception as exc:
        raise DouyinAdapterError(502, f"抖音视频信息请求失败：{exc}", "douyin_api_failed") from exc


def _first_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    if isinstance(value, list):
        for item in value:
            found = _first_url(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("url_list", "url", "uri", "download_url"):
            found = _first_url(value.get(key))
            if found:
                return found
    return None


def _all_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.startswith(("http://", "https://")) else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_all_urls(item))
        return result
    if isinstance(value, dict):
        for key in ("url_list", "url", "download_url", "main_url", "backup_url", "fallback_url"):
            if key in value:
                result = _all_urls(value[key])
                if result:
                    return result
    return []


def _caption_tracks(detail: dict[str, Any]) -> list[DouyinTrack]:
    tracks: list[DouyinTrack] = []
    stickers = detail.get("interaction_stickers") or []
    if isinstance(stickers, list):
        for sticker in stickers:
            if not isinstance(sticker, dict):
                continue
            info = sticker.get("auto_video_caption_info") or {}
            captions = info.get("auto_captions") or [] if isinstance(info, dict) else []
            if not isinstance(captions, list):
                continue
            for caption in captions:
                if not isinstance(caption, dict):
                    continue
                url = _first_url(caption.get("url"))
                if url:
                    tracks.append(
                        DouyinTrack(
                            language=str(caption.get("language") or "zh"),
                            ext="json",
                            url=url,
                            name="抖音自动字幕",
                        )
                    )

    video = detail.get("video") or {}
    cla_info = video.get("cla_info") or {} if isinstance(video, dict) else {}
    caption_infos = cla_info.get("caption_infos") or [] if isinstance(cla_info, dict) else []
    ext_map = {"creator_caption": "json", "srt": "srt", "webvtt": "vtt"}
    if isinstance(caption_infos, list):
        for caption in caption_infos:
            if not isinstance(caption, dict):
                continue
            url = _first_url(caption.get("url"))
            if not url:
                continue
            tracks.append(
                DouyinTrack(
                    language=str(caption.get("lang") or "zh"),
                    ext=ext_map.get(str(caption.get("Format") or ""), "json"),
                    url=url,
                    name="抖音字幕",
                )
            )

    unique: list[DouyinTrack] = []
    seen: set[str] = set()
    for track in tracks:
        if track.url in seen:
            continue
        seen.add(track.url)
        unique.append(track)
    return unique


def _media_urls(detail: dict[str, Any]) -> list[str]:
    video = detail.get("video") or {}
    if not isinstance(video, dict):
        return []
    music = detail.get("music") or {}
    music_urls = _all_urls(music.get("play_url")) if isinstance(music, dict) else []
    original_sound = bool(
        isinstance(music, dict)
        and (
            music.get("is_original_sound")
            or "创作的原声" in str(music.get("title") or "")
        )
    )
    variants = [item for item in (video.get("bit_rate") or []) if isinstance(item, dict)]
    variants.sort(key=lambda item: int(item.get("bit_rate") or item.get("bitrate") or 0))
    candidates: list[str] = []
    if original_sound:
        candidates.extend(music_urls)
    for key in ("play_addr", "play_addr_h264"):
        candidates.extend(_all_urls(video.get(key)))
    if not original_sound:
        candidates.extend(music_urls)
    for variant in variants:
        candidates.extend(_all_urls(variant.get("play_addr")))
    candidates.extend(_all_urls(video.get("download_addr")))
    unique: list[str] = []
    seen: set[str] = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        unique.append(url)
    return unique


def get_douyin_video(canonical_url: str, force_refresh: bool = False) -> DouyinVideo:
    if os.getenv("DOUYIN_ENABLED", "true").strip().lower() not in {"1", "true", "yes", "on"}:
        raise DouyinAdapterError(503, "抖音提取功能当前已关闭。", "douyin_disabled")
    video_id = extract_douyin_video_id(canonical_url)
    if not video_id:
        raise DouyinAdapterError(400, "链接中没有识别到抖音视频编号。", "invalid_input")
    cache_ttl = _env_int("DOUYIN_DETAIL_CACHE_TTL_SECONDS", 600, 0)
    with DOUYIN_DETAIL_LOCK:
        cached = DOUYIN_DETAIL_CACHE.get(video_id)
        if cached and not force_refresh and time.time() - cached[0] <= cache_ttl:
            return cached[1]

    cookies = douyin_cookies(canonical_url, force_refresh=False)
    detail = _fetch_detail(video_id, cookies)
    if not detail:
        cookies = douyin_cookies(canonical_url, force_refresh=True)
        detail = _fetch_detail(video_id, cookies)
    if not detail:
        raise DouyinAdapterError(
            502,
            "抖音没有返回视频信息，可能触发了平台风控，请稍后重试。",
            "douyin_api_failed",
        )

    video = detail.get("video") or {}
    duration_ms = detail.get("duration") or (video.get("duration") if isinstance(video, dict) else None)
    try:
        duration = float(duration_ms) / 1000 if duration_ms else None
    except (TypeError, ValueError):
        duration = None
    author = detail.get("author") or {}
    author_name = str(author.get("nickname") or "").strip() if isinstance(author, dict) else ""
    title = str(detail.get("desc") or "").strip() or f"抖音视频 {video_id}"
    result = DouyinVideo(
        video_id=video_id,
        title=title,
        author=author_name or None,
        webpage_url=f"https://www.douyin.com/video/{video_id}",
        duration=duration,
        media_urls=_media_urls(detail),
        tracks=_caption_tracks(detail),
        cookies=cookies,
    )
    if not result.media_urls:
        raise DouyinAdapterError(502, "抖音视频信息中没有可用媒体地址。", "douyin_media_missing")
    with DOUYIN_DETAIL_LOCK:
        DOUYIN_DETAIL_CACHE[video_id] = (time.time(), result)
        if len(DOUYIN_DETAIL_CACHE) > 64:
            oldest = min(DOUYIN_DETAIL_CACHE, key=lambda key: DOUYIN_DETAIL_CACHE[key][0])
            DOUYIN_DETAIL_CACHE.pop(oldest, None)
    return result


def fetch_douyin_subtitle(track: DouyinTrack, video: DouyinVideo) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
        ),
        "Referer": video.webpage_url,
    }
    try:
        with httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers=headers,
            cookies=_scoped_douyin_cookies(video.cookies),
            event_hooks={"request": [validate_public_request]},
        ) as client:
            response = client.get(track.url)
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        raise DouyinAdapterError(502, f"抖音字幕下载失败：{exc}", "subtitle_download_failed") from exc


def download_douyin_media(
    video: DouyinVideo,
    target_dir: Path,
    require_video: bool = False,
) -> tuple[Path, dict[str, Any]]:
    target_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = _env_int("DOUYIN_MAX_DOWNLOAD_BYTES", 1_000_000_000, 10_000_000)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
    }
    last_error: Exception | None = None
    missing_requested_stream = False
    refreshed_urls = False
    current_video = video
    while True:
        for index, url in enumerate(current_video.media_urls[:10]):
            partial = target_dir / f"{video.video_id}.{index}.partial"
            final = target_dir / f"{video.video_id}.mp4"
            partial.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            downloaded = 0
            try:
                with httpx.Client(
                    timeout=_env_int("ASR_DOWNLOAD_TIMEOUT_SECONDS", 300, 30),
                    follow_redirects=True,
                    headers=headers,
                    cookies=_scoped_douyin_cookies(current_video.cookies),
                    event_hooks={"request": [validate_public_request]},
                ) as client:
                    with client.stream("GET", url) as response:
                        response.raise_for_status()
                        content_length = int(response.headers.get("content-length") or 0)
                        if content_length > max_bytes:
                            raise DouyinAdapterError(413, "抖音视频文件超过服务器下载限制。", "download_too_large")
                        content_type = (response.headers.get("content-type") or "").lower()
                        if content_type and not any(
                            kind in content_type for kind in ("video", "audio", "octet-stream")
                        ):
                            raise RuntimeError("media endpoint returned a non-media response")
                        with partial.open("xb") as handle:
                            for chunk in response.iter_bytes(1024 * 1024):
                                if not chunk:
                                    continue
                                downloaded += len(chunk)
                                if downloaded > max_bytes:
                                    raise DouyinAdapterError(
                                        413,
                                        "抖音视频文件超过服务器下载限制。",
                                        "download_too_large",
                                    )
                                handle.write(chunk)
                if downloaded < 1024:
                    raise RuntimeError("downloaded media is empty")
                os.replace(partial, final)
                ffprobe = shutil.which("ffprobe")
                if not ffprobe:
                    raise DouyinAdapterError(503, "服务器缺少 ffprobe。", "ffmpeg_missing")
                try:
                    probe = run_managed_process(
                        [
                            ffprobe,
                            "-v",
                            "error",
                            "-show_entries",
                            "format=duration:stream=index,codec_type",
                            "-of",
                            "json",
                            str(final),
                        ],
                        timeout=30,
                    )
                except OSError as exc:
                    raise DouyinAdapterError(503, "无法启动 ffprobe 媒体探测进程。", "ffmpeg_failed") from exc
                try:
                    probe_data = json.loads(probe.stdout) if probe.returncode == 0 else {}
                    streams = probe_data.get("streams") or []
                    has_audio = any(
                        item.get("codec_type") == "audio" for item in streams if isinstance(item, dict)
                    )
                    has_video = any(
                        item.get("codec_type") == "video" for item in streams if isinstance(item, dict)
                    )
                    media_duration = float((probe_data.get("format") or {}).get("duration") or 0) or None
                except (TypeError, ValueError, json.JSONDecodeError):
                    has_audio = False
                    has_video = False
                    media_duration = None
                if (require_video and not has_video) or (not require_video and not has_audio):
                    missing_requested_stream = True
                    raise RuntimeError("downloaded media does not contain the requested stream")
                if current_video.duration and media_duration:
                    allowed_shortfall = max(3.0, current_video.duration * 0.02)
                    if media_duration < current_video.duration - allowed_shortfall:
                        raise RuntimeError("downloaded media is shorter than the platform metadata")
                return final, {
                    "id": current_video.video_id,
                    "title": current_video.title,
                    "author": current_video.author,
                    "duration": current_video.duration,
                    "webpage_url": current_video.webpage_url,
                    "audio_download": "douyin_signed_api",
                    "media_bytes": downloaded,
                    "media_duration": media_duration,
                    "media_candidate_index": index,
                    "media_has_video": has_video,
                    "media_has_audio": has_audio,
                    "media_urls_refreshed": refreshed_urls,
                }
            except DouyinAdapterError as exc:
                partial.unlink(missing_ok=True)
                final.unlink(missing_ok=True)
                if exc.reason != "download_too_large":
                    raise
                last_error = exc
            except ManagedProcessTimeout as exc:
                last_error = exc
                partial.unlink(missing_ok=True)
                final.unlink(missing_ok=True)
            except Exception as exc:
                if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                    partial.unlink(missing_ok=True)
                    final.unlink(missing_ok=True)
                    raise DouyinAdapterError(507, "服务器下载目录剩余空间不足。", "disk_space_low") from exc
                last_error = exc
                partial.unlink(missing_ok=True)
                final.unlink(missing_ok=True)

        if isinstance(last_error, DouyinAdapterError) and last_error.reason == "download_too_large":
            raise last_error
        if refreshed_urls:
            break
        refreshed_urls = True
        try:
            current_video = get_douyin_video(video.webpage_url, force_refresh=True)
        except DouyinAdapterError as exc:
            last_error = exc
            break

    if missing_requested_stream:
        reason = "video_stream_missing" if require_video else "no_audio_stream"
        message = "下载的视频没有视频轨。" if require_video else "下载的视频没有音轨。"
        raise DouyinAdapterError(422, message, reason)
    LOGGER.warning("Douyin media download failed: %s", type(last_error).__name__ if last_error else "no URL")
    raise DouyinAdapterError(502, "抖音媒体下载失败，请稍后重试。", "download_failed")
