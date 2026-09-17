"""Conservative, offline Linux/NetworkManager recovery.

No credentials are read. Hardware is selected from ChatEnv or kernel evidence;
all subprocess arguments are fixed vectors, never shell programs. Importing this
module is platform independent; Linux-only facilities are loaded at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import math
import os
import platform
from pathlib import Path
import re
import subprocess
import time

from chatenv import EnvStore, get_paths

from .config import ChatNetProxyConfig


class RecoveryError(RuntimeError):
    """A sanitized stage/command/return-code failure (never raw tool output)."""

    def __init__(
        self, stage: str, command: str | None = None, returncode: int | None = None
    ):
        self.stage, self.command, self.returncode = stage, command, returncode
        message = stage
        if command:
            message += f": {command}"
        if returncode is not None:
            message += f" (returncode={returncode})"
        super().__init__(message)


def _interface(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}", value
    ):
        raise RecoveryError("invalid-interface")
    return value


def _ip(value: str) -> str:
    try:
        if not isinstance(value, str) or "%" in value:
            raise ValueError
        address = ipaddress.ip_address(value)
        if address.is_unspecified or address.is_multicast or address.is_loopback:
            raise ValueError
    except ValueError:
        raise RecoveryError("invalid-ip") from None
    return str(address)


def _number(value, *, minimum=0, maximum=31_536_000, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecoveryError("invalid-settings")
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise RecoveryError("invalid-settings")
    if integer and not isinstance(value, int):
        raise RecoveryError("invalid-settings")
    return value


@dataclass(frozen=True)
class RecoverySettings:
    interface: str = ""
    connection: str = ""
    rescue_peer: str = ""
    probe_host: str = ""
    cooldown: float = 300
    max_attempts: int = 3
    window_seconds: float = 3600
    allow_module_reload: bool = False

    def __post_init__(self):
        for name in ("interface", "connection", "rescue_peer", "probe_host"):
            if not isinstance(getattr(self, name), str):
                raise RecoveryError("invalid-settings")
        if self.interface:
            _interface(self.interface)
        if self.connection and (
            self.connection.startswith("-")
            or len(self.connection) > 256
            or any(ord(c) < 32 or ord(c) == 127 for c in self.connection)
        ):
            raise RecoveryError("invalid-connection")
        for value in (self.rescue_peer, self.probe_host):
            if value:
                _ip(value)
        _number(self.cooldown)
        _number(self.window_seconds, minimum=0.01)
        _number(self.max_attempts, minimum=1, maximum=1000, integer=True)
        if not isinstance(self.allow_module_reload, bool):
            raise RecoveryError("invalid-settings")


def recovery_home(home=None) -> Path:
    """Return the runtime directory without creating anything."""
    return get_paths(home).home_dir / "chatnet" / "recovery"


def load_recovery_settings(home=None) -> RecoverySettings:
    """Read the existing ChatNet profile, with process environment precedence."""
    try:
        profile = EnvStore(get_paths(home).envs_dir).load_active(ChatNetProxyConfig)
        fields = ChatNetProxyConfig.get_fields()
        values = {}
        names = {
            "interface": "INTERFACE",
            "connection": "CONNECTION",
            "rescue_peer": "RESCUE_PEER",
            "probe_host": "PROBE_HOST",
            "cooldown": "COOLDOWN",
            "max_attempts": "MAX_ATTEMPTS",
            "window_seconds": "WINDOW",
            "allow_module_reload": "MODULE_RELOAD",
        }
        for name, suffix in names.items():
            key = "CHATNET_RECOVERY_" + suffix
            raw = os.environ.get(key, profile.get(key, fields[key].default))
            raw = "" if raw is None else str(raw)
            if name in {"cooldown", "window_seconds"}:
                raw = float(raw)
            elif name in {"max_attempts"}:
                if not re.fullmatch(r"[0-9]+", raw):
                    raise ValueError
                raw = int(raw)
            elif name == "allow_module_reload":
                if raw.lower() not in {
                    "true",
                    "false",
                    "1",
                    "0",
                    "yes",
                    "no",
                    "on",
                    "off",
                }:
                    raise ValueError
                raw = raw.lower() in {"true", "1", "yes", "on"}
            values[name] = raw
        return RecoverySettings(**values)
    except RecoveryError:
        raise
    except (OSError, ValueError, TypeError, KeyError):
        raise RecoveryError("settings-load") from None


def _nm_fields(line):
    fields, value, escaped = [], "", False
    for char in line:
        if escaped:
            value += char
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append(value)
            value = ""
        else:
            value += char
    if escaped:
        raise RecoveryError("nm-output")
    return fields + [value]


def _uuid(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value
    ):
        raise RecoveryError("connection-uuid")
    return value


class _Adapter:
    def __init__(self, runner=None, sys_root=None, environ=None, platform_name=None):
        if (platform_name or platform.system()) != "Linux":
            raise RecoveryError("unsupported-platform")
        self.runner = runner or subprocess.run
        self.sys = Path(sys_root or "/sys")
        self.environ = dict(os.environ if environ is None else environ)
        self.command_env = {
            "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
            "LC_ALL": "C",
            "LANG": "C",
        }

    def call(self, args, stage, *, privileged=False, check=True, timeout=10):
        argv = ["sudo", "-n", "--", *args] if privileged else list(args)
        try:
            result = self.runner(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                stdin=subprocess.DEVNULL,
                env=self.command_env,
            )
        except (OSError, subprocess.SubprocessError):
            raise RecoveryError(stage, args[0]) from None
        if len(result.stdout or "") > 131072:
            raise RecoveryError(stage, args[0])
        if check and result.returncode:
            raise RecoveryError(stage, args[0], result.returncode)
        return result

    def wireless(self, name):
        root = self.sys / "class/net" / name
        return (root / "wireless").exists() or (root / "phy80211").exists()

    def interface(self, requested):
        try:
            names = [
                _interface(p.name)
                for p in (self.sys / "class/net").iterdir()
                if self.wireless(p.name)
            ]
        except OSError:
            raise RecoveryError("interface-read") from None
        if requested:
            if requested not in names:
                raise RecoveryError("interface-not-wireless")
            return requested
        if len(names) != 1:
            raise RecoveryError("interface-ambiguous")
        return names[0]

    def route(self, peer):
        value = self.call(
            ["ip", "-j", "route", "get", _ip(peer)], "management-route"
        ).stdout
        try:
            rows = json.loads(value)
            if (
                not isinstance(rows, list)
                or len(rows) != 1
                or not isinstance(rows[0], dict)
            ):
                raise ValueError
            return _interface(rows[0]["dev"])
        except (ValueError, KeyError, TypeError):
            raise RecoveryError("management-route") from None

    def ssh_peer(self):
        text = self.environ.get("SSH_CONNECTION", "")
        if not text:
            return None
        parts = text.split()
        if len(parts) != 4 or not all(
            re.fullmatch(r"[0-9]+", p) for p in (parts[1], parts[3])
        ):
            raise RecoveryError("ssh-context")
        return _ip(parts[0])

    def foreground_safe(self, interface):
        peer = self.ssh_peer()
        return peer is None or self.route(peer) != interface

    def module_info(self, interface):
        try:
            device = (self.sys / "class/net" / interface / "device").resolve(
                strict=True
            )
            module = (device / "driver/module").resolve(strict=True)
            if module.parent != self.sys / "module" or not re.fullmatch(
                r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", module.name
            ):
                return "", 0, str(device)
            bound = set()
            for link in (module / "drivers").iterdir():
                driver = link.resolve(strict=True)
                for entry in driver.iterdir():
                    if entry.is_symlink():
                        target = entry.resolve(strict=True)
                        if target.is_relative_to(self.sys / "devices"):
                            bound.add(target)
            if device not in bound:
                return "", 0, str(device)
            return module.name, len(bound), str(device)
        except (OSError, RuntimeError):
            return "", 0, ""

    def reload_guard(self, settings, snapshot):
        if not settings.allow_module_reload:
            return "module-reload-disabled"
        if not self.foreground_safe(snapshot["interface"]):
            return "ssh-target"
        peer = settings.rescue_peer or self.ssh_peer()
        if not peer:
            return "rescue-required"
        dev = self.route(peer)
        root = self.sys / "class/net" / dev
        try:
            physical = (root / "device").resolve(strict=True)
            safe = (
                dev != snapshot["interface"]
                and not self.wireless(dev)
                and physical.is_relative_to(self.sys / "devices")
                and "virtual" not in physical.relative_to(self.sys / "devices").parts
                and (root / "type").read_text().strip() == "1"
                and (root / "carrier").read_text().strip() == "1"
            )
        except OSError:
            safe = False
        if not safe:
            return "rescue-unsafe"
        module, count, identity = self.module_info(snapshot["interface"])
        if (
            not module
            or module != snapshot["module"]
            or identity != snapshot["device_id"]
        ):
            return "module-changed"
        if count != 1:
            return "shared-module"
        return None

    def connection(self, settings, interface, active):
        output = self.call(
            ["nmcli", "-t", "-f", "UUID,TYPE,NAME", "connection", "show"], "connections"
        ).stdout
        rows = [_nm_fields(line) for line in output.splitlines() if line]
        rows = [
            row
            for row in rows
            if len(row) == 3 and row[1] in ("802-11-wireless", "wifi")
        ]
        if settings.connection:
            rows = [r for r in rows if settings.connection in (r[0], r[2])]
        elif active and active != "--":
            _uuid(active)
            rows = [r for r in rows if r[0] == active]
        if len(rows) != 1:
            raise RecoveryError("connection-ambiguous")
        uuid = _uuid(rows[0][0])
        bound = self.call(
            [
                "nmcli",
                "-g",
                "connection.interface-name",
                "connection",
                "show",
                "uuid",
                uuid,
            ],
            "connection-binding",
        ).stdout.strip()
        if bound not in ("", "--", interface):
            raise RecoveryError("connection-interface")
        return uuid

    def ping(self, interface, host):
        return (
            self.call(
                ["ping", "-n", "-c", "1", "-W", "2", "-I", interface, _ip(host)],
                "ping",
                check=False,
                timeout=4,
            ).returncode
            == 0
        )

    def inspect(self, settings):
        interface = self.interface(settings.interface)
        result = {
            "status": "unhealthy",
            "reason": "link-down",
            "healthy": False,
            "recoverable": False,
            "interface": interface,
            "connection_uuid": None,
            "module": "",
            "device_id": "",
        }
        radio = (
            self.call(["nmcli", "-t", "-f", "RUNNING,WIFI-HW,WIFI", "general"], "radio")
            .stdout.strip()
            .split(":")
        )
        if len(radio) != 3 or radio[0] != "running":
            raise RecoveryError("networkmanager-unavailable")
        if radio[1:] != ["enabled", "enabled"]:
            return {**result, "status": "disabled", "reason": "radio-disabled"}
        types = [
            _nm_fields(line)
            for line in self.call(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"],
                "devices",
            ).stdout.splitlines()
            if line
        ]
        if not any(len(r) == 3 and r[0] == interface and r[1] == "wifi" for r in types):
            raise RecoveryError("interface-not-managed-wifi")
        values = self.call(
            [
                "nmcli",
                "-g",
                "GENERAL.STATE,GENERAL.CON-UUID,IP4.GATEWAY,IP6.GATEWAY",
                "device",
                "show",
                interface,
            ],
            "device-state",
        ).stdout.splitlines()
        if len(values) != 4 or not re.match(r"^\d+(?:\s|$)", values[0]):
            raise RecoveryError("device-state")
        state = int(values[0].split()[0])
        result["nm_state"] = state
        if state in (10, 20) or 40 <= state <= 90 or state == 110:
            label = {10: "unmanaged", 20: "unavailable"}.get(state, "connecting")
            return {**result, "status": label, "reason": label}
        if state not in (30, 100, 120):
            return {**result, "reason": "unknown-state"}
        result["connection_uuid"] = self.connection(settings, interface, values[1])
        module, count, device = self.module_info(interface)
        result.update(module=module, module_devices=count, device_id=device)
        if state in (30, 120):
            return {**result, "recoverable": True}
        gateway = next((x for x in values[2:] if x and x != "--"), None)
        if gateway is None:
            return {**result, "reason": "gateway-unknown"}
        gateway = _ip(gateway)
        result["gateway"] = gateway
        if self.ping(interface, gateway):
            reason = "gateway-ok"
            if settings.probe_host and not self.ping(interface, settings.probe_host):
                reason = "external-probe-failed"
            return {**result, "status": "healthy", "reason": reason, "healthy": True}
        return {**result, "reason": "gateway-unreachable", "recoverable": True}


def check_recovery(settings=None, **dependencies) -> dict:
    """Read-only local link diagnosis; an external outage is not a radio fault."""
    return _Adapter(**dependencies).inspect(settings or load_recovery_settings())


def _identity(snapshot):
    return tuple(
        snapshot.get(k) for k in ("interface", "connection_uuid", "module", "device_id")
    )


def recover_network(
    settings=None, *, execute=False, home=None, clock=None, **dependencies
) -> dict:
    """Run one proven recovery path, never an unattended repair loop."""
    if type(execute) is not bool:
        raise RecoveryError("invalid-execute")
    settings = settings or load_recovery_settings(home=home)
    adapter = _Adapter(**dependencies)
    snapshot = adapter.inspect(settings)
    base = {**snapshot, "ok": snapshot["healthy"], "performed": False}
    if not snapshot["recoverable"]:
        return base
    if not adapter.foreground_safe(snapshot["interface"]):
        return {**base, "status": "blocked", "reason": "ssh-target"}
    if settings.allow_module_reload:
        blocked = adapter.reload_guard(settings, snapshot)
        if blocked:
            return {**base, "status": "blocked", "reason": blocked}
    plan = (
        ["module-unload", "module-load", "device-ready", "reconnect"]
        if settings.allow_module_reload
        else ["rescan", "reconnect"]
    )
    if not execute:
        return {
            **base,
            "ok": True,
            "status": "dry-run",
            "reason": "explicit-execution-required",
            "plan": plan,
        }
    from . import recovery_state as state_io

    root = recovery_home(home)
    clock = clock or time.time
    with state_io.locked(root):
        current = adapter.inspect(settings)
        if _identity(current) != _identity(snapshot):
            return {**base, "status": "blocked", "reason": "identity-changed"}
        if not current["recoverable"]:
            return {**current, "ok": current["healthy"], "performed": False}
        if not adapter.foreground_safe(current["interface"]):
            return {**base, "status": "blocked", "reason": "ssh-target"}
        if settings.allow_module_reload:
            blocked = adapter.reload_guard(settings, current)
            if blocked:
                return {**base, "status": "blocked", "reason": blocked}
        now = clock()
        state = state_io.read_state(root, now)
        attempts = [t for t in state["attempts"] if t > now - settings.window_seconds]
        reason = None
        if (
            state["last_attempt"] is not None
            and now - state["last_attempt"] < settings.cooldown
        ):
            reason = "cooldown"
        elif len(attempts) >= settings.max_attempts:
            reason = "budget-exhausted"
        if reason:
            state["last_seen"] = now
            state_io.write_state(root, state)
            return {**base, "status": "blocked", "reason": reason}
        state.update(
            attempts=attempts + [now], last_attempt=now, last_seen=now, failures=0
        )
        state_io.write_state(root, state)
        state_io.audit(
            root,
            {
                "time": now,
                "status": "attempt-reserved",
                "interface": current["interface"],
            },
        )
        interface = current["interface"]
        uuid = current["connection_uuid"]
        try:
            if settings.allow_module_reload:
                adapter.call(
                    ["modprobe", "-r", current["module"]],
                    "module-unload",
                    privileged=True,
                    timeout=20,
                )
                adapter.call(
                    ["modprobe", current["module"]],
                    "module-load",
                    privileged=True,
                    timeout=20,
                )
                adapter.call(
                    ["udevadm", "settle", "--timeout=10"], "device-ready", timeout=15
                )
            else:
                adapter.call(
                    [
                        "nmcli",
                        "--wait",
                        "20",
                        "device",
                        "wifi",
                        "rescan",
                        "ifname",
                        interface,
                    ],
                    "rescan",
                    privileged=True,
                    timeout=25,
                )
            adapter.call(
                [
                    "nmcli",
                    "--wait",
                    "30",
                    "connection",
                    "up",
                    "uuid",
                    uuid,
                    "ifname",
                    interface,
                ],
                "reconnect",
                privileged=True,
                check=False,
                timeout=35,
            )
            after = adapter.inspect(settings)
            result = {
                **after,
                "ok": after["healthy"],
                "performed": True,
                "status": "recovered" if after["healthy"] else "failed",
                "reason": (
                    "module-reloaded" if settings.allow_module_reload else "reconnected"
                )
                if after["healthy"]
                else "postcheck-failed",
            }
        except RecoveryError as error:
            state["last_result"] = {
                "status": "failed",
                "stage": error.stage,
                "command": error.command,
                "returncode": error.returncode,
            }
            state_io.write_state(root, state)
            state_io.audit(root, {"time": now, **state["last_result"]})
            raise
        state["last_result"] = {
            k: result[k] for k in ("status", "reason", "ok", "performed")
        }
        state_io.write_state(root, state)
        state_io.audit(root, {"time": now, **state["last_result"]})
        return result
