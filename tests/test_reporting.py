from __future__ import annotations

import json
from pathlib import Path

import pytest

from trackjudge import app
from trackjudge.app import build_parser, run_interactive_wizard, save_json_report


def candidate() -> dict[str, object]:
    return {
        "url": "https://example.test/audio",
        "orig_file": "candidate.webm",
        "saved_file": "output/candidate.opus",
        "saved_spectrogram": None,
        "codec": "opus",
        "bitrate": 160,
        "sample_rate": 48_000,
        "channels": 2,
        "duration": 240.0,
        "source_duration": 240.0,
        "analysis_duration": 180.0,
        "cutoff": 19_200.0,
        "raw_cutoff": 19_300.0,
        "authenticity": 91.0,
        "fake_noise": False,
        "score": 93.5,
        "warnings": [],
    }


def test_parser_exposes_product_cli() -> None:
    parser = build_parser()
    args = parser.parse_args(["a.flac", "b.m4a", "--json-report", "--no-color"])

    assert args.urls == ["a.flac", "b.m4a"]
    assert args.json_report == "auto"
    assert args.no_color is True


def test_interactive_wizard_collects_sources_and_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = build_parser().parse_args([])
    args.dest = str(tmp_path)
    source_answers = iter(['"https://example.test/one"', "https://example.test/two", ""])
    confirmation_answers = iter([True, False, True])

    monkeypatch.setattr(app._CONSOLE, "input", lambda *args, **kwargs: next(source_answers))
    monkeypatch.setattr(app.Prompt, "ask", lambda *args, **kwargs: f'"{tmp_path}"')
    monkeypatch.setattr(
        app.Confirm,
        "ask",
        lambda *args, **kwargs: next(confirmation_answers),
    )

    assert run_interactive_wizard(args) is True
    assert args.urls == ["https://example.test/one", "https://example.test/two"]
    assert args.dest == str(tmp_path)
    assert args.spectrogram is True
    assert args.json_report is None


def test_json_report_is_machine_readable(tmp_path) -> None:
    report_path = tmp_path / "report.json"
    saved = save_json_report(str(report_path), [candidate()], [])
    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert saved == str(report_path)
    assert payload["tool"] == "TrackJudge"
    assert payload["winner"]["score"] == 93.5
    assert payload["winner"]["source_duration_seconds"] == 240.0
    assert payload["winner"]["analysis_duration_seconds"] == 180.0

    with pytest.raises(FileExistsError):
        save_json_report(str(report_path), [candidate()], [])
