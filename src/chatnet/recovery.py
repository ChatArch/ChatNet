"""Conservative, offline Linux/NetworkManager recovery.

No credentials are read. Hardware is selected from ChatEnv or kernel evidence;
all subprocess arguments are fixed vectors, never shell programs. Importing this
module is platform independent; Linux-only facilities are loaded at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
import os
import platform
from pathlib import Path
import re
import subprocess
import time
import uuid as uuid_module

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
        if not names:
            raise RecoveryError("interface-missing")
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

    def _module_devices(self, module_name):
        if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", module_name):
            raise RecoveryError("module-changed")
        try:
            module = (self.sys / "module" / module_name).resolve(strict=True)
            if module != (self.sys / "module" / module_name).absolute():
                raise OSError
            bound = set()
            for link in (module / "drivers").iterdir():
                driver = link.resolve(strict=True)
                for entry in driver.iterdir():
                    if entry.is_symlink():
                        target = entry.resolve(strict=True)
                        if target.is_relative_to(self.sys / "devices"):
                            bound.add(target)
            return bound
        except (OSError, RuntimeError):
            raise RecoveryError("module-changed") from None

    def _device_fingerprint(self, device, module):
        try:
            relative = device.relative_to(self.sys)
            raw = (device / "uevent").read_bytes()
            if len(raw) > 65536:
                return ""
            text = raw.decode("ascii")
            values = {
                line.split("=", 1)[0] for line in text.splitlines() if "=" in line
            }
            if not values.intersection({"MODALIAS", "PCI_ID", "PRODUCT"}):
                return ""
            material = (
                str(relative).encode("utf-8")
                + b"\0"
                + module.encode("ascii")
                + b"\0"
                + raw
            )
            return hashlib.sha256(material).hexdigest()
        except (OSError, UnicodeError, ValueError):
            return ""

    def module_identity(self, interface):
        try:
            device = (self.sys / "class/net" / interface / "device").resolve(
                strict=True
            )
            module = (device / "driver/module").resolve(strict=True)
            if module.parent != self.sys / "module" or not re.fullmatch(
                r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}", module.name
            ):
                raise OSError
            bound = self._module_devices(module.name)
            if device not in bound:
                raise OSError
            info = device.stat()
            return {
                "module": module.name,
                "module_devices": len(bound),
                "device_id": str(device),
                "_device_path": str(device.relative_to(self.sys)),
                "_device_inode": [info.st_dev, info.st_ino],
                "_device_fingerprint": self._device_fingerprint(device, module.name),
            }
        except (OSError, RuntimeError, RecoveryError):
            return {
                "module": "",
                "module_devices": 0,
                "device_id": "",
                "_device_path": "",
                "_device_inode": [],
                "_device_fingerprint": "",
            }

    def module_info(self, interface):
        identity = self.module_identity(interface)
        return (
            identity["module"],
            identity["module_devices"],
            identity["device_id"],
        )

    def cached_snapshot(self, settings, cached):
        interface = cached["interface"]
        interface_root = self.sys / "class/net" / interface
        if interface_root.exists() or interface_root.is_symlink():
            raise RecoveryError("cached-interface-changed")
        if settings.interface and settings.interface != interface:
            raise RecoveryError("cached-interface-changed")
        requested = self.sys / cached["device_path"]
        try:
            device = requested.resolve(strict=True)
        except (OSError, RuntimeError):
            raise RecoveryError("cached-device-missing") from None
        try:
            if device != requested.absolute() or not device.is_relative_to(
                self.sys / "devices"
            ):
                raise RecoveryError("cached-device-changed")
            info = device.stat()
        except OSError:
            raise RecoveryError("cached-device-missing") from None
        if [info.st_dev, info.st_ino] != cached["device_inode"] or (
            self._device_fingerprint(device, cached["module"])
            != cached["device_fingerprint"]
        ):
            raise RecoveryError("cached-device-changed")
        try:
            bound = self._module_devices(cached["module"])
        except RecoveryError:
            raise RecoveryError("module-changed") from None
        if any(bound_device != device for bound_device in bound):
            raise RecoveryError("shared-module")
        try:
            driver = device / "driver"
            if driver.exists() or driver.is_symlink():
                current_module = (driver / "module").resolve(strict=True)
                if (
                    current_module
                    != (self.sys / "module" / cached["module"]).absolute()
                ):
                    raise RecoveryError("module-changed")
        except (OSError, RuntimeError):
            raise RecoveryError("module-changed") from None
        try:
            connection_uuid, profile_fingerprint = self.connection_identity(
                settings, interface, cached["connection_uuid"]
            )
        except RecoveryError:
            raise RecoveryError("profile-changed") from None
        if (
            connection_uuid != cached["connection_uuid"]
            or not cached.get("profile_fingerprint")
            or profile_fingerprint != cached["profile_fingerprint"]
        ):
            raise RecoveryError("profile-changed")
        return {
            "status": "missing",
            "reason": "interface-missing",
            "healthy": False,
            "recoverable": True,
            "interface": interface,
            "connection_uuid": connection_uuid,
            "module": cached["module"],
            "module_devices": len(bound),
            "device_id": str(device),
            "missing": True,
            "_device_path": cached["device_path"],
            "_device_inode": cached["device_inode"],
            "_device_fingerprint": cached["device_fingerprint"],
            "_profile_fingerprint": cached["profile_fingerprint"],
        }

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
        if snapshot.get("missing"):
            module = snapshot["module"]
            count = snapshot["module_devices"]
            if not _hardware_evidence(snapshot):
                return "device-identity-unavailable"
        else:
            current_identity = self.module_identity(snapshot["interface"])
            module = current_identity["module"]
            count = current_identity["module_devices"]
            identity = current_identity["device_id"]
            if (
                not module
                or module != snapshot["module"]
                or identity != snapshot["device_id"]
            ):
                return "module-changed"
            if not _hardware_evidence(snapshot) or not _hardware_evidence(current_identity):
                return "device-identity-unavailable"
            if (
                current_identity["_device_inode"] != snapshot["_device_inode"]
                or current_identity["_device_fingerprint"] != snapshot["_device_fingerprint"]
            ):
                return "identity-changed"
        if count != 1:
            if snapshot.get("missing") and count == 0:
                return None
            return "shared-module"
        return None

    def connection_identity(self, settings, interface, active):
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
        fingerprint = hashlib.sha256(
            json.dumps(
                [uuid, rows[0][1], rows[0][2], bound],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return uuid, fingerprint

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
            "active_connection_uuid": None,
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
        if values[1] and values[1] != "--":
            result["active_connection_uuid"] = _uuid(values[1])
        if state in (10, 20) or 40 <= state <= 90 or state == 110:
            label = {10: "unmanaged", 20: "unavailable"}.get(state, "connecting")
            return {**result, "status": label, "reason": label}
        if state not in (30, 100, 120):
            return {**result, "reason": "unknown-state"}
        connection_uuid, profile_fingerprint = self.connection_identity(
            settings, interface, values[1]
        )
        result["connection_uuid"] = connection_uuid
        result["_profile_fingerprint"] = profile_fingerprint
        result.update(self.module_identity(interface))
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


def _public_snapshot(snapshot):
    return {key: value for key, value in snapshot.items() if not key.startswith("_")}


def _cached_identity(snapshot):
    if (
        snapshot.get("module")
        and snapshot.get("module_devices") == 1
        and snapshot.get("connection_uuid")
        and snapshot.get("_device_path")
        and len(snapshot.get("_device_inode", [])) == 2
        and snapshot.get("_device_fingerprint")
        and snapshot.get("_profile_fingerprint")
    ):
        return {
            "interface": snapshot["interface"],
            "connection_uuid": snapshot["connection_uuid"],
            "module": snapshot["module"],
            "device_path": snapshot["_device_path"],
            "device_inode": snapshot["_device_inode"],
            "device_fingerprint": snapshot["_device_fingerprint"],
            "profile_fingerprint": snapshot["_profile_fingerprint"],
        }
    return None


def _new_id():
    return str(uuid_module.uuid4())


def _clock_value(clock, context):
    try:
        value = clock()
    except Exception:
        raise RecoveryError("state-clock") from None
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value < 0
        or value < context.get("last_epoch", 0)
    ):
        raise RecoveryError("state-clock-regressed")
    context["last_epoch"] = value
    return value


def _timestamp(epoch):
    try:
        return datetime.fromtimestamp(epoch, timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        raise RecoveryError("state-clock") from None


def _error_record(error):
    return {
        "stage": error.stage,
        "command": error.command,
        "returncode": error.returncode,
    }


def _hardware_evidence(snapshot):
    inode = snapshot.get("_device_inode")
    fingerprint = snapshot.get("_device_fingerprint")
    return (
        isinstance(inode, list)
        and len(inode) == 2
        and all(type(value) is int and value >= 0 for value in inode)
        and isinstance(fingerprint, str)
        and re.fullmatch(r"[0-9a-f]{64}", fingerprint) is not None
    )


def _diagnosis(snapshot):
    keys = (
        "status",
        "reason",
        "healthy",
        "recoverable",
        "interface",
        "connection_uuid",
        "active_connection_uuid",
        "nm_state",
        "gateway",
        "missing",
    )
    return {key: snapshot[key] for key in keys if key in snapshot}


def _audit_event(state_io, root, epoch, event, status, run_id, **values):
    record = {
        "version": 1,
        "epoch": epoch,
        "timestamp": _timestamp(epoch),
        "event": event,
        "status": status,
        "run_id": run_id,
    }
    record.update({key: value for key, value in values.items() if value is not None})
    state_io.audit(root, record)


def read_recovery_logs(
    *, home=None, limit=100, status=None, incident_id=None
) -> list[dict]:
    """Return the newest retained, validated recovery events in chronological order."""
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise RecoveryError("log-filter")
    if status is not None and (
        not isinstance(status, str)
        or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", status) is None
    ):
        raise RecoveryError("log-filter")
    if incident_id is not None and (
        not isinstance(incident_id, str)
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            incident_id,
        )
        is None
    ):
        raise RecoveryError("log-filter")
    from . import recovery_state as state_io

    events = state_io.read_audit(recovery_home(home))
    if status is not None:
        events = [event for event in events if event["status"] == status]
    if incident_id is not None:
        events = [event for event in events if event.get("incident_id") == incident_id]
    return events[-limit:]


def _missing_result(settings, state, error):
    identity = state.get("identity")
    interface = settings.interface or (identity or {}).get("interface", "")
    return {
        "status": "missing",
        "reason": error.stage,
        "healthy": False,
        "recoverable": False,
        "interface": interface,
        "connection_uuid": (identity or {}).get("connection_uuid"),
        "module": (identity or {}).get("module", ""),
        "module_devices": 0,
        "device_id": "",
        "missing": True,
    }


def _execute_recovery(settings, adapter, root, clock, run_id, context, state_io):
    context["phase"] = "lock"
    with state_io.locked(root):
        context["phase"] = "inspection"
        state = state_io.read_state(root, context["last_epoch"])
        context["incident"] = state.get("incident")
        blocked_reason = None
        try:
            snapshot = adapter.inspect(settings)
        except RecoveryError as error:
            if settings.allow_module_reload and error.stage in {
                "interface-missing",
                "interface-not-wireless",
            }:
                if state.get("identity") is None:
                    snapshot = _missing_result(settings, state, error)
                    blocked_reason = "identity-unavailable"
                else:
                    try:
                        snapshot = adapter.cached_snapshot(settings, state["identity"])
                    except RecoveryError as guard_error:
                        snapshot = _missing_result(settings, state, error)
                        blocked_reason = guard_error.stage
            else:
                raise

        observed_at = _clock_value(clock, context)
        incident = state.get("incident")
        if snapshot["healthy"]:
            state["incident"] = None
        else:
            if incident is None:
                incident = {
                    "incident_id": _new_id(),
                    "detected_at": observed_at,
                }
            state["incident"] = incident
        context["incident"] = incident

        candidate = _cached_identity(snapshot)
        if candidate is not None:
            state["identity"] = candidate
        elif snapshot.get("device_id") and not snapshot.get("missing"):
            state["identity"] = None
        state["last_seen"] = observed_at
        state_io.write_state(root, state)
        ids = {}
        if incident is not None:
            ids = {
                "incident_id": incident["incident_id"],
                "detected_at": incident["detected_at"],
            }
        _audit_event(
            state_io,
            root,
            observed_at,
            "observation",
            snapshot["status"],
            run_id,
            diagnosis=_diagnosis(snapshot),
            **ids,
        )

        base = {
            **_public_snapshot(snapshot),
            "ok": snapshot["healthy"],
            "performed": False,
            "run_id": run_id,
            "run_started_at": context["started_at"],
            **ids,
        }

        def finish(result):
            finished_at = _clock_value(clock, context)
            result = {**result, "finished_at": finished_at}
            state["last_seen"] = finished_at
            state["last_result"] = {
                key: result[key] for key in ("status", "reason", "ok", "performed")
            }
            state_io.write_state(root, state)
            _audit_event(
                state_io,
                root,
                finished_at,
                "run-finished",
                result["status"],
                run_id,
                performed=result["performed"],
                reason=result.get("reason"),
                outcome=result["status"],
                diagnosis=_diagnosis(snapshot),
                **ids,
            )
            return result

        if blocked_reason is not None:
            return finish({**base, "status": "blocked", "reason": blocked_reason})
        if not snapshot["recoverable"]:
            return finish(base)
        if not adapter.foreground_safe(snapshot["interface"]):
            return finish({**base, "status": "blocked", "reason": "ssh-target"})
        if settings.allow_module_reload:
            blocked = adapter.reload_guard(settings, snapshot)
            if blocked:
                return finish({**base, "status": "blocked", "reason": blocked})

        actions = (
            ["module-unload", "module-load", "device-ready", "reconnect", "postcheck"]
            if settings.allow_module_reload
            else ["rescan", "reconnect", "postcheck"]
        )
        attempt_started_at = _clock_value(clock, context)
        attempts = [
            item
            for item in state["attempts"]
            if item > attempt_started_at - settings.window_seconds
        ]
        reason = None
        if (
            state["last_attempt"] is not None
            and attempt_started_at - state["last_attempt"] < settings.cooldown
        ):
            reason = "cooldown"
        elif len(attempts) >= settings.max_attempts:
            reason = "budget-exhausted"
        if reason:
            return finish({**base, "status": "blocked", "reason": reason})

        attempt_id = _new_id()
        context.update(phase="attempt", attempt_id=attempt_id)
        state.update(
            attempts=attempts + [attempt_started_at],
            last_attempt=attempt_started_at,
            last_seen=attempt_started_at,
            active_attempt={
                "attempt_id": attempt_id,
                "run_id": run_id,
                "incident_id": incident["incident_id"],
                "started_at": attempt_started_at,
                "actions": actions,
            },
        )
        state_io.write_state(root, state)
        _audit_event(
            state_io,
            root,
            attempt_started_at,
            "attempt-started",
            "started",
            run_id,
            attempt_id=attempt_id,
            actions=actions,
            diagnosis=_diagnosis(snapshot),
            **ids,
        )

        def stage_call(stage, args, *, privileged=False, check=True, timeout=10):
            _audit_event(
                state_io,
                root,
                _clock_value(clock, context),
                "stage-started",
                "started",
                run_id,
                incident_id=incident["incident_id"],
                attempt_id=attempt_id,
                stage=stage,
            )
            try:
                result = adapter.call(
                    args,
                    stage,
                    privileged=privileged,
                    check=check,
                    timeout=timeout,
                )
            except RecoveryError as error:
                ended_at = _clock_value(clock, context)
                _audit_event(
                    state_io,
                    root,
                    ended_at,
                    "stage-finished",
                    "failed",
                    run_id,
                    incident_id=incident["incident_id"],
                    attempt_id=attempt_id,
                    stage=stage,
                    error=_error_record(error),
                )
                raise
            ended_at = _clock_value(clock, context)
            _audit_event(
                state_io,
                root,
                ended_at,
                "stage-finished",
                "succeeded" if result.returncode == 0 else "failed",
                run_id,
                incident_id=incident["incident_id"],
                attempt_id=attempt_id,
                stage=stage,
                returncode=result.returncode,
            )
            return result

        interface = snapshot["interface"]
        connection_uuid = snapshot["connection_uuid"]
        try:
            if settings.allow_module_reload:
                stage_call(
                    "module-unload",
                    ["modprobe", "-r", snapshot["module"]],
                    privileged=True,
                    timeout=20,
                )
                stage_call(
                    "module-load",
                    ["modprobe", snapshot["module"]],
                    privileged=True,
                    timeout=20,
                )
                stage_call(
                    "device-ready",
                    ["udevadm", "settle", "--timeout=10"],
                    timeout=15,
                )
            else:
                stage_call(
                    "rescan",
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
                    privileged=True,
                    timeout=25,
                )
            stage_call(
                "reconnect",
                [
                    "nmcli",
                    "--wait",
                    "30",
                    "connection",
                    "up",
                    "uuid",
                    connection_uuid,
                    "ifname",
                    interface,
                ],
                privileged=True,
                check=False,
                timeout=35,
            )
            _audit_event(
                state_io,
                root,
                _clock_value(clock, context),
                "stage-started",
                "started",
                run_id,
                incident_id=incident["incident_id"],
                attempt_id=attempt_id,
                stage="postcheck",
            )
            try:
                after = adapter.inspect(settings)
            except RecoveryError as error:
                postchecked_at = _clock_value(clock, context)
                _audit_event(
                    state_io,
                    root,
                    postchecked_at,
                    "stage-finished",
                    "failed",
                    run_id,
                    incident_id=incident["incident_id"],
                    attempt_id=attempt_id,
                    stage="postcheck",
                    error=_error_record(error),
                )
                raise
            postchecked_at = _clock_value(clock, context)
            same_identity = (
                after.get("interface") == interface
                and after.get("connection_uuid") == connection_uuid
                and after.get("active_connection_uuid") == connection_uuid
                and after.get("_profile_fingerprint")
                == snapshot.get("_profile_fingerprint")
                and (
                    not snapshot.get("module")
                    or _hardware_evidence(snapshot)
                    and _hardware_evidence(after)
                    and after.get("module") == snapshot.get("module")
                    and after.get("device_id") == snapshot.get("device_id")
                    and after.get("_device_inode") == snapshot.get("_device_inode")
                    and after.get("_device_fingerprint")
                    == snapshot.get("_device_fingerprint")
                )
            )
            recovered = after["healthy"] and same_identity
            _audit_event(
                state_io,
                root,
                postchecked_at,
                "stage-finished",
                "succeeded" if recovered else "failed",
                run_id,
                incident_id=incident["incident_id"],
                attempt_id=attempt_id,
                stage="postcheck",
                diagnosis=_diagnosis(after),
            )
        except RecoveryError as error:
            finished_at = _clock_value(clock, context)
            state["active_attempt"] = None
            state["last_seen"] = finished_at
            state["failures"] = min(state["failures"] + 1, 1_000_000)
            state["last_result"] = {
                "status": "failed",
                "reason": error.stage,
                "ok": False,
                "performed": True,
            }
            state_io.write_state(root, state)
            _audit_event(
                state_io,
                root,
                finished_at,
                "attempt-finished",
                "failed",
                run_id,
                incident_id=incident["incident_id"],
                attempt_id=attempt_id,
                performed=True,
                reason=error.stage,
                outcome="failed",
                error=_error_record(error),
            )
            raise

        status = "recovered" if recovered else "failed"
        reason = (
            ("module-reloaded" if settings.allow_module_reload else "reconnected")
            if recovered
            else ("identity-changed" if after["healthy"] else "postcheck-failed")
        )
        finished_at = _clock_value(clock, context)
        result = {
            **_public_snapshot(after),
            "ok": recovered,
            "performed": True,
            "status": status,
            "reason": reason,
            "run_id": run_id,
            "incident_id": incident["incident_id"],
            "attempt_id": attempt_id,
            "detected_at": incident["detected_at"],
            "run_started_at": context["started_at"],
            "attempt_started_at": attempt_started_at,
            "finished_at": finished_at,
        }
        if recovered:
            result["recovered_at"] = postchecked_at
            state["incident"] = None
            state["failures"] = 0
        else:
            state["failures"] = min(state["failures"] + 1, 1_000_000)
        candidate = _cached_identity(after)
        if candidate is not None:
            state["identity"] = candidate
        state["active_attempt"] = None
        state["last_seen"] = finished_at
        state["last_result"] = {
            key: result[key] for key in ("status", "reason", "ok", "performed")
        }
        state_io.write_state(root, state)
        terminal_values = {
            "incident_id": incident["incident_id"],
            "attempt_id": attempt_id,
            "detected_at": incident["detected_at"],
            "recovered_at": result.get("recovered_at"),
            "performed": True,
            "reason": reason,
            "outcome": status,
            "diagnosis": _diagnosis(after),
        }
        _audit_event(
            state_io,
            root,
            finished_at,
            "attempt-finished",
            status,
            run_id,
            **terminal_values,
        )
        _audit_event(
            state_io,
            root,
            finished_at,
            "run-finished",
            status,
            run_id,
            **terminal_values,
        )
        return result


def recover_network(
    settings=None, *, execute=False, home=None, clock=None, **dependencies
) -> dict:
    """Run one proven recovery path, never an unattended repair loop."""
    if type(execute) is not bool:
        raise RecoveryError("invalid-execute")
    if not execute:
        settings = settings or load_recovery_settings(home=home)
        adapter = _Adapter(**dependencies)
        snapshot = adapter.inspect(settings)
        base = {
            **_public_snapshot(snapshot),
            "ok": snapshot["healthy"],
            "performed": False,
        }
        if not snapshot["recoverable"]:
            return base
        if not adapter.foreground_safe(snapshot["interface"]):
            return {**base, "status": "blocked", "reason": "ssh-target"}
        if settings.allow_module_reload:
            blocked = adapter.reload_guard(settings, snapshot)
            if blocked:
                return {**base, "status": "blocked", "reason": blocked}
        plan = (
            ["module-unload", "module-load", "device-ready", "reconnect", "postcheck"]
            if settings.allow_module_reload
            else ["rescan", "reconnect", "postcheck"]
        )
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
    run_id = _new_id()
    context = {"last_epoch": 0, "phase": "setup"}
    started_at = _clock_value(clock, context)
    context["started_at"] = started_at
    _audit_event(state_io, root, started_at, "run-started", "started", run_id)
    try:
        settings = settings or load_recovery_settings(home=home)
        adapter = _Adapter(**dependencies)
        return _execute_recovery(
            settings, adapter, root, clock, run_id, context, state_io
        )
    except RecoveryError as error:
        finished_at = _clock_value(clock, context)
        incident = context.get("incident")
        attempt_id = context.get("attempt_id")
        status = (
            "blocked"
            if context.get("phase") == "lock"
            else "failed"
            if attempt_id is not None
            else "inspection-error"
        )
        values = {
            "attempt_id": attempt_id,
            "performed": attempt_id is not None,
            "reason": error.stage,
            "outcome": status,
            "error": _error_record(error),
        }
        if incident is not None:
            values.update(
                incident_id=incident["incident_id"],
                detected_at=incident["detected_at"],
            )
        _audit_event(
            state_io,
            root,
            finished_at,
            "run-finished",
            status,
            run_id,
            **values,
        )
        raise
