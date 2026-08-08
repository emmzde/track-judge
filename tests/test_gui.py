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
from trackjudge.theme import CORE_COLORS, FONTS, SIZES, apply_font_scale, build_theme_colors


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


def test_single_theme_matches_the_reference_palette_and_geometry() -> None:
    colors = build_theme_colors()

    for token in (
        "canvas",
        "surface",
        "surface_muted",
        "ink",
        "muted",
        "sidebar",
        "portfolio",
        "asset_lilac",
        "asset_mint",
        "asset_sand",
    ):
        assert colors[token] == CORE_COLORS[token]

    assert colors["sidebar"] == "#222222"
    assert colors["portfolio"] == "#E5F1FD"
    assert colors["surface"] == "#F7F6F2"
    assert colors["surface"] != "#FFFFFF"
    assert SIZES["window_width"] == 1120
    assert SIZES["window_height"] == 720
    assert SIZES["portfolio_height"] == 194
    assert SIZES["analysis_height"] == 300
    assert SIZES["spectrogram_width"] == 520
    assert SIZES["spectrogram_height"] == 236


def test_fullscreen_font_scale_uses_larger_physical_pixels() -> None:
    try:
        apply_font_scale(1.0)
        baseline = {role: FONTS[role]["size"] for role in ("screen_title", "body", "label")}

        apply_font_scale(1.35)

        assert abs(FONTS["screen_title"]["size"]) > abs(baseline["screen_title"])
        assert abs(FONTS["body"]["size"]) > abs(baseline["body"])
        assert abs(FONTS["label"]["size"]) > abs(baseline["label"])
        assert FONTS["heading"] is FONTS["panel_title"]
    finally:
        apply_font_scale(1.0)


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
