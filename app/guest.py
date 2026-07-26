from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import base64
import hashlib
import hmac
import secrets
import struct
from threading import Lock
import time

from fastapi import Response


GUEST_COOKIE_NAME = "caption_guest"
_TOKEN_VERSION = 1
_PAYLOAD_SIZE = 1 + 8 + 16


@dataclass(frozen=True)
class GuestIdentity:
    owner_id: int
    expires_at: int


class GuestSessionCodec:
    def __init__(self, secret: str, ttl_seconds: int) -> None:
        self._secret = secret.encode("utf-8")
        self.ttl_seconds = max(300, int(ttl_seconds))
        self.enabled = len(self._secret) >= 32

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(value + padding)

    def _signature(self, payload: bytes) -> bytes:
        return hmac.new(self._secret, b"guest-session:" + payload, hashlib.sha256).digest()

    def _identity(self, payload: bytes, issued_at: int) -> GuestIdentity:
        digest = hmac.new(self._secret, b"guest-owner:" + payload, hashlib.sha256).digest()
        owner_value = int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
        return GuestIdentity(
            owner_id=-(owner_value or 1),
            expires_at=issued_at + self.ttl_seconds,
        )

    def issue(self, now: int | None = None) -> tuple[str, GuestIdentity]:
        if not self.enabled:
            raise RuntimeError("guest media secret is not configured")
        issued_at = int(time.time()) if now is None else int(now)
        payload = bytes([_TOKEN_VERSION]) + struct.pack(">Q", issued_at) + secrets.token_bytes(16)
        token = f"{self._encode(payload)}.{self._encode(self._signature(payload))}"
        return token, self._identity(payload, issued_at)

    def resolve(self, token: str | None, now: int | None = None) -> GuestIdentity | None:
        if not self.enabled or not token:
            return None
        try:
            payload_value, signature_value = token.split(".", 1)
            payload = self._decode(payload_value)
            signature = self._decode(signature_value)
        except (ValueError, TypeError):
            return None
        if len(payload) != _PAYLOAD_SIZE or len(signature) != hashlib.sha256().digest_size:
            return None
        if payload[0] != _TOKEN_VERSION or not hmac.compare_digest(
            signature,
            self._signature(payload),
        ):
            return None
        issued_at = struct.unpack(">Q", payload[1:9])[0]
        current = int(time.time()) if now is None else int(now)
        if issued_at > current + 300 or current >= issued_at + self.ttl_seconds:
            return None
        return self._identity(payload, issued_at)


@dataclass(frozen=True)
class GuestRateLimit:
    reason: str
    retry_after_seconds: int


class GuestMediaRateLimiter:
    def __init__(
        self,
        *,
        session_limit: int,
        global_limit: int,
        window_seconds: int = 3600,
    ) -> None:
        self.session_limit = max(1, int(session_limit))
        self.global_limit = max(self.session_limit, int(global_limit))
        self.window_seconds = max(60, int(window_seconds))
        self._lock = Lock()
        self._global_events: deque[float] = deque()
        self._session_events: dict[int, deque[float]] = defaultdict(deque)
        self._cleanup_counter = 0

    @staticmethod
    def _prune(events: deque[float], cutoff: float) -> None:
        while events and events[0] <= cutoff:
            events.popleft()

    def consume(self, owner_id: int, now: float | None = None) -> GuestRateLimit | None:
        current = time.time() if now is None else float(now)
        cutoff = current - self.window_seconds
        with self._lock:
            self._prune(self._global_events, cutoff)
            self._cleanup_counter += 1
            if self._cleanup_counter >= 64:
                self._cleanup_counter = 0
                for session_owner, events in list(self._session_events.items()):
                    self._prune(events, cutoff)
                    if not events:
                        self._session_events.pop(session_owner, None)
            session_events = self._session_events[owner_id]
            self._prune(session_events, cutoff)
            if len(self._global_events) >= self.global_limit:
                retry_after = max(1, int(self._global_events[0] + self.window_seconds - current))
                return GuestRateLimit("guest_media_global_limit", retry_after)
            if len(session_events) >= self.session_limit:
                retry_after = max(1, int(session_events[0] + self.window_seconds - current))
                return GuestRateLimit("guest_media_session_limit", retry_after)
            self._global_events.append(current)
            session_events.append(current)
        return None

    def refund(self, owner_id: int) -> None:
        with self._lock:
            session_events = self._session_events.get(owner_id)
            if not session_events:
                return
            event = session_events.pop()
            if not session_events:
                self._session_events.pop(owner_id, None)
            try:
                self._global_events.remove(event)
            except ValueError:
                pass

    def reset(self) -> None:
        with self._lock:
            self._global_events.clear()
            self._session_events.clear()
            self._cleanup_counter = 0


def set_guest_cookie(
    response: Response,
    token: str,
    expires_at: int,
    *,
    secure: bool = True,
) -> None:
    max_age = max(1, int(expires_at) - int(time.time()))
    response.set_cookie(
        key=GUEST_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
