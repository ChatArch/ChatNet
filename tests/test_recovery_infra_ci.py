"""Existing CI must validate bundled Infra from its independent wheel."""
from pathlib import Path


def test_existing_wheel_job_checks_recovery_resources_outside_checkout():
    path = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
    text = path.read_text()
    assert "Verify built wheel recovery assets" in text
    section = text.split("Verify built wheel recovery assets", 1)[1]
    assert 'cd "$RUNNER_TEMP"' in section
    assert '"$RUNNER_TEMP/chatnet-wheel/bin/python"' in section
    assert "files('chatnet').joinpath('data/systemd')" in section
    assert "chatnet-recovery.service" in section and "chatnet-recovery.timer" in section
    assert "assert root.joinpath(name).is_file()" in section
    assert "site-packages" in section
