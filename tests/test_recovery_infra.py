"""The packaged recovery timer must use one durable owner."""
from pathlib import Path
import importlib.resources

ROOT = Path(__file__).resolve().parents[1]


def assets():
    return importlib.resources.files("chatnet").joinpath("data/systemd")


def test_recovery_assets_are_available_from_package():
    root = assets()
    for name in ("chatnet-recovery.service", "chatnet-recovery.timer"):
        assert root.joinpath(name).is_file(), name


def test_recovery_service_is_isolated_and_durable():
    service = assets().joinpath("chatnet-recovery.service").read_text()
    assert "Type=oneshot" in service
    assert "WorkingDirectory=%h/.chatarch" in service
    assert "Environment=CHATARCH_HOME=%h/.chatarch" in service
    assert "ExecStart=%h/.chatarch/venv/bin/python -I -u -m chatnet.cli recovery run --execute --json-output" in service
    assert "UnsetEnvironment=PYTHONPATH PYTHONHOME LD_PRELOAD LD_LIBRARY_PATH SSH_CONNECTION" in service
    assert "Restart=no" in service
    assert "UMask=0077" in service
    assert "StandardOutput=journal" in service and "StandardError=journal" in service
    assert "StartLimitIntervalSec=300" in service and "StartLimitBurst=30" in service
    assert "/home/" not in service and "sudo" not in service
    assert "CPUQuota=10%" in service and "MemoryMax=128M" in service


def test_recovery_timer_uses_one_owner_at_bounded_cadence():
    timer = assets().joinpath("chatnet-recovery.timer").read_text()
    assert "OnCalendar=*-*-* *:*:00/15" in timer
    assert "Unit=chatnet-recovery.service" in timer
    assert "AccuracySec=1s" in timer
    assert "Persistent=true" in timer
    assert "WantedBy=timers.target" in timer
    assert "RandomizedDelaySec=0" in timer
