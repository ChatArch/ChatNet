import importlib
import json
from types import SimpleNamespace
from click.testing import CliRunner
from chatnet.cli import main


def test_recovery_cli_tree_is_hardware_free():
    result = CliRunner().invoke(main, ["recovery", "--help"])
    assert result.exit_code == 0
    assert set(main.commands["recovery"].commands) == {"check", "run", "logs"}
    for command in ["check", "run", "logs"]:
        result = CliRunner().invoke(main, ["recovery", command, "--help"])
        assert result.exit_code == 0
        assert all(
            flag not in result.output
            for flag in ["--interface", "--module", "--connection", "--host"]
        )


def api(monkeypatch, **overrides):
    module = importlib.import_module("chatnet.recovery_cli")
    calls = []

    def recover(**kw):
        calls.append(kw)
        return {"ok": True, "status": "planned", "performed": False}

    value = SimpleNamespace(
        RecoveryError=ValueError,
        check_recovery=lambda: {
            "healthy": False,
            "status": "unhealthy",
            "reason": "link_down",
        },
        recover_network=recover,
        watch_network=lambda **kw: {
            "ok": True,
            "status": "stopped",
            "cycles": int(kw["once"]),
        },
        read_recovery_logs=lambda **kw: [],
        **overrides,
    )
    monkeypatch.setattr(module, "_core", lambda: value)
    return calls


def test_run_defaults_to_plan_and_execute_is_explicit(monkeypatch):
    calls = api(monkeypatch)
    for execute in [False, True]:
        argv = ["recovery", "run", "--json-output"] + (["--execute"] if execute else [])
        result = CliRunner().invoke(main, argv)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "planned"
        assert calls[-1] == {"execute": execute}


def test_unhealthy_check_has_nonzero_exit_and_valid_json(monkeypatch):
    api(monkeypatch)
    result = CliRunner().invoke(main, ["recovery", "check", "--json-output"])
    assert result.exit_code == 1
    assert json.loads(result.output)["healthy"] is False


def test_cli_domain_error_is_clean_and_nonzero(monkeypatch):
    api(monkeypatch)
    module = importlib.import_module("chatnet.recovery_cli")
    fake = module._core()

    def fail(**kw):
        raise ValueError("Recovery configuration is invalid")

    fake.recover_network = fail
    monkeypatch.setattr(module, "_core", lambda: fake)
    result = CliRunner().invoke(main, ["recovery", "run"])
    assert result.exit_code == 1 and "Traceback" not in result.output
    assert "Recovery configuration is invalid" in result.output


def test_hardware_cli_flag_is_rejected_before_core(monkeypatch):
    calls = api(monkeypatch)
    result = CliRunner().invoke(main, ["recovery", "run", "--interface", "wlan-test"])
    assert result.exit_code == 2 and not calls


def test_logs_cli_is_thin_bounded_and_json_capable(monkeypatch):
    api(monkeypatch)
    module = importlib.import_module("chatnet.recovery_cli")
    fake = module._core()
    calls = []
    incident_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    def read_logs(**kwargs):
        calls.append(kwargs)
        return [
            {
                "timestamp": "2026-10-10T01:02:03+00:00",
                "status": "failed",
                "event": "run-finished",
                "reason": "postcheck-failed",
            }
        ]

    fake.read_recovery_logs = read_logs
    monkeypatch.setattr(module, "_core", lambda: fake)
    result = CliRunner().invoke(
        main,
        [
            "recovery",
            "logs",
            "--limit",
            "2",
            "--status",
            "failed",
            "--incident-id",
            incident_id,
            "--json-output",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["status"] == "failed"
    assert calls == [{"limit": 2, "status": "failed", "incident_id": incident_id}]

    result = CliRunner().invoke(main, ["recovery", "logs", "--limit", "0"])
    assert result.exit_code == 2
