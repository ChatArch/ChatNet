"""CLI entrypoint for ChatNet generic network helpers."""

from __future__ import annotations

import ipaddress
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import click
from chatstyle import CommandConstraint, CommandField, CommandSchema, add_interactive_option, resolve_command_inputs

from chatnet import __version__
from chatnet.link_check import check_service_url, check_urls, collect_urls
from chatnet.scanner import ping_scan, port_scan
from chatnet.service_urls import append_token, ensure_path


@click.group(name="chatnet")
@click.version_option(__version__, prog_name="chatnet")
def main() -> None:
    """ChatNet generic network helper CLI."""


@main.command()
@click.option("-net", "--network", required=True, help="Network segment to scan (e.g. 192.168.1.0/24).")
@click.option("-n", "--concurrency", default=50, show_default=True, help="Number of concurrent threads.")
@click.option("-o", "--output", default=None, help="Output file path.")
def ping(network: str, concurrency: int, output: str | None) -> None:
    """Scan a network for active hosts using ICMP ping."""

    try:
        active_hosts = ping_scan(network_segment=network, concurrency=concurrency, output_path=output)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    for host in active_hosts:
        click.echo(f"Active: {host}")
    click.echo(f"Total active: {len(active_hosts)}")
    if output:
        click.echo(f"Results saved to {output}")


@main.command()
@click.option("-i", "--input", "input_file", required=False, help="Input file containing list of IPs.")
@click.option("-net", "--network", required=False, help="Network segment to scan (e.g. 192.168.1.0/24).")
@click.option("-p", "--port", default=22, show_default=True, help="Port to scan.")
@click.option("-n", "--concurrency", default=50, show_default=True, help="Number of concurrent threads.")
@click.option("-o", "--output", default=None, help="Output file path.")
def ssh(input_file: str | None, network: str | None, port: int, concurrency: int, output: str | None) -> None:
    """Scan IPs for open SSH or arbitrary TCP ports."""

    ip_list: list[str]
    if input_file:
        path = Path(input_file)
        if not path.exists():
            raise click.ClickException(f"Input file '{input_file}' not found.")
        ip_list = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif network:
        try:
            net = ipaddress.ip_network(network, strict=False)
        except ValueError as exc:
            raise click.ClickException(f"Error parsing network: {exc}") from exc
        ip_list = [str(ip) for ip in net.hosts()]
    else:
        raise click.ClickException("Either --input or --network must be provided.")

    open_hosts = port_scan(ip_list=ip_list, port=port, concurrency=concurrency, output_path=output)
    for host in open_hosts:
        click.echo(f"Open: {host}:{port}")
    click.echo(f"Total open: {len(open_hosts)}")
    if output:
        click.echo(f"Results saved to {output}")


@main.command(name="links")
@click.option(
    "--path",
    "path_value",
    default=".",
    type=click.Path(exists=True, file_okay=True, dir_okay=True, path_type=Path),
    show_default=True,
    help="File or directory to scan for URLs.",
)
@click.option("--glob", "globs", multiple=True, default=["*.md", "*.txt"], show_default=True, help="File glob patterns.")
@click.option("--url", "urls", multiple=True, help="Explicit URL(s) to check. If provided, scanning is skipped.")
@click.option("--filter", "filter_regex", default=None, help="Optional regex to filter URLs.")
@click.option("--timeout", default=6.0, show_default=True, help="Request timeout in seconds.")
def links(path_value: Path, globs: tuple[str, ...], urls: tuple[str, ...], filter_regex: str | None, timeout: float) -> None:
    """Check URL validity from a file/directory or explicit list."""

    target_urls = list(urls) if urls else collect_urls(path_value, globs)
    if filter_regex:
        pattern = re.compile(filter_regex)
        target_urls = [url for url in target_urls if pattern.search(url)]
    if not target_urls:
        click.echo("No URLs found.")
        return

    results = check_urls(target_urls, timeout=timeout)
    failed = 0
    for result in results:
        status = result.status if result.status is not None else "ERR"
        line = f"[{status}] {result.url} ({result.elapsed_ms}ms)"
        if result.ok:
            click.secho(line, fg="green")
        else:
            failed += 1
            if result.error:
                line = f"{line} - {result.error}"
            click.secho(line, fg="red")
    click.echo(f"Total: {len(results)}, OK: {len(results) - failed}, Failed: {failed}")
    if failed:
        raise SystemExit(2)


def _redact_url_token(url: str) -> str:
    parsed = urlparse(url)
    pairs = []
    changed = False
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() == "token":
            pairs.append((key, "***"))
            changed = True
        else:
            pairs.append((key, value))
    if not changed:
        return url
    return urlunparse(parsed._replace(query=urlencode(pairs, doseq=True)))


@main.command(name="services")
@click.option("--chromium-url", default=None, help="Chromium service URL (or set CHATTOOL_CHROMIUM_URL).")
@click.option("--chromium-token", default=None, help="Chromium token (or set CHATTOOL_CHROMIUM_TOKEN). If set, added as ?token=.")
@click.option("--chromedriver-url", default=None, help="Chromedriver service URL (or set CHATTOOL_CHROMEDRIVER_URL).")
@click.option("--playwright-url", default=None, help="Playwright service URL (or set CHATTOOL_PLAYWRIGHT_URL).")
@click.option("--timeout", default=6.0, show_default=True, help="Request timeout in seconds.")
def services(chromium_url: str | None, chromium_token: str | None, chromedriver_url: str | None, playwright_url: str | None, timeout: float) -> None:
    """Check that chromium/chromedriver/playwright URLs respond with expected content."""

    chromium_url = chromium_url or os.getenv("CHATTOOL_CHROMIUM_URL")
    chromedriver_url = chromedriver_url or os.getenv("CHATTOOL_CHROMEDRIVER_URL")
    playwright_url = playwright_url or os.getenv("CHATTOOL_PLAYWRIGHT_URL")
    chromium_token = chromium_token or os.getenv("CHATTOOL_CHROMIUM_TOKEN")

    missing = [name for name, value in [("chromium", chromium_url), ("chromedriver", chromedriver_url), ("playwright", playwright_url)] if not value]
    if missing:
        click.secho("Missing service URL(s): " + ", ".join(missing) + ". Provide --<service>-url or set CHATTOOL_*_URL env vars.", fg="red")
        raise SystemExit(2)
    assert chromium_url is not None
    assert chromedriver_url is not None
    assert playwright_url is not None

    chromium_health = ensure_path(chromium_url, "/json/version")
    if chromium_token:
        chromium_health = append_token(chromium_health, chromium_token)
    targets = [
        ("chromium", chromium_health, "websocket"),
        ("chromedriver", ensure_path(chromedriver_url, "/status"), "ready"),
        ("playwright", playwright_url, None),
    ]

    failed = 0
    for name, url, expected in targets:
        result = check_service_url(url, expected, timeout=timeout)
        status = result.status if result.status is not None else "ERR"
        line = f"[{status}] {name}: {_redact_url_token(result.url)} ({result.elapsed_ms}ms)"
        if result.ok:
            click.secho(line, fg="green")
        else:
            failed += 1
            if result.error:
                line = f"{line} - {result.error}"
            click.secho(line, fg="red")
    click.echo(f"Total: {len(targets)}, OK: {len(targets) - failed}, Failed: {failed}")
    if failed:
        raise SystemExit(2)


def _load_proxy_defaults() -> dict[str, str | None]:
    from chatnet.config import load_chatnet_proxy_config

    config = load_chatnet_proxy_config()
    return {
        "bind": config.CHATNET_PROXY_BIND.value,
        "port": config.CHATNET_PROXY_PORT.value,
        "allow_cidr": config.CHATNET_PROXY_ALLOW_CIDR.value,
        "username": config.CHATNET_PROXY_USER.value,
        "password": config.CHATNET_PROXY_PASSWORD.value,
    }


def _proxy_default(name: str) -> str | None:
    value = _load_proxy_defaults().get(name)
    return str(value) if value not in (None, "") else None


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _to_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(str(value))


def _to_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value))


def _auth_pair_constraint(values: dict[str, object]) -> str | None:
    username = values.get("username")
    password = values.get("password")
    if bool(username) != bool(password):
        return "--user/CHATNET_PROXY_USER and --password/CHATNET_PROXY_PASSWORD must be provided together."
    return None


_AUTH_PAIR_CONSTRAINT = CommandConstraint(_auth_pair_constraint)

_PROXY_SERVE_SCHEMA = CommandSchema(
    name="chatnet proxy serve",
    fields=(
        CommandField("bind", "Listen address", default_factory=lambda: _proxy_default("bind") or "127.0.0.1", normalizer=_optional_text),
        CommandField("port", "Listen port", default_factory=lambda: _proxy_default("port") or 18080, normalizer=_to_int),
        CommandField("allow_cidr", "Client CIDR allowlist", default_factory=lambda: _proxy_default("allow_cidr") or "127.0.0.0/8", normalizer=_optional_text),
        CommandField("username", "Basic auth username", default_factory=lambda: _proxy_default("username"), normalizer=_optional_text),
        CommandField("password", "Basic auth password", default_factory=lambda: _proxy_default("password"), sensitive=True, normalizer=_optional_text),
        CommandField("timeout", "Socket timeout in seconds", default=30.0, normalizer=_to_float),
    ),
    constraints=(_AUTH_PAIR_CONSTRAINT,),
)

_PROXY_CHECK_SCHEMA = CommandSchema(
    name="chatnet proxy check",
    fields=(
        CommandField("proxy_url", "Proxy URL", required=True, normalizer=_optional_text),
        CommandField("target_url", "Target URL", default="https://www.gstatic.com/generate_204", normalizer=_optional_text),
        CommandField("username", "Proxy Basic auth username", default_factory=lambda: _proxy_default("username"), normalizer=_optional_text),
        CommandField("password", "Proxy Basic auth password", default_factory=lambda: _proxy_default("password"), sensitive=True, normalizer=_optional_text),
        CommandField("expect_status", "Expected HTTP status", normalizer=_to_int),
        CommandField("timeout", "Request timeout in seconds", default=10.0, normalizer=_to_float),
    ),
    constraints=(_AUTH_PAIR_CONSTRAINT,),
)

_PROXY_SERVICE_SCHEMA = CommandSchema(
    name="chatnet proxy autostart",
    fields=(
        CommandField("service_name", "User systemd service name", default="chatnet-forward-proxy", normalizer=_optional_text),
        CommandField("bind", "Listen address", default_factory=lambda: _proxy_default("bind") or "127.0.0.1", normalizer=_optional_text),
        CommandField("port", "Listen port", default_factory=lambda: _proxy_default("port") or 18080, normalizer=_to_int),
        CommandField("allow_cidr", "Client CIDR allowlist", default_factory=lambda: _proxy_default("allow_cidr") or "127.0.0.0/8", normalizer=_optional_text),
        CommandField("username", "Basic auth username", default_factory=lambda: _proxy_default("username"), normalizer=_optional_text),
        CommandField("env_file", "Systemd EnvironmentFile path", default="%h/.config/chatnet/proxy.env", normalizer=_optional_text),
        CommandField("python_bin", "Python executable for ExecStart", default_factory=lambda: sys.executable, normalizer=_optional_text),
    ),
)


def _resolve_inputs(schema: CommandSchema, provided: dict[str, object], interactive: bool | None, usage: str) -> dict[str, object]:
    return resolve_command_inputs(schema=schema, provided=provided, interactive=interactive, usage=usage)


@main.group(name="proxy")
def proxy_group() -> None:
    """Explicit forward proxy helpers."""


@proxy_group.command(name="serve")
@click.option("--bind", default=None, help="Listen address. Defaults to CHATNET_PROXY_BIND or 127.0.0.1.")
@click.option("--port", default=None, type=int, help="Listen port. Defaults to CHATNET_PROXY_PORT or 18080.")
@click.option("--allow-cidr", default=None, help="Comma-separated client CIDR allowlist. Defaults to CHATNET_PROXY_ALLOW_CIDR or 127.0.0.0/8.")
@click.option("--user", "username", default=None, help="Optional Basic auth username. Defaults to CHATNET_PROXY_USER.")
@click.option(
    "--password",
    default=None,
    envvar="CHATNET_PROXY_PASSWORD",
    help="Optional Basic auth password. Prefer CHATNET_PROXY_PASSWORD or ChatEnv.",
)
@click.option("--timeout", default=None, type=float, help="Socket timeout in seconds. Defaults to 30.")
@add_interactive_option
def proxy_serve(bind: str | None, port: int | None, allow_cidr: str | None, username: str | None, password: str | None, timeout: float | None, interactive: bool | None) -> None:
    """Serve a non-sudo HTTP/HTTPS CONNECT forward proxy."""

    from chatnet.forward_proxy import ForwardProxyConfig, parse_cidrs, serve_forward_proxy

    values = _resolve_inputs(
        _PROXY_SERVE_SCHEMA,
        {"bind": bind, "port": port, "allow_cidr": allow_cidr, "username": username, "password": password, "timeout": timeout},
        interactive,
        "Usage: chatnet proxy serve [OPTIONS] [-i|-I]",
    )
    bind = str(values["bind"])
    port = int(str(values["port"]))
    allow_cidr = str(values["allow_cidr"])
    username = values["username"] if values["username"] is None else str(values["username"])
    password = values["password"] if values["password"] is None else str(values["password"])
    timeout = float(str(values["timeout"]))
    try:
        cidrs = parse_cidrs(allow_cidr)
    except ValueError as exc:
        raise click.ClickException(f"Invalid --allow-cidr: {exc}") from exc
    config = ForwardProxyConfig(
        bind=bind,
        port=port,
        allow_cidrs=tuple(str(cidr) for cidr in cidrs),
        username=username,
        password=password,
        timeout=timeout,
    )
    auth_state = "enabled" if username else "disabled"
    click.echo(f"Serving forward proxy on {bind}:{port}; allow={','.join(config.allow_cidrs)}; auth={auth_state}")
    if bind == "0.0.0.0" and not username:
        click.secho("Warning: LAN-facing proxy is running without authentication.", fg="yellow")
    try:
        serve_forward_proxy(config)
    except OSError as exc:
        raise click.ClickException(str(exc)) from exc
    except KeyboardInterrupt:
        click.echo("Stopped forward proxy.")


@proxy_group.command(name="check")
@click.option("--proxy-url", default=None, help="Proxy URL, e.g. http://127.0.0.1:18080.")
@click.option("--url", "target_url", default=None, help="URL to fetch through the proxy. Defaults to https://www.gstatic.com/generate_204.")
@click.option("--user", "username", default=None, help="Optional proxy Basic auth username. Defaults to CHATNET_PROXY_USER.")
@click.option(
    "--password",
    default=None,
    envvar="CHATNET_PROXY_PASSWORD",
    help="Optional proxy Basic auth password. Prefer CHATNET_PROXY_PASSWORD or ChatEnv.",
)
@click.option("--expect-status", default=None, type=int, help="Expected HTTP status. Defaults to any 2xx/3xx response.")
@click.option("--timeout", default=None, type=float, help="Request timeout in seconds. Defaults to 10.")
@click.option("--show-body", is_flag=True, help="Print a short response body preview.")
@add_interactive_option
def proxy_check(
    proxy_url: str | None,
    target_url: str | None,
    username: str | None,
    password: str | None,
    expect_status: int | None,
    timeout: float | None,
    show_body: bool,
    interactive: bool | None,
) -> None:
    """Check a URL through an explicit forward proxy."""

    from chatnet.forward_proxy_check import check_forward_proxy

    values = _resolve_inputs(
        _PROXY_CHECK_SCHEMA,
        {"proxy_url": proxy_url, "target_url": target_url, "username": username, "password": password, "expect_status": expect_status, "timeout": timeout},
        interactive,
        "Usage: chatnet proxy check --proxy-url URL [OPTIONS] [-i|-I]",
    )
    proxy_url = str(values["proxy_url"])
    target_url = str(values["target_url"])
    username = values["username"] if values["username"] is None else str(values["username"])
    password = values["password"] if values["password"] is None else str(values["password"])
    expect_status = values["expect_status"] if values["expect_status"] is None else int(str(values["expect_status"]))
    timeout = float(str(values["timeout"]))
    result = check_forward_proxy(
        proxy_url,
        target_url,
        username=username,
        password=password,
        timeout=timeout,
        expected_status=expect_status,
    )
    status = result.status if result.status is not None else "ERR"
    line = f"[{status}] {result.target_url} via {result.proxy_url} ({result.elapsed_ms}ms)"
    if result.ok:
        click.secho(line, fg="green")
    else:
        if result.error:
            line = f"{line} - {result.error}"
        click.secho(line, fg="red")
    if show_body and result.body_preview:
        click.echo(result.body_preview)
    if not result.ok:
        raise SystemExit(2)


@proxy_group.group(name="autostart")
def proxy_autostart() -> None:
    """Generate or install non-sudo user autostart files."""


_PROXY_SERVICE_OPTIONS = [
    click.option("--service-name", default=None, help="User systemd service name. Defaults to chatnet-forward-proxy."),
    click.option("--bind", default=None, help="Listen address for the service. Defaults to CHATNET_PROXY_BIND or 127.0.0.1."),
    click.option("--port", default=None, type=int, help="Listen port. Defaults to CHATNET_PROXY_PORT or 18080."),
    click.option("--allow-cidr", default=None, help="Comma-separated client CIDR allowlist. Defaults to CHATNET_PROXY_ALLOW_CIDR or 127.0.0.0/8."),
    click.option("--user", "username", default=None, help="Optional Basic auth username. Defaults to CHATNET_PROXY_USER."),
    click.option("--env-file", default=None, help="Systemd EnvironmentFile path for CHATNET_PROXY_PASSWORD. Defaults to %h/.config/chatnet/proxy.env."),
    click.option("--python", "python_bin", default=None, help="Python executable for ExecStart. Defaults to current Python."),
]


def _apply_proxy_service_options(func):
    for option in reversed(_PROXY_SERVICE_OPTIONS):
        func = option(func)
    return func


def _service_config(service_name: str, bind: str, port: int, allow_cidr: str, username: str | None, env_file: str, python_bin: str | None):
    from chatnet.forward_proxy_service import ForwardProxyServiceConfig

    return ForwardProxyServiceConfig(
        service_name=service_name,
        bind=bind,
        port=port,
        allow_cidr=allow_cidr,
        username=username,
        env_file=env_file,
        python=python_bin or sys.executable,
    )


@proxy_autostart.command(name="print")
@_apply_proxy_service_options
@add_interactive_option
def proxy_autostart_print(service_name: str | None, bind: str | None, port: int | None, allow_cidr: str | None, username: str | None, env_file: str | None, python_bin: str | None, interactive: bool | None) -> None:
    """Print a user systemd unit without writing files."""

    from chatnet.forward_proxy_service import render_systemd_user_unit

    values = _resolve_inputs(
        _PROXY_SERVICE_SCHEMA,
        {"service_name": service_name, "bind": bind, "port": port, "allow_cidr": allow_cidr, "username": username, "env_file": env_file, "python_bin": python_bin},
        interactive,
        "Usage: chatnet proxy autostart print [OPTIONS] [-i|-I]",
    )
    config = _service_config(
        str(values["service_name"]),
        str(values["bind"]),
        int(str(values["port"])),
        str(values["allow_cidr"]),
        values["username"] if values["username"] is None else str(values["username"]),
        str(values["env_file"]),
        str(values["python_bin"]),
    )
    click.echo(render_systemd_user_unit(config))


@proxy_autostart.command(name="install")
@_apply_proxy_service_options
@click.option("--enable", is_flag=True, help="Run systemctl --user enable --now after writing the unit.")
@add_interactive_option
def proxy_autostart_install(
    service_name: str | None,
    bind: str | None,
    port: int | None,
    allow_cidr: str | None,
    username: str | None,
    env_file: str | None,
    python_bin: str | None,
    enable: bool,
    interactive: bool | None,
) -> None:
    """Install a user systemd unit without sudo."""

    from chatnet.forward_proxy_service import default_env_file_path, install_systemd_user_unit, render_env_file_example

    values = _resolve_inputs(
        _PROXY_SERVICE_SCHEMA,
        {"service_name": service_name, "bind": bind, "port": port, "allow_cidr": allow_cidr, "username": username, "env_file": env_file, "python_bin": python_bin},
        interactive,
        "Usage: chatnet proxy autostart install [OPTIONS] [-i|-I]",
    )
    username = values["username"] if values["username"] is None else str(values["username"])
    env_file = str(values["env_file"])
    config = _service_config(
        str(values["service_name"]),
        str(values["bind"]),
        int(str(values["port"])),
        str(values["allow_cidr"]),
        username,
        env_file,
        str(values["python_bin"]),
    )
    try:
        unit_path = install_systemd_user_unit(config, enable=enable)
    except subprocess.CalledProcessError as exc:
        raise click.ClickException(f"systemctl --user failed: {exc}") from exc
    click.echo(f"Wrote {unit_path}")
    if username:
        env_path = default_env_file_path(env_file)
        click.echo(f"Create {env_path} with mode 600 before starting if it does not exist:")
        click.echo(render_env_file_example(username).rstrip())
    if not enable:
        click.echo("Enable with: systemctl --user daemon-reload && systemctl --user enable --now " + unit_path.name)


if __name__ == "__main__":
    main()
