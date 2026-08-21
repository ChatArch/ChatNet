from click.testing import CliRunner
from chatstyle import render_click_tree

from chatnet import __version__
from chatnet.cli import _redact_url_token, main
from chatnet.config import ChatNetProxyConfig, load_chatnet_proxy_config
from chatnet.forward_proxy import expected_basic_auth, is_client_allowed, parse_cidrs, proxy_auth_valid
from chatnet.forward_proxy_check import build_proxy_url, redact_proxy_url
from chatnet.forward_proxy_service import ForwardProxyServiceConfig, render_systemd_user_unit
from chatnet.link_check import ServiceCheckResult, check_service_url, collect_urls
from chatnet.portal import BrowserPortalClient, parse_tables, table_to_dicts
from chatnet.scanner import check_port, get_platform_ping_args
from chatnet.service_urls import append_token, ensure_path


def test_help_does_not_expose_ecnu_group():
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "generic network helper" in result.output
    assert "--tree" in result.output
    assert "--tree-brief" in result.output
    assert "ecnu" not in result.output.lower()
    assert "links" in result.output
    assert "services" in result.output
    assert "proxy" in result.output


def test_version_option_reports_package_version():
    result = CliRunner().invoke(main, ["--version"])

    assert result.exit_code == 0
    assert result.output == f"chatnet, version {__version__}\n"


def test_tree_option_renders_registered_command_surface_with_signatures():
    result = CliRunner().invoke(main, ["--tree"])

    assert result.exit_code == 0, result.output
    assert result.output == render_click_tree(main, root_name="chatnet") + "\n"
    assert result.output.splitlines().count("chatnet") == 1
    assert "├── --tree-brief" in result.output
    assert "ping [--network NETWORK]" in result.output
    assert "ssh [--input INPUT-FILE]" in result.output
    assert "proxy  # Run explicit proxy helpers; credentials stay masked." in result.output
    assert "install [--service-name SERVICE-NAME]" in result.output
    assert "long-running listener with no secret output" in result.output
    assert "hello" not in result.output.lower()
    assert "ecnu" not in result.output.lower()


def test_tree_brief_keeps_nodes_and_descriptions_but_omits_signatures():
    result = CliRunner().invoke(main, ["--tree-brief"])

    assert result.exit_code == 0, result.output
    assert result.output == render_click_tree(main, root_name="chatnet", brief=True) + "\n"
    assert result.output.splitlines().count("chatnet") == 1
    assert "├── --tree-brief" in result.output
    assert "├── ping  # Scan hosts with ICMP" in result.output
    assert "│   └── serve  # Serve a forward proxy" in result.output
    assert "NETWORK" not in result.output
    assert "--password" not in result.output
    assert "hello" not in result.output.lower()
    assert "ecnu" not in result.output.lower()


def test_proxy_serve_help_documents_non_sudo_options():
    result = CliRunner().invoke(main, ["proxy", "serve", "--help"])

    assert result.exit_code == 0
    assert "forward proxy" in result.output
    assert "--bind" in result.output
    assert "--allow-cidr" in result.output
    assert "--user" in result.output
    assert "CHATNET_PROXY_PASSWORD" in result.output


def test_forward_proxy_auth_and_allowlist_helpers():
    networks = parse_cidrs("127.0.0.0/8,172.23.0.0/16")
    header = expected_basic_auth("user", "pass")

    assert is_client_allowed("172.23.148.39", networks)
    assert not is_client_allowed("10.0.0.5", networks)
    assert proxy_auth_valid(header, "user", "pass")
    assert not proxy_auth_valid(header, "user", "wrong")
    assert proxy_auth_valid(None, None, None)


def test_forward_proxy_check_helpers_redact_credentials():
    proxy_url = build_proxy_url("http://proxy.local:18080", "user", "pass")

    assert proxy_url == "http://user:pass@proxy.local:18080"
    assert redact_proxy_url(proxy_url) == "http://***@proxy.local:18080"


def test_proxy_autostart_print_renders_user_systemd_unit():
    unit = render_systemd_user_unit(
        ForwardProxyServiceConfig(
            bind="0.0.0.0",
            port=18080,
            allow_cidr="172.23.0.0/16",
            username="chatnet",
            python="/usr/bin/python3",
        )
    )

    assert "ExecStart=/usr/bin/python3 -m chatnet.cli proxy serve" in unit
    assert "--bind 0.0.0.0" in unit
    assert "--allow-cidr 172.23.0.0/16" in unit
    assert "--user chatnet" in unit
    assert "EnvironmentFile=-%h/.config/chatnet/proxy.env" in unit
    assert "CHATNET_PROXY_PASSWORD" not in unit


def test_proxy_check_help_and_autostart_help():
    check_result = CliRunner().invoke(main, ["proxy", "check", "--help"])
    autostart_result = CliRunner().invoke(main, ["proxy", "autostart", "--help"])

    assert check_result.exit_code == 0
    assert "--proxy-url" in check_result.output
    assert "CHATNET_PROXY_PASSWORD" in check_result.output
    assert "--interactive" in check_result.output
    assert autostart_result.exit_code == 0
    assert "print" in autostart_result.output
    assert "install" in autostart_result.output


def test_chatnet_proxy_config_loads_from_chatenv(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "arch"))
    monkeypatch.delenv("CHATNET_PROXY_BIND", raising=False)
    env_file = tmp_path / "arch" / "envs" / "ChatNet" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        "CHATNET_PROXY_BIND='0.0.0.0'\n"
        "CHATNET_PROXY_PORT='18081'\n"
        "CHATNET_PROXY_ALLOW_CIDR='172.23.0.0/16'\n"
        "CHATNET_PROXY_USER='chatnet'\n"
        "CHATNET_PROXY_PASSWORD='placeholder-password'\n",
        encoding="utf-8",
    )

    config = load_chatnet_proxy_config()

    assert config is ChatNetProxyConfig
    assert config.CHATNET_PROXY_BIND.value == "0.0.0.0"
    assert config.CHATNET_PROXY_PORT.value == "18081"
    assert config.CHATNET_PROXY_ALLOW_CIDR.value == "172.23.0.0/16"
    assert config.CHATNET_PROXY_PASSWORD.is_sensitive is True


def test_proxy_autostart_uses_chatenv_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path / "arch"))
    env_file = tmp_path / "arch" / "envs" / "ChatNet" / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(
        "CHATNET_PROXY_BIND='0.0.0.0'\n"
        "CHATNET_PROXY_PORT='18081'\n"
        "CHATNET_PROXY_ALLOW_CIDR='172.23.0.0/16'\n"
        "CHATNET_PROXY_USER='chatnet'\n",
        encoding="utf-8",
    )

    result = CliRunner().invoke(main, ["proxy", "autostart", "print", "-I"])

    assert result.exit_code == 0, result.output
    assert "--bind 0.0.0.0" in result.output
    assert "--port 18081" in result.output
    assert "--allow-cidr 172.23.0.0/16" in result.output
    assert "--user chatnet" in result.output
    assert "placeholder-password" not in result.output


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
