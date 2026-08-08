from __future__ import annotations

import argparse
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse


def enable_windows_dpi_awareness() -> None:
    """Opt in before Tk/matplotlib load so Windows does not bitmap-scale the interface."""
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("TrackJudge.TrackJudge")
        # PER_MONITOR_AWARE_V2. Negative constants are predefined DPI contexts.
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        with suppress(Exception):
            ctypes.windll.user32.SetProcessDPIAware()


# This must run before importing the analysis module: matplotlib may initialize
# process-level display behavior while it is imported.
enable_windows_dpi_awareness()

from .app import (  # noqa: E402
    MAX_URLS,
    build_parser,
    configure_console,
    default_dest_folder,
    render_spectrogram,
    run_analysis,
    unique_dest_path,
)
from .theme import (  # noqa: E402
    FONTS,
    RADII,
    SIZES,
    SPACING,
    apply_font_scale,
)
from .theme import (  # noqa: E402
    build_theme_colors as _build_theme_colors,
)

APP_TITLE = "TrackJudge"


def _rounded_rectangle(
    canvas: Any,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    radius: float,
    fill: str,
    outline: str,
    width: int = 1,
    tags: str | None = None,
) -> int:
    radius = min(radius, (x2 - x1) / 2, (y2 - y1) / 2)
    points = (
        x1 + radius,
        y1,
        x2 - radius,
        y1,
        x2,
        y1,
        x2,
        y1 + radius,
        x2,
        y2 - radius,
        x2,
        y2,
        x2 - radius,
        y2,
        x1 + radius,
        y2,
        x1,
        y2,
        x1,
        y2 - radius,
        x1,
        y1 + radius,
        x1,
        y1,
    )
    return canvas.create_polygon(
        points,
        smooth=True,
        splinesteps=24,
        fill=fill,
        outline=outline,
        width=width,
        tags=tags,
    )


def _apply_rounded_corners(
    tk: Any,
    frame: Any,
    *,
    radius: int,
    fill: str,
    outside: str,
    outline: str | None = None,
) -> None:
    outline = COLORS["border"] if outline is None else outline
    definitions = (
        (0.0, 0.0, "nw", (0, 0, radius * 2, radius * 2), 90),
        (1.0, 0.0, "ne", (-radius, 0, radius, radius * 2), 0),
        (0.0, 1.0, "sw", (0, -radius, radius * 2, radius), 180),
        (1.0, 1.0, "se", (-radius, -radius, radius, radius), 270),
    )
    corners = []
    for relx, rely, anchor, bounds, start in definitions:
        canvas = tk.Canvas(
            frame,
            width=radius,
            height=radius,
            background=outside,
            highlightthickness=0,
            borderwidth=0,
        )
        canvas.create_arc(
            *bounds,
            start=start,
            extent=90,
            style="pieslice",
            fill=fill,
            outline=fill,
        )
        canvas.create_arc(
            *bounds,
            start=start,
            extent=90,
            style="arc",
            outline=outline,
            width=1,
        )
        canvas.place(relx=relx, rely=rely, anchor=anchor)
        corners.append(canvas)
    frame._trackjudge_rounded_corners = corners

    def lift_corners(_event: Any = None) -> None:
        for corner in corners:
            corner.tk.call("raise", corner._w)

    frame.bind(
        "<Configure>",
        lift_corners,
        add="+",
    )
    frame.after_idle(lift_corners)


COLORS = _build_theme_colors()

# Compact aliases keep the view code readable. Every value still comes from the
# explicit theme above.
BACKGROUND = COLORS["window"]
CARD = COLORS["surface"]
CARD_ALT = COLORS["surface_raised"]
INPUT = COLORS["field"]
TEXT = COLORS["text"]
MUTED = COLORS["text_secondary"]
ACCENT = COLORS["accent"]
ACCENT_ACTIVE = COLORS["accent_hover"]
GREEN = COLORS["success"]
GREEN_ACTIVE = COLORS["success"]
RED = COLORS["error"]
BORDER = COLORS["border"]
TITLE_BAR = COLORS["title_bar"]
GITHUB_URL = "https://github.com/emmzde"
TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        "workspace_title": "Сравнение аудиоисточников",
        "subtitle": "Сравните варианты одного трека и сохраните самый качественный.",
        "sources_title": "1. Вставьте ссылки на варианты трека",
        "source_placeholder": "Вставьте до 5 ссылок — по одной на строку.",
        "source_only_links": "Вставляются только веб-ссылки.",
        "sources_recognized": "Ссылки распознаны.",
        "too_many_links": "Найдено {count} ссылок. Оставьте не больше {maximum}.",
        "status_too_many": "Слишком много ссылок.",
        "status_ready": "Готово к сравнению.",
        "status_need_link": "Вставьте хотя бы одну ссылку.",
        "settings_title": "2. Сохранение и доступ к YouTube",
        "choose_folder": "Выбрать папку",
        "choose_folder_title": "Куда сохранить результат TrackJudge?",
        "spectrogram_option": "Создать спектрограммы для всех вариантов",
        "json_option": "Создать подробный JSON-отчёт",
        "browser_option": "Использовать вход из браузера при блокировке YouTube",
        "start": "Начать сравнение",
        "comparing": "Сравнение…",
        "result_placeholder_title": "Результат появится здесь",
        "result_placeholder": "TrackJudge покажет победителя, оценку и путь к сохранённому файлу.",
        "show_log": "Технический журнал",
        "hide_log": "Скрыть журнал",
        "view_analysis": "Посмотреть анализ",
        "open_audio": "Открыть аудио",
        "open_folder": "Открыть папку",
        "open_json": "Открыть JSON",
        "running_title": "Сравнение выполняется",
        "running_text": "Ссылки скачиваются последовательно, аудиоанализ выполняется параллельно.",
        "running_status": "Загрузка и анализ…",
        "started_log": "TrackJudge начал сравнение.",
        "winner": "Лучший вариант",
        "spectrum_to": "спектр до ~{cutoff:.1f} кГц",
        "errors_count": "ошибок: {count}",
        "completed": "Анализ завершён",
        "return_form": "Вернуться к форме",
        "analysis_title": "Подробный анализ вариантов",
        "analysis_subtitle": "Метрики, объяснение оценки и спектрограмма каждого источника",
        "spectrogram_gallery_title": "Спектрограммы всех вариантов",
        "spectrogram_ready": "Готово: {ready} из {total}",
        "spectrogram_full_size_hint": "Каждое изображение открывается в полном размере.",
        "back": "← Назад",
        "no_candidates": "Нет успешно обработанных вариантов.",
        "winner_badge": "  •  ПОБЕДИТЕЛЬ",
        "untitled": "Без названия",
        "format": "Формат",
        "duration": "Длительность",
        "cutoff": "Полезный срез",
        "authenticity": "Достоверность ВЧ",
        "kbps": "кбит/с",
        "seconds": "с",
        "khz": "кГц",
        "open_spectrogram": "Открыть спектрограмму",
        "save_spectrogram": "Сохранить в папку результата",
        "spectrogram_saved": "Спектрограмма сохранена: {path}",
        "spectrogram_saved_button": "Сохранено",
        "spectrogram_missing": "Спектрограмма для этого варианта не создана.",
        "source_failed": "Не удалось обработать источник",
        "unknown_error": "Неизвестная ошибка",
        "clipboard_empty": "В буфере обмена нет текста.",
        "clipboard_no_links": "В буфере обмена не найдено веб-ссылок.",
        "links_not_found": "Не найдены ссылки",
        "insert_full_link": "Вставьте хотя бы одну полную веб-ссылку.",
        "too_many_variants": "Слишком много вариантов",
        "leave_max_links": "Оставьте в поле не больше {maximum} ссылок.",
        "folder_missing": "Не указана папка",
        "enter_folder": "Введите путь для сохранения результата.",
        "folder_create_failed": "Не удалось создать папку",
        "comparison_failed": "Сравнение не завершено",
        "no_links_processed": "Не удалось обработать ни одной ссылки. Причина показана в журнале ниже.",
        "open_failed": "Не удалось открыть",
        "save_failed": "Не удалось сохранить",
        "wait_until_done": "Сравнение ещё выполняется — дождитесь завершения.",
        "quality_high": "высокое качество",
        "quality_medium": "среднее качество",
        "quality_low": "низкое качество",
        "analysis_variants": "Вариантов",
        "analysis_best_score": "Лучшая оценка",
        "analysis_best_format": "Формат победителя",
        "analysis_failures": "Ошибок",
        "analytics": "Обзор",
        "kpi_sources": "Источники",
        "kpi_limit": "Лимит вариантов",
        "kpi_spectrogram": "Спектрограммы",
        "kpi_report": "JSON-отчёт",
        "enabled": "Включено",
        "disabled": "Выключено",
        "evidence_title": "Источники для сравнения",
        "evidence_helper": "Добавьте до пяти ссылок на варианты одного трека.",
        "ranking_title": "Лучший вариант",
        "ranking_helper": "Итоговый рейтинг появится после анализа.",
        "configuration_title": "Параметры сравнения",
        "configuration_helper": "Папка сохранения, отчёт и параметры спектрограммы.",
        "option": "Параметр",
        "value": "Значение",
        "action": "Действие",
        "ranking_empty": "Ожидаем запуск сравнения",
        "score": "Оценка",
        "quality": "Качество",
        "sources_table_title": "Результаты по источникам",
        "sources_table_helper": "Ранжирование по спектральной достоверности и качеству.",
        "candidate": "Источник",
        "rank": "Место",
        "table_format": "Формат",
        "table_cutoff": "Срез",
    },
    "en": {
        "workspace_title": "Audio source comparison",
        "subtitle": "Compare versions of one track and keep the highest-quality source.",
        "sources_title": "1. Paste links to track versions",
        "source_placeholder": "Paste up to 5 links — one per line.",
        "source_only_links": "Only web links are accepted.",
        "sources_recognized": "Links recognized.",
        "too_many_links": "{count} links found. Keep no more than {maximum}.",
        "status_too_many": "Too many links.",
        "status_ready": "Ready to compare.",
        "status_need_link": "Paste at least one link.",
        "settings_title": "2. Saving and YouTube access",
        "choose_folder": "Choose folder",
        "choose_folder_title": "Where should TrackJudge save the result?",
        "spectrogram_option": "Create spectrograms for all versions",
        "json_option": "Create a detailed JSON report",
        "browser_option": "Use browser sign-in if YouTube blocks access",
        "start": "Start comparison",
        "comparing": "Comparing…",
        "result_placeholder_title": "The result will appear here",
        "result_placeholder": "TrackJudge will show the winner, score, and saved file location.",
        "show_log": "Technical log",
        "hide_log": "Hide log",
        "view_analysis": "View analysis",
        "open_audio": "Open audio",
        "open_folder": "Open folder",
        "open_json": "Open JSON",
        "running_title": "Comparison in progress",
        "running_text": "Links are downloaded sequentially while audio analysis runs in parallel.",
        "running_status": "Downloading and analyzing…",
        "started_log": "TrackJudge started the comparison.",
        "winner": "Best version",
        "spectrum_to": "spectrum to ~{cutoff:.1f} kHz",
        "errors_count": "errors: {count}",
        "completed": "Analysis complete",
        "return_form": "Return to form",
        "analysis_title": "Detailed version analysis",
        "analysis_subtitle": "Metrics, score explanation, and a spectrogram for every source",
        "spectrogram_gallery_title": "Spectrograms for every version",
        "spectrogram_ready": "Ready: {ready} of {total}",
        "spectrogram_full_size_hint": "Open any image at full size.",
        "back": "← Back",
        "no_candidates": "No versions were processed successfully.",
        "winner_badge": "  •  WINNER",
        "untitled": "Untitled",
        "format": "Format",
        "duration": "Duration",
        "cutoff": "Useful cutoff",
        "authenticity": "HF authenticity",
        "kbps": "kbps",
        "seconds": "s",
        "khz": "kHz",
        "open_spectrogram": "Open spectrogram",
        "save_spectrogram": "Save to results folder",
        "spectrogram_saved": "Spectrogram saved: {path}",
        "spectrogram_saved_button": "Saved",
        "spectrogram_missing": "No spectrogram was created for this version.",
        "source_failed": "Could not process source",
        "unknown_error": "Unknown error",
        "clipboard_empty": "The clipboard contains no text.",
        "clipboard_no_links": "No web links were found in the clipboard.",
        "links_not_found": "No links found",
        "insert_full_link": "Paste at least one complete web link.",
        "too_many_variants": "Too many versions",
        "leave_max_links": "Keep no more than {maximum} links in the field.",
        "folder_missing": "No folder specified",
        "enter_folder": "Enter a folder for the result.",
        "folder_create_failed": "Could not create folder",
        "comparison_failed": "Comparison did not finish",
        "no_links_processed": "No links could be processed. The reason is shown in the log below.",
        "open_failed": "Could not open",
        "save_failed": "Could not save",
        "wait_until_done": "Comparison is still running — wait until it finishes.",
        "quality_high": "high quality",
        "quality_medium": "medium quality",
        "quality_low": "low quality",
        "analysis_variants": "Versions",
        "analysis_best_score": "Best score",
        "analysis_best_format": "Winner format",
        "analysis_failures": "Failures",
        "analytics": "Overview",
        "kpi_sources": "Sources",
        "kpi_limit": "Variant limit",
        "kpi_spectrogram": "Spectrograms",
        "kpi_report": "JSON report",
        "enabled": "Enabled",
        "disabled": "Disabled",
        "evidence_title": "Comparison sources",
        "evidence_helper": "Add up to five versions of the same track.",
        "ranking_title": "Top candidate",
        "ranking_helper": "The ranked result appears after analysis.",
        "configuration_title": "Comparison settings",
        "configuration_helper": "Output folder, report and spectrogram options.",
        "option": "Option",
        "value": "Value",
        "action": "Action",
        "ranking_empty": "Waiting for a comparison",
        "score": "Score",
        "quality": "Quality",
        "sources_table_title": "Source results",
        "sources_table_helper": "Ranking by spectral authenticity and quality.",
        "candidate": "Source",
        "rank": "Rank",
        "table_format": "Format",
        "table_cutoff": "Cutoff",
    },
    "de": {
        "workspace_title": "Audioquellen vergleichen",
        "subtitle": "Vergleiche Versionen eines Tracks und behalte die hochwertigste Quelle.",
        "sources_title": "1. Links zu den Track-Versionen einfügen",
        "source_placeholder": "Bis zu 5 Links einfügen — einen pro Zeile.",
        "source_only_links": "Es werden nur Weblinks akzeptiert.",
        "sources_recognized": "Links erkannt.",
        "too_many_links": "{count} Links gefunden. Höchstens {maximum} behalten.",
        "status_too_many": "Zu viele Links.",
        "status_ready": "Bereit zum Vergleichen.",
        "status_need_link": "Mindestens einen Link einfügen.",
        "settings_title": "2. Speichern und YouTube-Zugriff",
        "choose_folder": "Ordner wählen",
        "choose_folder_title": "Wo soll TrackJudge das Ergebnis speichern?",
        "spectrogram_option": "Spektrogramme für alle Versionen erstellen",
        "json_option": "Detaillierten JSON-Bericht erstellen",
        "browser_option": "Browser-Anmeldung bei YouTube-Sperre verwenden",
        "start": "Vergleich starten",
        "comparing": "Vergleich läuft…",
        "result_placeholder_title": "Das Ergebnis erscheint hier",
        "result_placeholder": "TrackJudge zeigt Gewinner, Bewertung und Speicherort der Datei.",
        "show_log": "Technisches Protokoll",
        "hide_log": "Protokoll ausblenden",
        "view_analysis": "Analyse ansehen",
        "open_audio": "Audio öffnen",
        "open_folder": "Ordner öffnen",
        "open_json": "JSON öffnen",
        "running_title": "Vergleich läuft",
        "running_text": "Links werden nacheinander geladen, die Audioanalyse läuft parallel.",
        "running_status": "Download und Analyse…",
        "started_log": "TrackJudge hat den Vergleich gestartet.",
        "winner": "Beste Version",
        "spectrum_to": "Spektrum bis ~{cutoff:.1f} kHz",
        "errors_count": "Fehler: {count}",
        "completed": "Analyse abgeschlossen",
        "return_form": "Zurück zum Formular",
        "analysis_title": "Detaillierte Versionsanalyse",
        "analysis_subtitle": "Messwerte, Bewertungserklärung und Spektrogramm jeder Quelle",
        "spectrogram_gallery_title": "Spektrogramme aller Varianten",
        "spectrogram_ready": "Bereit: {ready} von {total}",
        "spectrogram_full_size_hint": "Jedes Bild kann in voller Größe geöffnet werden.",
        "back": "← Zurück",
        "no_candidates": "Keine Version wurde erfolgreich verarbeitet.",
        "winner_badge": "  •  GEWINNER",
        "untitled": "Ohne Titel",
        "format": "Format",
        "duration": "Dauer",
        "cutoff": "Nutzbarer Cutoff",
        "authenticity": "HF-Authentizität",
        "kbps": "kbit/s",
        "seconds": "s",
        "khz": "kHz",
        "open_spectrogram": "Spektrogramm öffnen",
        "save_spectrogram": "Im Ergebnisordner speichern",
        "spectrogram_saved": "Spektrogramm gespeichert: {path}",
        "spectrogram_saved_button": "Gespeichert",
        "spectrogram_missing": "Für diese Version wurde kein Spektrogramm erstellt.",
        "source_failed": "Quelle konnte nicht verarbeitet werden",
        "unknown_error": "Unbekannter Fehler",
        "clipboard_empty": "Die Zwischenablage enthält keinen Text.",
        "clipboard_no_links": "Keine Weblinks in der Zwischenablage gefunden.",
        "links_not_found": "Keine Links gefunden",
        "insert_full_link": "Mindestens einen vollständigen Weblink einfügen.",
        "too_many_variants": "Zu viele Versionen",
        "leave_max_links": "Höchstens {maximum} Links im Feld behalten.",
        "folder_missing": "Kein Ordner angegeben",
        "enter_folder": "Einen Ordner für das Ergebnis eingeben.",
        "folder_create_failed": "Ordner konnte nicht erstellt werden",
        "comparison_failed": "Vergleich nicht abgeschlossen",
        "no_links_processed": "Kein Link konnte verarbeitet werden. Der Grund steht im Protokoll.",
        "open_failed": "Öffnen fehlgeschlagen",
        "save_failed": "Speichern fehlgeschlagen",
        "wait_until_done": "Der Vergleich läuft noch — bitte bis zum Abschluss warten.",
        "quality_high": "hohe Qualität",
        "quality_medium": "mittlere Qualität",
        "quality_low": "niedrige Qualität",
        "analysis_variants": "Varianten",
        "analysis_best_score": "Beste Wertung",
        "analysis_best_format": "Siegerformat",
        "analysis_failures": "Fehler",
        "analytics": "Übersicht",
        "kpi_sources": "Quellen",
        "kpi_limit": "Variantenlimit",
        "kpi_spectrogram": "Spektrogramme",
        "kpi_report": "JSON-Bericht",
        "enabled": "Aktiv",
        "disabled": "Inaktiv",
        "evidence_title": "Vergleichsquellen",
        "evidence_helper": "Bis zu fünf Versionen desselben Titels hinzufügen.",
        "ranking_title": "Beste Variante",
        "ranking_helper": "Das Ranking erscheint nach der Analyse.",
        "configuration_title": "Vergleichseinstellungen",
        "configuration_helper": "Zielordner, Bericht und Spektrogrammoptionen.",
        "option": "Option",
        "value": "Wert",
        "action": "Aktion",
        "ranking_empty": "Vergleich noch nicht gestartet",
        "score": "Bewertung",
        "quality": "Qualität",
        "sources_table_title": "Quellergebnisse",
        "sources_table_helper": "Ranking nach Spektrumauthentizität und Qualität.",
        "candidate": "Quelle",
        "rank": "Rang",
        "table_format": "Format",
        "table_cutoff": "Grenze",
    },
}

URL_PATTERN = re.compile(
    r"https?://.*?(?=(?:https?://)|[\s<>'\"\[\]]|$)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class GuiRunConfig:
    sources: tuple[str, ...]
    output_folder: str
    save_spectrogram: bool = True
    save_json_report: bool = True
    use_browser_cookies: bool = True
    spectrogram_folder: str | None = None


def extract_sources(text: str) -> list[str]:
    """Extract unique URLs, including URLs pasted immediately one after another."""
    sources: list[str] = []
    for match in URL_PATTERN.finditer(text):
        value = match.group(0).strip().rstrip(".,;:!?)]}")
        if value and value not in sources:
            sources.append(value)
    return sources


def shorten_path(path: str | None, max_length: int = 72) -> str:
    if not path:
        return ""
    if len(path) <= max_length:
        return path
    value = PureWindowsPath(path) if "\\" in path else Path(path)
    anchor = value.anchor.rstrip("\\/")
    tail = str(Path(value.parent.name) / value.name)
    compact = f"{anchor}\\…\\{tail}" if anchor else f"…\\{tail}"
    if len(compact) <= max_length:
        return compact
    keep = max(12, max_length - len(anchor) - 5)
    return f"{anchor}\\…\\{value.name[-keep:]}"


def candidate_explanation(candidate: dict[str, Any], language: str = "ru") -> str:
    cutoff = float(candidate.get("effective_cutoff_hz", 0.0))
    raw_cutoff = float(candidate.get("raw_cutoff_hz", 0.0))
    score = float(candidate.get("score", 0.0))
    authenticity = float(candidate.get("authenticity", 0.0))
    reasons: list[str] = []

    language = language if language in TRANSLATIONS else "ru"
    if candidate.get("fake_noise") and language == "ru":
        reasons.append(
            "Выше полезного среза обнаружена почти неподвижная шумовая полка: "
            "высокие частоты выглядят добавленными искусственно."
        )
    elif candidate.get("fake_noise") and language == "en":
        reasons.append(
            "A nearly static noise shelf was found above the useful cutoff; "
            "the high frequencies appear to have been added artificially."
        )
    elif candidate.get("fake_noise"):
        reasons.append(
            "Oberhalb des nutzbaren Cutoffs wurde ein fast statisches Rauschband erkannt; "
            "die hohen Frequenzen wirken künstlich hinzugefügt."
        )
    elif cutoff < 15_500 and language == "ru":
        reasons.append(
            f"Полезный спектр заканчивается примерно на {cutoff / 1000:.1f} кГц — "
            "это характерный признак источника низкого качества или апскейла."
        )
    elif cutoff < 15_500 and language == "en":
        reasons.append(
            f"The useful spectrum ends at about {cutoff / 1000:.1f} kHz, "
            "a common sign of a low-quality source or an upscale."
        )
    elif cutoff < 15_500:
        reasons.append(
            f"Das nutzbare Spektrum endet bei etwa {cutoff / 1000:.1f} kHz — "
            "ein typisches Zeichen für eine minderwertige Quelle oder ein Upscale."
        )
    elif cutoff < 17_500 and language == "ru":
        reasons.append(
            f"Заметный ранний срез около {cutoff / 1000:.1f} кГц ограничивает детализацию "
            "верхнего диапазона."
        )
    elif cutoff < 17_500 and language == "en":
        reasons.append(
            f"A clear early cutoff near {cutoff / 1000:.1f} kHz limits upper-range detail."
        )
    elif cutoff < 17_500:
        reasons.append(
            f"Ein deutlicher früher Cutoff bei {cutoff / 1000:.1f} kHz begrenzt die Details "
            "im oberen Frequenzbereich."
        )
    elif cutoff < 19_000 and language == "ru":
        reasons.append(
            f"Верхний диапазон ослабевает около {cutoff / 1000:.1f} кГц; "
            "качество приемлемое, но уступает более полному спектру."
        )
    elif cutoff < 19_000 and language == "en":
        reasons.append(
            f"The upper range fades near {cutoff / 1000:.1f} kHz; quality is acceptable "
            "but below a fuller spectrum."
        )
    elif cutoff < 19_000:
        reasons.append(
            f"Der obere Bereich fällt bei etwa {cutoff / 1000:.1f} kHz ab; die Qualität "
            "ist brauchbar, liegt aber unter einem vollständigeren Spektrum."
        )
    elif language == "ru":
        reasons.append(
            f"Полезный спектр сохраняется примерно до {cutoff / 1000:.1f} кГц "
            "без явного раннего среза."
        )
    elif language == "en":
        reasons.append(
            f"The useful spectrum extends to about {cutoff / 1000:.1f} kHz "
            "without an obvious early cutoff."
        )
    else:
        reasons.append(
            f"Das nutzbare Spektrum reicht bis etwa {cutoff / 1000:.1f} kHz, "
            "ohne erkennbaren frühen Cutoff."
        )

    if raw_cutoff - cutoff > 1_500 and not candidate.get("fake_noise"):
        reasons.append(
            {
                "ru": "Энергия выше полезного среза есть, но она слабо похожа на музыкальный сигнал.",
                "en": "There is energy above the useful cutoff, but it barely resembles musical content.",
                "de": "Oberhalb des nutzbaren Cutoffs ist Energie vorhanden, sie ähnelt jedoch kaum einem Musiksignal.",
            }[language]
        )
    if authenticity < 45:
        template = {
            "ru": "Достоверность высокочастотного содержимого низкая: {value:.0f}/100.",
            "en": "High-frequency content authenticity is low: {value:.0f}/100.",
            "de": "Die Authentizität des Hochfrequenzinhalts ist niedrig: {value:.0f}/100.",
        }[language]
        reasons.append(template.format(value=authenticity))
    elif score >= 70:
        template = {
            "ru": "Итоговая спектральная оценка высокая: {value:.1f}/100.",
            "en": "The final spectral score is high: {value:.1f}/100.",
            "de": "Die abschließende Spektralbewertung ist hoch: {value:.1f}/100.",
        }[language]
        reasons.append(template.format(value=score))

    warnings = [str(item) for item in candidate.get("warnings", []) if str(item).strip()]
    if language == "ru":
        reasons.extend(warnings[:2])
    return " ".join(reasons)


def build_gui_namespace(config: GuiRunConfig, report_path: str) -> argparse.Namespace:
    """Translate GUI selections into the same arguments used by the CLI."""
    parser = build_parser()
    argv = [
        *config.sources,
        "--output",
        config.output_folder,
        "--json-report",
        report_path,
        "--pause",
        "0",
        "--browser-cookies",
        "auto" if config.use_browser_cookies else "off",
        "--no-color",
    ]
    if config.save_spectrogram:
        argv.extend(["--spectrogram", "--keep-loser-spectrograms"])
        if config.spectrogram_folder:
            argv.extend(["--spectrogram-dir", config.spectrogram_folder])
    args = parser.parse_args(argv)
    return args


def resource_path(relative_path: str) -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root) / relative_path
    return Path(__file__).resolve().parents[2] / relative_path


class QueueWriter:
    """File-like adapter that forwards Rich output to the Tk event queue."""

    encoding = "utf-8"

    def __init__(self, events: queue.Queue[tuple[str, Any]]) -> None:
        self.events = events
        self.buffer = ""

    def write(self, text: str) -> int:
        self.buffer += text.replace("\r", "")
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                self.events.put(("log", line.rstrip()))
        return len(text)

    def flush(self) -> None:
        if self.buffer.strip():
            self.events.put(("log", self.buffer.rstrip()))
        self.buffer = ""

    def isatty(self) -> bool:
        return False


class RoundedButton:
    """Keyboard-accessible canvas button matching the reference control geometry."""

    def __init__(
        self,
        tk: Any,
        parent: Any,
        *,
        text: str,
        style: str,
        command: Any = None,
    ) -> None:
        self.tk = tk
        self.parent = parent
        self.text = text
        self.style = style
        self.command = command
        self.state = "normal"
        self.hovered = False
        self.pressed = False
        self.focused = False
        self.font = getattr(parent.winfo_toplevel(), "_trackjudge_button_font", "TkDefaultFont")
        self.canvas = tk.Canvas(
            parent,
            height=SIZES["button"],
            background=parent.cget("background"),
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )
        self._resize_to_text()
        self.canvas.bind("<Configure>", lambda _event: self._redraw())
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<FocusIn>", self._on_focus)
        self.canvas.bind("<FocusOut>", self._on_focus)
        self.canvas.bind("<space>", self._invoke_from_keyboard)
        self.canvas.bind("<Return>", self._invoke_from_keyboard)
        self._redraw()

    @property
    def primary(self) -> bool:
        return self.style == "Accent.TButton"

    @property
    def result_action(self) -> bool:
        return self.style == "ResultAction.TButton"

    @property
    def result_secondary(self) -> bool:
        return self.style in {"ResultText.TButton", "ResultStrong.TButton"}

    def _resize_to_text(self) -> None:
        width = max(
            SIZES["button"],
            int(self.font.measure(self.text)) + SPACING[4] * 2,
        )
        self.canvas.configure(width=width)

    def _on_enter(self, _event: Any = None) -> None:
        self.hovered = True
        self._redraw()

    def _on_leave(self, _event: Any = None) -> None:
        self.hovered = False
        self.pressed = False
        self._redraw()

    def _on_press(self, _event: Any = None) -> None:
        if self.state != "disabled":
            self.pressed = True
            self.canvas.focus_set()
            self._redraw()

    def _on_release(self, event: Any) -> None:
        invoke = (
            self.pressed
            and self.state != "disabled"
            and 0 <= event.x <= self.canvas.winfo_width()
            and 0 <= event.y <= self.canvas.winfo_height()
        )
        self.pressed = False
        self._redraw()
        if invoke and callable(self.command):
            self.command()

    def _on_focus(self, _event: Any = None) -> None:
        self.focused = self.canvas.focus_get() == self.canvas
        self._redraw()

    def _invoke_from_keyboard(self, _event: Any = None) -> str:
        if self.state != "disabled" and callable(self.command):
            self.command()
        return "break"

    def _redraw(self) -> None:
        disabled = self.state == "disabled"
        if self.result_action:
            fill = COLORS["action_hover"] if self.hovered or self.pressed else COLORS["action"]
            foreground = TEXT
            border = fill
        elif self.primary:
            fill = ACCENT
            if self.hovered:
                fill = ACCENT_ACTIVE
            if self.pressed:
                fill = COLORS["accent_pressed"]
            foreground = COLORS["accent_text"]
            border = fill
        elif self.result_secondary:
            fill = COLORS["sidebar_muted"] if self.hovered else COLORS["result"]
            if self.pressed:
                fill = COLORS["sidebar"]
            foreground = COLORS["result_text"]
            border = COLORS["result_muted"]
        else:
            fill = COLORS["surface"]
            if self.hovered:
                fill = COLORS["hover"]
            if self.pressed:
                fill = COLORS["border"]
            foreground = TEXT
            border = COLORS["border_strong"] if self.hovered else BORDER
        if disabled:
            if self.result_action or self.result_secondary:
                fill = COLORS["result"]
                foreground = COLORS["result_muted"]
                border = COLORS["sidebar_muted"]
            else:
                fill = COLORS["canvas"] if self.primary else COLORS["surface"]
                foreground = COLORS["text_disabled"]
                border = BORDER

        width = max(self.canvas.winfo_width(), self.canvas.winfo_reqwidth())
        height = SIZES["button"]
        self.canvas.delete("all")
        _rounded_rectangle(
            self.canvas,
            1,
            1,
            width - 1,
            height - 1,
            radius=RADII["md"],
            fill=fill,
            outline=COLORS["action"] if self.focused and not disabled else border,
            width=SIZES["focus_ring"] if self.focused and not disabled else 1,
        )
        self.canvas.create_text(
            width / 2,
            height / 2,
            text=self.text,
            fill=foreground,
            font=self.font,
            anchor="center",
        )
        self.canvas.configure(cursor="arrow" if disabled else "hand2")

    def configure(self, **kwargs: Any) -> None:
        if "text" in kwargs:
            self.text = str(kwargs.pop("text"))
            self._resize_to_text()
        if "state" in kwargs:
            self.state = str(kwargs.pop("state"))
        if "command" in kwargs:
            self.command = kwargs.pop("command")
        if kwargs:
            self.canvas.configure(**kwargs)
        self._redraw()

    config = configure

    def grid(self, *args: Any, **kwargs: Any) -> Any:
        return self.canvas.grid(*args, **kwargs)

    def pack(self, *args: Any, **kwargs: Any) -> Any:
        return self.canvas.pack(*args, **kwargs)

    def grid_remove(self) -> None:
        self.canvas.grid_remove()


class StyledCheck:
    """A DPI-aware, theme-native checkbox drawn with simple outline geometry."""

    def __init__(
        self,
        tk: Any,
        parent: Any,
        *,
        text: str,
        variable: Any,
        font: tuple[Any, ...],
        background: str = CARD,
    ) -> None:
        self.tk = tk
        self.variable = variable
        self.state = "normal"
        self.background = background
        self.hovered = False
        self.box_size = SIZES["compact_icon"]
        self.frame = tk.Frame(
            parent,
            background=background,
            cursor="hand2",
            takefocus=1,
        )
        self.box = tk.Canvas(
            self.frame,
            width=self.box_size,
            height=self.box_size,
            background=background,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        self.box.pack(side="left", padx=(0, SPACING[2]))
        self.label = tk.Label(
            self.frame,
            text=text,
            background=background,
            foreground=TEXT,
            font=font,
            anchor="w",
            cursor="hand2",
        )
        self.label.pack(side="left", fill="x", expand=True)
        for widget in (self.frame, self.box, self.label):
            widget.bind("<Button-1>", self._toggle)
            widget.bind("<Enter>", self._on_enter)
            widget.bind("<Leave>", self._on_leave)
        self.frame.bind("<space>", self._toggle)
        self.frame.bind("<Return>", self._toggle)
        self.frame.bind("<FocusIn>", lambda _event: self._render())
        self.frame.bind("<FocusOut>", lambda _event: self._render())
        self._trace_id = self.variable.trace_add("write", lambda *_args: self._render())
        self._render()

    def _toggle(self, _event: Any = None) -> str:
        if self.state != "disabled":
            self.variable.set(not bool(self.variable.get()))
        return "break"

    def _on_enter(self, _event: Any = None) -> None:
        self.hovered = True
        self._render()

    def _on_leave(self, _event: Any = None) -> None:
        self.hovered = False
        self._render()

    def _render(self) -> None:
        disabled = self.state == "disabled"
        checked = bool(self.variable.get())
        focused = self.frame.focus_get() == self.frame
        fill = COLORS["field_disabled"] if disabled else ACCENT if checked else INPUT
        border = COLORS["text_disabled"] if disabled else BORDER
        if checked and not disabled:
            border = ACCENT
        if self.hovered and not disabled:
            border = COLORS["border_strong"]
        if focused and not disabled:
            border = ACCENT
        self.box.configure(background=self.background)
        self.box.delete("all")
        inset = 1
        _rounded_rectangle(
            self.box,
            inset,
            inset,
            self.box_size - inset,
            self.box_size - inset,
            radius=RADII["sm"],
            fill=fill,
            outline=border,
            width=1,
        )
        if checked:
            check_color = COLORS["text_disabled"] if disabled else COLORS["accent_text"]
            self.box.create_line(
                self.box_size * 0.25,
                self.box_size * 0.52,
                self.box_size * 0.43,
                self.box_size * 0.70,
                self.box_size * 0.77,
                self.box_size * 0.31,
                fill=check_color,
                width=max(2, round(self.box_size * 0.11)),
                capstyle="round",
                joinstyle="round",
            )
        color = COLORS["text_disabled"] if disabled else TEXT
        cursor = "arrow" if disabled else "hand2"
        self.frame.configure(cursor=cursor)
        self.box.configure(cursor=cursor)
        self.label.configure(foreground=color, cursor=cursor)

    def grid(self, *args: Any, **kwargs: Any) -> Any:
        return self.frame.grid(*args, **kwargs)

    def configure(self, **kwargs: Any) -> None:
        if "state" in kwargs:
            self.state = str(kwargs.pop("state"))
        if "text" in kwargs:
            self.label.configure(text=kwargs.pop("text"))
        if "background" in kwargs:
            self.background = str(kwargs.pop("background"))
            self.frame.configure(background=self.background)
            self.label.configure(background=self.background)
        if kwargs:
            self.frame.configure(**kwargs)
        self._render()


class LoadingSpinner:
    """Small animated activity indicator for the indeterminate analysis stage."""

    def __init__(self, tk: Any, parent: Any) -> None:
        self.tk = tk
        self.canvas = tk.Canvas(
            parent,
            width=SIZES["icon"],
            height=SIZES["icon"],
            background=parent.cget("background"),
            highlightthickness=0,
            borderwidth=0,
        )
        self.angle = 0
        self.running = False
        self.after_id: str | None = None
        self.canvas.grid_remove()

    def grid(self, *args: Any, **kwargs: Any) -> Any:
        result = self.canvas.grid(*args, **kwargs)
        if not self.running:
            self.canvas.grid_remove()
        return result

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.canvas.grid()
        self._tick()

    def stop(self) -> None:
        self.running = False
        if self.after_id is not None:
            with suppress(Exception):
                self.canvas.after_cancel(self.after_id)
        self.after_id = None
        self.canvas.delete("all")
        self.canvas.grid_remove()

    def _tick(self) -> None:
        if not self.running:
            return
        self.canvas.delete("all")
        inset = SPACING[1]
        end = SIZES["icon"] - inset
        self.canvas.create_oval(inset, inset, end, end, outline=COLORS["border"], width=2)
        self.canvas.create_arc(
            inset,
            inset,
            end,
            end,
            start=self.angle,
            extent=105,
            style="arc",
            outline=ACCENT,
            width=2,
        )
        self.canvas.create_arc(
            inset,
            inset,
            end,
            end,
            start=self.angle + 180,
            extent=35,
            style="arc",
            outline=COLORS["text_secondary"],
            width=2,
        )
        self.angle = (self.angle + 12) % 360
        self.after_id = self.canvas.after(40, self._tick)


class TrackJudgeWindow:
    def __init__(
        self,
        tk: Any,
        ttk: Any,
        tkfont: Any,
        initial_sources: list[str] | None = None,
    ) -> None:
        self.tk = tk
        self.ttk = ttk
        self.tkfont = tkfont
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.running = False
        self.last_output_folder: str | None = None
        self.last_winner_file: str | None = None
        self.last_report_path: str | None = None
        self.last_payload: dict[str, Any] | None = None
        self.log_lines: list[str] = []
        self.log_visible = False
        self.notification_overlay: Any | None = None
        self.analysis_overlay: Any | None = None
        self._analysis_images: list[Any] = []
        self._normalizing_sources = False
        self._controls: list[Any] = []
        self.language = "ru"
        self.spectrogram_temp_folder: str | None = None
        self.report_temp_folder: str | None = None
        self.language_popup: Any | None = None
        self._is_maximized = False
        self._font_scale = 1.0
        self._normal_geometry = f"{SIZES['window_width']}x{SIZES['window_height']}"
        self._drag_origin: tuple[int, int, int, int] | None = None

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry(self._normal_geometry)
        self.root.minsize(SIZES["window_min_width"], SIZES["window_min_height"])
        self.root.configure(background=BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        apply_font_scale(self._font_scale)
        self._configure_dpi_and_fonts()
        self._set_icon()
        self._configure_styles()
        self.root.overrideredirect(True)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self._build_title_bar()
        self.content_host = self.tk.Frame(self.root, background=BACKGROUND)
        self.content_host.grid(row=1, column=0, sticky="nsew")
        self.content_host.columnconfigure(0, weight=1)
        self.content_host.rowconfigure(0, weight=1)
        self._build_layout()
        self._center_window()
        self.root.after(20, self._configure_native_window)

        if initial_sources:
            self.source_text.insert("1.0", "\n".join(initial_sources))
        self._sync_sources()
        self.root.after(100, self._poll_events)

    def _configure_dpi_and_fonts(self) -> None:
        self.root.update_idletasks()
        with suppress(Exception):
            dpi = float(self.root.winfo_fpixels("1i"))
            self.root.tk.call("tk", "scaling", dpi / 72.0)

        families = {name.casefold(): name for name in self.tkfont.families(self.root)}
        self.font_family = next(
            (
                families[name.casefold()]
                for name in (
                    "Poppins",
                    "Segoe UI Variable Text Semibold",
                    "Segoe UI Variable Text",
                    "Segoe UI Variable",
                    "Segoe UI",
                )
                if name.casefold() in families
            ),
            "TkDefaultFont",
        )
        self.heading_family = next(
            (
                families[name.casefold()]
                for name in (
                    "Poppins",
                    "Segoe UI Variable Display Semib",
                    "Segoe UI Variable Display",
                    "Segoe UI Semibold",
                    self.font_family,
                )
                if name.casefold() in families
            ),
            self.font_family,
        )
        # Poppins uses tabular numerals for the metric strings used in this UI;
        # keeping one family also matches the reference's compact typography.
        self.mono_family = self.font_family
        self.button_font = self.tkfont.Font(
            root=self.root,
            family=self.font_family,
            size=FONTS["body"]["size"],
            weight=FONTS["control_strong"]["weight"],
        )
        self.root._trackjudge_button_font = self.button_font
        self.root.option_add("*Font", (self.font_family, FONTS["body"]["size"]))

    def tr(self, key: str, **values: Any) -> str:
        text = TRANSLATIONS.get(self.language, TRANSLATIONS["ru"]).get(key, key)
        return text.format(**values) if values else text

    def _set_icon(self) -> None:
        ico_path = resource_path("assets/trackjudge-v2.ico")
        png_path = resource_path("assets/trackjudge-icon-v2.png")
        try:
            if ico_path.is_file():
                self.root.iconbitmap(default=str(ico_path))
        except Exception:
            pass
        try:
            if png_path.is_file():
                icon = self.tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, icon)
                self._window_icon = icon
        except Exception:
            self._window_icon = None

    def _configure_styles(self) -> None:
        style = self.ttk.Style(self.root)
        style.theme_use("clam")
        space = SPACING
        body_font = (self.font_family, FONTS["body"]["size"])
        label_font = (
            self.font_family,
            FONTS["label"]["size"],
            FONTS["label"]["weight"],
        )
        heading_font = (
            self.heading_family,
            FONTS["heading"]["size"],
            FONTS["heading"]["weight"],
        )

        for frame_style, background in (
            ("App.TFrame", BACKGROUND),
            ("Card.TFrame", CARD),
            ("CardAlt.TFrame", CARD_ALT),
            ("Settings.TFrame", CARD),
            ("Result.TFrame", CARD),
        ):
            style.configure(frame_style, background=background)

        style.configure(
            "Title.TLabel",
            background=BACKGROUND,
            foreground=TEXT,
            font=(
                self.heading_family,
                FONTS["display"]["size"],
                FONTS["display"]["weight"],
            ),
        )
        style.configure(
            "Subtitle.TLabel",
            background=BACKGROUND,
            foreground=COLORS["muted"],
            font=body_font,
        )
        style.configure(
            "Section.TLabel",
            background=CARD,
            foreground=TEXT,
            font=heading_font,
        )
        style.configure(
            "SettingsSection.TLabel",
            background=CARD,
            foreground=TEXT,
            font=heading_font,
        )
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=body_font)
        style.configure(
            "Muted.TLabel",
            background=CARD,
            foreground=COLORS["muted"],
            font=body_font,
        )
        style.configure("Error.TLabel", background=CARD, foreground=RED, font=body_font)
        style.configure(
            "Settings.TLabel",
            background=CARD,
            foreground=COLORS["muted"],
            font=body_font,
        )
        for status_style, foreground in (
            ("Status.TLabel", COLORS["muted"]),
            ("StatusReady.TLabel", GREEN),
            ("StatusError.TLabel", RED),
        ):
            style.configure(
                status_style,
                background=COLORS["portfolio"],
                foreground=foreground,
                font=label_font,
            )
        style.configure(
            "PortfolioMuted.TLabel",
            background=COLORS["portfolio"],
            foreground=COLORS["muted"],
            font=label_font,
        )
        style.configure(
            "PortfolioError.TLabel",
            background=COLORS["portfolio"],
            foreground=RED,
            font=label_font,
        )
        style.configure(
            "Counter.TLabel",
            background=CARD,
            foreground=COLORS["muted"],
            padding=(space[2], space[1]),
            font=(self.mono_family, FONTS["label"]["size"], "bold"),
        )
        for result_style, foreground in (
            ("ResultTitle.TLabel", COLORS["result_text"]),
            ("ResultError.TLabel", COLORS["asset_sand"]),
        ):
            style.configure(
                result_style,
                background=COLORS["result"],
                foreground=foreground,
                font=heading_font,
            )
        style.configure(
            "Result.TLabel",
            background=COLORS["result"],
            foreground=COLORS["result_muted"],
            font=body_font,
        )
        style.configure(
            "ResultPath.TLabel",
            background=COLORS["result"],
            foreground=COLORS["result_muted"],
            font=(self.mono_family, FONTS["label"]["size"]),
        )

        style.configure(
            "App.TEntry",
            fieldbackground=INPUT,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            borderwidth=1,
            padding=(space[3], space[2]),
            font=body_font,
        )
        style.map(
            "App.TEntry",
            fieldbackground=[("disabled", COLORS["field_disabled"]), ("readonly", INPUT)],
            foreground=[("disabled", COLORS["text_disabled"]), ("readonly", TEXT)],
            bordercolor=[("focus", ACCENT), ("active", COLORS["border_strong"])],
            lightcolor=[("focus", ACCENT)],
            darkcolor=[("focus", ACCENT)],
        )

        button_font = (
            self.font_family,
            FONTS["body"]["size"],
            FONTS["control_strong"]["weight"],
        )
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground=COLORS["accent_text"],
            bordercolor=ACCENT,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            borderwidth=1,
            padding=(space[4], space[2]),
            font=button_font,
        )
        style.map(
            "Accent.TButton",
            background=[
                ("pressed", COLORS["accent_pressed"]),
                ("active", ACCENT_ACTIVE),
                ("disabled", COLORS["canvas"]),
            ],
            bordercolor=[("disabled", BORDER)],
            lightcolor=[("disabled", BORDER)],
            darkcolor=[("disabled", BORDER)],
            foreground=[("disabled", COLORS["text_disabled"])],
        )

        secondary_styles = (
            "Secondary.TButton",
            "SecondaryStrong.TButton",
            "ResultText.TButton",
            "CardText.TButton",
            "ResultStrong.TButton",
            "ModalText.TButton",
            "ModalStrong.TButton",
        )
        for button_style in secondary_styles:
            style.configure(
                button_style,
                background=CARD,
                foreground=TEXT,
                bordercolor=BORDER,
                lightcolor=BORDER,
                darkcolor=BORDER,
                borderwidth=1,
                padding=(space[3], space[2]),
                font=button_font,
            )
            style.map(
                button_style,
                background=[("pressed", COLORS["border"]), ("active", COLORS["hover"])],
                bordercolor=[("active", COLORS["border_strong"]), ("disabled", BORDER)],
                foreground=[("disabled", COLORS["text_disabled"])],
            )

        style.configure(
            "TCheckbutton",
            background=CARD,
            foreground=TEXT,
            font=body_font,
        )
        style.map(
            "TCheckbutton",
            background=[("active", CARD)],
            foreground=[("disabled", COLORS["text_disabled"])],
            indicatorcolor=[("selected", ACCENT), ("!selected", INPUT)],
        )
        style.configure(
            "Horizontal.TProgressbar",
            background=ACCENT,
            troughcolor=COLORS["border"],
            borderwidth=0,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=SIZES["progress"],
        )
        style.configure(
            "Analysis.Vertical.TScrollbar",
            background=COLORS["border_strong"],
            troughcolor=BACKGROUND,
            bordercolor=BACKGROUND,
            arrowcolor=COLORS["muted"],
            lightcolor=COLORS["border_strong"],
            darkcolor=BORDER,
        )

    def _build_waveform_mark(
        self,
        parent: Any,
        *,
        background: str,
        width: int,
        height: int,
        color: str = TEXT,
    ) -> Any:
        canvas = self.tk.Canvas(
            parent,
            width=width,
            height=height,
            background=background,
            highlightthickness=0,
            borderwidth=0,
        )
        levels = (0.18, 0.38, 0.68, 0.42, 0.86, 0.52, 0.72, 0.34, 0.16)
        step = width / (len(levels) + 1)
        center = height / 2
        line_width = max(1, round(width / 28))
        for index, level in enumerate(levels, 1):
            x = index * step
            half = max(2, height * level / 2)
            canvas.create_line(
                x,
                center - half,
                x,
                center + half,
                fill=color,
                width=line_width,
                capstyle="round",
            )
        return canvas

    def _build_github_button(self, parent: Any) -> Any:
        item_size = SPACING[7]
        icon_size = SIZES["icon"]
        canvas = self.tk.Canvas(
            parent,
            width=item_size,
            height=item_size,
            background=COLORS["sidebar"],
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
            takefocus=1,
        )

        def point(x: float, y: float) -> tuple[float, float]:
            inset = (item_size - icon_size) / 2
            return inset + x * icon_size, inset + y * icon_size

        def draw(active: bool = False) -> None:
            canvas.delete("all")
            background = COLORS["selected"] if active else COLORS["sidebar"]
            color = COLORS["surface"] if active else COLORS["sidebar_muted"]
            _rounded_rectangle(
                canvas,
                1,
                1,
                item_size - 1,
                item_size - 1,
                radius=RADII["md"],
                fill=background,
                outline=background,
            )
            silhouette = (
                point(0.08, 0.46),
                point(0.12, 0.29),
                point(0.26, 0.16),
                point(0.27, 0.02),
                point(0.43, 0.13),
                point(0.57, 0.13),
                point(0.73, 0.02),
                point(0.74, 0.17),
                point(0.88, 0.30),
                point(0.92, 0.48),
                point(0.87, 0.66),
                point(0.74, 0.78),
                point(0.62, 0.82),
                point(0.62, 0.98),
                point(0.38, 0.98),
                point(0.38, 0.82),
                point(0.25, 0.78),
                point(0.13, 0.65),
            )
            canvas.create_polygon(
                *(coordinate for pair in silhouette for coordinate in pair),
                smooth=True,
                splinesteps=24,
                fill=color,
                outline=color,
            )
            tail = (point(0.39, 0.88), point(0.26, 0.90), point(0.18, 0.78), point(0.06, 0.77))
            canvas.create_line(
                *(coordinate for pair in tail for coordinate in pair),
                smooth=True,
                fill=color,
                width=SIZES["stroke"],
                capstyle="round",
                joinstyle="round",
            )

        def open_profile(_event: Any = None) -> str:
            self._open_path(GITHUB_URL)
            return "break"

        canvas.bind("<Enter>", lambda _event: draw(True))
        canvas.bind("<Leave>", lambda _event: draw(canvas.focus_get() == canvas))
        canvas.bind("<FocusIn>", lambda _event: draw(True))
        canvas.bind("<FocusOut>", lambda _event: draw(False))
        canvas.bind("<Button-1>", open_profile)
        canvas.bind("<Return>", open_profile)
        canvas.bind("<space>", open_profile)
        draw()
        return canvas

    def _build_title_bar(self) -> None:
        space = SPACING
        bar = self.tk.Frame(
            self.root,
            background=TITLE_BAR,
            height=SIZES["top_bar"],
            highlightbackground=COLORS["divider"],
            highlightthickness=0,
        )
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(2, weight=1)
        self.title_bar = bar

        logo_cell = self.tk.Frame(
            bar,
            width=SIZES["sidebar"],
            height=SIZES["top_bar"],
            background=COLORS["sidebar"],
        )
        logo_cell.grid(row=0, column=0, sticky="nsw")
        logo_cell.grid_propagate(False)
        logo_badge = self.tk.Frame(
            logo_cell,
            width=SIZES["button"],
            height=SIZES["button"],
            background=COLORS["asset_sand"],
        )
        logo_badge.place(relx=0.5, rely=0.5, anchor="center")
        logo_badge.pack_propagate(False)
        _apply_rounded_corners(
            self.tk,
            logo_badge,
            radius=RADII["md"],
            fill=COLORS["asset_sand"],
            outside=COLORS["sidebar"],
            outline=COLORS["asset_sand"],
        )
        mark = self._build_waveform_mark(
            logo_badge,
            background=COLORS["asset_sand"],
            width=SIZES["icon"],
            height=SIZES["compact_icon"],
            color=COLORS["sidebar"],
        )
        mark.place(relx=0.5, rely=0.5, anchor="center")

        self.destination_var = self.tk.StringVar(value=self.tr("analytics"))
        title = self.tk.Label(
            bar,
            textvariable=self.destination_var,
            background=TITLE_BAR,
            foreground=TEXT,
            font=(
                self.heading_family,
                FONTS["screen_title"]["size"],
                FONTS["screen_title"]["weight"],
            ),
        )
        title.grid(row=0, column=1, sticky="w", padx=(space[6], 0))

        self.language_button = self._title_button(
            bar,
            "RU  ▾",
            self._toggle_language_popup,
            width=6,
            hover=COLORS["hover"],
        )
        self.language_button.grid(row=0, column=3, sticky="e", padx=(space[2], space[1]))

        self._minimize_button = self._window_control_button(
            bar,
            "minimize",
            self._minimize_window,
            hover=COLORS["hover"],
        )
        self._minimize_button.grid(row=0, column=4, sticky="e")
        self._maximize_button = self._window_control_button(
            bar,
            "maximize",
            self._toggle_maximize,
            hover=COLORS["hover"],
        )
        self._maximize_button.grid(row=0, column=5, sticky="e")
        self._close_button = self._window_control_button(
            bar,
            "close",
            self._on_close,
            hover=COLORS["error"],
        )
        self._close_button.grid(row=0, column=6, sticky="e")

        for widget in (bar, logo_cell, logo_badge, mark, title):
            widget.bind("<ButtonPress-1>", self._start_window_drag)
            widget.bind("<B1-Motion>", self._drag_window)
            widget.bind("<Double-Button-1>", lambda _event: self._toggle_maximize())

    def _title_button(
        self,
        parent: Any,
        text: str,
        command: Any,
        *,
        width: int,
        hover: str,
    ) -> Any:
        button = self.tk.Label(
            parent,
            text=text,
            width=width,
            background=TITLE_BAR,
            foreground=TEXT,
            borderwidth=0,
            padx=SPACING[3],
            pady=SPACING[2],
            font=(self.font_family, FONTS["label"]["size"], "bold"),
            cursor="hand2",
        )
        button.bind("<Button-1>", lambda _event: command())
        button.bind("<Enter>", lambda _event: button.configure(background=hover))
        button.bind("<Leave>", lambda _event: button.configure(background=TITLE_BAR))
        return button

    def _window_control_button(
        self,
        parent: Any,
        kind: str,
        command: Any,
        *,
        hover: str,
    ) -> Any:
        button = self.tk.Canvas(
            parent,
            width=SIZES["button"],
            height=SIZES["top_bar"] - (SPACING[1] * 2),
            background=TITLE_BAR,
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        button._trackjudge_icon = kind
        self._draw_window_control(button, kind)
        button.bind("<Button-1>", lambda _event: command())
        button.bind(
            "<Enter>",
            lambda _event: self._set_window_control_background(button, hover),
        )
        button.bind(
            "<Leave>",
            lambda _event: self._set_window_control_background(button, TITLE_BAR),
        )
        return button

    def _set_window_control_background(self, button: Any, color: str) -> None:
        button.configure(background=color)
        self._draw_window_control(button, button._trackjudge_icon)

    def _draw_window_control(self, button: Any, kind: str) -> None:
        button._trackjudge_icon = kind
        button.delete("window-icon")
        color = COLORS["accent_text"] if button.cget("background") == RED else COLORS["text"]
        center = SIZES["button"] // 2
        half = SIZES["compact_icon"] // 2
        left = center - half
        right = center + half
        top = (SIZES["top_bar"] - (SPACING[1] * 2) - SIZES["compact_icon"]) // 2
        bottom = top + SIZES["compact_icon"]
        if kind == "minimize":
            button.create_line(
                left,
                bottom - SPACING[1],
                right,
                bottom - SPACING[1],
                fill=color,
                width=1,
                tags="window-icon",
            )
        elif kind == "maximize":
            button.create_rectangle(
                left,
                top,
                right,
                bottom,
                outline=color,
                width=1,
                tags="window-icon",
            )
        elif kind == "restore":
            button.create_rectangle(
                left + SPACING[1],
                top,
                right,
                bottom - SPACING[1],
                outline=color,
                width=1,
                tags="window-icon",
            )
            button.create_rectangle(
                left,
                top + SPACING[1],
                right - SPACING[1],
                bottom,
                fill=button.cget("background"),
                outline=color,
                width=1,
                tags="window-icon",
            )
        else:
            button.create_line(left, top, right, bottom, fill=color, width=1, tags="window-icon")
            button.create_line(right, top, left, bottom, fill=color, width=1, tags="window-icon")

    def _configure_native_window(self) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            ex_style = ctypes.windll.user32.GetWindowLongW(hwnd, -20)
            ex_style = (ex_style | 0x00040000) & ~0x00000080
            ctypes.windll.user32.SetWindowLongW(hwnd, -20, ex_style)
        except Exception:
            pass

    def _native_window_handle(self) -> int:
        if os.name != "nt":
            return 0
        try:
            import ctypes

            return int(ctypes.windll.user32.GetParent(self.root.winfo_id()))
        except Exception:
            return 0

    def _minimize_window(self) -> None:
        self._dismiss_language_popup()
        hwnd = self._native_window_handle()
        if hwnd:
            import ctypes

            ctypes.windll.user32.ShowWindow(hwnd, 6)
        else:
            self.root.iconify()

    def _toggle_maximize(self) -> None:
        self._dismiss_language_popup()
        if self._is_maximized:
            self.root.geometry(self._normal_geometry)
            self._is_maximized = False
            self.root.after(80, lambda: self._rebuild_interface_for_scale(1.0))
            return
        self._normal_geometry = self.root.geometry()
        left, top, right, bottom = self._work_area()
        self.root.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
        self._is_maximized = True
        scale = min((right - left) / SIZES["window_width"], (bottom - top) / SIZES["window_height"])
        self.root.after(80, lambda value=scale: self._rebuild_interface_for_scale(value))

    def _rebuild_interface_for_scale(self, scale: float) -> None:
        target_scale = max(1.0, min(1.35, float(scale)))
        if abs(target_scale - self._font_scale) < 0.01:
            self._draw_window_control(
                self._maximize_button,
                "restore" if self._is_maximized else "maximize",
            )
            return

        sources = self._current_sources()
        output = self.output_var.get()
        spectrogram = bool(self.spectrogram_var.get())
        json_report = bool(self.json_var.get())
        browser = bool(self.browser_cookies_var.get())
        log_visible = self.log_visible
        log_lines = list(self.log_lines)
        show_analysis = self.analysis_overlay is not None
        result_title = self.result_title_var.get()
        result_text = self.result_text_var.get()
        result_path = self.result_path_var.get()
        result_style = str(self.result_title_label.cget("style"))
        status = self.status_var.get()
        status_style = str(self.status_label.cget("style"))

        if self.running:
            self.loading_spinner.stop()
        self._dismiss_notification()
        self._close_analysis_screen()
        self._dismiss_language_popup()
        self.title_bar.destroy()
        self.content_host.destroy()

        self._font_scale = target_scale
        apply_font_scale(target_scale)
        self._configure_dpi_and_fonts()
        self._configure_styles()
        self._build_title_bar()
        self.content_host = self.tk.Frame(self.root, background=BACKGROUND)
        self.content_host.grid(row=1, column=0, sticky="nsew")
        self.content_host.columnconfigure(0, weight=1)
        self.content_host.rowconfigure(0, weight=1)
        self._build_layout()

        self.output_var.set(output)
        self.spectrogram_var.set(spectrogram)
        self.json_var.set(json_report)
        self.browser_cookies_var.set(browser)
        self._set_source_values(sources)
        self.log_lines = []
        for line in log_lines:
            self._append_log(line)
        self.log_visible = log_visible
        if log_visible:
            self.log_text.grid()
            self.log_toggle_button.configure(text=self.tr("hide_log"))

        winner = self.last_payload.get("winner") if self.last_payload else None
        if isinstance(winner, dict):
            self._render_winner_summary(winner, self.last_payload.get("failures", []))
        else:
            self.result_title_var.set(result_title)
            self.result_text_var.set(result_text)
            self.result_path_var.set(result_path)
            self.result_title_label.configure(style=result_style)
            self.status_var.set(status)
            self.status_label.configure(style=status_style)
        if self.running:
            self.start_button.configure(text=self.tr("comparing"))
            self._set_controls_enabled(False)
            self.loading_spinner.start()
        else:
            self.status_var.set(status)
            self.status_label.configure(style=status_style)
        self._sync_button_states()
        self._draw_window_control(
            self._maximize_button,
            "restore" if self._is_maximized else "maximize",
        )
        if show_analysis and self.last_payload:
            self._show_analysis_screen()

    def _start_window_drag(self, event: Any) -> None:
        self._dismiss_language_popup()
        if self._is_maximized:
            return
        self._drag_origin = (
            int(event.x_root),
            int(event.y_root),
            self.root.winfo_x(),
            self.root.winfo_y(),
        )

    def _drag_window(self, event: Any) -> None:
        if self._is_maximized or not self._drag_origin:
            return
        start_x, start_y, window_x, window_y = self._drag_origin
        x = window_x + int(event.x_root) - start_x
        y = window_y + int(event.y_root) - start_y
        self.root.geometry(f"+{x}+{y}")

    def _toggle_language_popup(self) -> None:
        if self.running:
            return
        if self.language_popup is not None:
            self._dismiss_language_popup()
            return
        popup = self.tk.Frame(
            self.root,
            background=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        popup.place(
            relx=1.0,
            x=-(SIZES["button"] * 3 + SPACING[2]),
            y=SIZES["top_bar"] - SPACING[1],
            width=SIZES["language_menu"],
            anchor="ne",
        )
        self.language_popup = popup
        for row, (code, label) in enumerate(
            (("ru", "Русский"), ("en", "English"), ("de", "Deutsch"))
        ):
            button = self.tk.Label(
                popup,
                text=("✓  " if code == self.language else "     ") + label,
                background=CARD,
                foreground=TEXT if code == self.language else MUTED,
                anchor="w",
                padx=SPACING[3],
                pady=SPACING[2],
                cursor="hand2",
                font=(self.font_family, FONTS["body"]["size"]),
            )
            button.grid(row=row, column=0, sticky="ew")
            button.bind("<Button-1>", lambda _event, value=code: self._change_language(value))
            button.bind(
                "<Enter>",
                lambda _event, item=button: item.configure(background=COLORS["hover"]),
            )
            button.bind("<Leave>", lambda _event, item=button: item.configure(background=CARD))
        popup.columnconfigure(0, weight=1)
        popup.lift()

    def _dismiss_language_popup(self) -> None:
        if self.language_popup is not None:
            with suppress(Exception):
                self.language_popup.destroy()
            self.language_popup = None

    def _change_language(self, language: str) -> None:
        if language == self.language or language not in TRANSLATIONS or self.running:
            self._dismiss_language_popup()
            return
        sources = self._current_sources()
        output = self.output_var.get()
        spectrogram = bool(self.spectrogram_var.get())
        json_report = bool(self.json_var.get())
        browser = bool(self.browser_cookies_var.get())
        log_visible = self.log_visible
        log_lines = list(self.log_lines)
        self._dismiss_notification()
        self._close_analysis_screen()
        self._dismiss_language_popup()
        self.language = language
        self.language_button.configure(text=f"{language.upper()}  ▾")
        self.destination_var.set(self.tr("analytics"))
        self._main_outer.destroy()
        self._build_layout()
        self.output_var.set(output)
        self.spectrogram_var.set(spectrogram)
        self.json_var.set(json_report)
        self.browser_cookies_var.set(browser)
        self._set_source_values(sources)
        self.log_lines = []
        for line in log_lines:
            self._append_log(line)
        self.log_visible = log_visible
        if log_visible:
            self.log_text.grid()
            self.log_toggle_button.configure(text=self.tr("hide_log"))
        if self.last_payload:
            winner = self.last_payload.get("winner")
            if isinstance(winner, dict):
                self._render_winner_summary(winner, self.last_payload.get("failures", []))
        self._sync_button_states()

    def _build_layout(self) -> None:
        space = SPACING
        surface = COLORS["surface"]
        outer = self.tk.Frame(self.content_host, background=surface)
        outer.grid(row=0, column=0, sticky="nsew")
        self._main_outer = outer
        outer.columnconfigure(0, minsize=SIZES["sidebar"])
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        sidebar = self.tk.Frame(outer, background=COLORS["sidebar"], width=SIZES["sidebar"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(6, weight=1)

        def nav_item(row: int, kind: str, command: Any, *, active: bool = False) -> Any:
            size = space[8]
            canvas = self.tk.Canvas(
                sidebar,
                width=size,
                height=size,
                background=COLORS["sidebar"],
                highlightthickness=0,
                borderwidth=0,
                cursor="hand2",
            )

            def draw(hovered: bool = False) -> None:
                canvas.delete("all")
                fill = COLORS["selected"] if active or hovered else COLORS["sidebar"]
                _rounded_rectangle(
                    canvas,
                    space[1],
                    space[1],
                    size - space[1],
                    size - space[1],
                    radius=RADII["md"],
                    fill=fill,
                    outline=fill,
                )
                if active:
                    canvas.create_line(
                        space[1],
                        space[3],
                        space[1],
                        size - space[3],
                        fill=COLORS["surface"],
                        width=2,
                        capstyle="round",
                    )
                color = COLORS["surface"] if active or hovered else COLORS["sidebar_muted"]
                icon = SIZES["icon"]
                left = (size - icon) / 2
                top = (size - icon) / 2
                right = left + icon
                bottom = top + icon
                if kind == "overview":
                    cell = SPACING[1]
                    for x in (left + SPACING[1], right - SPACING[2]):
                        for y in (top + SPACING[1], bottom - SPACING[2]):
                            canvas.create_rectangle(
                                x, y, x + cell, y + cell, outline=color, width=1
                            )
                elif kind == "folder":
                    canvas.create_line(
                        left,
                        top + SPACING[2],
                        left + SPACING[2],
                        top + SPACING[2],
                        left + SPACING[3],
                        top + SPACING[1],
                        right,
                        top + SPACING[1],
                        right,
                        bottom - SPACING[1],
                        left,
                        bottom - SPACING[1],
                        left,
                        top + SPACING[2],
                        fill=color,
                        width=1,
                        joinstyle="round",
                    )
                elif kind == "chart":
                    for index, height in enumerate((SPACING[2], SPACING[3], SPACING[4])):
                        x = left + SPACING[1] + index * SPACING[2]
                        canvas.create_line(
                            x,
                            bottom - SPACING[1],
                            x,
                            bottom - height,
                            fill=color,
                            width=2,
                            capstyle="round",
                        )
                elif kind == "cube":
                    canvas.create_polygon(
                        (
                            size / 2,
                            top,
                            right,
                            top + SPACING[2],
                            size / 2,
                            bottom,
                            left,
                            top + SPACING[2],
                        ),
                        outline=color,
                        fill="",
                        width=1,
                    )
                    canvas.create_line(
                        left,
                        top + SPACING[2],
                        size / 2,
                        top + SPACING[4],
                        right,
                        top + SPACING[2],
                        fill=color,
                        width=1,
                    )
                    canvas.create_line(
                        size / 2, top + SPACING[4], size / 2, bottom, fill=color, width=1
                    )
                else:
                    canvas.create_oval(
                        size / 2 - SPACING[1],
                        top + SPACING[1],
                        size / 2 + SPACING[1],
                        top + SPACING[3],
                        outline=color,
                        width=1,
                    )
                    canvas.create_arc(
                        left + SPACING[1],
                        top + SPACING[3],
                        right - SPACING[1],
                        bottom,
                        start=20,
                        extent=140,
                        style="arc",
                        outline=color,
                        width=1,
                    )

            canvas.grid(row=row, column=0, pady=(space[2], 0))
            canvas.bind("<Enter>", lambda _event: draw(True))
            canvas.bind("<Leave>", lambda _event: draw(False))
            canvas.bind("<Button-1>", lambda _event: command())
            draw()
            return canvas

        nav_item(0, "overview", lambda: self.source_text.focus_set(), active=True)
        nav_item(1, "folder", self._choose_output_folder)
        github_button = self._build_github_button(sidebar)
        github_button.grid(row=7, column=0, padx=space[4], pady=space[4])

        main = self.tk.Frame(outer, background=surface)
        main.grid(row=0, column=1, sticky="nsew", padx=space[6], pady=(space[2], space[5]))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1, minsize=SIZES["table_min_height"])
        self.output_var = self.tk.StringVar(value=default_dest_folder())

        section_head = self.tk.Frame(main, background=surface)
        section_head.grid(row=0, column=0, sticky="ew", pady=(0, space[3]))
        section_head.columnconfigure(0, weight=5)
        section_head.columnconfigure(1, weight=2)
        self.tk.Label(
            section_head,
            text=self.tr("evidence_title"),
            background=surface,
            foreground=TEXT,
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.tk.Label(
            section_head,
            text=self.tr("configuration_title"),
            background=surface,
            foreground=TEXT,
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).grid(row=0, column=1, sticky="w", padx=(space[3], 0))
        self.output_entry = self.ttk.Entry(
            section_head,
            textvariable=self.output_var,
            style="App.TEntry",
            state="readonly",
            width=22,
            cursor="xterm",
        )
        self.output_entry.grid(row=0, column=2, sticky="e", padx=(space[3], space[2]))
        self.output_browse_button = RoundedButton(
            self.tk,
            section_head,
            text=self.tr("choose_folder"),
            style="SecondaryStrong.TButton",
            command=self._choose_output_folder,
        )
        self.output_browse_button.grid(row=0, column=3, sticky="e")

        top_cards = self.tk.Frame(main, background=surface, height=SIZES["portfolio_height"])
        top_cards.grid(row=1, column=0, sticky="ew")
        top_cards.grid_propagate(False)
        for column, weight in enumerate((5, 2, 2, 2)):
            top_cards.columnconfigure(column, weight=weight, uniform="reference-top")
        top_cards.rowconfigure(0, weight=1)

        portfolio = self.tk.Frame(top_cards, background=COLORS["portfolio"])
        portfolio.grid(row=0, column=0, sticky="nsew", padx=(0, space[3]))
        _apply_rounded_corners(
            self.tk,
            portfolio,
            radius=RADII["md"],
            fill=COLORS["portfolio"],
            outside=surface,
            outline=COLORS["portfolio"],
        )
        portfolio.columnconfigure(0, weight=1)
        portfolio.rowconfigure(1, weight=1)
        card_header = self.tk.Frame(portfolio, background=COLORS["portfolio"])
        card_header.grid(row=0, column=0, sticky="ew", padx=space[4], pady=(space[3], space[1]))
        card_header.columnconfigure(0, weight=1)
        self.source_count_var = self.tk.StringVar(value=f"0 / {MAX_URLS}")
        self.tk.Label(
            card_header,
            textvariable=self.source_count_var,
            background=COLORS["portfolio"],
            foreground=TEXT,
            anchor="w",
            font=(self.heading_family, FONTS["metric"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.start_button = RoundedButton(
            self.tk,
            card_header,
            text=self.tr("start"),
            style="Accent.TButton",
            command=self._start_comparison,
        )
        self.start_button.grid(row=0, column=1, rowspan=2, sticky="e")
        self.tk.Label(
            card_header,
            text=self.tr("kpi_sources"),
            background=COLORS["portfolio"],
            foreground=MUTED,
            anchor="w",
            font=(self.font_family, FONTS["label"]["size"]),
        ).grid(row=1, column=0, sticky="w")

        input_frame = self.tk.Frame(portfolio, background=COLORS["portfolio"])
        input_frame.grid(row=1, column=0, sticky="nsew", padx=space[4])
        self.source_text = self.tk.Text(
            input_frame,
            height=SIZES["source_rows"],
            wrap="word",
            undo=True,
            background=COLORS["portfolio"],
            foreground=TEXT,
            insertbackground=TEXT,
            selectbackground=COLORS["selection"],
            selectforeground=TEXT,
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
            padx=0,
            pady=space[1],
            font=(self.font_family, FONTS["body"]["size"]),
        )
        self.source_text.pack(fill="both", expand=True)
        self.source_placeholder = self.tk.Label(
            input_frame,
            text=self.tr("source_placeholder"),
            justify="left",
            anchor="nw",
            background=COLORS["portfolio"],
            foreground=COLORS["text_muted"],
            font=(self.font_family, FONTS["body"]["size"]),
            cursor="xterm",
        )
        self.source_placeholder.place(x=0, y=space[1])
        self.source_placeholder.bind("<Button-1>", self._focus_source_input)
        self.source_text.bind("<<Modified>>", self._on_source_modified)
        self.source_text.bind("<Control-KeyPress>", self._on_source_shortcut)
        self.source_text.bind("<Shift-Insert>", self._paste_sources)
        self.source_text.bind("<FocusIn>", lambda _event: self._sync_placeholder())
        self.source_text.bind("<FocusOut>", self._normalize_source_input)

        card_footer = self.tk.Frame(portfolio, background=COLORS["portfolio"])
        card_footer.grid(row=2, column=0, sticky="ew", padx=space[4], pady=(space[1], space[3]))
        card_footer.columnconfigure(1, weight=1)
        self.loading_spinner = LoadingSpinner(self.tk, card_footer)
        self.loading_spinner.grid(row=0, column=0, sticky="w", padx=(0, space[2]))
        self.status_var = self.tk.StringVar(value=self.tr("status_need_link"))
        self.status_label = self.ttk.Label(
            card_footer, textvariable=self.status_var, style="Status.TLabel"
        )
        self.status_label.grid(row=0, column=1, sticky="w")
        self.source_error_var = self.tk.StringVar(value=self.tr("source_only_links"))
        self.source_hint = self.ttk.Label(
            card_footer,
            textvariable=self.source_error_var,
            style="PortfolioMuted.TLabel",
        )
        self.source_hint.grid(row=0, column=2, sticky="e", padx=(space[2], 0))

        self.spectrogram_var = self.tk.BooleanVar(value=True)
        self.json_var = self.tk.BooleanVar(value=True)
        self.browser_cookies_var = self.tk.BooleanVar(value=True)
        self.spectrogram_kpi_var = self.tk.StringVar(value=self.tr("enabled"))
        self.report_kpi_var = self.tk.StringVar(value=self.tr("enabled"))
        self.browser_kpi_var = self.tk.StringVar(value=self.tr("enabled"))

        def option_card(
            column: int,
            title: str,
            value_var: Any,
            variable: Any,
            background: str,
            symbol: str,
            attribute: str,
        ) -> None:
            card = self.tk.Frame(top_cards, background=background)
            card.grid(row=0, column=column, sticky="nsew", padx=(0, space[3] if column < 3 else 0))
            _apply_rounded_corners(
                self.tk,
                card,
                radius=RADII["md"],
                fill=background,
                outside=surface,
                outline=background,
            )
            card.columnconfigure(0, weight=1)
            card.rowconfigure(2, weight=1)
            self.tk.Label(
                card,
                text=title,
                background=background,
                foreground=TEXT,
                anchor="w",
                font=(self.font_family, FONTS["label"]["size"], "bold"),
            ).grid(row=0, column=0, sticky="ew", padx=space[3], pady=(space[3], space[1]))
            self.tk.Label(
                card,
                textvariable=value_var,
                background=background,
                foreground=TEXT,
                anchor="w",
                font=(self.heading_family, FONTS["body"]["size"], "bold"),
            ).grid(row=1, column=0, sticky="ew", padx=space[3])
            icon = self.tk.Canvas(
                card,
                width=SIZES["compact_button"],
                height=SIZES["compact_button"],
                background=background,
                highlightthickness=0,
                borderwidth=0,
            )
            _rounded_rectangle(
                icon,
                0,
                0,
                SIZES["compact_button"],
                SIZES["compact_button"],
                radius=RADII["sm"],
                fill=surface,
                outline=surface,
            )
            icon.create_text(
                SIZES["compact_button"] / 2,
                SIZES["compact_button"] / 2,
                text=symbol,
                fill=TEXT,
                font=(self.heading_family, FONTS["body"]["size"], "bold"),
            )
            icon.grid(row=3, column=0, sticky="sw", padx=space[3], pady=(space[2], space[3]))
            check = StyledCheck(
                self.tk,
                card,
                text="",
                variable=variable,
                font=(self.font_family, FONTS["label"]["size"]),
                background=background,
            )
            check.grid(row=3, column=1, sticky="se", padx=space[3], pady=(space[2], space[3]))
            setattr(self, attribute, check)

        option_card(
            1,
            self.tr("kpi_spectrogram"),
            self.spectrogram_kpi_var,
            self.spectrogram_var,
            COLORS["asset_lilac"],
            "≋",
            "spectrogram_check",
        )
        option_card(
            2,
            self.tr("kpi_report"),
            self.report_kpi_var,
            self.json_var,
            COLORS["asset_mint"],
            "{}",
            "json_check",
        )
        option_card(
            3,
            "YouTube",
            self.browser_kpi_var,
            self.browser_cookies_var,
            COLORS["asset_sand"],
            "▶",
            "browser_check",
        )

        def sync_option_cards(*_args: Any) -> None:
            self.spectrogram_kpi_var.set(
                self.tr("enabled") if self.spectrogram_var.get() else self.tr("disabled")
            )
            self.report_kpi_var.set(
                self.tr("enabled") if self.json_var.get() else self.tr("disabled")
            )
            self.browser_kpi_var.set(
                self.tr("enabled") if self.browser_cookies_var.get() else self.tr("disabled")
            )

        self.spectrogram_var.trace_add("write", sync_option_cards)
        self.json_var.trace_add("write", sync_option_cards)
        self.browser_cookies_var.trace_add("write", sync_option_cards)

        lower = self.tk.Frame(main, background=surface)
        lower.grid(row=2, column=0, sticky="nsew", pady=(space[5], 0))
        lower.columnconfigure(0, weight=7, uniform="reference-lower")
        lower.columnconfigure(
            1, weight=4, minsize=SIZES["narrow_wrap"] + space[6], uniform="reference-lower"
        )
        lower.rowconfigure(0, weight=1)

        table = self.tk.Frame(lower, background=surface)
        table.grid(row=0, column=0, sticky="nsew", padx=(0, space[5]))
        table.columnconfigure(0, weight=1)
        table.rowconfigure(2, weight=1)
        table_title = self.tk.Frame(table, background=surface)
        table_title.grid(row=0, column=0, sticky="ew", pady=(0, space[3]))
        table_title.columnconfigure(0, weight=1)
        self.market_title_var = self.tk.StringVar(value=self.tr("sources_table_title"))
        self.tk.Label(
            table_title,
            textvariable=self.market_title_var,
            background=surface,
            foreground=TEXT,
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.log_toggle_button = RoundedButton(
            self.tk,
            table_title,
            text=self.tr("show_log"),
            style="Secondary.TButton",
            command=self._toggle_log,
        )
        self.log_toggle_button.grid(row=0, column=1, sticky="e")
        table_header = self.tk.Frame(table, background=surface, height=SIZES["table_header"])
        table_header.grid(row=1, column=0, sticky="ew")
        table_header.grid_propagate(False)
        table_weights = (5, 2, 2, 1)
        for column, heading in enumerate(
            (self.tr("candidate"), self.tr("table_format"), self.tr("quality"), self.tr("action"))
        ):
            table_header.columnconfigure(column, weight=table_weights[column])
            self.tk.Label(
                table_header,
                text=heading,
                background=surface,
                foreground=MUTED,
                anchor="w" if column == 0 else "e",
                font=(self.font_family, FONTS["label"]["size"]),
            ).grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else space[2], 0))
        self.source_rows_host = self.tk.Frame(table, background=surface)
        self.source_rows_host.grid(row=2, column=0, sticky="nsew")
        self.source_rows_host.columnconfigure(0, weight=1)

        result_shell = self.tk.Frame(lower, background=COLORS["result"])
        result_shell.grid(row=0, column=1, sticky="nsew")
        _apply_rounded_corners(
            self.tk,
            result_shell,
            radius=RADII["md"],
            fill=COLORS["result"],
            outside=surface,
            outline=COLORS["result"],
        )
        result_shell.columnconfigure(1, weight=1)
        result_shell.rowconfigure(0, weight=1)
        self.result_accent_strip = self.tk.Frame(
            result_shell, background=COLORS["result"], width=space[1]
        )
        self.result_accent_strip.grid(row=0, column=0, sticky="ns", pady=space[3])
        result_column = self.tk.Frame(result_shell, background=COLORS["result"])
        result_column.grid(row=0, column=1, sticky="nsew", padx=space[5], pady=space[5])
        result_column.columnconfigure(0, weight=1)
        result_column.rowconfigure(3, weight=1)
        self.result_title_var = self.tk.StringVar(value=self.tr("ranking_title"))
        self.result_title_label = self.ttk.Label(
            result_column,
            textvariable=self.result_title_var,
            style="ResultTitle.TLabel",
            justify="left",
            wraplength=SIZES["narrow_wrap"],
        )
        self.result_title_label.grid(row=0, column=0, sticky="w")
        self.result_text_var = self.tk.StringVar(value=self.tr("ranking_helper"))
        self.ttk.Label(
            result_column,
            textvariable=self.result_text_var,
            style="Result.TLabel",
            justify="left",
            wraplength=SIZES["narrow_wrap"],
        ).grid(row=1, column=0, sticky="ew", pady=(space[2], space[1]))
        self.result_path_var = self.tk.StringVar(value="")
        self.ttk.Label(
            result_column,
            textvariable=self.result_path_var,
            style="ResultPath.TLabel",
            justify="left",
            wraplength=SIZES["narrow_wrap"],
        ).grid(row=2, column=0, sticky="w")
        self.ranking_canvas = self.tk.Canvas(
            result_column,
            background=COLORS["result"],
            highlightthickness=0,
            borderwidth=0,
        )
        self.ranking_canvas.grid(row=3, column=0, sticky="nsew", pady=space[2])
        self.ranking_canvas.bind("<Configure>", lambda _event: self._draw_ranking_summary())
        self.result_actions = self.tk.Frame(result_column, background=COLORS["result"])
        self.result_actions.grid(row=4, column=0, sticky="ew")
        self.result_actions.columnconfigure(0, weight=1)
        self.result_actions.columnconfigure(1, weight=1)
        self.analysis_button = RoundedButton(
            self.tk,
            self.result_actions,
            text=self.tr("view_analysis"),
            style="ResultAction.TButton",
            command=self._show_analysis_screen,
        )
        self.analysis_button.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, space[2]))
        self.open_file_button = RoundedButton(
            self.tk,
            self.result_actions,
            text=self.tr("open_audio"),
            style="ResultText.TButton",
            command=self._open_winner,
        )
        self.open_file_button.canvas.configure(width=SIZES["button"])
        self.open_file_button.grid(row=1, column=0, sticky="ew", padx=(0, space[1]))
        self.open_folder_button = RoundedButton(
            self.tk,
            self.result_actions,
            text=self.tr("open_folder"),
            style="ResultText.TButton",
            command=self._open_output_folder,
        )
        self.open_folder_button.canvas.configure(width=SIZES["button"])
        self.open_folder_button.grid(row=1, column=1, sticky="ew", padx=(space[1], 0))
        self.open_json_button = RoundedButton(
            self.tk,
            self.result_actions,
            text=self.tr("open_json"),
            style="ResultText.TButton",
            command=self._open_json_report,
        )
        self.open_json_button.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(space[1], 0))
        self.result_actions.grid_remove()

        self.log_text = self.tk.Text(
            main,
            height=SIZES["log_rows"],
            wrap="word",
            background=COLORS["surface_muted"],
            foreground=COLORS["text_secondary"],
            selectbackground=COLORS["selection"],
            highlightbackground=BORDER,
            highlightthickness=1,
            borderwidth=0,
            padx=space[3],
            pady=space[2],
            font=(self.mono_family, FONTS["technical"]["size"]),
            state="disabled",
        )
        self.log_text.grid(row=3, column=0, sticky="ew", pady=(space[3], 0))
        self.log_text.grid_remove()

        self._controls = [
            self.source_text,
            self.output_entry,
            self.output_browse_button,
            self.spectrogram_check,
            self.json_check,
            self.browser_check,
        ]
        self._render_source_table([])
        self._draw_ranking_summary()
        self._sync_button_states()

    def _render_source_table(self, sources: list[str]) -> None:
        if not hasattr(self, "source_rows_host"):
            return
        for child in self.source_rows_host.winfo_children():
            child.destroy()
        if hasattr(self, "market_title_var"):
            self.market_title_var.set(
                f"{self.tr('sources_table_title')}  {len(sources)}/{MAX_URLS}"
            )

        if not sources:
            empty = self.tk.Frame(
                self.source_rows_host,
                background=COLORS["surface"],
                height=SIZES["table_row"],
            )
            empty.grid(row=0, column=0, sticky="ew")
            empty.grid_propagate(False)
            self.tk.Label(
                empty,
                text=self.tr("source_only_links"),
                background=COLORS["surface"],
                foreground=MUTED,
                anchor="w",
                font=(self.font_family, FONTS["body"]["size"]),
            ).pack(fill="both", expand=True, anchor="w")
            return

        weights = (5, 2, 2, 1)
        for row_index, source in enumerate(sources[:MAX_URLS]):
            host = re.sub(r"^www\.", "", urlparse(source).netloc.casefold())
            platform = (
                "YouTube"
                if "youtu" in host
                else "SoundCloud"
                if "soundcloud" in host
                else host.split(":", 1)[0] or "Web"
            )
            symbol = platform[:1].upper()
            row = self.tk.Frame(
                self.source_rows_host,
                background=COLORS["surface"],
                height=SIZES["table_row"],
            )
            row.grid(row=row_index, column=0, sticky="ew")
            row.rowconfigure(0, minsize=SIZES["table_row"])
            for column, weight in enumerate(weights):
                row.columnconfigure(column, weight=weight)

            source_cell = self.tk.Frame(row, background=COLORS["surface"])
            source_cell.grid(row=0, column=0, sticky="ew")
            source_cell.columnconfigure(1, weight=1)
            icon = self.tk.Canvas(
                source_cell,
                width=SIZES["compact_button"],
                height=SIZES["compact_button"],
                background=COLORS["surface"],
                highlightthickness=0,
                borderwidth=0,
            )
            _rounded_rectangle(
                icon,
                0,
                0,
                SIZES["compact_button"],
                SIZES["compact_button"],
                radius=RADII["md"],
                fill=COLORS["sidebar"],
                outline=COLORS["sidebar"],
            )
            icon.create_text(
                SIZES["compact_button"] / 2,
                SIZES["compact_button"] / 2,
                text=symbol,
                fill=COLORS["surface"],
                font=(self.heading_family, FONTS["body"]["size"], "bold"),
            )
            icon.grid(row=0, column=0, padx=(0, SPACING[2]))
            self.tk.Label(
                source_cell,
                text=shorten_path(source, 44),
                background=COLORS["surface"],
                foreground=TEXT,
                anchor="w",
                font=(self.font_family, FONTS["body"]["size"]),
            ).grid(row=0, column=1, sticky="ew")
            values = (platform, self.tr("status_ready"), "☆")
            for column, value in enumerate(values, 1):
                self.tk.Label(
                    row,
                    text=value,
                    background=COLORS["surface"],
                    foreground=GREEN if column == 2 else MUTED,
                    anchor="e",
                    font=(self.font_family, FONTS["label"]["size"]),
                ).grid(row=0, column=column, sticky="ew", padx=(SPACING[2], 0))

    def _draw_ranking_summary(self) -> None:
        if not hasattr(self, "ranking_canvas"):
            return
        candidates = self.last_payload.get("candidates", []) if self.last_payload else []
        self._draw_ranking_canvas(self.ranking_canvas, candidates)

    def _draw_ranking_canvas(
        self,
        canvas: Any,
        candidates: list[dict[str, Any]],
    ) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), SIZES["narrow_wrap"])
        height = max(canvas.winfo_height(), SPACING[9])
        on_result = str(canvas.cget("background")).upper() == COLORS["result"].upper()
        primary_text = COLORS["result_text"] if on_result else TEXT
        secondary_text = COLORS["result_muted"] if on_result else MUTED
        track_color = COLORS["sidebar_muted"] if on_result else BORDER
        winner_color = COLORS["action"] if on_result else ACCENT
        comparison_color = COLORS["asset_lilac"] if on_result else COLORS["accent_secondary"]
        if not candidates:
            canvas.create_text(
                SPACING[1],
                height / 2,
                text=self.tr("ranking_empty"),
                fill=secondary_text,
                font=(self.font_family, FONTS["label"]["size"]),
                anchor="w",
            )
            return
        rows = sorted(candidates, key=lambda item: int(item.get("rank", 999)))[:5]
        start_y = SPACING[2]
        for index, candidate in enumerate(rows):
            y = start_y + index * SIZES["compact_button"]
            name = str(candidate.get("file_name") or self.tr("untitled"))
            if len(name) > 18:
                name = name[:17] + "…"
            score = max(0.0, min(100.0, float(candidate.get("score", 0.0))))
            canvas.create_text(
                0,
                y,
                text=name,
                fill=primary_text,
                font=(self.font_family, FONTS["label"]["size"]),
                anchor="w",
            )
            canvas.create_text(
                width,
                y,
                text=f"{score:.1f}",
                fill=secondary_text,
                font=(self.font_family, FONTS["label"]["size"]),
                anchor="e",
            )
            track_left = width / 3
            track_right = width - SPACING[8]
            bar_y = y + SPACING[2]
            canvas.create_line(
                track_left,
                bar_y,
                track_right,
                bar_y,
                fill=track_color,
                width=SIZES["progress"],
                capstyle="round",
            )
            canvas.create_line(
                track_left,
                bar_y,
                track_left + (track_right - track_left) * score / 100.0,
                bar_y,
                fill=winner_color if index == 0 else comparison_color,
                width=SIZES["progress"],
                capstyle="round",
            )

    def _work_area(self) -> tuple[int, int, int, int]:
        if os.name == "nt":
            try:
                import ctypes

                class Rect(ctypes.Structure):
                    _fields_ = [
                        ("left", ctypes.c_long),
                        ("top", ctypes.c_long),
                        ("right", ctypes.c_long),
                        ("bottom", ctypes.c_long),
                    ]

                rect = Rect()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    return rect.left, rect.top, rect.right, rect.bottom
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def _center_window(self) -> None:
        self.root.update_idletasks()
        left, top, right, bottom = self._work_area()
        width = min(SIZES["window_width"], right - left)
        height = min(SIZES["window_height"], bottom - top)
        x = max(left, left + (right - left - width) // 2)
        y = max(top, top + (bottom - top - height) // 2)
        geometry = f"{width}x{height}+{x}+{y}"
        self.root.geometry(geometry)
        self._normal_geometry = geometry

    def _on_source_modified(self, _event: Any = None) -> None:
        if self.source_text.edit_modified() and not self._normalizing_sources:
            self.source_text.edit_modified(False)
            self._sync_sources()

    def _focus_source_input(self, _event: Any = None) -> str:
        self.source_text.focus_set()
        self.source_placeholder.place_forget()
        return "break"

    def _on_source_shortcut(self, event: Any) -> str | None:
        # On a Russian keyboard layout Tk reports the physical V key as
        # Cyrillic "м", so binding only <Control-v> is not sufficient.
        if getattr(event, "keycode", None) == 86 or str(event.keysym).lower() == "v":
            return self._paste_sources(event)
        return None

    def _paste_sources(self, _event: Any = None) -> str:
        if str(self.source_text.cget("state")) == "disabled":
            return "break"
        try:
            clipboard = self.root.clipboard_get()
        except self.tk.TclError:
            self.status_var.set(self.tr("clipboard_empty"))
            return "break"
        pasted_sources = extract_sources(clipboard)
        if not pasted_sources:
            self.status_var.set(self.tr("clipboard_no_links"))
            return "break"

        existing = self._current_sources()
        selected_sources: set[str] = set()
        with suppress(self.tk.TclError):
            selected_sources = set(extract_sources(self.source_text.get("sel.first", "sel.last")))
        combined = [source for source in existing if source not in selected_sources]
        for source in pasted_sources:
            if source not in combined:
                combined.append(source)
        self._set_source_values(combined)
        self.source_text.mark_set("insert", "end-1c")
        return "break"

    def _set_source_values(self, sources: list[str]) -> None:
        self._normalizing_sources = True
        try:
            self.source_text.configure(state="normal")
            self.source_text.delete("1.0", "end")
            self.source_text.insert("1.0", "\n".join(sources))
            self.source_text.edit_modified(False)
        finally:
            self._normalizing_sources = False
        self._sync_sources()

    def _normalize_source_input(self, _event: Any = None) -> None:
        sources = self._current_sources()
        if sources:
            self._set_source_values(sources)
        self._sync_placeholder()

    def _current_sources(self) -> list[str]:
        return extract_sources(self.source_text.get("1.0", "end-1c"))

    def _sync_placeholder(self) -> None:
        if (
            self.source_text.get("1.0", "end-1c").strip()
            or self.root.focus_get() == self.source_text
        ):
            self.source_placeholder.place_forget()
        else:
            self.source_placeholder.place(x=0, y=SPACING[1])

    def _sync_sources(self) -> None:
        self._sync_placeholder()
        sources = self._current_sources()
        self.source_count_var.set(f"{len(sources)} / {MAX_URLS}")
        self._render_source_table(sources)
        if self.running:
            self._sync_button_states()
            return
        if len(sources) > MAX_URLS:
            self.source_error_var.set(
                self.tr("too_many_links", count=len(sources), maximum=MAX_URLS)
            )
            self.source_hint.configure(style="PortfolioError.TLabel")
            self.status_label.configure(style="StatusError.TLabel")
            self.status_var.set(self.tr("status_too_many"))
        elif sources:
            self.source_error_var.set(self.tr("sources_recognized"))
            self.source_hint.configure(style="PortfolioMuted.TLabel")
            self.status_label.configure(style="StatusReady.TLabel")
            self.status_var.set(self.tr("status_ready"))
        else:
            self.source_error_var.set(self.tr("source_only_links"))
            self.source_hint.configure(style="PortfolioMuted.TLabel")
            self.status_label.configure(style="Status.TLabel")
            self.status_var.set(self.tr("status_need_link"))
        self._sync_button_states()

    def _sync_button_states(self) -> None:
        if self.running:
            self.start_button.configure(state="disabled")
            self.analysis_button.configure(state="disabled")
            self.open_file_button.configure(state="disabled")
            self.open_folder_button.configure(state="disabled")
            self.open_json_button.configure(state="disabled")
            self.result_actions.grid_remove()
            return
        sources = self._current_sources() if hasattr(self, "source_text") else []
        valid = 0 < len(sources) <= MAX_URLS
        self.start_button.configure(state="normal" if valid else "disabled")
        self.analysis_button.configure(state="normal" if self.last_payload else "disabled")
        self.open_file_button.configure(state="normal" if self.last_winner_file else "disabled")
        self.open_folder_button.configure(state="normal" if self.last_output_folder else "disabled")
        self.open_json_button.configure(state="normal" if self.last_report_path else "disabled")
        self._sync_result_actions()

    def _sync_result_actions(self) -> None:
        """Show only actions backed by a real result instead of disabled placeholders."""
        if not self.last_payload:
            self.result_actions.grid_remove()
            return

        self.result_actions.grid()
        self.analysis_button.grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(0, SPACING[2]),
        )
        if self.last_winner_file:
            self.open_file_button.grid(
                row=1,
                column=0,
                columnspan=1,
                sticky="ew",
                padx=(0, SPACING[1]),
            )
        else:
            self.open_file_button.grid_remove()
        if self.last_output_folder:
            self.open_folder_button.grid(
                row=1,
                column=1 if self.last_winner_file else 0,
                columnspan=1 if self.last_winner_file else 2,
                sticky="ew",
                padx=(SPACING[1], 0) if self.last_winner_file else 0,
            )
        else:
            self.open_folder_button.grid_remove()
        if self.last_report_path:
            self.open_json_button.grid(
                row=2,
                column=0,
                columnspan=2,
                sticky="ew",
                pady=(SPACING[1], 0),
            )
        else:
            self.open_json_button.grid_remove()

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in self._controls:
            with suppress(Exception):
                if widget is self.output_entry:
                    widget.configure(state="readonly" if enabled else "disabled")
                else:
                    widget.configure(state=state)
        self._sync_button_states()

    def _choose_output_folder(self) -> None:
        if self.running:
            return
        from tkinter import filedialog

        current = Path(self.output_var.get()).expanduser()
        initial_folder = current if current.is_dir() else Path.home()
        selected = filedialog.askdirectory(
            parent=self.root,
            title=self.tr("choose_folder_title"),
            initialdir=str(initial_folder),
            mustexist=True,
        )
        if selected:
            self.output_var.set(str(Path(selected).resolve()))

    def _set_inline_error(self, title: str, message: str) -> None:
        self.result_accent_strip.configure(background=COLORS["asset_sand"])
        self.result_title_var.set(title)
        self.result_title_label.configure(style="ResultError.TLabel")
        self.result_text_var.set(message)
        self.result_path_var.set("")
        self.status_label.configure(style="StatusError.TLabel")
        self.status_var.set(message)

    def _start_comparison(self) -> None:
        self._dismiss_notification()
        self._close_analysis_screen()
        self._dismiss_language_popup()
        sources = self._current_sources()
        if not sources:
            self._set_inline_error(self.tr("links_not_found"), self.tr("insert_full_link"))
            return
        if len(sources) > MAX_URLS:
            self._set_inline_error(
                self.tr("too_many_variants"),
                self.tr("leave_max_links", maximum=MAX_URLS),
            )
            return
        output_folder = self.output_var.get().strip().strip('"')
        if not output_folder:
            self._set_inline_error(self.tr("folder_missing"), self.tr("enter_folder"))
            return
        try:
            Path(output_folder).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._set_inline_error(self.tr("folder_create_failed"), str(exc))
            return

        self._cleanup_spectrogram_temp()
        self._cleanup_report_temp()
        save_spectrogram = bool(self.spectrogram_var.get())
        if save_spectrogram:
            self.spectrogram_temp_folder = tempfile.mkdtemp(prefix="TrackJudge-spectrograms-")
        config = GuiRunConfig(
            sources=tuple(sources),
            output_folder=str(Path(output_folder).expanduser().resolve()),
            save_spectrogram=save_spectrogram,
            save_json_report=bool(self.json_var.get()),
            use_browser_cookies=bool(self.browser_cookies_var.get()),
            spectrogram_folder=self.spectrogram_temp_folder,
        )
        temp_folder = tempfile.mkdtemp(prefix="trackjudge_gui_")
        report_path = str(Path(temp_folder) / "trackjudge-report.json")
        if config.save_json_report:
            self.report_temp_folder = temp_folder

        self.running = True
        self.last_output_folder = None
        self.last_winner_file = None
        self.last_report_path = None
        self.last_payload = None
        self.result_accent_strip.configure(background=COLORS["action"])
        self.result_title_label.configure(style="ResultTitle.TLabel")
        self.result_title_var.set(self.tr("running_title"))
        self.result_text_var.set(self.tr("running_text"))
        self.result_path_var.set("")
        self.status_label.configure(style="Status.TLabel")
        self.status_var.set(self.tr("running_status"))
        self._clear_log()
        self._append_log(self.tr("started_log"))
        self.start_button.configure(text=self.tr("comparing"))
        self._set_controls_enabled(False)
        self.loading_spinner.start()

        worker = threading.Thread(
            target=self._run_worker,
            args=(config, report_path, temp_folder),
            daemon=True,
            name="trackjudge-analysis",
        )
        worker.start()

    def _run_worker(
        self,
        config: GuiRunConfig,
        report_path: str,
        temp_folder: str,
    ) -> None:
        writer = QueueWriter(self.events)
        payload: dict[str, Any] | None = None
        error: str | None = None
        exit_code = 1
        try:
            args = build_gui_namespace(config, report_path)
            configure_console(no_color=True, file=writer, width=94)
            exit_code = run_analysis(args)
            writer.flush()
            if Path(report_path).is_file():
                with open(report_path, encoding="utf-8") as report_file:
                    payload = json.load(report_file)
        except Exception as exc:
            writer.flush()
            error = f"{type(exc).__name__}: {exc}"
        finally:
            if not config.save_json_report:
                shutil.rmtree(temp_folder, ignore_errors=True)
        self.events.put(
            (
                "finished",
                {
                    "exit_code": exit_code,
                    "payload": payload,
                    "error": error,
                    "output_folder": config.output_folder,
                    "report_path": report_path if config.save_json_report else None,
                },
            )
        )

    def _poll_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "log":
                    self._append_log(str(payload))
                elif event == "finished":
                    self._finish_comparison(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _finish_comparison(self, result: dict[str, Any]) -> None:
        self.running = False
        self.loading_spinner.stop()
        self.start_button.configure(text=self.tr("start"))
        self._set_controls_enabled(True)

        payload = result.get("payload")
        winner = payload.get("winner") if isinstance(payload, dict) else None
        failures = payload.get("failures", []) if isinstance(payload, dict) else []
        if result.get("exit_code") == 0 and isinstance(winner, dict):
            self.last_payload = payload
            self.last_output_folder = result["output_folder"]
            self.last_winner_file = winner.get("saved_file")
            report_path = result.get("report_path")
            self.last_report_path = (
                str(report_path) if report_path and Path(report_path).is_file() else None
            )
            self._render_winner_summary(winner, failures)
            self.status_label.configure(style="StatusReady.TLabel")
            self.status_var.set("")
        else:
            self._cleanup_spectrogram_temp()
            self._cleanup_report_temp()
            error = result.get("error")
            message = error or self.tr("no_links_processed")
            self._set_inline_error(self.tr("comparison_failed"), message)
            if not self.log_visible:
                self._toggle_log()
        self._sync_button_states()

    def _localized_quality(self, score: float) -> str:
        if score >= 70:
            return self.tr("quality_high")
        if score >= 45:
            return self.tr("quality_medium")
        return self.tr("quality_low")

    def _render_winner_summary(
        self,
        winner: dict[str, Any],
        failures: list[dict[str, Any]],
    ) -> None:
        score = float(winner.get("score", 0.0))
        cutoff = float(winner.get("effective_cutoff_hz", 0.0)) / 1000.0
        name = winner.get("file_name") or Path(self.last_winner_file or "").name
        summary = f"{score:.1f}/100  •  {self._localized_quality(score)}"
        if cutoff:
            summary += f"  •  {self.tr('spectrum_to', cutoff=cutoff)}"
        if failures:
            summary += f"  •  {self.tr('errors_count', count=len(failures))}"
        self.result_accent_strip.configure(background=COLORS["action"])
        self.result_title_label.configure(style="ResultTitle.TLabel")
        self.result_title_var.set(self.tr("winner"))
        self.result_text_var.set(f"{name}\n{summary}")
        self.result_path_var.set(shorten_path(self.last_winner_file))
        self._draw_ranking_summary()

    def _append_log(self, line: str) -> None:
        self.log_lines.append(line)
        if len(self.log_lines) > 600:
            self.log_lines = self.log_lines[-600:]
        if hasattr(self, "log_text"):
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_lines.clear()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _toggle_log(self) -> None:
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_text.grid()
            self.log_toggle_button.configure(text=self.tr("hide_log"))
        else:
            self.log_text.grid_remove()
            self.log_toggle_button.configure(text=self.tr("show_log"))

    def _show_success_notification(self, winner: dict[str, Any]) -> None:
        space = SPACING
        self._dismiss_notification()
        overlay = self.tk.Frame(self.content_host, background=COLORS["overlay"])
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        self.notification_overlay = overlay

        shadow = self.tk.Frame(
            overlay,
            background=COLORS["overlay_shadow"],
            width=SIZES["modal_width"],
            height=SIZES["modal_height"],
        )
        shadow.place(
            relx=0.5,
            rely=0.5,
            x=space[3],
            y=space[3],
            anchor="center",
        )
        _apply_rounded_corners(
            self.tk,
            shadow,
            radius=RADII["lg"],
            fill=shadow.cget("background"),
            outside=COLORS["overlay"],
            outline=shadow.cget("background"),
        )
        card = self.tk.Frame(
            overlay,
            background=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
            width=SIZES["modal_width"],
            height=SIZES["modal_height"],
        )
        card.place(relx=0.5, rely=0.5, anchor="center")
        _apply_rounded_corners(
            self.tk,
            card,
            radius=RADII["lg"],
            fill=CARD,
            outside=COLORS["overlay"],
        )
        card.grid_propagate(False)
        card.columnconfigure(0, weight=1)

        status_mark = self.tk.Canvas(
            card,
            width=space[8],
            height=space[8],
            background=CARD,
            highlightthickness=0,
            borderwidth=0,
        )
        inset = space[1]
        end = space[8] - inset
        status_mark.create_oval(inset, inset, end, end, outline=ACCENT, width=2)
        status_mark.create_line(
            space[4],
            space[5],
            space[5],
            space[6],
            space[7],
            space[4],
            fill=ACCENT,
            width=3,
            capstyle="round",
            joinstyle="round",
        )
        status_mark.grid(row=0, column=0, pady=(space[5], space[2]))
        self.tk.Label(
            card,
            text=self.tr("completed"),
            background=CARD,
            foreground=TEXT,
            font=(
                self.heading_family,
                FONTS["display"]["size"],
                FONTS["display"]["weight"],
            ),
        ).grid(row=1, column=0)

        name = winner.get("file_name") or Path(self.last_winner_file or "").name
        score = float(winner.get("score", 0.0))
        quality = self._localized_quality(score)
        self.tk.Label(
            card,
            text=name,
            background=CARD,
            foreground=TEXT,
            justify="center",
            wraplength=SIZES["modal_width"] - (space[7] * 2),
            font=(self.font_family, FONTS["body"]["size"]),
        ).grid(row=2, column=0, padx=space[7], pady=(space[2], space[1]))
        self.tk.Label(
            card,
            text=f"{score:.1f}/100  •  {quality}",
            background=CARD,
            foreground=ACCENT,
            font=(self.mono_family, FONTS["metric"]["size"], "bold"),
        ).grid(row=3, column=0)
        self.tk.Label(
            card,
            text=shorten_path(self.last_winner_file, 78),
            background=CARD,
            foreground=COLORS["text_muted"],
            font=(self.mono_family, FONTS["technical"]["size"]),
        ).grid(row=4, column=0, padx=space[7], pady=(space[1], space[4]))

        actions = self.ttk.Frame(card, style="CardAlt.TFrame")
        actions.grid(row=5, column=0)
        RoundedButton(
            self.tk,
            actions,
            text=self.tr("view_analysis"),
            style="Accent.TButton",
            command=self._show_analysis_screen,
        ).grid(row=0, column=0, padx=(0, space[2]))
        RoundedButton(
            self.tk,
            actions,
            text=self.tr("open_audio"),
            style="ModalText.TButton",
            command=self._open_winner,
        ).grid(row=0, column=1)
        RoundedButton(
            self.tk,
            card,
            text=self.tr("return_form"),
            style="ModalText.TButton",
            command=self._dismiss_notification,
        ).grid(row=6, column=0, pady=(space[2], space[5]))

    def _dismiss_notification(self) -> None:
        if self.notification_overlay is not None:
            with suppress(Exception):
                self.notification_overlay.destroy()
            self.notification_overlay = None

    def _show_analysis_screen(self) -> None:
        """Render every candidate spectrogram as a readable, scrollable gallery."""
        if not self.last_payload:
            return

        space = SPACING
        surface = COLORS["surface"]
        self._dismiss_notification()
        self._close_analysis_screen()
        self._analysis_images = []
        self.destination_var.set(self.tr("analysis_title"))

        candidates = sorted(
            self.last_payload.get("candidates", []),
            key=lambda item: int(item.get("rank", 999)),
        )
        failures = self.last_payload.get("failures", [])
        winner = self.last_payload.get("winner", {})
        available = sum(
            1
            for candidate in candidates
            if candidate.get("saved_spectrogram")
            and Path(str(candidate["saved_spectrogram"])).is_file()
        )

        screen = self.tk.Frame(self.content_host, background=surface)
        screen.place(x=0, y=0, relwidth=1, relheight=1)
        self.analysis_overlay = screen
        screen.columnconfigure(0, minsize=SIZES["sidebar"])
        screen.columnconfigure(1, weight=1)
        screen.rowconfigure(0, weight=1)

        sidebar = self.tk.Frame(screen, background=COLORS["sidebar"], width=SIZES["sidebar"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        sidebar.rowconfigure(1, weight=1)
        back = self.tk.Canvas(
            sidebar,
            width=space[8],
            height=space[8],
            background=COLORS["sidebar"],
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        back.grid(row=0, column=0, pady=space[2])
        center = space[5]
        back.create_line(
            center + space[2],
            center - space[3],
            center - space[1],
            center,
            center + space[2],
            center + space[3],
            fill=COLORS["surface"],
            width=2,
            capstyle="round",
            joinstyle="round",
        )
        back.bind("<Button-1>", lambda _event: self._close_analysis_screen())
        github_button = self._build_github_button(sidebar)
        github_button.grid(row=2, column=0, padx=space[4], pady=space[4], sticky="s")

        main = self.tk.Frame(screen, background=surface)
        main.grid(row=0, column=1, sticky="nsew", padx=space[6], pady=(space[2], space[5]))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1, minsize=SIZES["table_min_height"])

        header = self.tk.Frame(main, background=surface)
        header.grid(row=0, column=0, sticky="ew", pady=(0, space[3]))
        header.columnconfigure(0, weight=1)
        self.tk.Label(
            header,
            text=self.tr("analysis_title"),
            background=surface,
            foreground=TEXT,
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="w")
        if self.last_output_folder:
            RoundedButton(
                self.tk,
                header,
                text=self.tr("open_folder"),
                style="Secondary.TButton",
                command=self._open_output_folder,
            ).grid(row=0, column=1, sticky="e")

        summary = self.tk.Frame(
            main,
            background=surface,
            height=SIZES["analysis_summary_height"],
        )
        summary.grid(row=1, column=0, sticky="ew")
        summary.grid_propagate(False)
        summary.rowconfigure(0, weight=1)
        for column, weight in enumerate((5, 2, 2, 2)):
            summary.columnconfigure(column, weight=weight, uniform="analysis-summary")

        summary_values = (
            (
                self.tr("spectrogram_gallery_title"),
                self.tr("spectrogram_ready", ready=available, total=len(candidates)),
                COLORS["portfolio"],
            ),
            (
                self.tr("analysis_best_score"),
                f"{float(winner.get('score', 0.0)):.1f}",
                COLORS["asset_lilac"],
            ),
            (
                self.tr("analysis_best_format"),
                str(winner.get("codec", "—")).upper(),
                COLORS["asset_mint"],
            ),
            (self.tr("analysis_failures"), str(len(failures)), COLORS["asset_sand"]),
        )
        for column, (label, value, background) in enumerate(summary_values):
            card = self.tk.Frame(summary, background=background)
            card.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(0, space[3] if column < 3 else 0),
            )
            _apply_rounded_corners(
                self.tk,
                card,
                radius=RADII["md"],
                fill=background,
                outside=surface,
                outline=background,
            )
            self.tk.Label(
                card,
                text=label,
                background=background,
                foreground=TEXT,
                anchor="w",
                justify="left",
                wraplength=SIZES["narrow_wrap"] if column else SIZES["analysis_wrap"],
                font=(self.font_family, FONTS["label"]["size"], "bold"),
            ).pack(fill="x", padx=space[4], pady=(space[3], space[1]))
            self.tk.Label(
                card,
                text=value,
                background=background,
                foreground=TEXT,
                anchor="w",
                font=(
                    self.heading_family,
                    FONTS["body"]["size"] if column == 0 else FONTS["metric"]["size"],
                    "bold",
                ),
            ).pack(fill="x", padx=space[4])

        lower = self.tk.Frame(main, background=surface)
        lower.grid(row=2, column=0, sticky="nsew", pady=(space[5], 0))
        lower.columnconfigure(0, weight=7, uniform="analysis-content")
        lower.columnconfigure(
            1,
            weight=3,
            minsize=SIZES["narrow_wrap"] + space[6],
            uniform="analysis-content",
        )
        lower.rowconfigure(0, weight=1)

        gallery_panel = self.tk.Frame(lower, background=surface)
        gallery_panel.grid(row=0, column=0, sticky="nsew", padx=(0, space[5]))
        gallery_panel.columnconfigure(0, weight=1)
        gallery_panel.rowconfigure(1, weight=1)
        gallery_header = self.tk.Frame(gallery_panel, background=surface)
        gallery_header.grid(row=0, column=0, sticky="ew", pady=(0, space[3]))
        gallery_header.columnconfigure(0, weight=1)
        self.tk.Label(
            gallery_header,
            text=self.tr("spectrogram_gallery_title"),
            background=surface,
            foreground=TEXT,
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.tk.Label(
            gallery_header,
            text=self.tr("spectrogram_full_size_hint"),
            background=surface,
            foreground=MUTED,
            anchor="e",
            font=(self.font_family, FONTS["label"]["size"]),
        ).grid(row=0, column=1, sticky="e")
        self._build_spectrogram_gallery(gallery_panel, candidates)

        ranking_panel = self.tk.Frame(lower, background=COLORS["result"])
        ranking_panel.grid(row=0, column=1, sticky="nsew")
        _apply_rounded_corners(
            self.tk,
            ranking_panel,
            radius=RADII["md"],
            fill=COLORS["result"],
            outside=surface,
            outline=COLORS["result"],
        )
        ranking_panel.columnconfigure(0, weight=1)
        ranking_panel.rowconfigure(1, weight=1)
        self.tk.Label(
            ranking_panel,
            text=self.tr("ranking_title"),
            background=COLORS["result"],
            foreground=COLORS["result_text"],
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=space[5], pady=(space[5], space[2]))
        analysis_ranking = self.tk.Canvas(
            ranking_panel,
            background=COLORS["result"],
            highlightthickness=0,
            borderwidth=0,
        )
        analysis_ranking.grid(row=1, column=0, sticky="nsew", padx=space[5], pady=space[2])
        analysis_ranking.bind(
            "<Configure>",
            lambda _event, target=analysis_ranking: self._draw_ranking_canvas(target, candidates),
        )
        self._draw_ranking_canvas(analysis_ranking, candidates)
        RoundedButton(
            self.tk,
            ranking_panel,
            text=self.tr("back"),
            style="ResultAction.TButton",
            command=self._close_analysis_screen,
        ).grid(row=2, column=0, sticky="ew", padx=space[5], pady=(space[2], space[5]))

    def _build_spectrogram_gallery(
        self,
        parent: Any,
        candidates: list[dict[str, Any]],
    ) -> None:
        canvas = self.tk.Canvas(
            parent,
            background=COLORS["surface"],
            highlightthickness=0,
            borderwidth=0,
        )
        canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar = self.ttk.Scrollbar(
            parent,
            orient="vertical",
            command=canvas.yview,
            style="Analysis.Vertical.TScrollbar",
        )
        scrollbar.grid(row=1, column=1, sticky="ns", padx=(SPACING[2], 0))
        canvas.configure(yscrollcommand=scrollbar.set)

        content = self.tk.Frame(canvas, background=COLORS["surface"])
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        columns = 2 if self.root.winfo_width() >= 1440 else 1
        for column in range(columns):
            content.columnconfigure(column, weight=1, uniform="spectrogram-gallery")

        def update_scroll_region(_event: Any = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def resize_content(event: Any) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def scroll(event: Any) -> str:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", resize_content)
        canvas.bind_all("<MouseWheel>", scroll)

        if not candidates:
            self.tk.Label(
                content,
                text=self.tr("no_candidates"),
                background=COLORS["surface"],
                foreground=MUTED,
                font=(self.font_family, FONTS["body"]["size"]),
            ).grid(row=0, column=0, sticky="w", pady=SPACING[5])
            return

        for index, candidate in enumerate(candidates):
            row, column = divmod(index, columns)
            background = COLORS["surface_muted"]
            card = self.tk.Frame(
                content,
                background=background,
                highlightbackground=COLORS["border"],
                highlightthickness=1,
            )
            card.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=(0, SPACING[3] if column < columns - 1 else 0),
                pady=(0, SPACING[3]),
            )
            _apply_rounded_corners(
                self.tk,
                card,
                radius=RADII["md"],
                fill=background,
                outside=COLORS["surface"],
                outline=COLORS["border"],
            )
            card.columnconfigure(0, weight=1)
            title_row = self.tk.Frame(card, background=background)
            title_row.grid(
                row=0,
                column=0,
                sticky="ew",
                padx=SPACING[4],
                pady=(SPACING[3], SPACING[2]),
            )
            title_row.columnconfigure(0, weight=1)
            name = shorten_path(str(candidate.get("file_name") or self.tr("untitled")), 42)
            self.tk.Label(
                title_row,
                text=f"#{candidate.get('rank', '—')}  {name}",
                background=background,
                foreground=TEXT,
                anchor="w",
                font=(self.heading_family, FONTS["body"]["size"], "bold"),
            ).grid(row=0, column=0, sticky="w")
            self.tk.Label(
                title_row,
                text=f"{float(candidate.get('score', 0.0)):.1f}",
                background=background,
                foreground=GREEN if int(candidate.get("rank", 0)) == 1 else TEXT,
                anchor="e",
                font=(self.heading_family, FONTS["body"]["size"], "bold"),
            ).grid(row=0, column=1, sticky="e", padx=(SPACING[3], 0))

            spectrogram_path = candidate.get("saved_spectrogram")
            preview = self._load_spectrogram_preview(spectrogram_path)
            if preview is not None:
                self._analysis_images.append(preview)
                image_label = self.tk.Label(
                    card,
                    image=preview,
                    background=background,
                    borderwidth=0,
                    cursor="hand2",
                )
                image_label.grid(row=1, column=0, padx=SPACING[4])
                image_label.bind(
                    "<Button-1>",
                    lambda _event, path=str(spectrogram_path): self._open_path(path),
                )
            else:
                missing = self.tk.Frame(
                    card,
                    background=COLORS["asset_sand"],
                    width=SIZES["spectrogram_width"],
                    height=SIZES["spectrogram_height"],
                )
                missing.grid(row=1, column=0, padx=SPACING[4])
                missing.grid_propagate(False)
                self.tk.Label(
                    missing,
                    text=self.tr("spectrogram_missing"),
                    background=COLORS["asset_sand"],
                    foreground=TEXT,
                    wraplength=SIZES["spectrogram_width"] - SPACING[7],
                    justify="center",
                    font=(self.font_family, FONTS["body"]["size"]),
                ).place(relx=0.5, rely=0.5, anchor="center")

            footer = self.tk.Frame(card, background=background)
            footer.grid(
                row=2,
                column=0,
                sticky="ew",
                padx=SPACING[4],
                pady=SPACING[3],
            )
            footer.columnconfigure(0, weight=1)
            codec = str(candidate.get("codec", "—")).upper()
            cutoff = float(candidate.get("effective_cutoff_hz", 0.0)) / 1000.0
            details = codec
            if cutoff:
                details += f"  •  {cutoff:.1f} {self.tr('khz')}"
            self.tk.Label(
                footer,
                text=details,
                background=background,
                foreground=MUTED,
                anchor="w",
                font=(self.font_family, FONTS["label"]["size"], "bold"),
            ).grid(row=0, column=0, sticky="w")
            if preview is not None:
                RoundedButton(
                    self.tk,
                    footer,
                    text=self.tr("open_spectrogram"),
                    style="Secondary.TButton",
                    command=lambda path=str(spectrogram_path): self._open_path(path),
                ).grid(row=0, column=1, sticky="e")

        self.root.after_idle(update_scroll_region)
        self.root.after_idle(lambda: canvas.yview_moveto(0))

    def _load_spectrogram_preview(self, path: Any) -> Any | None:
        if not path or not Path(str(path)).is_file():
            return None
        try:
            from PIL import Image, ImageTk

            with Image.open(str(path)) as source:
                image = source.convert("RGB")
                image.thumbnail(
                    (SIZES["spectrogram_width"], SIZES["spectrogram_height"]),
                    Image.Resampling.LANCZOS,
                )
                background = Image.new(
                    "RGB",
                    (SIZES["spectrogram_width"], SIZES["spectrogram_height"]),
                    COLORS["surface_muted"],
                )
                offset = (
                    (background.width - image.width) // 2,
                    (background.height - image.height) // 2,
                )
                background.paste(image, offset)
            return ImageTk.PhotoImage(background, master=self.root)
        except Exception:
            return None

    def _show_analysis_screen_legacy(self) -> None:
        if not self.last_payload:
            return
        space = SPACING
        surface = COLORS["surface"]
        self._dismiss_notification()
        self._close_analysis_screen()
        self._analysis_images = []
        self.destination_var.set(self.tr("analysis_title"))

        screen = self.tk.Frame(self.content_host, background=surface)
        screen.place(x=0, y=0, relwidth=1, relheight=1)
        self.analysis_overlay = screen
        screen.columnconfigure(0, minsize=SIZES["sidebar"])
        screen.columnconfigure(1, weight=1)
        screen.rowconfigure(0, weight=1)

        candidates = self.last_payload.get("candidates", [])
        failures = self.last_payload.get("failures", [])
        winner = self.last_payload.get("winner", {})

        sidebar = self.tk.Frame(screen, background=COLORS["sidebar"], width=SIZES["sidebar"])
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.columnconfigure(0, weight=1)
        back = self.tk.Canvas(
            sidebar,
            width=space[8],
            height=space[8],
            background=COLORS["sidebar"],
            highlightthickness=0,
            borderwidth=0,
            cursor="hand2",
        )
        back.grid(row=0, column=0, pady=space[2])
        center = space[5]
        back.create_line(
            center + space[2],
            center - space[3],
            center - space[1],
            center,
            center + space[2],
            center + space[3],
            fill=COLORS["surface"],
            width=2,
            capstyle="round",
            joinstyle="round",
        )
        back.bind("<Button-1>", lambda _event: self._close_analysis_screen())
        github_button = self._build_github_button(sidebar)
        github_button.grid(row=2, column=0, padx=space[4], pady=space[4], sticky="s")
        sidebar.rowconfigure(1, weight=1)

        main = self.tk.Frame(screen, background=surface)
        main.grid(row=0, column=1, sticky="nsew", padx=space[6], pady=(space[2], space[5]))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1, minsize=SIZES["table_min_height"])

        header = self.tk.Frame(main, background=surface)
        header.grid(row=0, column=0, sticky="ew", pady=(0, space[3]))
        header.columnconfigure(0, weight=1)
        self.tk.Label(
            header,
            text=self.tr("analysis_title"),
            background=surface,
            foreground=TEXT,
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="w")
        RoundedButton(
            self.tk,
            header,
            text=self.tr("open_folder"),
            style="Secondary.TButton",
            command=self._open_output_folder,
        ).grid(row=0, column=1, sticky="e")

        top_cards = self.tk.Frame(main, background=surface, height=SIZES["analysis_height"])
        top_cards.grid(row=1, column=0, sticky="ew")
        top_cards.grid_propagate(False)
        for column, weight in enumerate((5, 2, 2, 2)):
            top_cards.columnconfigure(column, weight=weight, uniform="reference-analysis-top")
        top_cards.rowconfigure(0, weight=1)

        plot_panel = self.tk.Frame(top_cards, background=COLORS["portfolio"])
        plot_panel.grid(row=0, column=0, sticky="nsew", padx=(0, space[3]))
        _apply_rounded_corners(
            self.tk,
            plot_panel,
            radius=RADII["md"],
            fill=COLORS["portfolio"],
            outside=surface,
            outline=COLORS["portfolio"],
        )
        plot_panel.columnconfigure(0, weight=1)
        plot_panel.rowconfigure(1, weight=1)
        self.tk.Label(
            plot_panel,
            text=self.tr("analysis_subtitle"),
            background=COLORS["portfolio"],
            foreground=TEXT,
            anchor="w",
            font=(self.font_family, FONTS["label"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=space[4], pady=(space[3], space[2]))
        self._build_analysis_plot(plot_panel, candidates)

        def metric_card(column: int, label: str, value: str, background: str, symbol: str) -> None:
            card = self.tk.Frame(top_cards, background=background)
            card.grid(row=0, column=column, sticky="nsew", padx=(0, space[3] if column < 3 else 0))
            _apply_rounded_corners(
                self.tk,
                card,
                radius=RADII["md"],
                fill=background,
                outside=surface,
                outline=background,
            )
            card.columnconfigure(0, weight=1)
            card.rowconfigure(2, weight=1)
            self.tk.Label(
                card,
                text=label,
                background=background,
                foreground=TEXT,
                anchor="w",
                justify="left",
                wraplength=SIZES["narrow_wrap"],
                font=(self.font_family, FONTS["label"]["size"], "bold"),
            ).grid(row=0, column=0, sticky="ew", padx=space[3], pady=(space[3], space[1]))
            self.tk.Label(
                card,
                text=value,
                background=background,
                foreground=TEXT,
                anchor="w",
                font=(self.heading_family, FONTS["metric"]["size"], "bold"),
            ).grid(row=1, column=0, sticky="ew", padx=space[3])
            icon = self.tk.Canvas(
                card,
                width=SIZES["compact_button"],
                height=SIZES["compact_button"],
                background=background,
                highlightthickness=0,
                borderwidth=0,
            )
            _rounded_rectangle(
                icon,
                0,
                0,
                SIZES["compact_button"],
                SIZES["compact_button"],
                radius=RADII["sm"],
                fill=surface,
                outline=surface,
            )
            icon.create_text(
                SIZES["compact_button"] / 2,
                SIZES["compact_button"] / 2,
                text=symbol,
                fill=TEXT,
                font=(self.heading_family, FONTS["body"]["size"], "bold"),
            )
            icon.grid(row=3, column=0, sticky="sw", padx=space[3], pady=space[3])

        score = float(winner.get("score", 0.0))
        metric_card(1, self.tr("analysis_best_score"), f"{score:.1f}", COLORS["asset_lilac"], "#")
        metric_card(
            2,
            self.tr("analysis_best_format"),
            str(winner.get("codec", "—")).upper(),
            COLORS["asset_mint"],
            "♪",
        )
        metric_card(3, self.tr("analysis_failures"), str(len(failures)), COLORS["asset_sand"], "!")

        lower = self.tk.Frame(main, background=surface)
        lower.grid(row=3, column=0, sticky="nsew", pady=(space[5], 0))
        lower.columnconfigure(0, weight=7, uniform="reference-analysis-lower")
        lower.columnconfigure(
            1, weight=4, minsize=SIZES["narrow_wrap"] + space[6], uniform="reference-analysis-lower"
        )
        lower.rowconfigure(0, weight=1)

        table = self.tk.Frame(lower, background=surface)
        table.grid(row=0, column=0, sticky="nsew", padx=(0, space[5]))
        table.columnconfigure(0, weight=1)
        self.tk.Label(
            table,
            text=self.tr("sources_table_title"),
            background=surface,
            foreground=TEXT,
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="ew", pady=(0, space[3]))
        analysis_header = self.tk.Frame(table, background=surface, height=SIZES["table_header"])
        analysis_header.grid(row=1, column=0, sticky="ew")
        analysis_header.grid_propagate(False)
        weights = (5, 1, 2, 2)
        for column, heading in enumerate(
            (self.tr("candidate"), self.tr("rank"), self.tr("table_format"), self.tr("score"))
        ):
            analysis_header.columnconfigure(column, weight=weights[column])
            self.tk.Label(
                analysis_header,
                text=heading,
                background=surface,
                foreground=MUTED,
                anchor="w" if column == 0 else "e",
                font=(self.font_family, FONTS["label"]["size"]),
            ).grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else space[2], 0))

        rows_host = self.tk.Frame(table, background=surface)
        rows_host.grid(row=2, column=0, sticky="nsew")
        rows_host.columnconfigure(0, weight=1)
        for row_index, candidate in enumerate(
            sorted(candidates, key=lambda item: int(item.get("rank", 999)))[:MAX_URLS]
        ):
            row = self.tk.Frame(rows_host, background=surface, height=SIZES["table_row"])
            row.grid(row=row_index, column=0, sticky="ew")
            row.grid_propagate(False)
            for column, weight in enumerate(weights):
                row.columnconfigure(column, weight=weight)
            values = (
                shorten_path(str(candidate.get("file_name") or self.tr("untitled")), 38),
                f"#{candidate.get('rank', '—')}",
                str(candidate.get("codec", "—")).upper(),
                f"{float(candidate.get('score', 0.0)):.1f}",
            )
            for column, value in enumerate(values):
                self.tk.Label(
                    row,
                    text=value,
                    background=surface,
                    foreground=GREEN if column == 3 and row_index == 0 else TEXT,
                    anchor="w" if column == 0 else "e",
                    font=(
                        self.font_family,
                        FONTS["body"]["size"] if column == 0 else FONTS["label"]["size"],
                    ),
                ).grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else space[2], 0))

        ranking_panel = self.tk.Frame(lower, background=COLORS["result"])
        ranking_panel.grid(row=0, column=1, sticky="nsew")
        _apply_rounded_corners(
            self.tk,
            ranking_panel,
            radius=RADII["md"],
            fill=COLORS["result"],
            outside=surface,
            outline=COLORS["result"],
        )
        ranking_panel.columnconfigure(0, weight=1)
        ranking_panel.rowconfigure(1, weight=1)
        self.tk.Label(
            ranking_panel,
            text=self.tr("ranking_title"),
            background=COLORS["result"],
            foreground=COLORS["result_text"],
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="ew", padx=space[5], pady=(space[5], space[2]))
        analysis_ranking = self.tk.Canvas(
            ranking_panel,
            background=COLORS["result"],
            highlightthickness=0,
            borderwidth=0,
        )
        analysis_ranking.grid(row=1, column=0, sticky="nsew", padx=space[5], pady=space[2])
        analysis_ranking.bind(
            "<Configure>",
            lambda _event, target=analysis_ranking: self._draw_ranking_canvas(target, candidates),
        )
        self._draw_ranking_canvas(analysis_ranking, candidates)
        RoundedButton(
            self.tk,
            ranking_panel,
            text=self.tr("back"),
            style="ResultAction.TButton",
            command=self._close_analysis_screen,
        ).grid(row=2, column=0, sticky="ew", padx=space[5], pady=(space[2], space[5]))

    def _build_analysis_plot(
        self,
        panel: Any,
        candidates: list[dict[str, Any]],
    ) -> None:
        plot_bed = self.tk.Frame(panel, background=COLORS["surface_muted"])
        plot_bed.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=SPACING[4],
            pady=(0, SPACING[4]),
        )
        plot_bed.columnconfigure(0, weight=1)
        plot_bed.rowconfigure(0, weight=1)
        winner = next((item for item in candidates if int(item.get("rank", 0)) == 1), None)
        spectrogram_path = winner.get("saved_spectrogram") if winner else None
        if spectrogram_path and Path(str(spectrogram_path)).is_file():
            try:
                original = self.tk.PhotoImage(file=str(spectrogram_path))
                factor = max(
                    1,
                    math.ceil(original.width() / SIZES["analysis_wrap"]),
                    math.ceil(original.height() / SIZES["plot_min_height"]),
                )
                shown = original.subsample(factor, factor)
                self._analysis_images.extend([original, shown])
                self.tk.Label(
                    plot_bed,
                    image=shown,
                    background=COLORS["surface_muted"],
                    borderwidth=0,
                ).grid(row=0, column=0)
                return
            except self.tk.TclError:
                pass
        plot = self.tk.Canvas(
            plot_bed,
            background=COLORS["surface_muted"],
            highlightthickness=0,
            borderwidth=0,
        )
        plot.grid(row=0, column=0, sticky="nsew")
        plot.bind(
            "<Configure>",
            lambda _event: self._draw_analysis_fallback(plot, candidates),
        )
        self._draw_analysis_fallback(plot, candidates)

    def _draw_analysis_fallback(
        self,
        canvas: Any,
        candidates: list[dict[str, Any]],
    ) -> None:
        canvas.delete("all")
        width = max(canvas.winfo_width(), SIZES["analysis_breakpoint"] // 2)
        height = max(canvas.winfo_height(), SIZES["plot_min_height"])
        left, top = SPACING[6], SPACING[3]
        right, bottom = width - SPACING[4], height - SPACING[5]
        for step in range(5):
            y = top + (bottom - top) * step / 4
            canvas.create_line(
                left,
                y,
                right,
                y,
                fill=COLORS["border"],
                width=1,
            )
        scores = [float(item.get("score", 0.0)) for item in candidates]
        if not scores:
            canvas.create_text(
                width / 2,
                height / 2,
                text=self.tr("no_candidates"),
                fill=COLORS["muted"],
                font=(self.font_family, FONTS["body"]["size"]),
                anchor="center",
            )
            return
        if len(scores) == 1:
            scores = [scores[0], scores[0]]
        points: list[float] = []
        for index, score in enumerate(scores):
            x = left + (right - left) * index / (len(scores) - 1)
            y = bottom - (bottom - top) * max(0.0, min(100.0, score)) / 100.0
            points.extend((x, y))
        polygon = [left, bottom, *points, right, bottom]
        canvas.create_polygon(polygon, fill=COLORS["accent_fill"], outline="")
        canvas.create_line(*points, fill=ACCENT, width=SIZES["stroke"], smooth=True)
        canvas.create_text(
            left,
            bottom + SPACING[3],
            text=self.tr("score"),
            fill=COLORS["muted"],
            font=(self.font_family, FONTS["label"]["size"]),
            anchor="w",
        )

    def _build_analysis_table(
        self,
        parent: Any,
        candidates: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> None:
        table_panel = self.tk.Frame(
            parent,
            background=CARD,
            highlightbackground=COLORS["divider"],
            highlightthickness=1,
        )
        table_panel.grid(
            row=2,
            column=0,
            sticky="nsew",
            padx=SPACING[4],
            pady=(0, SPACING[4]),
        )
        _apply_rounded_corners(
            self.tk,
            table_panel,
            radius=RADII["md"],
            fill=CARD,
            outside=COLORS["surface_muted"],
            outline=COLORS["divider"],
        )
        table_panel.columnconfigure(0, weight=1)
        table_panel.rowconfigure(1, weight=1)
        title = self.tk.Frame(table_panel, background=CARD)
        title.grid(row=0, column=0, sticky="ew", padx=SPACING[4], pady=(SPACING[3], SPACING[2]))
        self.tk.Label(
            title,
            text=self.tr("sources_table_title"),
            background=CARD,
            foreground=TEXT,
            anchor="w",
            font=(self.heading_family, FONTS["panel_title"]["size"], "bold"),
        ).pack(anchor="w")
        self.tk.Label(
            title,
            text=self.tr("sources_table_helper"),
            background=CARD,
            foreground=COLORS["muted"],
            anchor="w",
            font=(self.font_family, FONTS["label"]["size"]),
        ).pack(anchor="w")
        body = self.tk.Frame(table_panel, background=CARD)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        weights = (5, 1, 1, 1, 2)
        headings = (
            self.tr("candidate"),
            self.tr("rank"),
            self.tr("table_format"),
            self.tr("table_cutoff"),
            self.tr("score"),
        )
        header = self.tk.Frame(
            body, background=COLORS["table_header"], height=SIZES["table_header"]
        )
        header.grid(row=0, column=0, sticky="ew")
        header.grid_propagate(False)
        for column, (heading, weight) in enumerate(zip(headings, weights, strict=True)):
            header.columnconfigure(column, weight=weight)
            self.tk.Label(
                header,
                text=heading.upper(),
                background=COLORS["table_header"],
                foreground=COLORS["muted"],
                anchor="e" if column else "w",
                font=(self.font_family, FONTS["label"]["size"], "bold"),
            ).grid(row=0, column=column, sticky="ew", padx=SPACING[3], pady=SPACING[2])

        rows = sorted(candidates, key=lambda item: int(item.get("rank", 999)))
        for row_index, candidate in enumerate(rows, 1):
            is_winner = int(candidate.get("rank", 0)) == 1
            row_color = COLORS["accent_faint"] if is_winner else CARD
            row = self.tk.Frame(body, background=row_color, height=SIZES["table_row"])
            row.grid(row=row_index, column=0, sticky="ew")
            row.grid_propagate(False)
            for column, weight in enumerate(weights):
                row.columnconfigure(column, weight=weight)
            if is_winner:
                self.tk.Frame(row, background=ACCENT, width=SPACING[1] - 1).place(
                    x=0, y=SPACING[1], relheight=1, height=-(SPACING[2])
                )
            values = (
                str(candidate.get("file_name") or self.tr("untitled")),
                f"#{candidate.get('rank', '—')}",
                str(candidate.get("codec", "—")).upper(),
                f"{float(candidate.get('effective_cutoff_hz', 0.0)) / 1000:.1f} {self.tr('khz')}",
                f"{float(candidate.get('score', 0.0)):.1f}/100",
            )
            for column, value in enumerate(values):
                self.tk.Label(
                    row,
                    text=value,
                    background=row_color,
                    foreground=TEXT,
                    anchor="e" if column else "w",
                    font=(self.font_family, FONTS["body"]["size"]),
                ).grid(row=0, column=column, sticky="ew", padx=SPACING[3], pady=SPACING[2])
            self.tk.Frame(body, background=COLORS["divider"], height=1).grid(
                row=row_index, column=0, sticky="sew"
            )

        offset = len(rows) + 1
        for failure_index, failure in enumerate(failures[: max(0, MAX_URLS - len(rows))]):
            row_index = offset + failure_index
            row = self.tk.Frame(body, background=COLORS["error_surface"], height=SIZES["table_row"])
            row.grid(row=row_index, column=0, sticky="ew")
            row.grid_propagate(False)
            for column, weight in enumerate(weights):
                row.columnconfigure(column, weight=weight)
            values = (
                shorten_path(str(failure.get("url", "")), 64),
                "—",
                self.tr("source_failed"),
                "—",
                "—",
            )
            for column, value in enumerate(values):
                self.tk.Label(
                    row,
                    text=value,
                    background=COLORS["error_surface"],
                    foreground=ACCENT if column in {0, 2} else TEXT,
                    anchor="e" if column else "w",
                    font=(self.font_family, FONTS["body"]["size"]),
                ).grid(row=0, column=column, sticky="ew", padx=SPACING[3], pady=SPACING[2])

    def _add_analysis_summary(
        self,
        parent: Any,
        candidates: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> None:
        content_bed = COLORS["surface_muted"]
        strip = self.tk.Frame(parent, background=content_bed)
        strip.pack(fill="both", expand=True)
        winner = self.last_payload.get("winner", {}) if self.last_payload else {}
        values = (
            (self.tr("analysis_variants"), str(len(candidates))),
            (self.tr("analysis_best_score"), f"{float(winner.get('score', 0.0)):.1f}/100"),
            (self.tr("analysis_best_format"), str(winner.get("codec", "—")).upper()),
            (self.tr("analysis_failures"), str(len(failures))),
        )
        for index, (label, value) in enumerate(values):
            strip.columnconfigure(index, weight=1)
            cell = self.tk.Frame(
                strip,
                background=CARD,
                height=SIZES["kpi_min_height"],
                highlightbackground=COLORS["divider"],
                highlightthickness=1,
            )
            cell.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0, SPACING[3] if index < len(values) - 1 else 0),
            )
            _apply_rounded_corners(
                self.tk,
                cell,
                radius=RADII["md"],
                fill=CARD,
                outside=content_bed,
                outline=COLORS["divider"],
            )
            cell.grid_propagate(False)
            self.tk.Frame(cell, background=ACCENT, width=SPACING[1] - 1).pack(
                side="left", fill="y", pady=SPACING[2]
            )
            body = self.tk.Frame(cell, background=CARD)
            body.pack(side="left", fill="both", expand=True)
            self.tk.Label(
                body,
                text=label,
                background=CARD,
                foreground=COLORS["muted"],
                anchor="w",
                font=(self.font_family, FONTS["label"]["size"], "bold"),
            ).pack(fill="x", padx=SPACING[3], pady=(SPACING[2], SPACING[1]))
            self.tk.Label(
                body,
                text=value,
                background=CARD,
                foreground=ACCENT if index == 1 else TEXT,
                anchor="w",
                font=(self.mono_family, FONTS["metric"]["size"], "bold"),
            ).pack(fill="x", padx=SPACING[3])

    def _add_candidate_card(self, parent: Any, candidate: dict[str, Any]) -> None:
        is_winner = int(candidate.get("rank", 0)) == 1
        score = float(candidate.get("score", 0.0))
        emphasis_color = ACCENT
        score_color = emphasis_color if is_winner else TEXT
        card_color = COLORS["success_surface"] if is_winner else CARD
        card = self.tk.Frame(
            parent,
            background=card_color,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=(0, SPACING[3]))
        _apply_rounded_corners(
            self.tk,
            card,
            radius=RADII["lg"],
            fill=card_color,
            outside=BACKGROUND,
        )
        card.columnconfigure(1, weight=1)
        self.tk.Frame(
            card,
            background=ACCENT if is_winner else card_color,
            width=SPACING[1] - 1,
        ).grid(row=0, column=0, rowspan=5, sticky="ns")

        top = self.tk.Frame(card, background=card_color)
        top.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=SPACING[4],
            pady=(SPACING[4], SPACING[2]),
        )
        top.columnconfigure(0, weight=1)
        name = str(candidate.get("file_name") or self.tr("untitled"))
        badge = self.tr("winner_badge") if is_winner else ""
        self.tk.Label(
            top,
            text=f"#{candidate.get('rank', '?')}  {name}{badge}",
            background=card_color,
            foreground=emphasis_color if is_winner else TEXT,
            anchor="w",
            justify="left",
            wraplength=SIZES["analysis_wrap"],
            font=(self.heading_family, FONTS["heading"]["size"], "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.tk.Label(
            top,
            text=f"{score:.1f}/100",
            background=card_color,
            foreground=score_color,
            font=(self.mono_family, FONTS["metric"]["size"], "bold"),
        ).grid(row=0, column=1, sticky="e", padx=(SPACING[4], 0))
        self.tk.Label(
            top,
            text=shorten_path(str(candidate.get("source", "")), 105),
            background=card_color,
            foreground=COLORS["text_muted"],
            anchor="w",
            font=(self.mono_family, FONTS["technical"]["size"]),
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(SPACING[1], 0))

        metrics = self.tk.Frame(card, background=card_color)
        metrics.grid(
            row=1,
            column=1,
            sticky="ew",
            padx=SPACING[4],
            pady=(0, SPACING[3]),
        )
        values = [
            (
                self.tr("format"),
                f"{candidate.get('codec', 'unknown')} · "
                f"{int(candidate.get('bitrate_kbps', 0))} {self.tr('kbps')}",
            ),
            (
                self.tr("duration"),
                f"{float(candidate.get('source_duration_seconds', 0.0)):.1f} {self.tr('seconds')}",
            ),
            (
                self.tr("cutoff"),
                f"{float(candidate.get('effective_cutoff_hz', 0.0)) / 1000:.1f} {self.tr('khz')}",
            ),
            (
                self.tr("authenticity"),
                f"{float(candidate.get('authenticity', 0.0)):.0f}/100",
            ),
        ]
        for index, (label, value) in enumerate(values):
            metrics.columnconfigure(index, weight=1)
            cell = self.tk.Frame(
                metrics,
                background=CARD,
                height=SIZES["kpi_min_height"],
                highlightbackground=BORDER,
                highlightthickness=1,
            )
            cell.grid(
                row=0,
                column=index,
                sticky="nsew",
                padx=(0, SPACING[3] if index < len(values) - 1 else 0),
            )
            _apply_rounded_corners(
                self.tk,
                cell,
                radius=RADII["md"],
                fill=CARD,
                outside=card_color,
            )
            cell.grid_propagate(False)
            self.tk.Label(
                cell,
                text=label,
                background=CARD,
                foreground=COLORS["text_muted"],
                font=(self.font_family, FONTS["label"]["size"], "bold"),
            ).pack(anchor="w", padx=SPACING[4], pady=(SPACING[3], SPACING[1]))
            self.tk.Label(
                cell,
                text=value,
                background=CARD,
                foreground=TEXT,
                font=(self.mono_family, FONTS["label"]["size"], "bold"),
            ).pack(anchor="w", padx=SPACING[4])

        self.tk.Label(
            card,
            text=candidate_explanation(candidate, self.language),
            background=card_color,
            foreground=TEXT,
            justify="left",
            anchor="w",
            wraplength=SIZES["analysis_wrap"],
            font=(self.font_family, FONTS["body"]["size"]),
        ).grid(
            row=2,
            column=1,
            sticky="ew",
            padx=SPACING[4],
            pady=(0, SPACING[3]),
        )

        spectrogram_path = candidate.get("saved_spectrogram")
        if spectrogram_path and Path(spectrogram_path).is_file():
            try:
                original = self.tk.PhotoImage(file=str(spectrogram_path))
                factor = max(1, math.ceil(original.width() / SIZES["analysis_wrap"]))
                shown = original.subsample(factor, factor)
                self._analysis_images.extend([original, shown])
                self.tk.Label(
                    card,
                    image=shown,
                    background=card_color,
                    borderwidth=0,
                ).grid(row=3, column=1, padx=SPACING[4], pady=(0, SPACING[3]))
                spectrogram_actions = self.tk.Frame(card, background=card_color)
                spectrogram_actions.grid(
                    row=4,
                    column=1,
                    sticky="w",
                    padx=SPACING[4],
                    pady=(0, SPACING[4]),
                )
                RoundedButton(
                    self.tk,
                    spectrogram_actions,
                    text=self.tr("open_spectrogram"),
                    style="SecondaryStrong.TButton",
                    command=lambda path=str(spectrogram_path): self._open_path(path),
                ).grid(row=0, column=0, sticky="w", padx=(0, SPACING[2]))
                save_button = RoundedButton(
                    self.tk,
                    spectrogram_actions,
                    text=self.tr("save_spectrogram"),
                    style="CardText.TButton",
                )
                save_button.configure(
                    command=lambda path=str(spectrogram_path), button=save_button: (
                        self._save_spectrogram_copy(path, button)
                    )
                )
                save_button.grid(row=0, column=1, sticky="w")
            except self.tk.TclError:
                self._add_missing_spectrogram_label(card, row=3, background=card_color)
        else:
            self._add_missing_spectrogram_label(card, row=3, background=card_color)

    def _add_missing_spectrogram_label(
        self,
        card: Any,
        row: int,
        *,
        background: str = CARD,
    ) -> None:
        self.tk.Label(
            card,
            text=self.tr("spectrogram_missing"),
            background=background,
            foreground=COLORS["muted"],
            font=(self.font_family, FONTS["body"]["size"]),
        ).grid(
            row=row,
            column=1,
            sticky="w",
            padx=SPACING[4],
            pady=(0, SPACING[4]),
        )

    def _add_failure_card(self, parent: Any, failure: dict[str, Any]) -> None:
        card = self.tk.Frame(
            parent,
            background=COLORS["error_surface"],
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        card.pack(fill="x", pady=(0, SPACING[3]))
        _apply_rounded_corners(
            self.tk,
            card,
            radius=RADII["md"],
            fill=COLORS["error_surface"],
            outside=BACKGROUND,
        )
        self.tk.Frame(
            card,
            background=RED,
            width=SPACING[1] - 1,
        ).pack(side="left", fill="y")
        content = self.tk.Frame(card, background=COLORS["error_surface"])
        content.pack(side="left", fill="both", expand=True)
        self.tk.Label(
            content,
            text=self.tr("source_failed"),
            background=COLORS["error_surface"],
            foreground=RED,
            font=(self.heading_family, FONTS["heading"]["size"], "bold"),
        ).pack(anchor="w", padx=SPACING[4], pady=(SPACING[4], SPACING[1]))
        self.tk.Label(
            content,
            text=str(failure.get("url", "")),
            background=COLORS["error_surface"],
            foreground=TEXT,
            font=(self.mono_family, FONTS["technical"]["size"]),
            wraplength=SIZES["analysis_wrap"],
            justify="left",
        ).pack(anchor="w", padx=SPACING[4])
        self.tk.Label(
            content,
            text=str(failure.get("reason", self.tr("unknown_error"))),
            background=COLORS["error_surface"],
            foreground=RED,
            font=(self.font_family, FONTS["body"]["size"]),
            wraplength=SIZES["analysis_wrap"],
            justify="left",
        ).pack(anchor="w", padx=SPACING[4], pady=(SPACING[1], SPACING[4]))

    def _close_analysis_screen(self) -> None:
        if self.analysis_overlay is not None:
            with suppress(Exception):
                self.root.unbind_all("<MouseWheel>")
                self.analysis_overlay.destroy()
            self.analysis_overlay = None
            self._analysis_images = []
            self.destination_var.set(self.tr("analytics"))

    def _open_output_folder(self) -> None:
        if self.last_output_folder:
            self._open_path(self.last_output_folder)

    def _open_winner(self) -> None:
        if self.last_winner_file:
            self._open_path(self.last_winner_file)

    def _open_json_report(self) -> None:
        if self.last_report_path:
            self._open_path(self.last_report_path)

    def _save_spectrogram_copy(self, source: str, button: Any) -> None:
        if not self.last_output_folder or not Path(source).is_file():
            self._set_inline_error(self.tr("save_failed"), self.tr("spectrogram_missing"))
            return
        try:
            destination = unique_dest_path(source, self.last_output_folder)
            shutil.copy2(source, destination)
        except OSError as exc:
            self._set_inline_error(self.tr("save_failed"), str(exc))
            return
        button.configure(text=self.tr("spectrogram_saved_button"), state="disabled")
        self.status_var.set(self.tr("spectrogram_saved", path=shorten_path(destination, 64)))

    def _open_path(self, path: str) -> None:
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as exc:
            self._set_inline_error(self.tr("open_failed"), str(exc))

    def _cleanup_spectrogram_temp(self) -> None:
        if self.spectrogram_temp_folder:
            shutil.rmtree(self.spectrogram_temp_folder, ignore_errors=True)
            self.spectrogram_temp_folder = None

    def _cleanup_report_temp(self) -> None:
        if self.report_temp_folder:
            shutil.rmtree(self.report_temp_folder, ignore_errors=True)
            self.report_temp_folder = None
        self.last_report_path = None

    def _on_close(self) -> None:
        if self.running:
            self.status_var.set(self.tr("wait_until_done"))
            return
        self._cleanup_spectrogram_temp()
        self._cleanup_report_temp()
        self.root.destroy()

    def run(self) -> int:
        self.root.mainloop()
        return 0


def _show_startup_error(message: str) -> None:
    if sys.stderr is not None:
        print(message, file=sys.stderr)


def _prepare_analysis_preview(window: TrackJudgeWindow) -> None:
    """Create realistic local spectrograms for visual regression screenshots."""
    import numpy as np

    preview_folder = tempfile.mkdtemp(prefix="trackjudge-analysis-preview-")
    candidates = [
        {
            "rank": 1,
            "file_name": "reference-mix.opus",
            "codec": "opus",
            "score": 84.6,
            "effective_cutoff_hz": 20500.0,
        },
        {
            "rank": 2,
            "file_name": "alternate-source.m4a",
            "codec": "aac",
            "score": 76.2,
            "effective_cutoff_hz": 18600.0,
        },
        {
            "rank": 3,
            "file_name": "archive-upload.webm",
            "codec": "opus",
            "score": 63.8,
            "effective_cutoff_hz": 16300.0,
        },
        {
            "rank": 4,
            "file_name": "low-bitrate-copy.mp3",
            "codec": "mp3",
            "score": 45.1,
            "effective_cutoff_hz": 12800.0,
        },
    ]
    frequencies = np.linspace(0.0, 24000.0, 180)
    times = np.linspace(0.0, 210.0, 420)
    for index, candidate in enumerate(candidates):
        cutoff = float(candidate["effective_cutoff_hz"])
        envelope = np.exp(-frequencies / (9000.0 - index * 900.0))
        envelope *= 1.0 / (1.0 + np.exp((frequencies - cutoff) / 320.0))
        rhythm = 0.34 + 0.66 * np.square(np.sin(times * (0.17 + index * 0.012)))
        harmonics = 0.72 + 0.28 * np.square(np.sin(frequencies[:, None] / 650.0 + times / 5.0))
        spectrum = envelope[:, None] * rhythm[None, :] * harmonics
        spectrum += 0.0025 * np.square(np.sin(frequencies[:, None] / 3100.0 + times / 13.0))
        output = str(Path(preview_folder) / f"candidate-{index + 1}.png")
        render_spectrogram(
            frequencies,
            times,
            spectrum,
            float(np.max(spectrum)),
            24000.0,
            cutoff,
            cutoff,
            False,
            output,
            str(candidate["file_name"]),
        )
        candidate["saved_spectrogram"] = output

    window.spectrogram_temp_folder = preview_folder
    window.last_output_folder = preview_folder
    window.last_payload = {
        "winner": candidates[0],
        "candidates": candidates,
        "failures": [],
    }


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--headless"]:
        from .app import main as cli_main

        return cli_main(arguments[1:])
    if arguments[:1] and arguments[0] in {"--help", "--version", "-h"}:
        from .app import main as cli_main

        return cli_main(arguments)

    enable_windows_dpi_awareness()
    try:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import ttk
    except ImportError as exc:
        _show_startup_error(f"Не удалось запустить графический интерфейс: {exc}")
        return 1

    gui_smoke_test = arguments == ["--gui-smoke-test"]
    reference_smoke_test = arguments == ["--gui-reference-smoke-test"]
    fullscreen_smoke_test = arguments == ["--gui-fullscreen-smoke-test"]
    analysis_smoke_test = arguments == ["--gui-analysis-smoke-test"]
    analysis_fullscreen_smoke_test = arguments == ["--gui-analysis-fullscreen-smoke-test"]
    paste_smoke_test = arguments == ["--gui-paste-smoke-test"]
    if reference_smoke_test or fullscreen_smoke_test:
        initial_sources = [
            "https://youtu.be/reference-source",
            "https://soundcloud.com/artist/alternate-source",
        ]
    elif (
        gui_smoke_test or analysis_smoke_test or analysis_fullscreen_smoke_test or paste_smoke_test
    ):
        initial_sources = []
    else:
        initial_sources = [value for value in arguments if value.strip()]
    try:
        window = TrackJudgeWindow(tk, ttk, tkfont, initial_sources)
        if paste_smoke_test:
            expected = ["https://youtu.be/first", "https://youtu.be/second"]
            window.root.withdraw()
            window.root.clipboard_clear()
            window.root.clipboard_append("\n".join(expected))
            window.root.update()
            event = SimpleNamespace(keycode=86, keysym="Cyrillic_em")
            result = window._on_source_shortcut(event)
            actual = window._current_sources()
            window.root.destroy()
            return 0 if result == "break" and actual == expected else 1
        if gui_smoke_test:
            window.root.after(500, window.root.destroy)
        if reference_smoke_test:
            window.root.after(6000, window.root.destroy)
        if fullscreen_smoke_test:
            window.root.after(120, window._toggle_maximize)
            window.root.after(8000, window.root.destroy)
        if analysis_smoke_test or analysis_fullscreen_smoke_test:
            _prepare_analysis_preview(window)
            window.root.after(100, window._show_analysis_screen)
            if analysis_fullscreen_smoke_test:
                window.root.after(220, window._toggle_maximize)
                window.root.after(10000, window.root.destroy)
            else:
                window.root.after(8000, window.root.destroy)
        return window.run()
    except Exception as exc:
        _show_startup_error(f"Не удалось открыть TrackJudge: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
