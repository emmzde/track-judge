from __future__ import annotations

import json
import math
import os
import tempfile
from typing import Any

from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__, console
from .media import _fix_permissions, publish_file

APP_NAME = "TrackJudge"


def print_header(candidate_count: int, destination: str) -> None:
    subtitle = (
        f"{candidate_count} candidate{'s' if candidate_count != 1 else ''}  •  "
        f"output: {destination}"
    )
    title = Text(APP_NAME, style="bold cyan")
    title.append("  spectral candidate selector", style="dim")
    console._CONSOLE.print(
        Panel(
            Text.assemble(title, "\n", Text(subtitle, style="dim")),
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


def quality_label(score: float, fake_noise: bool = False) -> str:
    if fake_noise:
        return "фейковые ВЧ (подмешан шум)"
    if score >= 70.0:
        return "хорошее качество"
    if score >= 45.0:
        return "подозрительно"
    return "вероятный апскейл"


def fmt_optional_float(value: float | None, digits: int = 4) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    return f"{value:.{digits}f}"


def _score_style(result: dict[str, Any]) -> str:
    if result.get("fake_noise"):
        return "bold red"
    score = float(result["score"])
    if score >= 70:
        return "bold green"
    if score >= 45:
        return "bold yellow"
    return "bold red"


def print_report(results: list[dict[str, Any]], failures: list[dict[str, str]]) -> None:
    table = Table(
        title="Рейтинг кандидатов",
        title_style="bold",
        box=box.ROUNDED,
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("Файл", overflow="fold")
    table.add_column("Кодек", style="dim")
    table.add_column("Длительность", justify="right")
    table.add_column("Срез", justify="right")
    table.add_column("ВЧ", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Оценка")

    for index, result in enumerate(results, 1):
        duration = float(result.get("source_duration") or result["duration"])
        label = quality_label(result["score"], result.get("fake_noise", False))
        table.add_row(
            str(index),
            Text(os.path.basename(result["orig_file"])),
            f"{result['codec']} · {result['bitrate']}k",
            f"{duration:.1f} с",
            f"{result['cutoff'] / 1000:.1f} кГц",
            f"{result['authenticity']:.0f}/100",
            f"{result['score']:.1f}",
            label,
            style=_score_style(result) if index == 1 else None,
        )

    if results:
        console._CONSOLE.print()
        console._CONSOLE.print(table)

    warning_lines: list[str] = []
    for index, result in enumerate(results, 1):
        warning_lines.extend(f"#{index}: {warning}" for warning in result.get("warnings", []))
    if warning_lines:
        console._CONSOLE.print(
            Panel(
                Text("\n".join(warning_lines)),
                title="Предупреждения",
                border_style="yellow",
                box=box.ROUNDED,
            )
        )

    if failures:
        failed = Table(
            title="Не обработаны",
            box=box.SIMPLE,
            header_style="bold red",
        )
        failed.add_column("Источник", overflow="fold")
        failed.add_column("Причина")
        for item in failures:
            failed.add_row(Text(item["url"]), Text(item["reason"]))
        console._CONSOLE.print(failed)


def _json_candidate(result: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "source": result["url"],
        "file_name": os.path.basename(result["orig_file"]),
        "saved_file": result.get("saved_file"),
        "saved_spectrogram": result.get("saved_spectrogram"),
        "codec": result["codec"],
        "bitrate_kbps": int(result["bitrate"]),
        "sample_rate_hz": int(result["sample_rate"]),
        "channels": int(result["channels"]),
        "source_duration_seconds": float(result.get("source_duration") or result["duration"]),
        "analysis_duration_seconds": float(result.get("analysis_duration") or result["duration"]),
        "effective_cutoff_hz": float(result["cutoff"]),
        "raw_cutoff_hz": float(result["raw_cutoff"]),
        "authenticity": float(result["authenticity"]),
        "fake_noise": bool(result["fake_noise"]),
        "score": float(result["score"]),
        "quality_label": quality_label(result["score"], result.get("fake_noise", False)),
        "warnings": list(result.get("warnings", [])),
    }


def save_json_report(
    report_path: str,
    results: list[dict[str, Any]],
    failures: list[dict[str, str]],
) -> str:
    report_path = os.path.abspath(report_path)
    if os.path.exists(report_path):
        raise FileExistsError(f"JSON-отчёт уже существует: {report_path}")
    parent = os.path.dirname(report_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    payload = {
        "tool": APP_NAME,
        "version": __version__,
        "winner": _json_candidate(results[0], 1),
        "candidates": [_json_candidate(item, index) for index, item in enumerate(results, 1)],
        "failures": failures,
    }
    with tempfile.TemporaryDirectory(dir=parent, prefix=".trackjudge-") as staging:
        temporary_path = os.path.join(staging, "report.json")
        with open(temporary_path, "w", encoding="utf-8", newline="\n") as report_file:
            json.dump(payload, report_file, ensure_ascii=False, indent=2)
            report_file.write("\n")
        publish_file(temporary_path, report_path)
    _fix_permissions(report_path)
    return report_path


def build_verdict(results: list[dict[str, Any]], winner: dict[str, Any]) -> str:
    def describe(item: dict[str, Any]) -> str:
        if item.get("fake_noise"):
            return f"фейковые ВЧ (живой звук до ~{item['cutoff'] / 1000:.1f} кГц, выше — шум)"
        c = item["cutoff"] / 1000.0
        if c >= 18.5:
            return f"честные ~{c:.1f} кГц"
        if c >= 16.5:
            return f"срез на ~{c:.1f} кГц"
        return f"низкий срез ~{c:.1f} кГц (апскейл)"

    lines = [f"Победитель: {os.path.basename(winner.get('saved_file') or winner['orig_file'])}"]
    lines.append(f"{describe(winner)}, score {winner['score']:.1f}/100.")
    losers = [r for r in results if r is not winner]
    if losers:
        parts = [f"{describe(item)} ({item['score']:.1f})" for item in losers]
        lines.append("У остальных: " + "; ".join(parts) + ".")
        best_loser_cutoff = max((item["cutoff"] for item in losers), default=0)
        if winner["cutoff"] - best_loser_cutoff > 1500:
            lines.append(
                f"Победитель честнее по верху: {winner['cutoff'] / 1000:.1f} кГц против "
                f"{best_loser_cutoff / 1000:.1f} кГц у ближайшего."
            )
    return "\n".join(lines)
