from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from trackjudge import updater


def _fake_version(path: Path) -> str | None:
    versions = {
        b"stable": "2026.07.04",
        b"nightly": "2026.07.28.232900",
    }
    try:
        return versions.get(path.read_bytes())
    except OSError:
        return None


@pytest.fixture()
def updater_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "runtime"
    monkeypatch.setenv("TRACKJUDGE_RUNTIME_DIR", str(root))
    monkeypatch.setattr(updater, "_binary_version", _fake_version)
    return root


def test_first_run_copies_seed_and_checks_for_updates(
    updater_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = tmp_path / "yt-dlp.exe"
    seed.write_bytes(b"stable")
    calls: list[list[str]] = []

    def fake_run(
        _path: Path, arguments: list[str], timeout: int
    ) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        assert timeout == updater.UPDATE_TIMEOUT_SECONDS
        return subprocess.CompletedProcess(arguments, 0, "yt-dlp is up to date\n", "")

    monkeypatch.setattr(updater, "_run_binary", fake_run)

    result = updater.ensure_current_ytdlp(seed)

    assert result.checked is True
    assert result.updated is False
    assert result.version == "2026.07.04"
    assert updater.managed_ytdlp_path().read_bytes() == b"stable"
    assert calls[0][-2:] == ["--update-to", "nightly"]


def test_successful_update_keeps_previous_binary_for_rollback(
    updater_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = tmp_path / "yt-dlp.exe"
    seed.write_bytes(b"stable")

    def fake_run(
        path: Path, arguments: list[str], timeout: int
    ) -> subprocess.CompletedProcess[str]:
        path.write_bytes(b"nightly")
        return subprocess.CompletedProcess(arguments, 0, "Updated\n", "")

    monkeypatch.setattr(updater, "_run_binary", fake_run)

    result = updater.ensure_current_ytdlp(seed, force=True)
    state = json.loads((updater_root / "yt-dlp-state.json").read_text(encoding="utf-8"))

    assert result.updated is True
    assert result.pending_validation is True
    assert updater.managed_ytdlp_path().read_bytes() == b"nightly"
    assert updater.previous_ytdlp_path().read_bytes() == b"stable"
    assert state["active_version"] == "2026.07.28.232900"
    assert state["pending_validation"] is True


def test_invalid_update_is_rolled_back_immediately(
    updater_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = tmp_path / "yt-dlp.exe"
    seed.write_bytes(b"stable")

    def fake_run(
        path: Path, arguments: list[str], timeout: int
    ) -> subprocess.CompletedProcess[str]:
        path.write_bytes(b"broken")
        return subprocess.CompletedProcess(arguments, 0, "Updated\n", "")

    monkeypatch.setattr(updater, "_run_binary", fake_run)

    result = updater.ensure_current_ytdlp(seed, force=True)

    assert result.updated is False
    assert result.repaired is True
    assert result.version == "2026.07.04"
    assert updater.managed_ytdlp_path().read_bytes() == b"stable"


def test_unverified_update_is_rejected(
    updater_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = tmp_path / "yt-dlp.exe"
    seed.write_bytes(b"stable")

    def fake_run(
        path: Path, arguments: list[str], timeout: int
    ) -> subprocess.CompletedProcess[str]:
        path.write_bytes(b"nightly")
        return subprocess.CompletedProcess(
            arguments,
            0,
            "",
            "No hash information found for the release, skipping verification",
        )

    monkeypatch.setattr(updater, "_run_binary", fake_run)

    result = updater.ensure_current_ytdlp(seed, force=True)

    assert result.updated is False
    assert result.version == "2026.07.04"
    assert updater.managed_ytdlp_path().read_bytes() == b"stable"


def test_pending_update_can_be_rolled_back_after_download_failure(
    updater_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = tmp_path / "yt-dlp.exe"
    seed.write_bytes(b"stable")

    def fake_run(
        path: Path, arguments: list[str], timeout: int
    ) -> subprocess.CompletedProcess[str]:
        path.write_bytes(b"nightly")
        return subprocess.CompletedProcess(arguments, 0, "Updated\n", "")

    monkeypatch.setattr(updater, "_run_binary", fake_run)
    updater.ensure_current_ytdlp(seed, force=True)

    result = updater.rollback_ytdlp("download failed")
    state = json.loads((updater_root / "yt-dlp-state.json").read_text(encoding="utf-8"))

    assert result is not None
    assert result.version == "2026.07.04"
    assert updater.managed_ytdlp_path().read_bytes() == b"stable"
    assert state["pending_validation"] is False


def test_mark_working_accepts_pending_update(
    updater_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = tmp_path / "yt-dlp.exe"
    seed.write_bytes(b"stable")

    def fake_run(
        path: Path, arguments: list[str], timeout: int
    ) -> subprocess.CompletedProcess[str]:
        path.write_bytes(b"nightly")
        return subprocess.CompletedProcess(arguments, 0, "Updated\n", "")

    monkeypatch.setattr(updater, "_run_binary", fake_run)
    updater.ensure_current_ytdlp(seed, force=True)

    updater.mark_ytdlp_working()
    state = json.loads((updater_root / "yt-dlp-state.json").read_text(encoding="utf-8"))

    assert state["pending_validation"] is False
    assert state["last_working"] > 0
