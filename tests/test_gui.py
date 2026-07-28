from __future__ import annotations

import queue

from trackjudge.gui import (
    GuiRunConfig,
    QueueWriter,
    build_gui_namespace,
    candidate_explanation,
    extract_sources,
    shorten_path,
)


def test_gui_options_map_to_analysis_arguments(tmp_path) -> None:
    config = GuiRunConfig(
        sources=("one.flac", "two.m4a"),
        output_folder=str(tmp_path),
        save_spectrogram=True,
        save_json_report=False,
        spectrogram_folder=str(tmp_path / "temporary-spectrograms"),
    )
    report_path = str(tmp_path / "internal-report.json")

    args = build_gui_namespace(config, report_path)

    assert args.urls == ["one.flac", "two.m4a"]
    assert args.dest == str(tmp_path)
    assert args.spectrogram is True
    assert args.keep_loser_spectrograms is True
    assert args.spectrogram_dir == str(tmp_path / "temporary-spectrograms")
    assert args.json_report == report_path
    assert args.no_color is True
    assert args.pause == 0
    assert args.browser_cookies == "auto"


def test_queue_writer_emits_complete_log_lines() -> None:
    events: queue.Queue[tuple[str, object]] = queue.Queue()
    writer = QueueWriter(events)

    writer.write("first")
    writer.write(" line\nsecond")
    writer.flush()

    assert events.get_nowait() == ("log", "first line")
    assert events.get_nowait() == ("log", "second")


def test_extract_sources_accepts_mixed_and_adjacent_links() -> None:
    text = (
        "https://youtu.be/first?si=abc\n"
        "some words https://youtube.com/watch?v=second"
        "https://youtu.be/third, https://youtu.be/first?si=abc"
    )

    assert extract_sources(text) == [
        "https://youtu.be/first?si=abc",
        "https://youtube.com/watch?v=second",
        "https://youtu.be/third",
    ]


def test_candidate_explanation_names_low_cutoff() -> None:
    explanation = candidate_explanation(
        {
            "effective_cutoff_hz": 14_800,
            "raw_cutoff_hz": 19_900,
            "authenticity": 30,
            "score": 22,
            "warnings": [],
        }
    )

    assert "14.8 кГц" in explanation
    assert "апскейла" in explanation
    assert "Достоверность" in explanation


def test_candidate_explanation_supports_english_and_german() -> None:
    candidate = {
        "effective_cutoff_hz": 14_800,
        "raw_cutoff_hz": 19_900,
        "authenticity": 30,
        "score": 22,
        "warnings": [],
    }

    assert "low-quality source" in candidate_explanation(candidate, "en")
    assert "minderwertige Quelle" in candidate_explanation(candidate, "de")


def test_shorten_path_preserves_filename() -> None:
    path = r"C:\Users\Emil\Downloads\TrackJudge\very-long-winner-file-name.opus"

    shortened = shorten_path(path, 46)

    assert "…" in shortened
    assert shortened.endswith("very-long-winner-file-name.opus")
