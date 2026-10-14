"""Offline bound-to-unbound sysfs recovery regression."""

from dataclasses import replace
import hashlib
import json
import shutil

import pytest

from test_recovery_core import recovery as recovery
from test_recovery_operations import UUID, lab as lab


def _device(deps):
    return deps["sys_root"] / "devices/pci0000:00/0000:01:00.0"


def _unbound(deps):
    root = deps["sys_root"]
    device = _device(deps)
    shutil.rmtree(root / "class/net/wlan0")
    (device / "driver").unlink()
    (root / "bus/pci/drivers/test_wifi/0000:01:00.0").unlink()
    raw = (device / "uevent").read_text()
    (device / "uevent").write_text(
        "".join(line for line in raw.splitlines(keepends=True) if not line.startswith("DRIVER="))
    )


def _rebound(deps):
    root = deps["sys_root"]
    device = _device(deps)
    driver = root / "bus/pci/drivers/test_wifi"
    if not (device / "driver").exists():
        (device / "driver").symlink_to(driver)
    if not (driver / device.name).exists():
        (driver / device.name).symlink_to(device)
    (device / "uevent").write_text(
        "DRIVER=test_wifi\nMODALIAS=pci:test_wifi\nPCI_ID=1234:5678\n"
    )
    interface = root / "class/net/wlan0"
    interface.mkdir()
    (interface / "device").symlink_to(device)
    (interface / "type").write_text("1\n")
    (interface / "carrier").write_text("1\n")
    (interface / "wireless").mkdir()


def _legacy_hash(deps):
    device = _device(deps)
    return hashlib.sha256(
        b"devices/pci0000:00/0000:01:00.0\0test_wifi\0"
        + (device / "uevent").read_bytes()
    ).hexdigest()


def _bind_without_interface(deps):
    root = deps["sys_root"]
    device = _device(deps)
    driver = root / "bus/pci/drivers/test_wifi"
    (device / "driver").symlink_to(driver)
    (driver / device.name).symlink_to(device)
    (device / "uevent").write_text(
        "DRIVER=test_wifi\nMODALIAS=pci:test_wifi\nPCI_ID=1234:5678\n"
    )


def test_stable_fingerprint_survives_driver_unbind(lab):
    api, _, _, deps, _ = lab
    adapter = api._Adapter(**deps)
    device = _device(deps)
    before = adapter._device_fingerprint(device, "test_wifi")
    _unbound(deps)
    assert before and adapter._device_fingerprint(device, "test_wifi") == before


def test_legacy_bound_cache_recovers_same_unbound_device_and_preserves_budget(lab):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True, cooldown=10)
    net.gateway_ok = True
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)
    path = api.recovery_home(home) / "state.json"
    state = json.loads(path.read_text())
    state["identity"].pop("fingerprint_version", None)
    state["identity"]["device_fingerprint"] = _legacy_hash(deps)
    state["attempts"] = [900]
    state["last_attempt"] = 900
    path.write_text(json.dumps(state) + "\n")
    _unbound(deps)
    net.gateway_ok = False
    net.on_module_load = lambda: _rebound(deps)

    result = api.recover_network(settings, execute=True, home=home, clock=lambda: 1100, **deps)

    assert result["status"] == "recovered" and result["performed"]
    state = json.loads(path.read_text())
    assert state["attempts"] == [900, 1100]
    assert state["identity"]["fingerprint_version"] == 2
    assert [command[0] for command in net.mutations] == ["modprobe", "modprobe", "nmcli"]


def test_healthy_legacy_cache_migrates_without_resetting_history(lab):
    api, net, settings, deps, home = lab
    net.gateway_ok = True
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)
    path = api.recovery_home(home) / "state.json"
    state = json.loads(path.read_text())
    state["identity"].pop("fingerprint_version")
    state["identity"]["device_fingerprint"] = _legacy_hash(deps)
    state["attempts"] = [900]
    state["last_attempt"] = 900
    path.write_text(json.dumps(state) + "\n")
    history = api.read_recovery_logs(home=home)

    result = api.recover_network(settings, execute=True, home=home, clock=lambda: 1001, **deps)
    state = json.loads(path.read_text())
    assert result["status"] == "healthy" and not result["performed"]
    assert state["identity"]["fingerprint_version"] == 2
    assert state["attempts"] == [900] and state["last_attempt"] == 900
    assert api.read_recovery_logs(home=home)[:len(history)] == history
    assert not net.mutations


def test_ambiguous_registered_driver_blocks_legacy_unbound_migration(lab):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    net.gateway_ok = True
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)
    path = api.recovery_home(home) / "state.json"
    state = json.loads(path.read_text())
    state["identity"].pop("fingerprint_version")
    state["identity"]["device_fingerprint"] = _legacy_hash(deps)
    path.write_text(json.dumps(state) + "\n")
    _unbound(deps)
    root = deps["sys_root"]
    second = root / "bus/pci/drivers/second_driver"
    second.mkdir()
    (second / "module").symlink_to(root / "module/test_wifi")
    (root / "module/test_wifi/drivers/pci:second_driver").symlink_to(second)

    result = api.recover_network(settings, execute=True, home=home, clock=lambda: 1100, **deps)
    assert result["status"] == "blocked" and result["reason"] == "cached-device-changed"
    assert not net.mutations


@pytest.mark.parametrize("probe", ["unbound", "bound-without-interface"])
def test_load_rc_zero_without_interface_fails_device_ready_and_can_retry(lab, probe):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True, cooldown=10)
    net.gateway_ok = True
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)
    _unbound(deps)
    net.gateway_ok = False
    if probe == "bound-without-interface":
        net.on_module_load = lambda: _bind_without_interface(deps)

    with pytest.raises(api.RecoveryError, match="device-not-ready"):
        api.recover_network(settings, execute=True, home=home, clock=lambda: 1100, **deps)
    assert not any(command[0] == "nmcli" for command in net.mutations)
    stages = [e for e in api.read_recovery_logs(home=home) if e.get("stage") == "device-ready"]
    assert [e["status"] for e in stages] == ["started", "failed"]
    terminal = api.read_recovery_logs(home=home)[-1]
    assert terminal["status"] == "failed" and terminal["reason"] == "device-not-ready"
    assert "recovered_at" not in terminal
    assert json.loads((api.recovery_home(home) / "state.json").read_text())["attempts"] == [1100]

    blocked = api.recover_network(settings, execute=True, home=home, clock=lambda: 1105, **deps)
    assert blocked["status"] == "blocked" and blocked["reason"] == "cooldown"

    net.on_module_load = lambda: _rebound(deps)
    recovered = api.recover_network(settings, execute=True, home=home, clock=lambda: 1111, **deps)
    assert recovered["status"] == "recovered" and recovered["recovered_at"] >= 1111


@pytest.mark.parametrize("field", ["MODALIAS", "PCI_ID", "PRODUCT", "SERIAL"])
def test_unbound_hardware_field_change_blocks_cached_recovery(lab, field):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    device = _device(deps)
    if field in {"PRODUCT", "SERIAL"}:
        with (device / "uevent").open("a") as stream:
            stream.write(f"{field}=original\n")
    net.gateway_ok = True
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)
    _unbound(deps)
    raw = (device / "uevent").read_text()
    (device / "uevent").write_text(
        raw.replace(next(line for line in raw.splitlines() if line.startswith(field + "=")), field + "=replacement")
    )

    result = api.recover_network(settings, execute=True, home=home, clock=lambda: 1100, **deps)
    assert result["status"] == "blocked" and result["reason"] == "cached-device-changed"
    assert not net.mutations


@pytest.mark.parametrize("change,reason", [
    ("inode", "cached-device-changed"),
    ("path", "cached-device-missing"),
    ("module", "module-changed"),
    ("shared", "shared-module"),
    ("profile", "profile-changed"),
    ("no-rescue", "rescue-required"),
    ("rescue", "rescue-unsafe"),
])
def test_unbound_recovery_rejects_changed_evidence(lab, change, reason):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    net.gateway_ok = True
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)
    _unbound(deps)
    root, device = deps["sys_root"], _device(deps)
    if change == "inode":
        old = device.with_name(device.name + "-old")
        device.rename(old)
        shutil.copytree(old, device, symlinks=True)
    elif change == "path":
        state_path = api.recovery_home(home) / "state.json"
        state = json.loads(state_path.read_text())
        state["identity"]["device_path"] = "devices/pci0000:00/absent"
        state_path.write_text(json.dumps(state) + "\n")
    elif change == "module":
        other = root / "module/other_wifi"
        other.mkdir()
        driver = root / "bus/pci/drivers/other_wifi"
        driver.mkdir()
        (driver / "module").symlink_to(other)
        (device / "driver").symlink_to(driver)
    elif change == "shared":
        other = root / "devices/pci0000:00/0000:03:00.0"
        other.mkdir()
        (root / "bus/pci/drivers/test_wifi/0000:03:00.0").symlink_to(other)
    elif change == "profile":
        net.profiles = [(UUID, "wifi", "different-profile")]
    elif change == "no-rescue":
        settings = replace(settings, rescue_peer="")
    else:
        net.rescue_dev = "lo"

    result = api.recover_network(settings, execute=True, home=home, clock=lambda: 1100, **deps)
    assert result["status"] == "blocked" and result["reason"] == reason
    assert not net.mutations


@pytest.mark.parametrize("change", ["corrupt", "incomplete", "unknown-version", "unknown-fingerprint", "legacy-mismatch"])
def test_invalid_or_unverified_cache_never_mutates(lab, change):
    api, net, settings, deps, home = lab
    settings = replace(settings, allow_module_reload=True)
    net.gateway_ok = True
    api.recover_network(settings, execute=True, home=home, clock=lambda: 1000, **deps)
    path = api.recovery_home(home) / "state.json"
    state = json.loads(path.read_text())
    identity = state["identity"]
    if change == "corrupt":
        path.write_text("{broken\n")
    elif change == "incomplete":
        del identity["device_inode"]
    elif change == "unknown-version":
        identity["fingerprint_version"] = 3
    elif change == "legacy-mismatch":
        identity.pop("fingerprint_version")
        identity["device_fingerprint"] = "0" * 64
    else:
        identity["device_fingerprint"] = "0" * 64
    if change != "corrupt":
        path.write_text(json.dumps(state) + "\n")
    _unbound(deps)

    if change in {"unknown-fingerprint", "legacy-mismatch"}:
        result = api.recover_network(settings, execute=True, home=home, clock=lambda: 1100, **deps)
        assert result["reason"] == "cached-device-changed"
    else:
        with pytest.raises(api.RecoveryError, match="state-invalid"):
            api.recover_network(settings, execute=True, home=home, clock=lambda: 1100, **deps)
    assert not net.mutations
