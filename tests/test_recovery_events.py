"""Durable recovery event contracts; all network behavior is synthetic."""

from datetime import datetime
import json
import os
from pathlib import Path

import pytest

from test_recovery_operations import lab as lab
from test_recovery_core import recovery as recovery


RADIO_COMMAND = ("nmcli", "-t", "-f", "RUNNING,WIFI-HW,WIFI", "general")


class StepClock:
    def __init__(self, start):
        self.value = start

    def __call__(self):
        value = self.value
        self.value += 1
        return value


def test_healthy_execute_writes_private_timestamped_terminal_event(lab):
    api, net, settings, deps, home = lab
    net.gateway_ok = True
    result = api.recover_network(
        settings, execute=True, home=home, clock=StepClock(1000), **deps
    )
    events = api.read_recovery_logs(home=home)

    assert result["status"] == "healthy" and not result["performed"]
    assert {event["event"] for event in events} >= {
        "run-started",
        "observation",
        "run-finished",
    }
    terminal = [event for event in events if event["event"] == "run-finished"][-1]
    assert terminal["run_id"] == result["run_id"]
    assert terminal["status"] == "healthy" and terminal["performed"] is False
    for event in events:
        assert type(event["epoch"]) in (int, float)
        assert datetime.fromisoformat(event["timestamp"]).tzinfo is not None
    root = api.recovery_home(home)
    assert root.stat().st_mode & 0o777 == 0o700
    assert (root / "events.jsonl").stat().st_mode & 0o777 == 0o600


def test_incident_persists_across_failure_and_block_then_relapse_gets_new_id(lab):
    api, net, settings, deps, home = lab
    settings = type(settings)(
        rescue_peer=settings.rescue_peer,
        cooldown=0,
        max_attempts=10,
    )

    failed = api.recover_network(
        settings, execute=True, home=home, clock=StepClock(1000), **deps
    )
    deps["environ"] = {"SSH_CONNECTION": "203.0.113.10 50000 192.0.2.5 22"}
    net.ssh_dev = "wlan0"
    blocked = api.recover_network(
        settings, execute=True, home=home, clock=StepClock(1100), **deps
    )
    deps["environ"] = {}
    net.reconnect_ok = True
    recovered = api.recover_network(
        settings, execute=True, home=home, clock=StepClock(1200), **deps
    )
    net.gateway_ok = False
    net.reconnect_ok = False
    relapse = api.recover_network(
        settings, execute=True, home=home, clock=StepClock(1300), **deps
    )

    assert failed["status"] == "failed" and failed["performed"]
    assert blocked["status"] == "blocked" and not blocked["performed"]
    assert recovered["status"] == "recovered" and recovered["performed"]
    assert failed["incident_id"] == blocked["incident_id"] == recovered["incident_id"]
    assert failed["detected_at"] == blocked["detected_at"] == recovered["detected_at"]
    assert relapse["incident_id"] != recovered["incident_id"]
    assert relapse["detected_at"] > recovered["recovered_at"]

    events = api.read_recovery_logs(home=home, incident_id=recovered["incident_id"])
    attempt = next(
        event
        for event in events
        if event["event"] == "attempt-started"
        and event["run_id"] == recovered["run_id"]
    )
    terminal = next(
        event
        for event in events
        if event["event"] == "attempt-finished"
        and event["run_id"] == recovered["run_id"]
    )
    assert attempt["actions"] == ["rescan", "reconnect", "postcheck"]
    assert terminal["status"] == "recovered"
    assert terminal["recovered_at"] == recovered["recovered_at"]
    assert terminal["epoch"] > attempt["epoch"]
    assert any(
        event["event"] == "stage-finished"
        and event["stage"] == "postcheck"
        and event["status"] == "succeeded"
        for event in events
    )


def test_inspection_error_is_logged_with_sanitized_terminal_result(lab):
    api, net, settings, deps, home = lab
    net.fail[RADIO_COMMAND] = (7, "SECRET=password")
    with pytest.raises(api.RecoveryError, match="radio"):
        api.recover_network(
            settings, execute=True, home=home, clock=StepClock(1000), **deps
        )

    terminal = api.read_recovery_logs(home=home)[-1]
    assert terminal["event"] == "run-finished"
    assert terminal["status"] == "inspection-error"
    assert terminal["error"] == {
        "stage": "radio",
        "command": "nmcli",
        "returncode": 7,
    }
    assert "SECRET" not in json.dumps(terminal)


def test_interrupted_attempt_keeps_unmatched_durable_start(lab):
    api, net, settings, deps, home = lab

    def interrupt(_command):
        raise KeyboardInterrupt

    net.before_mutation = interrupt
    with pytest.raises(KeyboardInterrupt):
        api.recover_network(
            settings, execute=True, home=home, clock=StepClock(1000), **deps
        )

    events = api.read_recovery_logs(home=home)
    started = [event for event in events if event["event"] == "attempt-started"]
    assert len(started) == 1
    attempt_id = started[0]["attempt_id"]
    assert not any(
        event["event"] == "attempt-finished" and event.get("attempt_id") == attempt_id
        for event in events
    )
    state = json.loads((api.recovery_home(home) / "state.json").read_text())
    assert state["active_attempt"]["attempt_id"] == attempt_id


def test_reader_spans_bounded_rotation_and_validates_filters_and_shape(
    recovery, tmp_path, monkeypatch
):
    from chatnet import recovery_state

    monkeypatch.setattr(recovery_state, "EVENT_LOG_BYTES", 1)
    monkeypatch.setattr(recovery_state, "EVENT_LOG_FILES", 4)
    root = recovery.recovery_home(tmp_path)
    run_id = "11111111-2222-4333-8444-555555555555"
    incident_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    for index in range(6):
        recovery_state.audit(
            root,
            {
                "version": 1,
                "epoch": index,
                "timestamp": f"1970-01-01T00:00:0{index}+00:00",
                "event": "run-finished",
                "status": "failed",
                "run_id": run_id,
                "incident_id": incident_id,
                "performed": False,
            },
        )

    events = recovery.read_recovery_logs(
        home=tmp_path, limit=2, status="failed", incident_id=incident_id
    )
    assert [event["epoch"] for event in events] == [4, 5]
    assert len(list(root.glob("events*.jsonl"))) == 4
    with pytest.raises(recovery.RecoveryError, match="log-filter"):
        recovery.read_recovery_logs(home=tmp_path, limit=0)

    current = root / "events.jsonl"
    current.write_text('{"status":"failed"}\n')
    os.chmod(current, 0o600)
    with pytest.raises(recovery.RecoveryError, match="log-invalid"):
        recovery.read_recovery_logs(home=tmp_path)


def test_reader_rejects_non_private_log_file(recovery, tmp_path):
    root = recovery.recovery_home(tmp_path)
    root.mkdir(parents=True, mode=0o700)
    path = Path(root, "events.jsonl")
    path.write_text("{}\n")
    path.chmod(0o644)
    with pytest.raises(recovery.RecoveryError, match="permissions"):
        recovery.read_recovery_logs(home=tmp_path)


def test_legacy_budget_state_gains_optional_fields_without_losing_attempts(lab):
    api, net, settings, deps, home = lab
    root = api.recovery_home(home)
    root.mkdir(parents=True, mode=0o700)
    path = root / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "attempts": [900],
                "last_attempt": 900,
                "last_seen": 900,
                "failures": 1,
            }
        )
    )
    path.chmod(0o600)
    net.gateway_ok = True

    result = api.recover_network(
        settings, execute=True, home=home, clock=lambda: 1000, **deps
    )
    state = json.loads(path.read_text())

    assert result["status"] == "healthy" and not result["performed"]
    assert state["attempts"] == [900] and state["last_attempt"] == 900
    assert state["identity"]["interface"] == "wlan0"
    assert state["incident"] is None and state["active_attempt"] is None
