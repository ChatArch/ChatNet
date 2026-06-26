from click.testing import CliRunner

from chatnet.cli import _redact_url_token, main
from chatnet.link_check import ServiceCheckResult, check_service_url, collect_urls
from chatnet.portal import BrowserPortalClient, parse_tables, table_to_dicts
from chatnet.scanner import check_port, get_platform_ping_args
from chatnet.service_urls import append_token, ensure_path


def test_help_does_not_expose_ecnu_group():
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "generic network helper" in result.output
    assert "ecnu" not in result.output.lower()
    assert "links" in result.output
    assert "services" in result.output


def test_browser_portal_client_cookie_state(tmp_path):
    state_file = tmp_path / "state.json"
    client = BrowserPortalClient("https://example.invalid/base", state_file, cookie_header="a=1; b=2")

    assert client._url("/login") == "https://example.invalid/base/login"
    assert client.cookie_header() in {"a=1; b=2", "b=2; a=1"}
    client._save_state({"ok": True})
    assert state_file.exists()


def test_table_helpers_parse_simple_table():
    tables = parse_tables("<table><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></table>")

    assert table_to_dicts(tables[0]) == [{"A": "x", "B": "y"}]


def test_service_url_helpers():
    assert append_token("http://example.com/json/version", "abc") == "http://example.com/json/version?token=abc"
    assert append_token("http://example.com/json/version?token=abc", "zzz") == "http://example.com/json/version?token=abc"
    assert ensure_path("http://example.com", "/status") == "http://example.com/status"
    assert ensure_path("http://example.com/status", "/status") == "http://example.com/status"


def test_collect_urls_from_file(tmp_path):
    doc = tmp_path / "README.md"
    doc.write_text("See https://example.com and http://example.org.", encoding="utf-8")

    assert collect_urls(doc, ["*.md"]) == ["https://example.com", "http://example.org."]


def test_scanner_helpers_are_importable():
    assert get_platform_ping_args()
    host, open_ = check_port("127.0.0.1", 1, timeout=0.001)
    assert host == "127.0.0.1"
    assert isinstance(open_, bool)


def test_redact_url_token_masks_query_value():
    assert _redact_url_token("http://example.com/json/version?token=SECRET123&x=1") == "http://example.com/json/version?token=%2A%2A%2A&x=1"


def test_service_check_expected_matches_body_not_url(monkeypatch):
    monkeypatch.setattr("chatnet.link_check._request_text", lambda url, timeout, max_bytes: (200, "plain ok"))

    result = check_service_url("http://example.com/websocket", "websocket", timeout=1)

    assert result.ok is False
    assert result.matched is False


def test_services_cli_redacts_token_in_output(monkeypatch):
    def fake_check(url, expected, timeout):
        return ServiceCheckResult(url=url, expected=expected, ok=False, status=None, elapsed_ms=1, matched=False, error="boom")

    monkeypatch.setattr("chatnet.cli.check_service_url", fake_check)
    result = CliRunner().invoke(
        main,
        [
            "services",
            "--chromium-url",
            "http://example.com",
            "--chromium-token",
            "SECRET123",
            "--chromedriver-url",
            "http://example.com",
            "--playwright-url",
            "http://example.com",
        ],
    )

    assert result.exit_code == 2
    assert "SECRET123" not in result.output
    assert "token=" in result.output
