"""CLI entrypoint for ChatNet generic network helpers."""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import click

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


if __name__ == "__main__":
    main()
