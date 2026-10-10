"""Existing deployments must retain legacy history without breaking new logs."""
from datetime import datetime, timezone
import json
import uuid

from chatnet import recovery_state as state_io


def test_new_audit_after_legacy_log_remains_readable_and_preserves_history(tmp_path):
    root = tmp_path / 'chatnet/recovery'
    root.mkdir(parents=True, mode=0o700)
    old = json.dumps({'time': 100, 'status': 'attempt-reserved', 'interface': 'wlan0'}) + '\n'
    log = root / 'events.jsonl'
    log.write_text(old)
    log.chmod(0o600)
    event = {'version': 1, 'epoch': 101, 'timestamp': datetime.fromtimestamp(101, timezone.utc).isoformat(), 'event': 'run-finished', 'status': 'healthy', 'run_id': str(uuid.uuid4()), 'performed': False}
    state_io.audit(root, event)
    records = state_io.read_audit(root)
    assert event in records
    assert any(old.encode() in p.read_bytes() for p in root.glob('*.jsonl'))
