from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_UPDATE_CHANNEL = "nightly"
DEFAULT_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
FAILED_CHECK_INTERVAL_SECONDS = 60 * 60
UPDATE_TIMEOUT_SECONDS = 75
LOCK_WAIT_SECONDS = 8
LOCK_STALE_SECONDS = 10 * 60
STATE_SCHEMA_VERSION = 1
_VERSION_PATTERN = re.compile(r"^\d{4}\.\d{1,2}\.\d{1,2}(?:\.\d+)?$")
_PROCESS_LOCK = threading.Lock()


@dataclass(frozen=True)
class UpdateResult:
    executable: str | None
    version: str | None
    checked: bool = False
    updated: bool = False
    repaired: bool = False
    pending_validation: bool = False
    message: str = ""


def auto_update_supported() -> bool:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    if os.environ.get("TRACKJUDGE_TOOL_DIR"):
        return False
    disabled = os.environ.get("TRACKJUDGE_DISABLE_YTDLP_UPDATE", "").strip().lower()
    return disabled not in {"1", "true", "yes", "on"}


def runtime_root() -> Path:
    configured = os.environ.get("TRACKJUDGE_RUNTIME_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "TrackJudge" / "runtime"
    return Path.home() / ".trackjudge" / "runtime"


def managed_ytdlp_path() -> Path:
    return runtime_root() / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")


def previous_ytdlp_path() -> Path:
    return runtime_root() / (
        "yt-dlp.previous.exe" if sys.platform == "win32" else "yt-dlp.previous"
    )


def candidate_ytdlp_path() -> Path:
    return runtime_root() / (
        "yt-dlp.candidate.exe" if sys.platform == "win32" else "yt-dlp.candidate"
    )


def _state_path() -> Path:
    return runtime_root() / "yt-dlp-state.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_key(version: str | None) -> tuple[int, ...]:
    if not version:
        return ()
    return tuple(int(part) for part in re.findall(r"\d+", version))


def _hidden_process_options() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }


def _run_binary(path: Path, arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(path), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **_hidden_process_options(),
    )


def _binary_version(path: Path) -> str | None:
    if not path.is_file() or path.stat().st_size <= 0:
        return None
    try:
        result = _run_binary(path, ["--ignore-config", "--version"], timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    version = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    return version if _VERSION_PATTERN.fullmatch(version) else None


def _read_state() -> dict[str, Any]:
    path = _state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema") != STATE_SCHEMA_VERSION:
        return {}
    return payload


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    with contextlib.suppress(OSError):
        temporary.unlink()
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)


@contextlib.contextmanager
def _exclusive_update_lock(wait_seconds: float = LOCK_WAIT_SECONDS) -> Iterator[bool]:
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "yt-dlp-update.lock"
    deadline = time.monotonic() + wait_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()}\n".encode())
        except FileExistsError:  # noqa: PERF203 - lock acquisition must retry
            with contextlib.suppress(OSError):
                if time.time() - lock_path.stat().st_mtime > LOCK_STALE_SECONDS:
                    lock_path.unlink()
                    continue
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(0.1)
    try:
        yield True
    finally:
        os.close(descriptor)
        with contextlib.suppress(OSError):
            lock_path.unlink()


def _valid_managed_binary(path: Path, state: dict[str, Any]) -> tuple[str | None, bool]:
    version = _binary_version(path)
    if not version:
        return None, False
    expected_hash = state.get("active_sha256")
    if isinstance(expected_hash, str) and expected_hash:
        try:
            if _sha256(path) != expected_hash:
                return None, False
        except OSError:
            return None, False
    return version, True


def _new_state(
    state: dict[str, Any],
    active: Path,
    version: str,
    **updates: Any,
) -> dict[str, Any]:
    payload = dict(state)
    payload.update(
        {
            "schema": STATE_SCHEMA_VERSION,
            "channel": update_channel(),
            "active_version": version,
            "active_sha256": _sha256(active),
        }
    )
    payload.update(updates)
    return payload


def update_channel() -> str:
    configured = os.environ.get("TRACKJUDGE_YTDLP_CHANNEL", DEFAULT_UPDATE_CHANNEL).strip()
    if configured in {"stable", "nightly", "master"}:
        return configured
    return DEFAULT_UPDATE_CHANNEL


def ensure_current_ytdlp(
    seed_executable: str | os.PathLike[str], force: bool = False
) -> UpdateResult:
    seed = Path(seed_executable).resolve()
    if not seed.is_file():
        return UpdateResult(None, None, message="Встроенный yt-dlp не найден.")

    with _PROCESS_LOCK, _exclusive_update_lock() as acquired:
        active = managed_ytdlp_path()
        if not acquired:
            version = _binary_version(active)
            return UpdateResult(
                str(active) if version else str(seed),
                version or _binary_version(seed),
                message="Обновление yt-dlp уже выполняется в другом окне.",
            )

        state = _read_state()
        active_version, active_valid = _valid_managed_binary(active, state)
        seed_version = _binary_version(seed)
        if not seed_version:
            return UpdateResult(
                str(active) if active_valid else None,
                active_version,
                message="Не удалось проверить встроенный yt-dlp.",
            )

        repaired = False
        if (
            not active_valid
            or not active_version
            or _version_key(seed_version) > _version_key(active_version)
        ):
            if active_valid:
                _atomic_copy(active, previous_ytdlp_path())
            _atomic_copy(seed, active)
            active_version = seed_version
            repaired = True
            state = _new_state(
                state,
                active,
                active_version,
                pending_validation=False,
                next_check=0,
            )

        now = time.time()
        next_check = float(state.get("next_check") or 0)
        if not force and now < next_check:
            if repaired:
                _write_state(state)
            return UpdateResult(
                str(active),
                active_version,
                repaired=repaired,
                pending_validation=bool(state.get("pending_validation")),
                message=f"yt-dlp {active_version} готов.",
            )

        backup = previous_ytdlp_path()
        _atomic_copy(active, backup)
        before_version = active_version
        try:
            result = _run_binary(
                active,
                [
                    "--ignore-config",
                    "--socket-timeout",
                    "10",
                    "--update-to",
                    update_channel(),
                ],
                timeout=UPDATE_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            state = _new_state(
                state,
                active,
                active_version,
                last_attempt=now,
                last_error=str(exc),
                next_check=now + FAILED_CHECK_INTERVAL_SECONDS,
            )
            _write_state(state)
            return UpdateResult(
                str(active),
                active_version,
                checked=True,
                repaired=repaired,
                pending_validation=bool(state.get("pending_validation")),
                message="Проверка обновления yt-dlp не удалась; используется рабочая копия.",
            )

        after_version = _binary_version(active)
        updater_output = f"{result.stdout}\n{result.stderr}".lower()
        verification_failed = (
            "skipping verification" in updater_output
            or "unverified builds" in updater_output
            or "no hash information found" in updater_output
        )
        if result.returncode != 0 or not after_version or verification_failed:
            _atomic_copy(backup, active)
            restored_version = _binary_version(active) or before_version
            state = _new_state(
                state,
                active,
                restored_version,
                last_attempt=now,
                last_error=(result.stderr or result.stdout).strip()[-500:],
                next_check=now + FAILED_CHECK_INTERVAL_SECONDS,
                pending_validation=False,
            )
            _write_state(state)
            return UpdateResult(
                str(active),
                restored_version,
                checked=True,
                repaired=True,
                message="Обновление yt-dlp отменено; восстановлена рабочая версия.",
            )

        updated = _version_key(after_version) > _version_key(before_version)
        if updated:
            with contextlib.suppress(OSError):
                candidate_ytdlp_path().unlink()
        state = _new_state(
            state,
            active,
            after_version,
            last_attempt=now,
            last_successful_check=now,
            last_error="",
            next_check=now + DEFAULT_CHECK_INTERVAL_SECONDS,
            pending_validation=updated or bool(state.get("pending_validation")),
        )
        _write_state(state)
        message = (
            f"yt-dlp обновлён: {before_version} -> {after_version}."
            if updated
            else f"yt-dlp {after_version} уже актуален."
        )
        return UpdateResult(
            str(active),
            after_version,
            checked=True,
            updated=updated,
            repaired=repaired,
            pending_validation=bool(state.get("pending_validation")),
            message=message,
        )


def mark_ytdlp_working() -> None:
    with _PROCESS_LOCK, _exclusive_update_lock(wait_seconds=2) as acquired:
        if not acquired:
            return
        state = _read_state()
        active = managed_ytdlp_path()
        version, valid = _valid_managed_binary(active, state)
        if not valid or not version:
            return
        state = _new_state(
            state,
            active,
            version,
            pending_validation=False,
            last_working=time.time(),
        )
        _write_state(state)
        with contextlib.suppress(OSError):
            candidate_ytdlp_path().unlink()


def rollback_ytdlp(reason: str) -> UpdateResult | None:
    with _PROCESS_LOCK, _exclusive_update_lock() as acquired:
        if not acquired:
            return None
        state = _read_state()
        if not state.get("pending_validation"):
            return None
        active = managed_ytdlp_path()
        previous = previous_ytdlp_path()
        previous_version = _binary_version(previous)
        if not previous_version:
            return None
        _atomic_copy(active, candidate_ytdlp_path())
        _atomic_copy(previous, active)
        restored_version = _binary_version(active)
        if not restored_version:
            return None
        now = time.time()
        state = _new_state(
            state,
            active,
            restored_version,
            pending_validation=False,
            last_error=reason[-500:],
            last_rollback=now,
            next_check=now + FAILED_CHECK_INTERVAL_SECONDS,
        )
        _write_state(state)
        return UpdateResult(
            str(active),
            restored_version,
            checked=True,
            repaired=True,
            message=f"yt-dlp возвращён к рабочей версии {restored_version}.",
        )


def restore_ytdlp_candidate(reason: str) -> UpdateResult | None:
    with _PROCESS_LOCK, _exclusive_update_lock() as acquired:
        if not acquired:
            return None
        candidate = candidate_ytdlp_path()
        candidate_version = _binary_version(candidate)
        if not candidate_version:
            return None
        active = managed_ytdlp_path()
        _atomic_copy(candidate, active)
        restored_version = _binary_version(active)
        if not restored_version:
            return None
        now = time.time()
        state = _new_state(
            _read_state(),
            active,
            restored_version,
            pending_validation=True,
            last_error=reason[-500:],
            next_check=now + FAILED_CHECK_INTERVAL_SECONDS,
        )
        _write_state(state)
        with contextlib.suppress(OSError):
            candidate.unlink()
        return UpdateResult(
            str(active),
            restored_version,
            checked=True,
            repaired=True,
            pending_validation=True,
            message=f"yt-dlp {restored_version} восстановлен: старая версия тоже не помогла.",
        )
