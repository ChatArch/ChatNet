"""Network scanning helpers."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import platform
import socket
import subprocess
import threading
from pathlib import Path


def get_platform_ping_args(count: int = 1, timeout: int = 1) -> list[str]:
    """Return platform-specific ping arguments."""

    system = platform.system().lower()
    args = ["ping"]
    if system == "windows":
        args.extend(["-n", str(count), "-w", str(timeout * 1000)])
    elif system == "darwin":
        args.extend(["-c", str(count), "-W", str(timeout * 1000)])
    else:
        args.extend(["-c", str(count), "-W", str(timeout)])
    return args


def ping_host(host: str, timeout: int = 1) -> tuple[str, bool]:
    """Ping a single host and return ``(host, is_active)``."""

    command = get_platform_ping_args(count=1, timeout=timeout) + [host]
    try:
        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return host, True
    except (subprocess.CalledProcessError, OSError):
        return host, False


def check_port(host: str, port: int, timeout: float = 1.0) -> tuple[str, bool]:
    """Check whether ``port`` is open on ``host``."""

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return host, True
    except (socket.timeout, OSError):
        return host, False


def _write_lines(path: str | Path, values: list[str]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(f"{value}\n" for value in values), encoding="utf-8")


def ping_scan(network_segment: str, concurrency: int = 50, output_path: str | Path | None = None) -> list[str]:
    """Scan a network segment for active hosts using ICMP ping."""

    try:
        network = ipaddress.ip_network(network_segment, strict=False)
    except ValueError as exc:
        raise ValueError(f"Error parsing network segment: {exc}") from exc

    hosts = [str(ip) for ip in network.hosts()]
    active_hosts: list[str] = []
    write_lock = threading.Lock()

    if output_path:
        _write_lines(output_path, [])

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_host = {executor.submit(ping_host, host): host for host in hosts}
        for future in concurrent.futures.as_completed(future_to_host):
            host, is_active = future.result()
            if is_active:
                active_hosts.append(host)
                if output_path:
                    with write_lock:
                        with Path(output_path).open("a", encoding="utf-8") as handle:
                            handle.write(f"{host}\n")
                            handle.flush()

    active_hosts.sort(key=lambda ip: ipaddress.ip_address(ip))
    return active_hosts


def port_scan(ip_list: list[str], port: int, concurrency: int = 50, output_path: str | Path | None = None) -> list[str]:
    """Scan a specific port on a list of IP addresses or hostnames."""

    open_hosts: list[str] = []
    write_lock = threading.Lock()

    if output_path:
        _write_lines(output_path, [])

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        future_to_host = {executor.submit(check_port, ip, port): ip for ip in ip_list}
        for future in concurrent.futures.as_completed(future_to_host):
            host, is_open = future.result()
            if is_open:
                open_hosts.append(host)
                if output_path:
                    with write_lock:
                        with Path(output_path).open("a", encoding="utf-8") as handle:
                            handle.write(f"{host}\n")
                            handle.flush()

    def sort_key(value: str) -> tuple[int, object]:
        try:
            return (0, ipaddress.ip_address(value))
        except ValueError:
            return (1, value)

    open_hosts.sort(key=sort_key)
    return open_hosts
