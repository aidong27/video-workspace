from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse


class UnsafeRemoteUrl(ValueError):
    pass


def _public_address(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_global
    except ValueError:
        return False


def ensure_public_host(host: str) -> None:
    normalized = host.lower().rstrip(".")
    try:
        literal = ipaddress.ip_address(normalized)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise UnsafeRemoteUrl("remote URL resolves to a non-public address")
        return
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(normalized, None, type=socket.SOCK_STREAM)
            if item[4]
        }
    except socket.gaierror as exc:
        raise UnsafeRemoteUrl("remote URL host could not be resolved") from exc
    if not addresses or any(not _public_address(address) for address in addresses):
        raise UnsafeRemoteUrl("remote URL resolves to a non-public address")


def ensure_public_http_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeRemoteUrl("remote URL must use HTTP or HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeRemoteUrl("remote URL must not contain credentials")
    ensure_public_host(parsed.hostname)


def validate_public_request(request: Any) -> None:
    ensure_public_http_url(str(request.url))
