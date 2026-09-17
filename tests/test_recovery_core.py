"""Offline recovery contracts: never execute a real network command."""

from dataclasses import FrozenInstanceError
import importlib
import importlib.util
import subprocess

import pytest


def test_recovery_api_exists():
    assert importlib.util.find_spec("chatnet.recovery") is not None, (
        "recovery API missing"
    )


@pytest.fixture
def recovery(monkeypatch):
    assert importlib.util.find_spec("chatnet.recovery") is not None, (
        "recovery API missing"
    )
    module = importlib.import_module("chatnet.recovery")

    def forbidden(*args, **kwargs):
        pytest.fail("real subprocess forbidden in offline recovery tests")

    monkeypatch.setattr(subprocess, "run", forbidden)
    return module


def test_settings_defaults_frozen_and_home(recovery, tmp_path, monkeypatch):
    settings = recovery.RecoverySettings()
    assert settings.cooldown == 300
    assert not hasattr(settings, "interval") and not hasattr(settings, "failures")
    assert (
        settings.max_attempts,
        settings.window_seconds,
        settings.allow_module_reload,
    ) == (3, 3600, False)
    with pytest.raises(FrozenInstanceError):
        settings.interface = "wlan9"
    monkeypatch.setenv("CHATARCH_HOME", str(tmp_path))
    assert recovery.recovery_home() == tmp_path / "chatnet" / "recovery"
    assert not recovery.recovery_home().exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("interface", "-bad"),
        ("interface", "wlan0;id"),
        ("interface", "../wlan0"),
        ("interface", "a" * 16),
        ("connection", "--help"),
        ("connection", "secret\nvalue"),
        ("rescue_peer", "example.invalid"),
        ("probe_host", "1.2.3.4;id"),
        ("rescue_peer", "127.0.0.1"),
        ("probe_host", "::%wlan0"),
        ("cooldown", float("nan")),
        ("cooldown", float("inf")),
        ("window_seconds", 0),
        ("max_attempts", 1.5),
        ("max_attempts", True),
        ("max_attempts", 0),
        ("window_seconds", -1),
        ("allow_module_reload", "false"),
        ("cooldown", -1),
    ],
)
def test_settings_reject_unsafe_values(recovery, field, value):
    with pytest.raises(recovery.RecoveryError) as error:
        recovery.RecoverySettings(**{field: value})
    assert "secret" not in str(error.value)


def test_config_uses_existing_namespace_and_process_overrides(
    recovery, tmp_path, monkeypatch
):
    from chatenv import EnvStore, get_paths
    from chatnet.config import ChatNetProxyConfig

    fields = ChatNetProxyConfig.get_fields()
    expected = {
        "INTERFACE",
        "CONNECTION",
        "RESCUE_PEER",
        "PROBE_HOST",
        "COOLDOWN",
        "MAX_ATTEMPTS",
        "WINDOW",
        "MODULE_RELOAD",
    }
    assert {"CHATNET_RECOVERY_" + key for key in expected} <= set(fields)
    assert ChatNetProxyConfig._storage_dir == "ChatNet"
    store = EnvStore(get_paths(tmp_path).envs_dir)
    store.save_active(
        ChatNetProxyConfig,
        {"CHATNET_RECOVERY_COOLDOWN": "40", "CHATNET_RECOVERY_INTERFACE": "wlan0"},
    )
    monkeypatch.setenv("CHATNET_RECOVERY_COOLDOWN", "12.5")
    settings = recovery.load_recovery_settings(home=tmp_path)
    assert settings.cooldown == 12.5
    assert settings.interface == "wlan0"
    monkeypatch.delenv("CHATNET_RECOVERY_COOLDOWN")
    assert recovery.load_recovery_settings(home=tmp_path).cooldown == 40


@pytest.mark.parametrize(
    "key,value",
    [
        ("COOLDOWN", "NaN"),
        ("MAX_ATTEMPTS", "1.5"),
        ("MODULE_RELOAD", "maybe"),
        ("COOLDOWN", "1e999"),
    ],
)
def test_env_validation_fails_without_leaking_values(
    recovery, tmp_path, monkeypatch, key, value
):
    monkeypatch.setenv("CHATNET_RECOVERY_" + key, value)
    with pytest.raises(recovery.RecoveryError):
        recovery.load_recovery_settings(home=tmp_path)
