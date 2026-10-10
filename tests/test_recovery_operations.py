"""Synthetic NetworkManager/sysfs tests; no command reaches the host."""

from dataclasses import replace
import json
import os
import shutil
import subprocess

import pytest

from test_recovery_core import recovery as recovery


UUID = "11111111-2222-3333-4444-555555555555"
GATEWAY = "192.0.2.1"
PEER = "198.51.100.2"


class Network:
    def __init__(self):
        self.calls = []
        self.mutations = []
        self.state = 100
        self.radio = "enabled"
        self.gateway_ok = False
        self.extra_ok = False
        self.reconnect_ok = False
        self.reload_ok = True
        self.loaded = False
        self.rescue_dev = "eth0"
        self.ssh_dev = "eth0"
        self.profiles = [(UUID, "802-11-wireless", "saved-network")]
        self.current_uuid = UUID
        self.bound_interface = "wlan0"
        self.fail = {}
        self.before_mutation = None
        self.on_module_load = None

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        assert not kwargs.get("shell")
        assert kwargs["timeout"] <= 60
        assert kwargs["env"]["LC_ALL"] == "C"
        assert "LD_PRELOAD" not in kwargs["env"]
        assert kwargs["stdin"] == subprocess.DEVNULL
        privileged = argv[:3] == ["sudo", "-n", "--"]
        command = argv[3:] if privileged else argv
        if privileged:
            if self.before_mutation:
                self.before_mutation(command)
            self.mutations.append(command)
        text, rc = "", 0
        if tuple(command) in self.fail:
            rc, text = self.fail[tuple(command)]
        elif command == ["nmcli", "-t", "-f", "RUNNING,WIFI-HW,WIFI", "general"]:
            text = f"running:enabled:{self.radio}\n"
        elif command == ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"]:
            text = "wlan0:wifi:connected\neth0:ethernet:connected\nlo:loopback:connected\ntun0:tun:connected\n"
        elif command == [
            "nmcli",
            "-g",
            "GENERAL.STATE,GENERAL.CON-UUID,IP4.GATEWAY,IP6.GATEWAY",
            "device",
            "show",
            "wlan0",
        ]:
            text = f"{self.state} (state)\n{self.current_uuid}\n{GATEWAY}\n--\n"
        elif command == ["nmcli", "-t", "-f", "UUID,TYPE,NAME", "connection", "show"]:
            text = "\n".join(":".join(p) for p in self.profiles) + "\n"
        elif command == [
            "nmcli",
            "-g",
            "connection.interface-name",
            "connection",
            "show",
            "uuid",
            UUID,
        ]:
            text = self.bound_interface + "\n"
        elif command[:2] == ["ping", "-n"]:
            assert command[command.index("-I") + 1] == "wlan0"
            rc = (
                0
                if (self.gateway_ok if command[-1] == GATEWAY else self.extra_ok)
                else 1
            )
        elif command[:4] == ["ip", "-j", "route", "get"]:
            dev = self.rescue_dev if command[-1] == PEER else self.ssh_dev
            text = json.dumps(
                [{"dst": command[-1], "dev": dev, "prefsrc": "198.51.100.1"}]
            )
        elif command == [
            "nmcli",
            "--wait",
            "20",
            "device",
            "wifi",
            "rescan",
            "ifname",
            "wlan0",
        ]:
            pass
        elif command == [
            "nmcli",
            "--wait",
            "30",
            "connection",
            "up",
            "uuid",
            UUID,
            "ifname",
            "wlan0",
        ]:
            self.gateway_ok = self.reconnect_ok or (self.loaded and self.reload_ok)
            rc = 0 if self.gateway_ok else 4
        elif command == ["modprobe", "-r", "test_wifi"]:
            pass
        elif command == ["modprobe", "test_wifi"]:
            self.loaded = True
            if self.on_module_load:
                self.on_module_load()
        elif command == ["udevadm", "settle", "--timeout=10"]:
            assert not privileged
        else:
            raise AssertionError(f"unexpected command: {command!r}")
        return subprocess.CompletedProcess(
            argv, rc, text, "SECRET=password authorization private-stderr"
        )


@pytest.fixture
def lab(recovery, tmp_path):
    root = tmp_path / "sys"
    module = root / "module" / "test_wifi"
    driver = root / "bus" / "pci" / "drivers" / "test_wifi"
    device = root / "devices" / "pci0000:00" / "0000:01:00.0"
    ethernet = root / "devices" / "pci0000:00" / "0000:02:00.0"
    for path in (module / "drivers", driver, device, ethernet):
        path.mkdir(parents=True, exist_ok=True)
    (module / "drivers" / "pci:test_wifi").symlink_to(driver)
    (driver / "module").symlink_to(module)
    (driver / device.name).symlink_to(device)
    (device / "driver").symlink_to(driver)
    (device / "uevent").write_text(
        "DRIVER=test_wifi\nMODALIAS=pci:test_wifi\nPCI_ID=1234:5678\n"
    )
    for name, target in (("wlan0", device), ("eth0", ethernet)):
        interface = root / "class" / "net" / name
        interface.mkdir(parents=True)
        (interface / "device").symlink_to(target)
        (interface / "type").write_text("1\n")
        (interface / "carrier").write_text("1\n")
    (root / "class" / "net" / "wlan0" / "wireless").mkdir()
    net = Network()
    settings = recovery.RecoverySettings(rescue_peer=PEER)
    deps = {"runner": net, "sys_root": root, "environ": {}, "platform_name": "Linux"}
    return recovery, net, settings, deps, tmp_path / "home"


def test_check_api_exists(recovery):
    assert callable(getattr(recovery, "check_recovery", None)), "check API missing"
    assert callable(getattr(recovery, "recover_network", None)), "recover API missing"


def test_healthy_gateway_with_failed_external_probe_is_not_repaired(lab):
    api, net, settings, deps, home = lab
    net.gateway_ok = True
    settings = replace(settings, probe_host="203.0.113.9")
    checked = api.check_recovery(settings, **deps)
    assert checked["healthy"] and not checked["recoverable"]
    assert checked["reason"] == "external-probe-failed"
    result = api.recover_network(settings, execute=True, home=home, **deps)
    assert result["ok"] and not result["performed"]
    assert not net.mutations
    assert api.read_recovery_logs(home=home)[-1]["status"] == "healthy"


def test_dry_run_never_creates_state_or_runs_privileged(lab):
    api, net, settings, deps, home = lab
    result = api.recover_network(settings, home=home, **deps)
    assert result["status"] == "dry-run"
    assert not result["performed"] and not home.exists() and not net.mutations
    assert result["connection_uuid"] == UUID


@pytest.mark.parametrize(
    "state,status",
    [
        (10, "unmanaged"),
        (20, "unavailable"),
        (40, "connecting"),
        (90, "connecting"),
        (110, "connecting"),
    ],
)
def test_nm_special_states_are_not_repaired(lab, state, status):
    api, net, settings, deps, home = lab
    net.state = state
    checked = api.check_recovery(settings, **deps)
    assert checked["status"] == status and not checked["recoverable"]
    assert not api.recover_network(settings, execute=True, home=home, **deps)[
        "performed"
    ]
    assert not net.mutations
    assert api.read_recovery_logs(home=home)[-1]["status"] == status


def test_disabled_radio_not_repaired(lab):
    api, net, settings, deps, home = lab
    net.radio = "disabled"
    assert api.check_recovery(settings, **deps)["status"] == "disabled"
    assert not api.recover_network(settings, execute=True, home=home, **deps)[
        "performed"
    ]
    assert not net.mutations


def test_linux_restriction_is_runtime_only(lab):
    api, net, settings, deps, _ = lab
    deps["platform_name"] = "Darwin"
    with pytest.raises(api.RecoveryError, match="platform"):
        api.check_recovery(settings, **deps)
    assert not net.calls


def test_ambiguous_kernel_wifi_not_selected(lab):
    api, net, settings, deps, _ = lab
    (deps["sys_root"] / "class" / "net" / "wlan1" / "wireless").mkdir(parents=True)
    with pytest.raises(api.RecoveryError, match="interface"):
        api.check_recovery(settings, **deps)
    assert not net.mutations


def test_saved_connection_uuid_only_and_successful_reconnect(lab):
    api, net, settings, deps, home = lab
    settings = replace(settings, connection="saved-network")
    net.reconnect_ok = True
    result = api.recover_network(
        settings, execute=True, home=home, clock=lambda: 1000, **deps
    )
    assert result["ok"] and result["status"] == "recovered"
    assert [c[0] for c in net.mutations] == ["nmcli", "nmcli"]
    assert "saved-network" not in repr(net.mutations)
    assert net.mutations[-1] == [
        "nmcli",
        "--wait",
        "30",
        "connection",
        "up",
        "uuid",
        UUID,
        "ifname",
        "wlan0",
    ]
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("bad_uuid", ["--help", "x;id", "../module", "123"])
def test_untrusted_nm_uuid_never_becomes_root_argv(lab, bad_uuid):
    api, net, settings, deps, home = lab
    net.profiles = [(bad_uuid, "802-11-wireless", "saved-network")]
    net.current_uuid = bad_uuid
    with pytest.raises(api.RecoveryError):
        api.recover_network(settings, execute=True, home=home, **deps)
    assert not net.mutations


def test_current_ssh_on_target_refuses_all_mutations(lab):
    api, net, settings, deps, home = lab
    deps["environ"] = {"SSH_CONNECTION": "203.0.113.10 50000 192.0.2.5 22"}
    net.ssh_dev = "wlan0"
    result = api.recover_network(settings, execute=True, home=home, **deps)
    assert result["status"] == "blocked" and result["reason"] == "ssh-target"
    assert not net.mutations
    assert api.read_recovery_logs(home=home)[-1]["status"] == "blocked"


def test_reload_requires_explicit_authorization(lab):
    api, net, settings, deps, home = lab
    result = api.recover_network(
        settings, execute=True, home=home, clock=lambda: 1000, **deps
    )
    assert not result["ok"]
    assert all(c[0] != "modprobe" for c in net.mutations)


def test_guarded_module_reload_uses_derived_module_without_force(lab):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    result = api.recover_network(
        settings, execute=True, home=home, clock=lambda: 1000, **deps
    )
    assert result["ok"]
    assert net.mutations[0] == ["modprobe", "-r", "test_wifi"]
    assert [c for c in net.mutations if c[0] == "modprobe"] == [
        ["modprobe", "-r", "test_wifi"],
        ["modprobe", "test_wifi"],
    ]
    assert net.mutations[-1][0] == "nmcli"
    assert "force" not in repr(net.mutations)


@pytest.mark.parametrize("dev", ["wlan0", "lo", "tun0"])
def test_non_ethernet_rescue_never_authorizes_module_reload(lab, dev):
    api, net, settings, deps, home = lab
    net.rescue_dev = dev
    result = api.recover_network(
        replace(settings, allow_module_reload=True),
        execute=True,
        home=home,
        clock=lambda: 1000,
        **deps,
    )
    assert not result["ok"]
    assert all(c[0] != "modprobe" for c in net.mutations)


def test_rescue_requires_carrier_and_physical_device(lab):
    api, net, settings, deps, home = lab
    (deps["sys_root"] / "class" / "net" / "eth0" / "carrier").write_text("0\n")
    result = api.recover_network(
        replace(settings, allow_module_reload=True),
        execute=True,
        home=home,
        clock=lambda: 1000,
        **deps,
    )
    assert not result["ok"]
    assert all(c[0] != "modprobe" for c in net.mutations)


def test_shared_driver_non_network_device_blocks_reload(lab):
    api, net, settings, deps, home = lab
    device = deps["sys_root"] / "devices" / "pci0000:00" / "0000:03:00.0"
    driver = deps["sys_root"] / "bus" / "pci" / "drivers" / "test_wifi"
    device.mkdir()
    (device / "driver").symlink_to(driver)
    (driver / device.name).symlink_to(device)
    result = api.recover_network(
        replace(settings, allow_module_reload=True),
        execute=True,
        home=home,
        clock=lambda: 1000,
        **deps,
    )
    assert not result["ok"] and result["reason"] == "shared-module"
    assert all(c[0] != "modprobe" for c in net.mutations)


@pytest.mark.parametrize(
    "command,stage",
    [
        (
            ("nmcli", "--wait", "20", "device", "wifi", "rescan", "ifname", "wlan0"),
            "rescan",
        ),
        (("modprobe", "-r", "test_wifi"), "module-unload"),
        (("modprobe", "test_wifi"), "module-load"),
        (("udevadm", "settle", "--timeout=10"), "device-ready"),
    ],
)
def test_mutation_errors_are_stage_only(lab, command, stage):
    api, net, settings, deps, home = lab
    net.fail[command] = (7, "SECRET=password")
    with pytest.raises(api.RecoveryError) as error:
        api.recover_network(
            replace(settings, allow_module_reload=command[0] != "nmcli"),
            execute=True,
            home=home,
            clock=lambda: 1000,
            **deps,
        )
    assert str(error.value) == f"{stage}: {command[0]} (returncode=7)"
    assert "SECRET" not in str(error.value)
    if stage == "module-unload":
        assert ["modprobe", "test_wifi"] not in net.mutations


def test_safe_environment_rejects_loader_and_path_injection(lab):
    api, net, settings, deps, home = lab
    deps["environ"] = {"PATH": "/attacker", "LD_PRELOAD": "/attacker.so"}
    net.reconnect_ok = True
    assert api.recover_network(
        settings, execute=True, home=home, clock=lambda: 1000, **deps
    )["ok"]


def test_budget_is_fsynced_before_first_recovery_command(lab, monkeypatch):
    api, net, settings, deps, home = lab
    events = []
    original = os.fsync

    def fsync(fd):
        events.append("fsync")
        return original(fd)

    monkeypatch.setattr(os, "fsync", fsync)

    def verify(command):
        state = json.loads((api.recovery_home(home) / "state.json").read_text())
        assert state["attempts"] == [1000]
        assert state["last_attempt"] == 1000
        assert len(events) >= 2

    net.before_mutation = verify
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)


def test_budget_and_cooldown_survive_new_calls(lab):
    api, net, settings, deps, home = lab
    settings = replace(settings, max_attempts=2, cooldown=10, window_seconds=100)
    first = api.recover_network(
        settings, execute=True, home=home, clock=lambda: 1000, **deps
    )
    assert not first["ok"]
    count = len(net.mutations)
    assert (
        api.recover_network(
            settings, execute=True, home=home, clock=lambda: 1005, **deps
        )["reason"]
        == "cooldown"
    )
    assert len(net.mutations) == count
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1010, **deps)
    count = len(net.mutations)
    assert (
        api.recover_network(
            settings, execute=True, home=home, clock=lambda: 1020, **deps
        )["reason"]
        == "budget-exhausted"
    )
    assert len(net.mutations) == count
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1100, **deps)
    state = json.loads((api.recovery_home(home) / "state.json").read_text())
    assert state["attempts"] == [1010, 1100]


@pytest.mark.parametrize(
    "content", ["{", "{}", '{"version":1,"last_seen":NaN}', "[]", "null"]
)
def test_corrupt_state_does_not_reset_budget(lab, content):
    api, net, settings, deps, home = lab
    state_dir = api.recovery_home(home)
    state_dir.mkdir(parents=True, mode=0o700)
    state = state_dir / "state.json"
    state.write_text(content)
    state.chmod(0o600)
    with pytest.raises(api.RecoveryError, match="state"):
        api.recover_network(
            settings, execute=True, home=home, clock=lambda: 1000, **deps
        )
    assert not net.mutations and state.read_text() == content


def test_clock_rollback_does_not_reset_budget(lab):
    api, net, settings, deps, home = lab
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)
    count = len(net.mutations)
    with pytest.raises(api.RecoveryError, match="clock"):
        api.recover_network(
            settings, execute=True, home=home, clock=lambda: 999, **deps
        )
    assert len(net.mutations) == count


def test_fsync_failure_refuses_every_mutation(lab, monkeypatch):
    api, net, settings, deps, home = lab

    def denied(fd):
        raise OSError("SECRET")

    monkeypatch.setattr(os, "fsync", denied)
    with pytest.raises(api.RecoveryError, match="state") as error:
        api.recover_network(
            settings, execute=True, home=home, clock=lambda: 1000, **deps
        )
    assert "SECRET" not in str(error.value) and not net.mutations


def test_mutation_lock_conflict_does_not_run_commands(lab):
    import fcntl

    api, net, settings, deps, home = lab
    state_dir = api.recovery_home(home)
    state_dir.mkdir(parents=True, mode=0o700)
    with (state_dir / "mutation.lock").open("w") as handle:
        os.chmod(handle.name, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(api.RecoveryError, match="lock"):
            api.recover_network(
                settings, execute=True, home=home, clock=lambda: 1000, **deps
            )
    assert not net.mutations


def _remove_wireless_interface(deps):
    shutil.rmtree(deps["sys_root"] / "class" / "net" / "wlan0")


def _restore_wireless_interface(deps):
    root = deps["sys_root"]
    interface = root / "class" / "net" / "wlan0"
    interface.mkdir(parents=True)
    (interface / "device").symlink_to(root / "devices" / "pci0000:00" / "0000:01:00.0")
    (interface / "type").write_text("1\n")
    (interface / "carrier").write_text("1\n")
    (interface / "wireless").mkdir()


def test_missing_interface_recovers_only_from_verified_cached_identity(lab):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    net.gateway_ok = True
    observed = api.recover_network(
        settings, execute=True, home=home, clock=lambda: 1000, **deps
    )
    assert observed["status"] == "healthy" and not observed["performed"]

    _remove_wireless_interface(deps)
    net.gateway_ok = False
    net.on_module_load = lambda: _restore_wireless_interface(deps)
    result = api.recover_network(
        settings, execute=True, home=home, clock=lambda: 1100, **deps
    )

    assert result["status"] == "recovered" and result["performed"]
    assert [command[0] for command in net.mutations] == [
        "modprobe",
        "modprobe",
        "nmcli",
    ]
    assert net.mutations[0:2] == [
        ["modprobe", "-r", "test_wifi"],
        ["modprobe", "test_wifi"],
    ]


@pytest.mark.parametrize(
    "unsafe,reason",
    [
        ("removed", "cached-device-missing"),
        ("replaced", "cached-device-changed"),
        ("shared", "shared-module"),
        ("profile", "profile-changed"),
        ("route", "rescue-unsafe"),
    ],
)
def test_missing_interface_cached_recovery_fails_closed(lab, unsafe, reason):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    net.gateway_ok = True
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)
    _remove_wireless_interface(deps)
    root = deps["sys_root"]
    device = root / "devices" / "pci0000:00" / "0000:01:00.0"
    driver = root / "bus" / "pci" / "drivers" / "test_wifi"

    if unsafe == "removed":
        shutil.rmtree(device)
    elif unsafe == "replaced":
        shutil.rmtree(device)
        device.mkdir()
        (device / "driver").symlink_to(driver)
        (device / "uevent").write_text(
            "DRIVER=test_wifi\nMODALIAS=pci:replacement\nPCI_ID=9999:0001\n"
        )
    elif unsafe == "shared":
        other = root / "devices" / "pci0000:00" / "0000:03:00.0"
        other.mkdir()
        (other / "driver").symlink_to(driver)
        (driver / other.name).symlink_to(other)
    elif unsafe == "profile":
        net.profiles = [(UUID, "wifi", "replacement")]
    else:
        net.rescue_dev = "lo"

    result = api.recover_network(
        settings, execute=True, home=home, clock=lambda: 1100, **deps
    )
    assert result["status"] == "blocked" and result["reason"] == reason
    assert not net.mutations


def test_missing_interface_without_cached_identity_never_mutates(lab):
    api, net, settings, deps, home = lab
    _remove_wireless_interface(deps)
    result = api.recover_network(
        replace(settings, allow_module_reload=True),
        execute=True,
        home=home,
        clock=lambda: 1000,
        **deps,
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "identity-unavailable"
    assert not net.mutations
