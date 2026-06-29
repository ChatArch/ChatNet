"""Explicit HTTP/HTTPS forward proxy helpers.

The proxy is designed for user-mode, high-port LAN use. It supports regular
HTTP proxy requests and HTTPS CONNECT tunnels without requiring sudo.
"""

from __future__ import annotations

import base64
import dataclasses
import hmac
import ipaddress
import select
import socket
import socketserver
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from typing import Iterable, TextIO

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "proxy-connection",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


@dataclasses.dataclass(frozen=True)
class ForwardProxyConfig:
    """Configuration for the explicit forward proxy server."""

    bind: str = "127.0.0.1"
    port: int = 18080
    allow_cidrs: tuple[str, ...] = ("127.0.0.0/8",)
    username: str | None = None
    password: str | None = None
    timeout: float = 30.0


def parse_cidrs(raw: str | Iterable[str]) -> list[ipaddress._BaseNetwork]:
    """Parse comma-separated or iterable CIDR values."""

    if isinstance(raw, str):
        items = raw.split(",")
    else:
        items = raw
    networks: list[ipaddress._BaseNetwork] = []
    for item in items:
        value = item.strip()
        if value:
            networks.append(ipaddress.ip_network(value, strict=False))
    return networks


def is_client_allowed(client_ip: str, allow_cidrs: Iterable[ipaddress._BaseNetwork]) -> bool:
    """Return whether a client IP is covered by the configured allowlist."""

    ip = ipaddress.ip_address(client_ip)
    return any(ip in network for network in allow_cidrs)


def expected_basic_auth(username: str, password: str) -> str:
    """Build the expected Proxy-Authorization header value."""

    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def proxy_auth_valid(header_value: str | None, username: str | None, password: str | None) -> bool:
    """Validate a Proxy-Authorization header against optional credentials."""

    if not username and not password:
        return True
    if not username or password is None or not header_value:
        return False
    return hmac.compare_digest(header_value.strip(), expected_basic_auth(username, password))


class ThreadingForwardProxyServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    """Threaded TCP server carrying parsed proxy config."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], config: ForwardProxyConfig, log_file: TextIO | None = None):
        self.config = config
        self.allow_networks = parse_cidrs(config.allow_cidrs)
        self.log_file = log_file or sys.stderr
        super().__init__(server_address, ForwardProxyHandler)


class ForwardProxyHandler(BaseHTTPRequestHandler):
    """Handle HTTP proxy requests and HTTPS CONNECT tunnels."""

    protocol_version = "HTTP/1.1"

    @property
    def proxy_server(self) -> ThreadingForwardProxyServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: object) -> None:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.proxy_server.log_file.write(f"{ts} {self.client_address[0]} {format % args}\n")
        self.proxy_server.log_file.flush()

    def _reject_if_not_allowed(self) -> bool:
        if is_client_allowed(self.client_address[0], self.proxy_server.allow_networks):
            return False
        self.send_error(403, "client IP is not allowed")
        return True

    def _reject_if_not_authenticated(self) -> bool:
        config = self.proxy_server.config
        if proxy_auth_valid(self.headers.get("Proxy-Authorization"), config.username, config.password):
            return False
        self.send_response(407, "Proxy Authentication Required")
        self.send_header("Proxy-Authenticate", 'Basic realm="chatnet-forward-proxy"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def _preflight_rejected(self) -> bool:
        return self._reject_if_not_allowed() or self._reject_if_not_authenticated()

    def do_CONNECT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self._preflight_rejected():
            return
        host, port = self._parse_connect_target(self.path)
        if not host:
            self.send_error(400, "invalid CONNECT target")
            return
        try:
            upstream = socket.create_connection((host, port), timeout=self.proxy_server.config.timeout)
        except OSError as exc:
            self.send_error(502, f"upstream connect failed: {exc}")
            return

        self.send_response(200, "Connection established")
        self.end_headers()
        self.log_message("CONNECT %s:%s", host, port)
        try:
            self._tunnel(self.connection, upstream)
        finally:
            upstream.close()

    def do_GET(self) -> None:  # noqa: N802
        self._proxy_http_request()

    def do_HEAD(self) -> None:  # noqa: N802
        self._proxy_http_request()

    def do_POST(self) -> None:  # noqa: N802
        self._proxy_http_request()

    def do_PUT(self) -> None:  # noqa: N802
        self._proxy_http_request()

    def do_PATCH(self) -> None:  # noqa: N802
        self._proxy_http_request()

    def do_DELETE(self) -> None:  # noqa: N802
        self._proxy_http_request()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._proxy_http_request()

    def _parse_connect_target(self, target: str) -> tuple[str | None, int]:
        if ":" not in target:
            return None, 443
        host, port_text = target.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            return None, 443
        return host.strip("[]"), port

    def _proxy_http_request(self) -> None:
        if self._preflight_rejected():
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.scheme not in {"http", ""}:
            self.send_error(400, "only http:// proxy requests or CONNECT are supported")
            return

        host = parsed.hostname or self.headers.get("Host", "").split(":", 1)[0]
        if not host:
            self.send_error(400, "missing target host")
            return
        port = parsed.port or 80
        path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))

        try:
            upstream = socket.create_connection((host, port), timeout=self.proxy_server.config.timeout)
        except OSError as exc:
            self.send_error(502, f"upstream connect failed: {exc}")
            return

        try:
            upstream.settimeout(self.proxy_server.config.timeout)
            self._send_http_upstream(upstream, host, port, path)
            self.log_message("%s http://%s:%s%s", self.command, host, port, path)
            self._pipe_response(upstream)
        except OSError as exc:
            self.send_error(502, f"upstream IO failed: {exc}")
        finally:
            upstream.close()

    def _send_http_upstream(self, upstream: socket.socket, host: str, port: int, path: str) -> None:
        upstream.sendall(f"{self.command} {path} HTTP/1.1\r\n".encode("ascii"))
        sent_host = False
        for key, value in self.headers.items():
            if key.lower() in HOP_BY_HOP_HEADERS:
                continue
            if key.lower() == "host":
                sent_host = True
            upstream.sendall(f"{key}: {value}\r\n".encode("latin-1", errors="replace"))
        if not sent_host:
            host_value = host if port == 80 else f"{host}:{port}"
            upstream.sendall(f"Host: {host_value}\r\n".encode("ascii"))
        upstream.sendall(b"Connection: close\r\n\r\n")

        length = self.headers.get("Content-Length")
        if length:
            remaining = int(length)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                upstream.sendall(chunk)

    def _pipe_response(self, upstream: socket.socket) -> None:
        while True:
            data = upstream.recv(65536)
            if not data:
                break
            self.connection.sendall(data)

    def _tunnel(self, client: socket.socket, upstream: socket.socket) -> None:
        sockets = [client, upstream]
        for sock in sockets:
            sock.setblocking(False)
        while True:
            readable, _, errored = select.select(sockets, [], sockets, self.proxy_server.config.timeout)
            if errored or not readable:
                return
            for src in readable:
                dst = upstream if src is client else client
                try:
                    data = src.recv(65536)
                    if not data:
                        return
                    dst.sendall(data)
                except OSError:
                    return


def make_forward_proxy_server(config: ForwardProxyConfig, log_file: TextIO | None = None) -> ThreadingForwardProxyServer:
    """Create a forward proxy server instance without starting its loop."""

    return ThreadingForwardProxyServer((config.bind, config.port), config, log_file=log_file)


def serve_forward_proxy(config: ForwardProxyConfig, log_file: TextIO | None = None) -> None:
    """Run the forward proxy until interrupted."""

    with make_forward_proxy_server(config, log_file=log_file) as server:
        server.serve_forever()
