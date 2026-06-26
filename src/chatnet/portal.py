"""Reusable HTTP/session/html helpers for ChatArch network packages."""

from __future__ import annotations

import json
import re
import shlex
from html import unescape
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class BrowserPortalClient:
    """Small stateful browser-like client for portal automation.

    This is intentionally domain-neutral: it owns base URL resolution, cookie/state
    persistence, browser-like headers, and simple GET/POST wrappers. Site-specific
    packages such as ChatECNU own login flows, field names, and parsing semantics.
    """

    def __init__(
        self,
        base_url: str,
        state_file: Path,
        cookie_header: str | None = None,
        timeout: int = 20,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.state_file = state_file
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(headers or BROWSER_HEADERS)
        self.state = load_json(self.state_file)
        state_cookies = self.state.get("cookies") or {}
        if state_cookies:
            requests.utils.add_dict_to_cookiejar(self.session.cookies, state_cookies)
        if cookie_header:
            requests.utils.add_dict_to_cookiejar(self.session.cookies, parse_cookie_header(cookie_header))

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    def _save_state(self, extra: dict[str, Any] | None = None) -> None:
        payload = dict(self.state)
        payload["base_url"] = self.base_url
        payload["cookies"] = requests.utils.dict_from_cookiejar(self.session.cookies)
        if extra:
            payload.update(extra)
        save_json(self.state_file, payload)
        self.state = payload

    def cookie_header(self) -> str:
        cookies = requests.utils.dict_from_cookiejar(self.session.cookies)
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    def get(self, path: str, **kwargs: Any) -> requests.Response:
        resp = self.session.get(self._url(path), timeout=self.timeout, allow_redirects=True, **kwargs)
        self._save_state()
        return resp

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        resp = self.session.post(self._url(path), timeout=self.timeout, allow_redirects=True, **kwargs)
        self._save_state()
        return resp

    def authenticated_response(self, resp: requests.Response, login_path: str) -> requests.Response:
        resp.raise_for_status()
        if urlparse(resp.url).path == login_path:
            raise RuntimeError("Not authenticated: request was redirected to the login page.")
        return resp


class SimpleTableParser(HTMLParser):
    """Minimal table parser for portal pages with simple th/td rows."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[dict[str, Any]]]] = []
        self._current_table: list[list[dict[str, Any]]] | None = None
        self._current_row: list[dict[str, Any]] | None = None
        self._current_cell: list[str] | None = None
        self._current_cell_is_header = False
        self._cell_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._current_cell_is_header = tag == "th"
            self._cell_depth = 1
        elif self._current_cell is not None:
            self._cell_depth += 1
            if tag == "br":
                self._current_cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None
        elif tag == "tr" and self._current_table is not None and self._current_row is not None:
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            text = clean_text("".join(self._current_cell))
            self._current_row.append({"text": text, "is_header": self._current_cell_is_header})
            self._current_cell = None
            self._current_cell_is_header = False
            self._cell_depth = 0
        elif self._current_cell is not None and self._cell_depth > 0:
            self._cell_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text or "")).strip()


def strip_tags(fragment: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", fragment, flags=re.S))


def require_value(value: str | None, message: str) -> str:
    if not value:
        raise RuntimeError(message)
    return value


def extract_meta_content(html: str, meta_name: str) -> str | None:
    match = re.search(rf'<meta[^>]+name=["\']{re.escape(meta_name)}["\'][^>]+content=["\']([^"\']+)["\']', html, re.I)
    return match.group(1) if match else None


def parse_cookie_header(cookie_header: str) -> dict[str, str]:
    cookie = SimpleCookie()
    cookie.load(cookie_header)
    return {key: morsel.value for key, morsel in cookie.items()}


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_tables(html: str) -> list[dict[str, Any]]:
    parser = SimpleTableParser()
    parser.feed(html)
    results: list[dict[str, Any]] = []
    for raw_table in parser.tables:
        headers: list[str] = []
        rows: list[list[str]] = []
        if raw_table:
            first = raw_table[0]
            if first and all(cell["is_header"] for cell in first):
                headers = [cell["text"] for cell in first]
                body_rows = raw_table[1:]
            else:
                body_rows = raw_table
            rows = [[cell["text"] for cell in row] for row in body_rows]
        results.append({"headers": headers, "rows": rows})
    return results


def table_to_dicts(table: dict[str, Any]) -> list[dict[str, str]]:
    headers = table.get("headers") or []
    rows = table.get("rows") or []
    if not headers:
        return [{str(i): value for i, value in enumerate(row)} for row in rows]
    return [{headers[i]: (row + [""] * max(0, len(headers) - len(row)))[i] for i in range(len(headers))} for row in rows]


def parse_detail_view_table(table: dict[str, Any]) -> dict[str, str]:
    return {row[0]: row[1] for row in table.get("rows") or [] if len(row) >= 2}


def first_multirow_table(tables: list[dict[str, Any]]) -> dict[str, Any] | None:
    for table in tables:
        if table.get("headers") and table.get("rows"):
            return table
    return None


def find_table_with_headers(tables: list[dict[str, Any]], expected: list[str]) -> dict[str, Any] | None:
    for table in tables:
        headers = table.get("headers") or []
        if len(headers) >= len(expected) and headers[: len(expected)] == expected:
            return table
    return None


def extract_summary_text(html: str) -> str | None:
    match = re.search(r'<div class="summary">(.*?)</div>', html, re.S | re.I)
    return strip_tags(match.group(1)) if match else None


def request_spec(method: str, url: str, headers: dict[str, str], data: dict[str, str] | None = None) -> dict[str, Any]:
    return {"method": method, "url": url, "headers": headers, "data": data or {}}


def curl_string(method: str, url: str, headers: dict[str, str], data: dict[str, str] | None = None) -> str:
    parts = ["curl", "-X", shlex.quote(method)]
    for key, value in headers.items():
        parts.extend(["-H", shlex.quote(f"{key}: {value}")])
    if data:
        encoded = "&".join(f"{quote(str(k), safe='[]')}={quote(str(v))}" for k, v in data.items())
        parts.extend(["--data", shlex.quote(encoded)])
    parts.append(shlex.quote(url))
    return " ".join(parts)
