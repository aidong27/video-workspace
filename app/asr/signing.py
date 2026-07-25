from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
from pathlib import Path
import secrets
from threading import Lock
import time
from urllib.parse import quote, urlparse


class SignedAudioError(ValueError):
    pass


@dataclass(frozen=True)
class SignedAudioRecord:
    token: str
    path: Path
    expires_at: int
    content_type: str


class SignedAudioStore:
    def __init__(
        self,
        *,
        root: Path,
        public_base_url: str,
        secret: str,
        default_ttl_seconds: int = 1800,
        clock: callable = time.time,
    ) -> None:
        self.root = root.resolve()
        self.public_base_url = public_base_url.strip().rstrip("/")
        parsed_base = urlparse(self.public_base_url)
        if (
            parsed_base.scheme != "https"
            or not parsed_base.hostname
            or parsed_base.username is not None
            or parsed_base.password is not None
            or parsed_base.query
            or parsed_base.fragment
            or parsed_base.path.rstrip("/")
        ):
            raise ValueError("PUBLIC_BASE_URL must be an HTTPS origin without a path")
        if len(secret.encode("utf-8")) < 32:
            raise ValueError("AUDIO_SIGNING_SECRET must contain at least 32 bytes")
        self.secret = secret.encode("utf-8")
        self.default_ttl_seconds = max(60, min(3600, int(default_ttl_seconds)))
        self.clock = clock
        self.lock = Lock()
        self.records: dict[str, SignedAudioRecord] = {}

    def _signature(self, token: str, expires_at: int) -> str:
        message = f"{token}.{expires_at}".encode("ascii")
        return hmac.new(self.secret, message, hashlib.sha256).hexdigest()

    def register(
        self,
        path: Path,
        *,
        content_type: str = "audio/mpeg",
        ttl_seconds: int | None = None,
    ) -> tuple[str, str]:
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise SignedAudioError("audio file is outside the configured temporary root") from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise SignedAudioError("audio file is not a regular file")
        token = secrets.token_hex(32)
        ttl = self.default_ttl_seconds if ttl_seconds is None else max(60, min(3600, int(ttl_seconds)))
        expires_at = int(self.clock()) + ttl
        record = SignedAudioRecord(token, resolved, expires_at, content_type)
        with self.lock:
            self._cleanup_locked()
            self.records[token] = record
        signature = self._signature(token, expires_at)
        url = (
            f"{self.public_base_url}/api/provider-audio/{quote(token)}"
            f"?expires={expires_at}&signature={signature}"
        )
        return token, url

    def resolve(self, token: str, expires_at: int, signature: str) -> SignedAudioRecord:
        if len(token) != 64 or any(character not in "0123456789abcdef" for character in token):
            raise SignedAudioError("invalid signed audio token")
        now = int(self.clock())
        if expires_at < now or expires_at > now + 3600:
            raise SignedAudioError("signed audio URL expired")
        expected = self._signature(token, expires_at)
        if not hmac.compare_digest(expected, signature):
            raise SignedAudioError("invalid signed audio signature")
        with self.lock:
            self._cleanup_locked()
            record = self.records.get(token)
        if record is None or record.expires_at != expires_at:
            raise SignedAudioError("signed audio URL is no longer active")
        try:
            resolved = record.path.resolve(strict=True)
            resolved.relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise SignedAudioError("signed audio file is unavailable") from exc
        if not resolved.is_file() or resolved.is_symlink():
            raise SignedAudioError("signed audio file is unavailable")
        return record

    def revoke(self, token: str) -> None:
        with self.lock:
            self.records.pop(token, None)

    def cleanup(self) -> int:
        with self.lock:
            return self._cleanup_locked()

    def _cleanup_locked(self) -> int:
        now = int(self.clock())
        expired = [token for token, record in self.records.items() if record.expires_at < now]
        for token in expired:
            self.records.pop(token, None)
        return len(expired)
