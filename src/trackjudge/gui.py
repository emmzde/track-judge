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
    run_analysis,
    unique_dest_path,
)

APP_TITLE = "TrackJudge"
BACKGROUND = "#09111d"
CARD = "#121e2d"
CARD_ALT = "#0e1826"
INPUT = "#0a1421"
TEXT = "#f1f7fb"
MUTED = "#9aafc1"
ACCENT = "#43cbe9"
ACCENT_ACTIVE = "#70dcef"
GREEN = "#4bd88c"
GREEN_ACTIVE = "#75e4aa"
RED = "#ff7480"
BORDER = "#294058"
TITLE_BAR = "#070d16"
GITHUB_URL = "https://github.com/emmzde"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        "subtitle": "Сравните варианты одного трека и сохраните самый качественный.",
        "sources_title": "1. Вставьте ссылки на варианты трека",
        "source_placeholder": (
            "Например: https://youtu.be/…\n"
            "Можно вставить до 5 ссылок сразу — через пробел, с новой строки или подряд."
        ),
        "source_only_links": "Вставляются только веб-ссылки.",
        "sources_recognized": "Ссылки распознаны. Их можно редактировать прямо в этом поле.",
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
    },
    "en": {
        "subtitle": "Compare versions of one track and keep the highest-quality source.",
        "sources_title": "1. Paste links to track versions",
        "source_placeholder": (
            "For example: https://youtu.be/…\n"
            "Paste up to 5 links at once — separated, line by line, or back to back."
        ),
        "source_only_links": "Only web links are accepted.",
        "sources_recognized": "Links recognized. You can edit them directly in this field.",
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
    },
    "de": {
        "subtitle": "Vergleiche Versionen eines Tracks und behalte die hochwertigste Quelle.",
        "sources_title": "1. Links zu den Track-Versionen einfügen",
        "source_placeholder": (
            "Zum Beispiel: https://youtu.be/…\n"
            "Bis zu 5 Links auf einmal einfügen — getrennt, zeilenweise oder direkt nacheinander."
        ),
        "source_only_links": "Es werden nur Weblinks akzeptiert.",
        "sources_recognized": "Links erkannt. Sie können direkt in diesem Feld bearbeitet werden.",
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
    return parser.parse_args(argv)


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


class StyledCheck:
    """A DPI-friendly checkbox built from regular Tk widgets."""

    def __init__(
        self,
        tk: Any,
        parent: Any,
        *,
        text: str,
        variable: Any,
        font: tuple[Any, ...],
    ) -> None:
        self.tk = tk
        self.variable = variable
        self.state = "normal"
        self.frame = tk.Frame(parent, background=CARD, cursor="hand2", takefocus=1)
        self.box = tk.Label(
            self.frame,
            width=2,
            height=1,
            borderwidth=0,
            relief="flat",
            font=(font[0], 11, "bold"),
            cursor="hand2",
        )
        self.box.pack(side="left", padx=(0, 10))
        self.label = tk.Label(
            self.frame,
            text=text,
            background=CARD,
            foreground=TEXT,
            font=font,
            anchor="w",
            cursor="hand2",
        )
        self.label.pack(side="left", fill="x", expand=True)
        for widget in (self.frame, self.box, self.label):
            widget.bind("<Button-1>", self._toggle)
        self.frame.bind("<space>", self._toggle)
        self.frame.bind("<Return>", self._toggle)
        self._trace_id = self.variable.trace_add("write", lambda *_args: self._render())
        self._render()

    def _toggle(self, _event: Any = None) -> str:
        if self.state != "disabled":
            self.variable.set(not bool(self.variable.get()))
        return "break"

    def _render(self) -> None:
        disabled = self.state == "disabled"
        checked = bool(self.variable.get())
        if checked:
            self.box.configure(
                text="✓",
                background="#2eabc5" if disabled else ACCENT,
                foreground="#17323b" if disabled else "#04131a",
                highlightbackground="#2eabc5" if disabled else ACCENT,
                highlightthickness=1,
            )
        else:
            self.box.configure(
                text="",
                background="#101c28" if disabled else INPUT,
                foreground=TEXT,
                highlightbackground="#26394b" if disabled else "#45627a",
                highlightthickness=1,
            )
        color = "#647689" if disabled else TEXT
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
        if kwargs:
            self.frame.configure(**kwargs)
        self._render()


class LoadingSpinner:
    """Small animated activity indicator for the indeterminate analysis stage."""

    def __init__(self, tk: Any, parent: Any) -> None:
        self.tk = tk
        self.canvas = tk.Canvas(
            parent,
            width=28,
            height=28,
            background=BACKGROUND,
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
        self.canvas.create_oval(5, 5, 23, 23, outline="#1d3b50", width=3)
        self.canvas.create_arc(
            5,
            5,
            23,
            23,
            start=self.angle,
            extent=105,
            style="arc",
            outline=ACCENT,
            width=3,
        )
        self.canvas.create_arc(
            5,
            5,
            23,
            23,
            start=self.angle + 180,
            extent=35,
            style="arc",
            outline=ACCENT_ACTIVE,
            width=3,
        )
        self.angle = (self.angle + 12) % 360
        self.after_id = self.canvas.after(32, self._tick)


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
        self._normal_geometry = "980x940"
        self._drag_origin: tuple[int, int, int, int] | None = None

        self.root = tk.Tk()
        self.root.title(APP_TITLE)
        self.root.geometry("980x940")
        self.root.minsize(820, 780)
        self.root.configure(background=BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
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
                for name in ("Segoe UI Variable Text", "Segoe UI Variable", "Segoe UI")
                if name.casefold() in families
            ),
            "TkDefaultFont",
        )
        self.heading_family = next(
            (
                families[name.casefold()]
                for name in ("Segoe UI Variable Display", "Segoe UI Semibold", self.font_family)
                if name.casefold() in families
            ),
            self.font_family,
        )
        self.mono_family = next(
            (
                families[name.casefold()]
                for name in ("Cascadia Mono", "Consolas")
                if name.casefold() in families
            ),
            self.font_family,
        )
        self.root.option_add("*Font", (self.font_family, 11))

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

        style.configure("App.TFrame", background=BACKGROUND)
        style.configure("Card.TFrame", background=CARD)
        style.configure("CardAlt.TFrame", background=CARD_ALT)
        style.configure(
            "Title.TLabel",
            background=BACKGROUND,
            foreground=TEXT,
            font=(self.heading_family, 25, "bold"),
        )
        style.configure(
            "Subtitle.TLabel",
            background=BACKGROUND,
            foreground=MUTED,
            font=(self.font_family, 11),
        )
        style.configure(
            "Section.TLabel",
            background=CARD,
            foreground=TEXT,
            font=(self.heading_family, 12, "bold"),
        )
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED)
        style.configure("Error.TLabel", background=CARD, foreground=RED)
        style.configure("Status.TLabel", background=BACKGROUND, foreground=MUTED)
        style.configure(
            "Counter.TLabel",
            background="#1c3449",
            foreground=ACCENT_ACTIVE,
            padding=(9, 4),
            font=(self.heading_family, 10, "bold"),
        )
        style.configure(
            "ResultTitle.TLabel",
            background=CARD_ALT,
            foreground=TEXT,
            font=(self.heading_family, 13, "bold"),
        )
        style.configure(
            "ResultError.TLabel",
            background=CARD_ALT,
            foreground=RED,
            font=(self.heading_family, 13, "bold"),
        )
        style.configure(
            "Result.TLabel",
            background=CARD_ALT,
            foreground=MUTED,
            font=(self.font_family, 11),
        )
        style.configure(
            "App.TEntry",
            fieldbackground=INPUT,
            foreground=TEXT,
            insertcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=(10, 8),
        )
        style.map(
            "App.TEntry",
            bordercolor=[("focus", ACCENT)],
            lightcolor=[("focus", ACCENT)],
            darkcolor=[("focus", ACCENT)],
        )
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#04131a",
            borderwidth=0,
            padding=(20, 10),
            font=(self.heading_family, 11, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_ACTIVE), ("disabled", "#24414c")],
            foreground=[("disabled", "#718995")],
        )
        style.configure(
            "Secondary.TButton",
            background="#1b2d40",
            foreground=TEXT,
            borderwidth=0,
            padding=(13, 8),
            font=(self.font_family, 10),
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#264059"), ("disabled", "#121f2c")],
            foreground=[("disabled", "#607486")],
        )
        style.configure(
            "SecondaryStrong.TButton",
            background="#24445f",
            foreground=TEXT,
            bordercolor="#3b6684",
            lightcolor="#3b6684",
            darkcolor="#3b6684",
            borderwidth=1,
            padding=(15, 9),
            font=(self.heading_family, 10, "bold"),
        )
        style.map(
            "SecondaryStrong.TButton",
            background=[("active", "#315d7d"), ("disabled", "#142434")],
            foreground=[("disabled", "#607486")],
        )
        style.configure(
            "TCheckbutton",
            background=CARD,
            foreground=TEXT,
            font=(self.font_family, 10),
        )
        style.map(
            "TCheckbutton",
            background=[("active", CARD)],
            foreground=[("disabled", "#647689")],
            indicatorcolor=[("selected", ACCENT), ("!selected", INPUT)],
        )
        style.configure(
            "Horizontal.TProgressbar",
            background=ACCENT,
            troughcolor="#182a3c",
            borderwidth=0,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
        )
        style.configure(
            "Analysis.Vertical.TScrollbar",
            background="#24445f",
            troughcolor=BACKGROUND,
            bordercolor=BACKGROUND,
            arrowcolor=MUTED,
            lightcolor="#315d7d",
            darkcolor="#1b3348",
        )

    def _build_title_bar(self) -> None:
        bar = self.tk.Frame(self.root, background=TITLE_BAR, height=42)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(1, weight=1)
        self.title_bar = bar

        mark = self.tk.Label(
            bar,
            text="♫",
            background=TITLE_BAR,
            foreground=ACCENT,
            font=(self.heading_family, 15, "bold"),
        )
        mark.grid(row=0, column=0, padx=(14, 8), sticky="w")
        title = self.tk.Label(
            bar,
            text=APP_TITLE,
            background=TITLE_BAR,
            foreground=TEXT,
            font=(self.heading_family, 10, "bold"),
        )
        title.grid(row=0, column=1, sticky="w")

        self.language_button = self._title_button(
            bar,
            "RU  ▾",
            self._toggle_language_popup,
            width=8,
            hover="#17283a",
        )
        self.language_button.grid(row=0, column=2, sticky="e", padx=(0, 5))
        self._minimize_button = self._window_control_button(
            bar,
            "minimize",
            self._minimize_window,
            hover="#17283a",
        )
        self._minimize_button.grid(row=0, column=3, sticky="e")
        self._maximize_button = self._window_control_button(
            bar,
            "maximize",
            self._toggle_maximize,
            hover="#17283a",
        )
        self._maximize_button.grid(row=0, column=4, sticky="e")
        self._close_button = self._window_control_button(
            bar,
            "close",
            self._on_close,
            hover="#c42b3a",
        )
        self._close_button.grid(row=0, column=5, sticky="e")

        for widget in (bar, mark, title):
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
            height=2,
            background=TITLE_BAR,
            foreground=TEXT,
            borderwidth=0,
            font=(self.font_family, 10),
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
            width=46,
            height=42,
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
        color = "#e6eef5"
        if kind == "minimize":
            button.create_line(
                18,
                23,
                28,
                23,
                fill=color,
                width=1,
                tags="window-icon",
            )
        elif kind == "maximize":
            button.create_rectangle(
                18,
                16,
                28,
                26,
                outline=color,
                width=1,
                tags="window-icon",
            )
        elif kind == "restore":
            button.create_rectangle(
                20,
                15,
                29,
                24,
                outline=color,
                width=1,
                tags="window-icon",
            )
            button.create_rectangle(
                17,
                18,
                26,
                27,
                fill=button.cget("background"),
                outline=color,
                width=1,
                tags="window-icon",
            )
        else:
            button.create_line(19, 17, 27, 25, fill=color, width=1, tags="window-icon")
            button.create_line(27, 17, 19, 25, fill=color, width=1, tags="window-icon")

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
            self._draw_window_control(self._maximize_button, "maximize")
            return
        self._normal_geometry = self.root.geometry()
        left, top, right, bottom = self._work_area()
        self.root.geometry(f"{right - left}x{bottom - top}+{left}+{top}")
        self._is_maximized = True
        self._draw_window_control(self._maximize_button, "restore")

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
        popup.place(relx=1.0, x=-150, y=39, width=145, anchor="ne")
        self.language_popup = popup
        for row, (code, label) in enumerate(
            (("ru", "Русский"), ("en", "English"), ("de", "Deutsch"))
        ):
            button = self.tk.Label(
                popup,
                text=("✓  " if code == self.language else "     ") + label,
                background=CARD,
                foreground=ACCENT_ACTIVE if code == self.language else TEXT,
                anchor="w",
                padx=13,
                pady=9,
                cursor="hand2",
                font=(self.font_family, 10),
            )
            button.grid(row=row, column=0, sticky="ew")
            button.bind("<Button-1>", lambda _event, value=code: self._change_language(value))
            button.bind("<Enter>", lambda _event, item=button: item.configure(background="#1b2d40"))
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
        outer = self.ttk.Frame(self.content_host, style="App.TFrame", padding=(26, 18, 26, 12))
        outer.grid(row=0, column=0, sticky="nsew")
        self._main_outer = outer
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        header = self.ttk.Frame(outer, style="App.TFrame")
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(1, weight=1)
        self._build_logo(header)
        title_block = self.ttk.Frame(header, style="App.TFrame")
        title_block.grid(row=0, column=1, sticky="w", padx=(15, 0))
        self.ttk.Label(title_block, text=APP_TITLE, style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.ttk.Label(
            title_block,
            text=self.tr("subtitle"),
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(1, 0))

        source_card = self.ttk.Frame(outer, style="Card.TFrame", padding=(18, 15))
        source_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        source_card.columnconfigure(0, weight=1)
        source_header = self.ttk.Frame(source_card, style="Card.TFrame")
        source_header.grid(row=0, column=0, sticky="ew", pady=(2, 11))
        source_header.columnconfigure(0, weight=1)
        self.ttk.Label(
            source_header,
            text=self.tr("sources_title"),
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w")
        self.source_count_var = self.tk.StringVar(value=f"0 / {MAX_URLS}")
        self.ttk.Label(
            source_header,
            textvariable=self.source_count_var,
            style="Counter.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(18, 2))

        input_frame = self.tk.Frame(source_card, background=CARD, borderwidth=0)
        input_frame.grid(row=1, column=0, sticky="ew")
        self.source_text = self.tk.Text(
            input_frame,
            height=4,
            wrap="word",
            undo=True,
            background=INPUT,
            foreground=TEXT,
            insertbackground=TEXT,
            selectbackground="#265370",
            selectforeground=TEXT,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            highlightthickness=1,
            borderwidth=0,
            relief="flat",
            padx=12,
            pady=10,
            font=(self.font_family, 11),
        )
        self.source_text.pack(fill="both", expand=True)
        self.source_placeholder = self.tk.Label(
            input_frame,
            text=self.tr("source_placeholder"),
            justify="left",
            anchor="nw",
            background=INPUT,
            foreground="#6f879a",
            font=(self.font_family, 11),
            cursor="xterm",
        )
        self.source_placeholder.place(x=13, y=10)
        self.source_placeholder.bind("<Button-1>", self._focus_source_input)
        self.source_text.bind("<<Modified>>", self._on_source_modified)
        self.source_text.bind("<Control-KeyPress>", self._on_source_shortcut)
        self.source_text.bind("<Shift-Insert>", self._paste_sources)
        self.source_text.bind("<FocusIn>", lambda _event: self._sync_placeholder())
        self.source_text.bind("<FocusOut>", self._normalize_source_input)
        self.source_error_var = self.tk.StringVar(value=self.tr("source_only_links"))
        self.source_hint = self.ttk.Label(
            source_card,
            textvariable=self.source_error_var,
            style="Muted.TLabel",
        )
        self.source_hint.grid(row=2, column=0, sticky="w", pady=(7, 0))

        settings_card = self.ttk.Frame(outer, style="Card.TFrame", padding=(18, 15))
        settings_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        settings_card.columnconfigure(0, weight=1)
        self.ttk.Label(
            settings_card,
            text=self.tr("settings_title"),
            style="Section.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(2, 10))
        self.output_var = self.tk.StringVar(value=default_dest_folder())
        output_row = self.ttk.Frame(settings_card, style="Card.TFrame")
        output_row.grid(row=1, column=0, sticky="ew")
        output_row.columnconfigure(0, weight=1)
        self.output_entry = self.ttk.Entry(
            output_row,
            textvariable=self.output_var,
            style="App.TEntry",
            state="readonly",
            cursor="arrow",
        )
        self.output_entry.grid(row=0, column=0, sticky="ew")
        self.output_browse_button = self.ttk.Button(
            output_row,
            text=self.tr("choose_folder"),
            style="SecondaryStrong.TButton",
            command=self._choose_output_folder,
        )
        self.output_browse_button.grid(row=0, column=1, sticky="e", padx=(10, 0))

        self.spectrogram_var = self.tk.BooleanVar(value=True)
        self.json_var = self.tk.BooleanVar(value=True)
        self.browser_cookies_var = self.tk.BooleanVar(value=True)
        self.spectrogram_check = StyledCheck(
            self.tk,
            settings_card,
            text=self.tr("spectrogram_option"),
            variable=self.spectrogram_var,
            font=(self.font_family, 10),
        )
        self.spectrogram_check.grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.json_check = StyledCheck(
            self.tk,
            settings_card,
            text=self.tr("json_option"),
            variable=self.json_var,
            font=(self.font_family, 10),
        )
        self.json_check.grid(row=3, column=0, sticky="w", pady=(6, 0))
        self.browser_check = StyledCheck(
            self.tk,
            settings_card,
            text=self.tr("browser_option"),
            variable=self.browser_cookies_var,
            font=(self.font_family, 10),
        )
        self.browser_check.grid(row=4, column=0, sticky="w", pady=(6, 0))

        action_row = self.ttk.Frame(outer, style="App.TFrame")
        action_row.grid(row=3, column=0, sticky="ew", pady=(2, 10))
        action_row.columnconfigure(0, weight=1)
        status_area = self.tk.Frame(action_row, background=BACKGROUND)
        status_area.grid(row=0, column=0, sticky="w")
        status_area.columnconfigure(1, weight=1)
        self.loading_spinner = LoadingSpinner(self.tk, status_area)
        self.loading_spinner.grid(row=0, column=0, sticky="w", padx=(0, 9))
        self.status_var = self.tk.StringVar(value=self.tr("status_need_link"))
        self.status_label = self.ttk.Label(
            status_area,
            textvariable=self.status_var,
            style="Status.TLabel",
        )
        self.status_label.grid(row=0, column=1, sticky="w", padx=(0, 12))
        self.start_button = self.ttk.Button(
            action_row,
            text=self.tr("start"),
            style="Accent.TButton",
            command=self._start_comparison,
        )
        self.start_button.grid(row=0, column=1, sticky="e")

        result_card = self.ttk.Frame(outer, style="CardAlt.TFrame", padding=14)
        result_card.grid(row=4, column=0, sticky="nsew")
        result_card.columnconfigure(0, weight=1)
        result_card.rowconfigure(5, weight=1)
        result_header = self.ttk.Frame(result_card, style="CardAlt.TFrame")
        result_header.grid(row=0, column=0, columnspan=2, sticky="ew")
        result_header.columnconfigure(0, weight=1)
        self.result_title_var = self.tk.StringVar(value=self.tr("result_placeholder_title"))
        self.result_title_label = self.ttk.Label(
            result_header,
            textvariable=self.result_title_var,
            style="ResultTitle.TLabel",
        )
        self.result_title_label.grid(row=0, column=0, sticky="w")
        self.log_toggle_button = self.ttk.Button(
            result_header,
            text=self.tr("show_log"),
            style="Secondary.TButton",
            command=self._toggle_log,
        )
        self.log_toggle_button.grid(row=0, column=1, sticky="e")

        self.result_text_var = self.tk.StringVar(value=self.tr("result_placeholder"))
        self.ttk.Label(
            result_card,
            textvariable=self.result_text_var,
            style="Result.TLabel",
            justify="left",
            wraplength=830,
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(7, 8))

        self.result_path_var = self.tk.StringVar(value="")
        self.ttk.Label(
            result_card,
            textvariable=self.result_path_var,
            style="Result.TLabel",
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 10))

        result_actions = self.ttk.Frame(result_card, style="CardAlt.TFrame")
        result_actions.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.analysis_button = self.ttk.Button(
            result_actions,
            text=self.tr("view_analysis"),
            style="SecondaryStrong.TButton",
            command=self._show_analysis_screen,
        )
        self.analysis_button.grid(row=0, column=0, sticky="w", padx=(0, 9))
        self.open_file_button = self.ttk.Button(
            result_actions,
            text=self.tr("open_audio"),
            style="SecondaryStrong.TButton",
            command=self._open_winner,
        )
        self.open_file_button.grid(row=0, column=1, sticky="w", padx=(0, 9))
        self.open_folder_button = self.ttk.Button(
            result_actions,
            text=self.tr("open_folder"),
            style="SecondaryStrong.TButton",
            command=self._open_output_folder,
        )
        self.open_folder_button.grid(row=0, column=2, sticky="w", padx=(0, 9))
        self.open_json_button = self.ttk.Button(
            result_actions,
            text=self.tr("open_json"),
            style="SecondaryStrong.TButton",
            command=self._open_json_report,
        )
        self.open_json_button.grid(row=0, column=3, sticky="w")

        self.log_text = self.tk.Text(
            result_card,
            height=7,
            wrap="word",
            background="#08121e",
            foreground="#bed0df",
            selectbackground="#265370",
            highlightbackground=BORDER,
            highlightthickness=1,
            borderwidth=0,
            padx=10,
            pady=9,
            font=(self.mono_family, 10),
            state="disabled",
        )
        self.log_text.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(11, 0))
        self.log_text.grid_remove()

        footer = self.tk.Frame(outer, background=BACKGROUND)
        footer.grid(row=5, column=0, sticky="e", pady=(8, 0))
        footer_link = self.tk.Label(
            footer,
            text="by emmzde  ·  github.com/emmzde",
            background=BACKGROUND,
            foreground="#718da3",
            font=(self.font_family, 9, "underline"),
            cursor="hand2",
        )
        footer_link.pack()
        footer_link.bind("<Button-1>", lambda _event: self._open_path(GITHUB_URL))
        footer_link.bind("<Enter>", lambda _event: footer_link.configure(foreground=ACCENT_ACTIVE))
        footer_link.bind("<Leave>", lambda _event: footer_link.configure(foreground="#718da3"))

        self._controls = [
            self.source_text,
            self.output_entry,
            self.output_browse_button,
            self.spectrogram_check,
            self.json_check,
            self.browser_check,
        ]
        self._sync_button_states()

    def _build_logo(self, parent: Any) -> None:
        png_path = resource_path("assets/trackjudge-icon-v2.png")
        try:
            image = self.tk.PhotoImage(file=str(png_path))
            factor = max(1, round(max(image.width(), image.height()) / 60))
            self.logo_image = image.subsample(factor, factor)
            self.tk.Label(
                parent,
                image=self.logo_image,
                background=BACKGROUND,
                borderwidth=0,
            ).grid(row=0, column=0, sticky="w")
        except Exception:
            self.logo_image = None
            self.tk.Label(
                parent,
                text="♫",
                background=BACKGROUND,
                foreground=ACCENT,
                font=(self.heading_family, 35, "bold"),
            ).grid(row=0, column=0, sticky="w")

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
        width = min(980, self.root.winfo_screenwidth())
        height = min(940, self.root.winfo_screenheight())
        left, top, right, bottom = self._work_area()
        x = max(left, left + (right - left - width) // 2)
        y = max(top, top + (bottom - top - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

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
            self.source_placeholder.place(x=13, y=10)

    def _sync_sources(self) -> None:
        self._sync_placeholder()
        sources = self._current_sources()
        self.source_count_var.set(f"{len(sources)} / {MAX_URLS}")
        if self.running:
            self._sync_button_states()
            return
        if len(sources) > MAX_URLS:
            self.source_error_var.set(
                self.tr("too_many_links", count=len(sources), maximum=MAX_URLS)
            )
            self.source_hint.configure(style="Error.TLabel")
            self.status_var.set(self.tr("status_too_many"))
        elif sources:
            self.source_error_var.set(self.tr("sources_recognized"))
            self.source_hint.configure(style="Muted.TLabel")
            self.status_var.set(self.tr("status_ready"))
        else:
            self.source_error_var.set(self.tr("source_only_links"))
            self.source_hint.configure(style="Muted.TLabel")
            self.status_var.set(self.tr("status_need_link"))
        self._sync_button_states()

    def _sync_button_states(self) -> None:
        if self.running:
            self.start_button.configure(state="disabled")
            self.analysis_button.configure(state="disabled")
            self.open_file_button.configure(state="disabled")
            self.open_folder_button.configure(state="disabled")
            self.open_json_button.configure(state="disabled")
            return
        sources = self._current_sources() if hasattr(self, "source_text") else []
        valid = 0 < len(sources) <= MAX_URLS
        self.start_button.configure(state="normal" if valid else "disabled")
        self.analysis_button.configure(state="normal" if self.last_payload else "disabled")
        self.open_file_button.configure(state="normal" if self.last_winner_file else "disabled")
        self.open_folder_button.configure(state="normal" if self.last_output_folder else "disabled")
        self.open_json_button.configure(state="normal" if self.last_report_path else "disabled")

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
        self.result_title_var.set(title)
        self.result_title_label.configure(style="ResultError.TLabel")
        self.result_text_var.set(message)
        self.result_path_var.set("")
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
        self.result_title_label.configure(style="ResultTitle.TLabel")
        self.result_title_var.set(self.tr("running_title"))
        self.result_text_var.set(self.tr("running_text"))
        self.result_path_var.set("")
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
            self.status_var.set("")
            self._show_success_notification(winner)
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
        self.result_title_label.configure(style="ResultTitle.TLabel")
        self.result_title_var.set(self.tr("winner"))
        self.result_text_var.set(f"{name}\n{summary}")
        self.result_path_var.set(shorten_path(self.last_winner_file))

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
        self._dismiss_notification()
        overlay = self.tk.Frame(self.content_host, background="#050b12")
        overlay.place(x=0, y=0, relwidth=1, relheight=1)
        self.notification_overlay = overlay

        card = self.tk.Frame(
            overlay,
            background=CARD,
            highlightbackground="#31546d",
            highlightthickness=1,
            width=720,
            height=410,
        )
        card.place(relx=0.5, rely=0.5, anchor="center")
        card.grid_propagate(False)
        card.columnconfigure(0, weight=1)

        self.tk.Label(
            card,
            text="✓",
            background="#123b32",
            foreground=GREEN,
            width=3,
            height=1,
            font=(self.heading_family, 24, "bold"),
        ).grid(row=0, column=0, pady=(32, 15))
        self.tk.Label(
            card,
            text=self.tr("completed"),
            background=CARD,
            foreground=TEXT,
            font=(self.heading_family, 22, "bold"),
        ).grid(row=1, column=0)

        name = winner.get("file_name") or Path(self.last_winner_file or "").name
        score = float(winner.get("score", 0.0))
        quality = self._localized_quality(score)
        self.tk.Label(
            card,
            text=f"{name}\n{score:.1f}/100  •  {quality}",
            background=CARD,
            foreground=MUTED,
            justify="center",
            wraplength=620,
            font=(self.font_family, 11),
        ).grid(row=2, column=0, padx=35, pady=(12, 7))
        self.tk.Label(
            card,
            text=shorten_path(self.last_winner_file, 78),
            background=CARD,
            foreground="#718da3",
            font=(self.mono_family, 9),
        ).grid(row=3, column=0, padx=35, pady=(0, 20))

        actions = self.ttk.Frame(card, style="Card.TFrame")
        actions.grid(row=4, column=0)
        self.ttk.Button(
            actions,
            text=self.tr("view_analysis"),
            style="Accent.TButton",
            command=self._show_analysis_screen,
        ).grid(row=0, column=0, padx=(0, 9))
        self.ttk.Button(
            actions,
            text=self.tr("open_audio"),
            style="SecondaryStrong.TButton",
            command=self._open_winner,
        ).grid(row=0, column=1)
        self.ttk.Button(
            card,
            text=self.tr("return_form"),
            style="Secondary.TButton",
            command=self._dismiss_notification,
        ).grid(row=5, column=0, pady=(14, 24))

    def _dismiss_notification(self) -> None:
        if self.notification_overlay is not None:
            with suppress(Exception):
                self.notification_overlay.destroy()
            self.notification_overlay = None

    def _show_analysis_screen(self) -> None:
        if not self.last_payload:
            return
        self._dismiss_notification()
        self._close_analysis_screen()
        self._analysis_images = []

        screen = self.tk.Frame(self.content_host, background=BACKGROUND)
        screen.place(x=0, y=0, relwidth=1, relheight=1)
        self.analysis_overlay = screen
        screen.columnconfigure(0, weight=1)
        screen.rowconfigure(1, weight=1)

        header = self.tk.Frame(screen, background=BACKGROUND)
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 12))
        header.columnconfigure(1, weight=1)
        self.ttk.Button(
            header,
            text=self.tr("back"),
            style="SecondaryStrong.TButton",
            command=self._close_analysis_screen,
        ).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 16))
        self.tk.Label(
            header,
            text=self.tr("analysis_title"),
            background=BACKGROUND,
            foreground=TEXT,
            font=(self.heading_family, 20, "bold"),
        ).grid(row=0, column=1, sticky="w")
        self.tk.Label(
            header,
            text=self.tr("analysis_subtitle"),
            background=BACKGROUND,
            foreground=MUTED,
            font=(self.font_family, 10),
        ).grid(row=1, column=1, sticky="w", pady=(2, 0))
        self.ttk.Button(
            header,
            text=self.tr("open_folder"),
            style="SecondaryStrong.TButton",
            command=self._open_output_folder,
        ).grid(row=0, column=2, rowspan=2, sticky="e")

        canvas_frame = self.tk.Frame(screen, background=BACKGROUND)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=(24, 10), pady=(0, 18))
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)
        canvas = self.tk.Canvas(
            canvas_frame,
            background=BACKGROUND,
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = self.ttk.Scrollbar(
            canvas_frame,
            orient="vertical",
            command=canvas.yview,
            style="Analysis.Vertical.TScrollbar",
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(8, 0))

        content = self.tk.Frame(canvas, background=BACKGROUND)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(content_window, width=event.width),
        )
        self.root.bind_all(
            "<MouseWheel>",
            lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"),
        )

        candidates = self.last_payload.get("candidates", [])
        for candidate in candidates:
            self._add_candidate_card(content, candidate)
        for failure in self.last_payload.get("failures", []):
            self._add_failure_card(content, failure)

        if not candidates:
            self.tk.Label(
                content,
                text=self.tr("no_candidates"),
                background=BACKGROUND,
                foreground=MUTED,
                font=(self.font_family, 12),
            ).pack(fill="x", padx=4, pady=30)
        self.root.after_idle(lambda: canvas.yview_moveto(0))

    def _add_candidate_card(self, parent: Any, candidate: dict[str, Any]) -> None:
        is_winner = int(candidate.get("rank", 0)) == 1
        score = float(candidate.get("score", 0.0))
        score_color = GREEN if score >= 70 else "#f2b866" if score >= 45 else RED
        card = self.tk.Frame(
            parent,
            background=CARD,
            highlightbackground=ACCENT if is_winner else BORDER,
            highlightthickness=2 if is_winner else 1,
        )
        card.pack(fill="x", padx=4, pady=(0, 12))
        card.columnconfigure(0, weight=1)

        top = self.tk.Frame(card, background=CARD)
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 8))
        top.columnconfigure(0, weight=1)
        name = str(candidate.get("file_name") or self.tr("untitled"))
        badge = self.tr("winner_badge") if is_winner else ""
        self.tk.Label(
            top,
            text=f"#{candidate.get('rank', '?')}  {name}{badge}",
            background=CARD,
            foreground=ACCENT_ACTIVE if is_winner else TEXT,
            anchor="w",
            justify="left",
            wraplength=720,
            font=(self.heading_family, 13, "bold"),
        ).grid(row=0, column=0, sticky="w")
        self.tk.Label(
            top,
            text=f"{score:.1f}/100",
            background=CARD,
            foreground=score_color,
            font=(self.heading_family, 18, "bold"),
        ).grid(row=0, column=1, sticky="e", padx=(16, 0))
        self.tk.Label(
            top,
            text=shorten_path(str(candidate.get("source", "")), 105),
            background=CARD,
            foreground="#718da3",
            anchor="w",
            font=(self.mono_family, 9),
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))

        metrics = self.tk.Frame(card, background=CARD_ALT)
        metrics.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
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
            cell = self.tk.Frame(metrics, background=CARD_ALT)
            cell.grid(row=0, column=index, sticky="ew", padx=12, pady=10)
            self.tk.Label(
                cell,
                text=label,
                background=CARD_ALT,
                foreground="#7690a5",
                font=(self.font_family, 9),
            ).pack(anchor="w")
            self.tk.Label(
                cell,
                text=value,
                background=CARD_ALT,
                foreground=TEXT,
                font=(self.heading_family, 10, "bold"),
            ).pack(anchor="w", pady=(2, 0))

        self.tk.Label(
            card,
            text=candidate_explanation(candidate, self.language),
            background=CARD,
            foreground=TEXT,
            justify="left",
            anchor="w",
            wraplength=860,
            font=(self.font_family, 10),
        ).grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))

        spectrogram_path = candidate.get("saved_spectrogram")
        if spectrogram_path and Path(spectrogram_path).is_file():
            try:
                original = self.tk.PhotoImage(file=str(spectrogram_path))
                factor = max(1, math.ceil(original.width() / 820))
                shown = original.subsample(factor, factor)
                self._analysis_images.extend([original, shown])
                self.tk.Label(
                    card,
                    image=shown,
                    background=CARD,
                    borderwidth=0,
                ).grid(row=3, column=0, padx=18, pady=(0, 10))
                spectrogram_actions = self.ttk.Frame(card, style="Card.TFrame")
                spectrogram_actions.grid(row=4, column=0, sticky="w", padx=18, pady=(0, 16))
                self.ttk.Button(
                    spectrogram_actions,
                    text=self.tr("open_spectrogram"),
                    style="SecondaryStrong.TButton",
                    command=lambda path=str(spectrogram_path): self._open_path(path),
                ).grid(row=0, column=0, sticky="w", padx=(0, 9))
                save_button = self.ttk.Button(
                    spectrogram_actions,
                    text=self.tr("save_spectrogram"),
                    style="SecondaryStrong.TButton",
                )
                save_button.configure(
                    command=lambda path=str(spectrogram_path), button=save_button: (
                        self._save_spectrogram_copy(path, button)
                    )
                )
                save_button.grid(row=0, column=1, sticky="w")
            except self.tk.TclError:
                self._add_missing_spectrogram_label(card, row=3)
        else:
            self._add_missing_spectrogram_label(card, row=3)

    def _add_missing_spectrogram_label(self, card: Any, row: int) -> None:
        self.tk.Label(
            card,
            text=self.tr("spectrogram_missing"),
            background=CARD,
            foreground=MUTED,
            font=(self.font_family, 10),
        ).grid(row=row, column=0, sticky="w", padx=18, pady=(0, 16))

    def _add_failure_card(self, parent: Any, failure: dict[str, Any]) -> None:
        card = self.tk.Frame(
            parent,
            background="#291820",
            highlightbackground="#6b3340",
            highlightthickness=1,
        )
        card.pack(fill="x", padx=4, pady=(0, 12))
        self.tk.Label(
            card,
            text=self.tr("source_failed"),
            background="#291820",
            foreground=RED,
            font=(self.heading_family, 12, "bold"),
        ).pack(anchor="w", padx=18, pady=(14, 5))
        self.tk.Label(
            card,
            text=str(failure.get("url", "")),
            background="#291820",
            foreground=TEXT,
            font=(self.mono_family, 9),
            wraplength=850,
            justify="left",
        ).pack(anchor="w", padx=18)
        self.tk.Label(
            card,
            text=str(failure.get("reason", self.tr("unknown_error"))),
            background="#291820",
            foreground="#e3a8b0",
            font=(self.font_family, 10),
            wraplength=850,
            justify="left",
        ).pack(anchor="w", padx=18, pady=(6, 14))

    def _close_analysis_screen(self) -> None:
        if self.analysis_overlay is not None:
            with suppress(Exception):
                self.root.unbind_all("<MouseWheel>")
                self.analysis_overlay.destroy()
            self.analysis_overlay = None
            self._analysis_images = []

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
    paste_smoke_test = arguments == ["--gui-paste-smoke-test"]
    initial_sources = (
        []
        if gui_smoke_test or paste_smoke_test
        else [value for value in arguments if value.strip()]
    )
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
        return window.run()
    except Exception as exc:
        _show_startup_error(f"Не удалось открыть TrackJudge: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
