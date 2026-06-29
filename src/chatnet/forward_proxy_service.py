"""User-level autostart helpers for the forward proxy."""

from __future__ import annotations

import dataclasses
import shlex
import subprocess
import sys
from pathlib import Path


@dataclasses.dataclass(frozen=True)
class ForwardProxyServiceConfig:
    """Configuration used to render a user systemd service."""

    service_name: str = "chatnet-forward-proxy"
    bind: str = "127.0.0.1"
    port: int = 18080
    allow_cidr: str = "127.0.0.0/8"
    username: str | None = None
    env_file: str = "%h/.config/chatnet/proxy.env"
    python: str = sys.executable


def render_systemd_user_unit(config: ForwardProxyServiceConfig) -> str:
    """Render a user-level systemd unit for `chatnet proxy serve`."""

    command = [
        config.python,
        "-m",
        "chatnet.cli",
        "proxy",
        "serve",
        "--bind",
        config.bind,
        "--port",
        str(config.port),
        "--allow-cidr",
        config.allow_cidr,
    ]
    if config.username:
        command.extend(["--user", config.username])
    exec_start = " ".join(shlex.quote(part) for part in command)
    lines = [
        "[Unit]",
        "Description=ChatNet non-sudo forward proxy",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        "Environment=PYTHONUNBUFFERED=1",
    ]
    if config.username:
        lines.append(f"EnvironmentFile=-{config.env_file}")
    lines.extend(
        [
            f"ExecStart={exec_start}",
            "Restart=on-failure",
            "RestartSec=5s",
            "NoNewPrivileges=true",
            "",
            "[Install]",
            "WantedBy=default.target",
            "",
        ]
    )
    return "\n".join(lines)


def install_systemd_user_unit(
    config: ForwardProxyServiceConfig,
    *,
    user_systemd_dir: Path | None = None,
    enable: bool = False,
) -> Path:
    """Write the user systemd unit and optionally enable it without sudo."""

    target_dir = user_systemd_dir or Path.home() / ".config" / "systemd" / "user"
    target_dir.mkdir(parents=True, exist_ok=True)
    unit_path = target_dir / f"{config.service_name}.service"
    unit_path.write_text(render_systemd_user_unit(config), encoding="utf-8")
    if enable:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", unit_path.name], check=True)
    return unit_path


def default_env_file_path(env_file: str) -> Path:
    """Expand a systemd-style env file path for user instructions."""

    return Path(env_file.replace("%h", str(Path.home()))).expanduser()


def render_env_file_example(username: str = "chatnet") -> str:
    """Render a non-secret env file example."""

    _ = username
    return "CHATNET_PROXY_PASSWORD=<replace-with-password>\n"
