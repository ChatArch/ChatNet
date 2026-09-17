"""Private, locked recovery budgets. Corruption never means a fresh budget."""

from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import stat
import tempfile

from .recovery import RecoveryError


def _valid_file(fd):
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
        or info.st_nlink != 1
    ):
        raise RecoveryError("state-permissions")


def ensure_directory(root: Path):
    try:
        if root.is_symlink() or root.parent.is_symlink():
            raise RecoveryError("state-symlink")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = root.stat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise RecoveryError("state-permissions")
    except OSError:
        raise RecoveryError("state-directory") from None


@contextmanager
def locked(root: Path, name="mutation.lock"):
    import fcntl

    ensure_directory(root)
    fd = None
    try:
        fd = os.open(root / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
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
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


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
        }
    fd = None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        _valid_file(fd)
        if os.fstat(fd).st_size > 65536:
            raise ValueError

        def invalid(value):
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
            or not all(finite(t) for t in attempts)
            or attempts != sorted(attempts)
        ):
            raise ValueError
        if not finite(data["last_seen"]):
            raise ValueError
        if data["last_attempt"] is not None and not finite(data["last_attempt"]):
            raise ValueError
        if type(data["failures"]) is not int or not 0 <= data["failures"] <= 1000000:
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
        if now < data["last_seen"]:
            raise RecoveryError("state-clock-regressed")
        return data
    except (OSError, ValueError, TypeError):
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
    except (OSError, ValueError, TypeError):
        raise RecoveryError("state-write") from None
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass


def audit(root: Path, event: dict):
    """Bounded metadata-only log; caller holds the mutation lock."""
    path = root / "events.jsonl"
    fd = None
    try:
        if path.is_symlink():
            raise RecoveryError("state-symlink")
        if path.exists() and path.stat().st_size > 1048576:
            previous = root / "events.previous.jsonl"
            if previous.is_symlink():
                raise RecoveryError("state-symlink")
            os.replace(path, previous)
        fd = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
        )
        _valid_file(fd)
        with os.fdopen(fd, "w") as stream:
            fd = None
            stream.write(
                json.dumps(event, allow_nan=False, separators=(",", ":")) + "\n"
            )
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError, TypeError):
        raise RecoveryError("state-audit") from None
    finally:
        if fd is not None:
            os.close(fd)
