from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from scipy.io import wavfile

from trackjudge import app, updater
from trackjudge.app import (
    ANALYSIS_SAMPLE_RATE,
    _tool_filename,
    check_external_tools,
    convert_to_wav,
    find_external_tool,
    run_command,
)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
def test_conversion_caps_high_resolution_sample_rate(tmp_path) -> None:
    source_rate = 96_000
    time_axis = np.arange(source_rate, dtype=np.float32) / source_rate
    audio = np.sin(2 * np.pi * 1_000 * time_axis).astype(np.float32)
    source = tmp_path / "high-resolution.wav"
    wavfile.write(source, source_rate, audio)

    converted = convert_to_wav(str(source), duration=1.0, channels=1)

    assert converted is not None
    converted_rate, converted_audio = wavfile.read(converted)
    assert converted_rate == ANALYSIS_SAMPLE_RATE
    assert converted_audio.ndim == 1


def test_local_mode_does_not_require_ytdlp(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_which(tool: str) -> str | None:
        return None if tool == "yt-dlp" else f"/tools/{tool}"

    monkeypatch.setattr(shutil, "which", fake_which)

    assert check_external_tools(require_downloader=False) == []
    assert check_external_tools(require_downloader=True) == ["yt-dlp"]


def test_external_tool_can_be_loaded_from_portable_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = tmp_path / _tool_filename("ffmpeg")
    tool.write_bytes(b"portable tool placeholder")
    monkeypatch.setenv("TRACKJUDGE_TOOL_DIR", str(tmp_path))

    assert find_external_tool("ffmpeg") == str(tool)


def test_managed_ytdlp_takes_priority_over_bundled_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    managed_root = tmp_path / "runtime"
    managed = managed_root / _tool_filename("yt-dlp")
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"managed yt-dlp")
    monkeypatch.setattr(updater, "auto_update_supported", lambda: True)
    monkeypatch.setattr(updater, "managed_ytdlp_path", lambda: managed)
    monkeypatch.setattr(app, "find_packaged_tool", lambda _tool: "/bundle/yt-dlp.exe")

    assert find_external_tool("yt-dlp") == str(managed)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific process flags")
def test_subprocesses_are_created_without_windows_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    run_command(["ffmpeg", "-version"])

    assert captured["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert captured["startupinfo"].dwFlags & subprocess.STARTF_USESHOWWINDOW
