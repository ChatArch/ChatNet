"""Forward proxy validation helpers."""

from __future__ import annotations

import dataclasses
import time
import urllib.parse

import requests


@dataclasses.dataclass(frozen=True)
class ForwardProxyCheckResult:
    """Result from testing a target URL through an explicit proxy."""

    proxy_url: str
    target_url: str
    ok: bool
    status: int | None
    elapsed_ms: int
    error: str | None = None
    body_preview: str = ""


def build_proxy_url(proxy_url: str, username: str | None = None, password: str | None = None) -> str:
    """Return a proxy URL with optional credentials inserted."""

    if not username and password is None:
        return proxy_url
    if not username or password is None:
        raise ValueError("username and password must be provided together")
    parsed = urllib.parse.urlsplit(proxy_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("proxy_url must include scheme and host")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("proxy_url must include host")
    netloc = f"{urllib.parse.quote(username, safe='')}:{urllib.parse.quote(password, safe='')}@{host}"
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urllib.parse.urlunsplit(parsed._replace(netloc=netloc))


def redact_proxy_url(proxy_url: str) -> str:
    """Redact credentials from a proxy URL for logs and CLI output."""

    parsed = urllib.parse.urlsplit(proxy_url)
    if "@" not in parsed.netloc:
        return proxy_url
    host_part = parsed.netloc.rsplit("@", 1)[1]
    return urllib.parse.urlunsplit(parsed._replace(netloc=f"***@{host_part}"))


def check_forward_proxy(
    proxy_url: str,
    target_url: str = "https://www.gstatic.com/generate_204",
    *,
    username: str | None = None,
    password: str | None = None,
    timeout: float = 10.0,
    expected_status: int | None = None,
    max_body: int = 200,
) -> ForwardProxyCheckResult:
    """Fetch a target URL through a proxy and return a structured result."""

    started = time.monotonic()
    try:
        final_proxy_url = build_proxy_url(proxy_url, username=username, password=password)
        response = requests.get(
            target_url,
            proxies={"http": final_proxy_url, "https": final_proxy_url},
            timeout=timeout,
            allow_redirects=True,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        body_preview = response.text[:max_body] if max_body > 0 else ""
        ok = response.ok if expected_status is None else response.status_code == expected_status
        return ForwardProxyCheckResult(
            proxy_url=redact_proxy_url(final_proxy_url),
            target_url=target_url,
            ok=ok,
            status=response.status_code,
            elapsed_ms=elapsed_ms,
            body_preview=body_preview,
        )
    except Exception as exc:  # pragma: no cover - exact requests exceptions vary by platform
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return ForwardProxyCheckResult(
            proxy_url=redact_proxy_url(proxy_url),
            target_url=target_url,
            ok=False,
            status=None,
            elapsed_ms=elapsed_ms,
            error=str(exc),
        )
