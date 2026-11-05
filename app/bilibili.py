"""Bilibili link parsing, WBI request signing, and platform-block tracking.

The network calls themselves stay in ``app.main`` (they share its HTTP
headers, cookie policy and SSRF guard). This module holds the pure pieces:

* parsing BV/av links, page numbers and trusted redirect hosts;
* WBI signing with a short-lived cache of the public mixin key, so a task
  does not fetch ``/x/web-interface/nav`` before every signed request;
* a cooldown guard. When Bilibili refuses the server outright (HTTP 412 or a
  risk-control API code) further requests during the cooldown are answered
  locally with the same clear error instead of repeating refused requests.
"""

from __future__ import annotations

import hashlib
from threading import Lock
import time
from typing import Any, Callable
import urllib.parse
import re

from .errors import ExtractionFailure

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]
BILI_URL_RE = re.compile(
    r"(https?://(?:www\.)?(?:bilibili\.com|b23\.tv)[^\s<>'\"]+|"
    r"(?:www\.)?(?:bilibili\.com|b23\.tv)/[^\s<>'\"]+)",
    re.IGNORECASE,
)
BVID_RE = re.compile(r"(BV[0-9A-Za-z]{8,})")
AID_PATH_RE = re.compile(r"/video/av(\d{1,19})(?=[/?#]|$)", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？、)]}）】》"

# Bilibili answers refused anonymous/server requests with HTTP 412, or with
# HTTP 200 and one of these API codes. Both mean "blocked", not "not found".
RISK_CONTROL_HTTP_STATUSES = frozenset({412})
RISK_CONTROL_API_CODES = frozenset({-352, -412})


def extract_bvid(value: str) -> str | None:
    match = BVID_RE.search(value)
    return match.group(1) if match else None


def extract_aid(value: str) -> int | None:
    match = AID_PATH_RE.search(urllib.parse.urlparse(value).path or "")
    if not match:
        return None
    aid = int(match.group(1))
    return aid if aid > 0 else None


def extract_bili_url(value: str) -> str | None:
    match = BILI_URL_RE.search(value)
    if not match:
        return None
    url = match.group(1).rstrip(TRAILING_URL_PUNCTUATION)
    if not re.match(r"https?://", url, flags=re.IGNORECASE):
        url = f"https://{url}"
    return url


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


def bili_redirect_host_allowed(host: str | None) -> bool:
    value = (host or "").lower().rstrip(".")
    return any(value == root or value.endswith(f".{root}") for root in ("b23.tv", "bilibili.com"))


def mixin_key_from_nav(payload: Any) -> str | None:
    """Derive the WBI mixin key from a ``/x/web-interface/nav`` response."""
    data = payload.get("data") if isinstance(payload, dict) else None
    wbi_img = (data.get("wbi_img") or {}) if isinstance(data, dict) else {}
    if not isinstance(wbi_img, dict):
        return None
    img_key = str(wbi_img.get("img_url") or "").rsplit("/", 1)[-1].split(".")[0]
    sub_key = str(wbi_img.get("sub_url") or "").rsplit("/", 1)[-1].split(".")[0]
    raw = img_key + sub_key
    if len(raw) < 64:
        return None
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def wbi_sign(params: dict[str, Any], mixin_key: str, now: float | None = None) -> dict[str, str]:
    signed = {
        key: "".join(ch for ch in str(value) if ch not in "!'()*")
        for key, value in params.items()
        if value is not None and value != ""
    }
    signed["wts"] = str(int(time.time() if now is None else now))
    query = urllib.parse.urlencode(sorted(signed.items()))
    signed["w_rid"] = hashlib.md5(
        (query + mixin_key).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    return dict(sorted(signed.items()))


class WbiKeyCache:
    """Caches the public WBI mixin key; Bilibili rotates it about daily."""

    def __init__(self, ttl_seconds: float = 1800, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._lock = Lock()
        self._key: str | None = None
        self._expires_at = 0.0

    def get(self, fetch: Callable[[], str | None]) -> str | None:
        with self._lock:
            if self._key and self._clock() < self._expires_at:
                return self._key
        key = fetch()
        if key:
            with self._lock:
                self._key = key
                self._expires_at = self._clock() + self._ttl
        return key

    def invalidate(self) -> None:
        with self._lock:
            self._key = None
            self._expires_at = 0.0


class PlatformAccessGuard:
    """Remembers that Bilibili refused this server, per cookie mode.

    ``check`` raises the stored refusal while the cooldown lasts, so users get
    an immediate answer and the server stops repeating refused requests. After
    the cooldown the next request is allowed through as a probe; a successful
    response clears the state.
    """

    def __init__(self, cooldown_seconds: float = 300, clock: Callable[[], float] = time.time) -> None:
        self._cooldown = max(0.0, float(cooldown_seconds))
        self._clock = clock
        self._lock = Lock()
        self._blocked_until: dict[str, float] = {}

    @staticmethod
    def _mode(with_cookie: bool) -> str:
        return "cookie" if with_cookie else "anonymous"

    def record_block(self, with_cookie: bool) -> None:
        if self._cooldown <= 0:
            return
        with self._lock:
            self._blocked_until[self._mode(with_cookie)] = self._clock() + self._cooldown

    def record_success(self, with_cookie: bool) -> None:
        with self._lock:
            self._blocked_until.pop(self._mode(with_cookie), None)

    def blocked_until(self, with_cookie: bool) -> float | None:
        with self._lock:
            until = self._blocked_until.get(self._mode(with_cookie))
            if until is None:
                return None
            if until <= self._clock():
                self._blocked_until.pop(self._mode(with_cookie), None)
                return None
            return until

    def check(self, with_cookie: bool) -> None:
        if self.blocked_until(with_cookie) is not None:
            raise platform_block_failure(cached=True)

    def reset(self) -> None:
        with self._lock:
            self._blocked_until.clear()


def platform_block_failure(*, cached: bool = False) -> ExtractionFailure:
    detail = (
        "Bilibili refused requests from this server recently; waiting for the cooldown."
        if cached
        else "Bilibili refused the request (HTTP 412 / risk control)."
    )
    return ExtractionFailure(
        503,
        detail,
        "platform_risk_control",
        can_try_asr=False,
        terminal=True,
        retryable=False,
    )
