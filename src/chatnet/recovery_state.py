"""Private recovery state, mutation locks, and bounded durable event logs."""

from contextlib import contextmanager
from datetime import datetime
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

from .recovery import RecoveryError


EVENT_LOG_BYTES = 1_048_576
EVENT_LOG_FILES = 8
EVENT_LINE_BYTES = 16_384

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_TOKEN = re.compile(r"[a-z][a-z0-9-]{0,63}")
_INTERFACE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,14}")
_MODULE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]{0,63}")
_CONNECTION_UUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def _valid_file(fd, stage="state-permissions"):
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
    ):
        raise RecoveryError(stage)
    return info


def _valid_directory(root: Path):
    try:
        if root.is_symlink() or root.parent.is_symlink():
            raise RecoveryError("state-symlink")
        info = root.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
        ):
            raise RecoveryError("state-permissions")
    except RecoveryError:
        raise
    except OSError:
        raise RecoveryError("state-directory") from None


def ensure_directory(root: Path):
    try:
        if root.is_symlink() or root.parent.is_symlink():
            raise RecoveryError("state-symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    except RecoveryError:
        raise
    except OSError:
        raise RecoveryError("state-directory") from None
    _valid_directory(root)


@contextmanager
def locked(root: Path, name="mutation.lock"):
    import fcntl

    ensure_directory(root)
    fd = None
    try:
        fd = os.open(root / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        _valid_file(fd)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if fd is not None:
            os.close(fd)
        raise RecoveryError("state-lock") from None
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise
    try:
        yield
    finally:
        os.close(fd)


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _uuid(value):
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _valid_incident(value):
    return (
        isinstance(value, dict)
        and set(value) == {"incident_id", "detected_at"}
        and _uuid(value["incident_id"])
        and finite(value["detected_at"])
    )


def _valid_identity(value):
    if not isinstance(value, dict):
        return False
    required = frozenset(
        {
            "interface",
            "connection_uuid",
            "module",
            "device_path",
            "device_inode",
            "device_fingerprint",
        }
    )
    if frozenset(value) not in {
        required,
        required | {"profile_fingerprint"},
    }:
        return False
    path = (
        PurePosixPath(value["device_path"])
        if isinstance(value["device_path"], str)
        else None
    )
    inode = value["device_inode"]
    return (
        _INTERFACE.fullmatch(value["interface"] or "") is not None
        and _CONNECTION_UUID.fullmatch(value["connection_uuid"] or "") is not None
        and _MODULE.fullmatch(value["module"] or "") is not None
        and path is not None
        and not path.is_absolute()
        and path.parts
        and path.parts[0] == "devices"
        and ".." not in path.parts
        and isinstance(inode, list)
        and len(inode) == 2
        and all(type(part) is int and part >= 0 for part in inode)
        and isinstance(value["device_fingerprint"], str)
        and re.fullmatch(r"[0-9a-f]{64}", value["device_fingerprint"]) is not None
        and (
            "profile_fingerprint" not in value
            or isinstance(value["profile_fingerprint"], str)
            and re.fullmatch(r"[0-9a-f]{64}", value["profile_fingerprint"]) is not None
        )
    )


def _valid_active_attempt(value):
    return (
        isinstance(value, dict)
        and set(value)
        == {"attempt_id", "run_id", "incident_id", "started_at", "actions"}
        and all(_uuid(value[key]) for key in ("attempt_id", "run_id", "incident_id"))
        and finite(value["started_at"])
        and isinstance(value["actions"], list)
        and 1 <= len(value["actions"]) <= 16
        and all(
            isinstance(item, str) and _TOKEN.fullmatch(item)
            for item in value["actions"]
        )
    )


def read_state(root: Path, now: float):
    if not finite(now):
        raise RecoveryError("state-clock")
    path = root / "state.json"
    if not path.exists() and not path.is_symlink():
        return {
            "version": 1,
            "attempts": [],
            "last_attempt": None,
            "last_seen": now,
            "failures": 0,
            "incident": None,
            "identity": None,
            "active_attempt": None,
        }
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        _valid_file(fd)
        if os.fstat(fd).st_size > 65536:
            raise ValueError

        def invalid(_value):
            raise ValueError

        with os.fdopen(fd) as stream:
            fd = None
            data = json.load(stream, parse_constant=invalid)
        required = {"version", "attempts", "last_attempt", "last_seen", "failures"}
        if (
            not isinstance(data, dict)
            or not required <= data.keys()
            or type(data["version"]) is not int
            or data["version"] != 1
        ):
            raise ValueError
        attempts = data["attempts"]
        if (
            not isinstance(attempts, list)
            or len(attempts) > 1000
            or not all(finite(item) for item in attempts)
            or attempts != sorted(attempts)
        ):
            raise ValueError
        if not finite(data["last_seen"]):
            raise ValueError
        if data["last_attempt"] is not None and not finite(data["last_attempt"]):
            raise ValueError
        if type(data["failures"]) is not int or not 0 <= data["failures"] <= 1_000_000:
            raise ValueError
        if (
            data["last_attempt"] is not None
            and data["last_attempt"] > data["last_seen"]
        ):
            raise ValueError
        if attempts and (
            attempts[-1] != data["last_attempt"] or attempts[-1] > data["last_seen"]
        ):
            raise ValueError
        incident = data.get("incident")
        identity = data.get("identity")
        active_attempt = data.get("active_attempt")
        if incident is not None and not _valid_incident(incident):
            raise ValueError
        if identity is not None and not _valid_identity(identity):
            raise ValueError
        if active_attempt is not None and not _valid_active_attempt(active_attempt):
            raise ValueError
        if now < data["last_seen"]:
            raise RecoveryError("state-clock-regressed")
        data.setdefault("incident", None)
        data.setdefault("identity", None)
        data.setdefault("active_attempt", None)
        return data
    except RecoveryError:
        raise
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise RecoveryError("state-invalid") from None
    finally:
        if fd is not None:
            os.close(fd)


def write_state(root: Path, state: dict):
    temporary = None
    try:
        target = root / "state.json"
        if target.is_symlink():
            raise RecoveryError("state-symlink")
        fd, temporary = tempfile.mkstemp(prefix=".state-", dir=root)
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except RecoveryError:
        raise
    except (OSError, ValueError, TypeError):
        raise RecoveryError("state-write") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def _valid_error(value):
    if not isinstance(value, dict) or set(value) != {"stage", "command", "returncode"}:
        return False
    return (
        isinstance(value["stage"], str)
        and _TOKEN.fullmatch(value["stage"]) is not None
        and (
            value["command"] is None
            or (
                isinstance(value["command"], str)
                and re.fullmatch(r"[A-Za-z0-9_.+-]{1,64}", value["command"])
            )
        )
        and (value["returncode"] is None or type(value["returncode"]) is int)
    )


def _valid_diagnosis(value):
    allowed = {
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
    }
    if not isinstance(value, dict) or not set(value) <= allowed:
        return False
    for key, item in value.items():
        if key in {"healthy", "recoverable", "missing"} and type(item) is not bool:
            return False
        if key == "nm_state" and type(item) is not int:
            return False
        if key not in {"healthy", "recoverable", "missing", "nm_state"} and not (
            item is None or isinstance(item, str) and len(item) <= 256
        ):
            return False
    return True


def validate_event(event):
    required = {"version", "epoch", "timestamp", "event", "status", "run_id"}
    allowed = required | {
        "incident_id",
        "attempt_id",
        "detected_at",
        "recovered_at",
        "performed",
        "reason",
        "outcome",
        "actions",
        "stage",
        "returncode",
        "error",
        "diagnosis",
    }
    if (
        not isinstance(event, dict)
        or not required <= set(event)
        or not set(event) <= allowed
        or type(event["version"]) is not int
        or event["version"] != 1
        or not finite(event["epoch"])
        or not isinstance(event["timestamp"], str)
        or not isinstance(event["event"], str)
        or _TOKEN.fullmatch(event["event"]) is None
        or not isinstance(event["status"], str)
        or _TOKEN.fullmatch(event["status"]) is None
        or not _uuid(event["run_id"])
    ):
        raise RecoveryError("log-invalid")
    try:
        parsed = datetime.fromisoformat(event["timestamp"])
        if parsed.tzinfo is None or abs(parsed.timestamp() - event["epoch"]) > 0.001:
            raise ValueError
    except (ValueError, OverflowError, OSError):
        raise RecoveryError("log-invalid") from None
    for key in ("incident_id", "attempt_id"):
        if key in event and not _uuid(event[key]):
            raise RecoveryError("log-invalid")
    for key in ("detected_at", "recovered_at"):
        if key in event and not finite(event[key]):
            raise RecoveryError("log-invalid")
    if "performed" in event and type(event["performed"]) is not bool:
        raise RecoveryError("log-invalid")
    for key in ("reason", "outcome", "stage"):
        if key in event and (
            not isinstance(event[key], str) or _TOKEN.fullmatch(event[key]) is None
        ):
            raise RecoveryError("log-invalid")
    if (
        "returncode" in event
        and event["returncode"] is not None
        and type(event["returncode"]) is not int
    ):
        raise RecoveryError("log-invalid")
    if "actions" in event and (
        not isinstance(event["actions"], list)
        or not 1 <= len(event["actions"]) <= 16
        or not all(
            isinstance(item, str) and _TOKEN.fullmatch(item)
            for item in event["actions"]
        )
    ):
        raise RecoveryError("log-invalid")
    if "error" in event and not _valid_error(event["error"]):
        raise RecoveryError("log-invalid")
    if "diagnosis" in event and not _valid_diagnosis(event["diagnosis"]):
        raise RecoveryError("log-invalid")
    return event


def _valid_legacy_event(event):
    """Recognize only the metadata-only shapes emitted before versioned logs."""
    if not isinstance(event, dict) or not finite(event.get("time")):
        return False
    keys = set(event)
    if keys == {"time", "status", "interface"}:
        return (
            event["status"] == "attempt-reserved"
            and isinstance(event["interface"], str)
            and _INTERFACE.fullmatch(event["interface"]) is not None
        )
    if (
        keys <= {"time", "status", "stage", "command", "returncode"}
        and {
            "time",
            "status",
            "stage",
        }
        <= keys
    ):
        return (
            event["status"] == "failed"
            and isinstance(event["stage"], str)
            and _TOKEN.fullmatch(event["stage"]) is not None
            and _valid_error(
                {
                    "stage": event["stage"],
                    "command": event.get("command"),
                    "returncode": event.get("returncode"),
                }
            )
        )
    if keys == {"time", "status", "reason", "ok", "performed"}:
        return (
            event["status"] in {"failed", "recovered"}
            and isinstance(event["reason"], str)
            and _TOKEN.fullmatch(event["reason"]) is not None
            and type(event["ok"]) is bool
            and type(event["performed"]) is bool
        )
    return False


def _archive(root: Path, index: int):
    return root / f"events.{index}.jsonl"


def _checked_size(path: Path):
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        return _valid_file(fd, "log-permissions").st_size
    except RecoveryError:
        raise
    except OSError:
        raise RecoveryError("log-read") from None
    finally:
        if fd is not None:
            os.close(fd)


def _prepare_legacy(root: Path):
    legacy = root / "events.previous.jsonl"
    if not legacy.exists() and not legacy.is_symlink():
        return
    _checked_size(legacy)
    if not any(_archive(root, index).exists() for index in range(1, EVENT_LOG_FILES)):
        os.replace(legacy, _archive(root, 1))


def _rotate(root: Path):
    oldest = _archive(root, EVENT_LOG_FILES - 1)
    if oldest.exists() or oldest.is_symlink():
        _checked_size(oldest)
        os.unlink(oldest)
    for index in range(EVENT_LOG_FILES - 2, 0, -1):
        source = _archive(root, index)
        if source.exists() or source.is_symlink():
            _checked_size(source)
            target = _archive(root, index + 1)
            if target.is_symlink():
                raise RecoveryError("state-symlink")
            os.replace(source, target)
    current = root / "events.jsonl"
    if current.exists() or current.is_symlink():
        _checked_size(current)
        os.replace(current, _archive(root, 1))


def audit(root: Path, event: dict):
    """Append one validated event under a private lock and bounded rotation."""
    validate_event(event)
    try:
        encoded = (
            json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n"
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise RecoveryError("log-invalid") from None
    if len(encoded) > EVENT_LINE_BYTES:
        raise RecoveryError("log-invalid")
    with locked(root, "events.lock"):
        path = root / "events.jsonl"
        fd = None
        try:
            _read_audit_unlocked(root, collect=False)
            _prepare_legacy(root)
            size = _checked_size(path) if path.exists() or path.is_symlink() else 0
            if size and size + len(encoded) > EVENT_LOG_BYTES:
                _rotate(root)
            fd = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600
            )
            _valid_file(fd, "log-permissions")
            written = os.write(fd, encoded)
            if written != len(encoded):
                raise OSError
            os.fsync(fd)
            os.close(fd)
            fd = None
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except RecoveryError:
            raise
        except (OSError, ValueError, TypeError):
            raise RecoveryError("state-audit") from None
        finally:
            if fd is not None:
                os.close(fd)


def _read_audit_unlocked(root: Path, *, collect=True):
    """Validate retained segments while the caller holds the events lock."""
    paths = []
    legacy = root / "events.previous.jsonl"
    if legacy.exists() or legacy.is_symlink():
        paths.append(legacy)
    paths.extend(
        _archive(root, index)
        for index in range(EVENT_LOG_FILES - 1, 0, -1)
        if _archive(root, index).exists() or _archive(root, index).is_symlink()
    )
    current = root / "events.jsonl"
    if current.exists() or current.is_symlink():
        paths.append(current)
    events = []
    for path in paths:
        fd = None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = _valid_file(fd, "log-permissions")
            if info.st_size > EVENT_LOG_BYTES + EVENT_LINE_BYTES:
                raise RecoveryError("log-invalid")
            with os.fdopen(fd, "rb") as stream:
                fd = None
                while True:
                    raw = stream.readline(EVENT_LINE_BYTES + 1)
                    if not raw:
                        break
                    if len(raw) > EVENT_LINE_BYTES or not raw.endswith(b"\n"):
                        raise RecoveryError("log-invalid")
                    try:
                        event = json.loads(
                            raw,
                            parse_constant=lambda _value: (_ for _ in ()).throw(
                                ValueError()
                            ),
                        )
                    except (ValueError, TypeError, UnicodeError, RecursionError):
                        raise RecoveryError("log-invalid") from None
                    try:
                        validated = validate_event(event)
                    except RecoveryError:
                        if not _valid_legacy_event(event):
                            raise
                    else:
                        if collect:
                            events.append(validated)
        except RecoveryError:
            raise
        except OSError:
            raise RecoveryError("log-read") from None
        finally:
            if fd is not None:
                os.close(fd)
    return events


def read_audit(root: Path):
    """Read all retained events oldest-first without trusting file contents."""
    if not root.exists() and not root.is_symlink():
        return []
    _valid_directory(root)
    with locked(root, "events.lock"):
        return _read_audit_unlocked(root)
