from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Any

from rich import box
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from . import __version__, console, updater
from .console import configure_console as configure_console
from .console import log
from .dsp import MIN_HARD_DURATION, MIN_RELIABLE_DURATION
from .dsp import analyze_file as analyze_file
from .dsp import apply_duration_cap as apply_duration_cap
from .dsp import safe_correlation as safe_correlation
from .media import (
    ANALYSIS_MAX_SECONDS,
    cleanup_files,
    download_audio,
    get_audio_details,
    prepare_ytdlp,
    save_candidate,
    save_spectrogram,
    unique_dest_path,
)
from .media import (
    ANALYSIS_SAMPLE_RATE as ANALYSIS_SAMPLE_RATE,
)
from .media import (
    _tool_filename as _tool_filename,
)
from .media import (
    check_external_tools as check_external_tools,
)
from .media import (
    convert_to_wav as convert_to_wav,
)
from .media import (
    find_external_tool as find_external_tool,
)
from .media import (
    find_packaged_tool as find_packaged_tool,
)
from .media import (
    run_command as run_command,
)
from .reporting import APP_NAME, build_verdict, print_header, print_report
from .reporting import quality_label as quality_label
from .reporting import save_json_report as save_json_report
from .spectrum import HAS_MPL
from .spectrum import render_spectrogram as render_spectrogram


def default_dest_folder() -> str:
    downloads = Path.home() / "Downloads"
    base = downloads if downloads.is_dir() else Path.cwd()
    return str(base / APP_NAME)


DEFAULT_DEST_FOLDER = default_dest_folder()
DEFAULT_COOKIES = None  # --cookies <путь>, по умолчанию не используется
DEFAULT_PAUSE = 0  # yt-dlp сам управляет короткими сетевыми повторами
MAX_URLS = 5
MAX_WORKERS = 2


def ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        with suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trackjudge",
        description=(
            "Сравнивает 1–5 источников одного трека, анализирует верхний спектр "
            "и сохраняет лучший аудиофайл."
        ),
        epilog=(
            "Пример:\n"
            "  trackjudge URL_1 URL_2 URL_3 --spectrogram --json-report\n\n"
            "Можно передавать как URL, так и пути к локальным аудиофайлам."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("urls", nargs="*", metavar="SOURCE", help="URL или локальный аудиофайл.")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Запустить пошаговый интерактивный режим.",
    )
    parser.add_argument(
        "-o",
        "--output",
        "--dest",
        dest="dest",
        default=DEFAULT_DEST_FOLDER,
        help=f"Папка результата (по умолчанию: {DEFAULT_DEST_FOLDER}).",
    )
    parser.add_argument(
        "--cookies",
        default=DEFAULT_COOKIES,
        help="Путь к файлу cookies для yt-dlp. По умолчанию: не используется.",
    )
    parser.add_argument(
        "--browser-cookies",
        choices=(
            "off",
            "auto",
            "brave",
            "chrome",
            "chromium",
            "edge",
            "firefox",
            "opera",
            "vivaldi",
        ),
        default="off",
        help=(
            "Взять cookies из браузера, если YouTube потребует подтверждение входа. "
            "В режиме auto используется установленный браузер. По умолчанию: off."
        ),
    )
    parser.add_argument(
        "--pause",
        type=int,
        default=DEFAULT_PAUSE,
        help=f"Пауза между загрузками в секундах. По умолчанию: {DEFAULT_PAUSE}.",
    )
    parser.add_argument(
        "--remote-components",
        default=None,
        help="Значение флага --remote-components для yt-dlp (напр. ejs:github). По умолчанию: не передаётся.",
    )
    parser.add_argument(
        "--min-reliable-duration",
        type=float,
        default=MIN_RELIABLE_DURATION,
        help=(
            "Минимальная длительность в секундах для полностью надежного спектрального "
            f"анализа. По умолчанию: {MIN_RELIABLE_DURATION:.0f}."
        ),
    )
    parser.add_argument(
        "--spectrogram",
        action="store_true",
        help="Сохранить спектрограмму победителя.",
    )
    parser.add_argument(
        "--keep-loser-spectrograms",
        action="store_true",
        help="Также сохранить спектрограммы проигравших.",
    )
    parser.add_argument(
        "--spectrogram-dir",
        default=None,
        metavar="PATH",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--json-report",
        nargs="?",
        const="auto",
        metavar="PATH",
        help="Сохранить машинно-читаемый JSON-отчёт; путь можно не указывать.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Отключить цветной вывод.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Число параллельных анализов (по умолчанию: {MAX_WORKERS}).",
    )
    return parser


def _clean_source_input(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def run_interactive_wizard(args: argparse.Namespace) -> bool:
    console._CONSOLE.print(
        Panel(
            Text(
                "Вставьте ссылки на разные источники одного трека.\n"
                "Также можно перетащить локальный аудиофайл в это окно."
            ),
            title="Быстрый старт",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )

    sources = list(args.urls)
    while len(sources) < MAX_URLS:
        suffix = " (Enter — закончить)" if sources else ""
        prompt = Text(f"Источник {len(sources) + 1}{suffix}: ", style="bold cyan")
        source = _clean_source_input(console._CONSOLE.input(prompt))
        if not source:
            break
        sources.append(source)

    if not sources:
        log("Не добавлено ни одного источника.")
        return False

    args.urls = sources
    output = _clean_source_input(
        Prompt.ask(
            "Папка результата",
            default=args.dest,
            console=console._CONSOLE,
        )
    )
    args.dest = os.path.abspath(os.path.expandvars(os.path.expanduser(output.strip())))
    args.spectrogram = Confirm.ask(
        "Сохранить спектрограмму победителя?",
        default=HAS_MPL,
        console=console._CONSOLE,
    )
    save_report = Confirm.ask(
        "Сохранить подробный JSON-отчёт?",
        default=False,
        console=console._CONSOLE,
    )
    args.json_report = "auto" if save_report else None

    summary = Table(box=box.SIMPLE, show_header=False)
    summary.add_column(style="bold cyan")
    summary.add_column(overflow="fold")
    summary.add_row("Источников", str(len(sources)))
    summary.add_row("Результат", Text(args.dest))
    summary.add_row("Спектрограмма", "да" if args.spectrogram else "нет")
    summary.add_row("JSON", "да" if save_report else "нет")
    console._CONSOLE.print(summary)
    return Confirm.ask("Начать сравнение?", default=True, console=console._CONSOLE)


def _run(args: argparse.Namespace, parser: argparse.ArgumentParser, preview=None) -> int:
    urls = args.urls
    if not urls:
        parser.print_help()
        return 2
    if len(urls) > MAX_URLS:
        log(f"Ожидается 1–{MAX_URLS} источников одного трека. Получено: {len(urls)}.")
        return 2
    if (
        not math.isfinite(args.min_reliable_duration)
        or args.min_reliable_duration < MIN_HARD_DURATION
    ):
        log(f"--min-reliable-duration должен быть не меньше {MIN_HARD_DURATION:.0f} с.")
        return 2
    if args.pause < 0:
        log("--pause не может быть отрицательным.")
        return 2
    if args.workers < 1:
        log("--workers должен быть не меньше 1.")
        return 2
    if args.cookies and not os.path.isfile(args.cookies):
        log(f"Файл cookies не найден: {args.cookies}")
        return 2

    require_downloader = any(not os.path.isfile(source) for source in urls)
    ytdlp_update: updater.UpdateResult | None = None
    if require_downloader:
        try:
            ytdlp_update = prepare_ytdlp()
        except Exception as exc:
            log(f"Автообновление yt-dlp пропущено: {exc}")
    missing_tools = check_external_tools(require_downloader=require_downloader)
    if missing_tools:
        log("Не найдены внешние зависимости: " + ", ".join(missing_tools))
        return 2

    make_spectrogram = args.spectrogram or args.keep_loser_spectrograms
    if make_spectrogram and not HAS_MPL:
        log("matplotlib не установлен — спектрограммы строиться не будут (pip install matplotlib).")

    dest_folder = os.path.abspath(args.dest)
    try:
        os.makedirs(dest_folder, exist_ok=True)
    except OSError as exc:
        log(f"Не удалось создать папку результата: {exc}")
        return 2
    print_header(len(urls), dest_folder)

    cookies_path = args.cookies
    browser_cookies = getattr(args, "browser_cookies", "off")
    remote_components = args.remote_components
    pause_seconds = args.pause

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    report_failed = False

    with tempfile.TemporaryDirectory(prefix="audio_candidates_") as work_dir:
        # Скачивание последовательное (YouTube блокирует параллельные запросы).
        downloaded: list[tuple[str, str, dict[str, str]]] = []
        failed_downloads: list[tuple[int, str, str]] = []
        preferred_browser: str | None = None

        def attempt_download(
            index: int,
            url: str,
            *,
            reset_folder: bool = False,
        ) -> tuple[str | None, dict[str, str]]:
            nonlocal preferred_browser
            candidate_dir = os.path.join(work_dir, f"candidate_{index}")
            if reset_folder:
                shutil.rmtree(candidate_dir, ignore_errors=True)
            if os.path.isfile(url):
                log(f"Локальный файл: {url}")
                return os.path.abspath(url), {}
            try:
                orig_file, metadata = download_audio(
                    url,
                    candidate_dir,
                    cookies_path,
                    remote_components,
                    browser_cookies,
                    preferred_browser,
                )
            except OSError as exc:
                return None, {"_error": str(exc)}
            used_browser = metadata.pop("_browser_cookies_used", None)
            if used_browser:
                preferred_browser = used_browser
            return orig_file, metadata

        def retry_downloads(
            pending: list[tuple[int, str, str]],
        ) -> tuple[list[tuple[int, str, str]], int]:
            remaining: list[tuple[int, str, str]] = []
            success_count = 0
            for index, url, _previous_reason in pending:
                orig_file, metadata = attempt_download(index, url, reset_folder=True)
                if orig_file and os.path.exists(orig_file):
                    downloaded.append((url, orig_file, metadata))
                    success_count += 1
                else:
                    reason = metadata.pop("_error", "скачивание не удалось")
                    remaining.append((index, url, reason))
            return remaining, success_count

        for idx, url in enumerate(urls, 1):
            if idx > 1 and pause_seconds > 0:
                log(f"Пауза {pause_seconds} с...")
                time.sleep(pause_seconds)
            # yt-dlp выполняет короткие сетевые повторы сам. Повтор всей команды
            # не помогает при блокировке YouTube и только многократно растягивает запуск.
            orig_file, metadata = attempt_download(idx, url)
            if orig_file and os.path.exists(orig_file):
                downloaded.append((url, orig_file, metadata))
            else:
                reason = metadata.pop("_error", "скачивание не удалось")
                failed_downloads.append((idx, url, reason))

        current_successes = sum(not os.path.isfile(url) for url, _, _ in downloaded)
        if current_successes and ytdlp_update is not None:
            updater.mark_ytdlp_working()

        if failed_downloads and ytdlp_update is not None and not ytdlp_update.updated:
            try:
                forced_update = prepare_ytdlp(force=True)
            except Exception as exc:
                log(f"Повторная проверка yt-dlp не удалась: {exc}")
                forced_update = None
            if forced_update is not None:
                ytdlp_update = forced_update
            if forced_update is not None and forced_update.updated:
                log("Повторяем неудачные ссылки после обновления yt-dlp.")
                current_successes = 0
                failed_downloads, current_successes = retry_downloads(failed_downloads)
                if current_successes:
                    updater.mark_ytdlp_working()

        if (
            failed_downloads
            and ytdlp_update is not None
            and ytdlp_update.pending_validation
            and current_successes == 0
        ):
            rollback = updater.rollback_ytdlp(
                "Новая версия не смогла скачать ни один из проверенных источников."
            )
            if rollback is not None:
                log(rollback.message)
                log("Повторяем неудачные ссылки с предыдущей рабочей версией.")
                failed_downloads, rollback_successes = retry_downloads(failed_downloads)
                if rollback_successes:
                    updater.mark_ytdlp_working()
                else:
                    restored_candidate = updater.restore_ytdlp_candidate(
                        "Предыдущая версия не смогла скачать эти же источники."
                    )
                    if restored_candidate is not None:
                        log(restored_candidate.message)

        failures.extend({"url": url, "reason": reason} for _index, url, reason in failed_downloads)

        # Анализ параллельный (CPU-intensive, не зависит от сети).
        workers = max(1, min(args.workers, len(downloaded)))

        def worker(
            item: tuple[str, str, dict[str, str]],
        ) -> tuple[str, dict[str, Any] | None, str | None]:
            url, orig_file, metadata = item
            scratch = Path(tempfile.mkdtemp(dir=work_dir))
            wav_file = None
            try:
                details = get_audio_details(orig_file)
                wav_file = convert_to_wav(
                    orig_file,
                    duration=details.get("duration", 0.0),
                    channels=details["channels"],
                    sample_rate=details["sample_rate"],
                    output_path=str(scratch / "analysis.wav"),
                )
                if not wav_file:
                    return url, None, "PCM-извлечение не удалось"

                spectro_path = None
                if make_spectrogram and HAS_MPL:
                    spectro_path = str(scratch / (Path(orig_file).name + ".spectrogram.png"))

                metrics = analyze_file(
                    wav_file,
                    spectro_path,
                    args.min_reliable_duration,
                    track_label=os.path.basename(orig_file),
                )
                if not metrics.get("valid"):
                    return (
                        url,
                        None,
                        "анализ не удался: "
                        + ("; ".join(metrics.get("warnings", [])) or "нет данных"),
                    )

                analysis_duration = metrics["duration"]
                source_duration = details["duration"] or analysis_duration
                metrics.update(
                    {
                        "url": url,
                        "codec": details["codec"],
                        "bitrate": details["bitrate"],
                        "sample_rate": details["sample_rate"],
                        "channels": details["channels"],
                        "orig_file": orig_file,
                        "saved_file": None,
                        "saved_spectrogram": None,
                        "metadata": metadata,
                        "source_duration": source_duration,
                        "analysis_duration": analysis_duration,
                        "duration": source_duration,
                    }
                )
                if (
                    details["duration"]
                    and abs(details["duration"] - analysis_duration) > 1.0
                    and details["duration"] <= ANALYSIS_MAX_SECONDS + 1.0
                ):
                    metrics["warnings"].append(
                        f"длительность контейнера ({details['duration']:.2f} с) отличается от PCM "
                        f"({analysis_duration:.2f} с)"
                    )
                if preview is not None:
                    try:
                        preview(url, wav_file, analysis_duration)
                    except (OSError, ValueError) as exc:
                        metrics["warnings"].append(f"Предпрослушивание недоступно: {exc}")
                return url, metrics, None
            except Exception as exc:
                return url, None, str(exc)
            finally:
                cleanup_files([wav_file])

        with ThreadPoolExecutor(max_workers=workers) as executor:
            for url, result, failure in executor.map(worker, downloaded):
                if result is not None:
                    results.append(result)
                else:
                    failures.append({"url": url, "reason": failure or "неизвестная ошибка"})

        if not results:
            if failures:
                print_report([], failures)
            log("Ни один файл не был успешно обработан.")
            return 1

        # Сортировка: score -> живой срез -> достоверность -> битрейт.
        results.sort(
            key=lambda item: (item["score"], item["cutoff"], item["authenticity"], item["bitrate"]),
            reverse=True,
        )
        winner = results[0]
        ties = [
            item
            for item in results
            if item is not winner and abs(winner["score"] - item["score"]) < 0.6
        ]

        try:
            saved_path = save_candidate(winner, dest_folder)
        except Exception as exc:
            log(f"Не удалось сохранить победителя: {exc}")
            return 1

        spectrogram_folder = os.path.abspath(args.spectrogram_dir or dest_folder)
        if make_spectrogram and HAS_MPL:
            try:
                os.makedirs(spectrogram_folder, exist_ok=True)
            except OSError as exc:
                log(f"Не удалось создать папку спектрограмм: {exc}")

        saved_spectrogram = None
        if make_spectrogram and HAS_MPL:
            try:
                saved_spectrogram = save_spectrogram(winner, spectrogram_folder)
            except Exception as exc:
                log(f"Не удалось сохранить спектрограмму победителя: {exc}")

        if args.keep_loser_spectrograms:
            for item in results:
                if item is winner:
                    continue
                try:
                    saved_loser_spectrogram = save_spectrogram(item, spectrogram_folder)
                    if saved_loser_spectrogram:
                        log(f"Спектрограмма проигравшего: {saved_loser_spectrogram}")
                except Exception as exc:
                    log(f"Не удалось сохранить спектрограмму проигравшего: {exc}")

        print_report(results, failures)
        console._CONSOLE.print(
            Panel(
                Text(build_verdict(results, winner)),
                title="Вердикт",
                border_style="green",
                box=box.ROUNDED,
            )
        )

        summary_lines = [f"Аудио: {saved_path}"]
        if saved_spectrogram:
            summary_lines.append(f"Спектрограмма: {saved_spectrogram}")

        report_path = None
        if args.json_report:
            if args.json_report == "auto":
                report_path = unique_dest_path("trackjudge-report.json", dest_folder)
            else:
                report_path = os.path.abspath(args.json_report)
            try:
                report_path = save_json_report(report_path, results, failures)
                summary_lines.append(f"JSON-отчёт: {report_path}")
            except Exception as exc:
                log(f"Не удалось сохранить JSON-отчёт: {exc}")
                report_path = None
                report_failed = True

        if ties:
            summary_lines.append(
                f"Близкий результат: ещё {len(ties)} кандидат(ов) отличаются менее чем на 0.6 score."
            )
        console._CONSOLE.print(
            Panel(
                Text("\n".join(summary_lines)),
                title="Готово",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )

    return 1 if report_failed else 0


def run_analysis(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser | None = None,
    *,
    preview=None,
) -> int:
    """Run one configured comparison without invoking argument parsing."""
    return _run(args, parser or build_parser(), preview)


def main(argv: list[str] | None = None) -> int:
    ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_console(args.no_color)

    interactive_mode = bool(args.interactive or (not args.urls and sys.stdin.isatty()))
    if not interactive_mode:
        return run_analysis(args, parser)

    exit_code = 0
    try:
        if not run_interactive_wizard(args):
            log("Запуск отменён.")
            return 0
        exit_code = run_analysis(args, parser)
        return exit_code
    except KeyboardInterrupt:
        console._CONSOLE.print("\nОперация отменена.", style="yellow")
        exit_code = 130
        return exit_code
    except EOFError:
        console._CONSOLE.print("\nНе удалось прочитать интерактивный ввод.", style="red")
        exit_code = 2
        return exit_code
    finally:
        if sys.stdin.isatty():
            with suppress(KeyboardInterrupt, EOFError):
                console._CONSOLE.input(
                    Text("\nНажмите Enter, чтобы закрыть TrackJudge…", style="dim")
                )


if __name__ == "__main__":
    raise SystemExit(main())
