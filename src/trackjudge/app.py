from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Any

import numpy as np
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text
from scipy.io import wavfile
from scipy.signal import butter, sosfiltfilt, spectrogram

from . import __version__, updater
from .theme import FONTS, blend, build_theme_colors

# Matplotlib опционален: если не установлен, скрипт работает без спектрограмм.
try:
    import matplotlib

    matplotlib.use("Agg")  # без GUI, потокобезопасно через Figure API
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.figure import Figure
    from matplotlib.ticker import MultipleLocator

    HAS_MPL = True
except Exception:  # pragma: no cover
    HAS_MPL = False


APP_NAME = "TrackJudge"


def default_dest_folder() -> str:
    downloads = Path.home() / "Downloads"
    base = downloads if downloads.is_dir() else Path.cwd()
    return str(base / APP_NAME)


DEFAULT_DEST_FOLDER = default_dest_folder()
DEFAULT_COOKIES = None  # --cookies <путь>, по умолчанию не используется
DEFAULT_PAUSE = 0  # yt-dlp сам управляет короткими сетевыми повторами
MAX_URLS = 5
MIN_RELIABLE_DURATION = 20.0
MIN_HARD_DURATION = 5.0
EPS = 1e-20

# --- Параметры DSP ---------------------------------------------------------
STFT_NPERSEG = 4096  # частотное разрешение ~10.8 Гц @ 44.1 кГц
ANALYSIS_MAX_SECONDS = 300.0  # анализируем не более 5 минут (центр трека)
PRESENCE_DB = -55.0  # порог "энергия присутствует" относительно опоры (dB)
FAKE_GAP_HZ = 1500.0  # raw - effective больше этого => полка фейкового шума
MAX_WORKERS = 2
ANALYSIS_SAMPLE_RATE = 48000

# Карта баллов по эффективному срезу (Гц -> 0..100).
CUTOFF_LOW_HZ = 15000.0
CUTOFF_HIGH_HZ = 19500.0

_PRINT_LOCK = threading.Lock()
_CONSOLE = Console()


def log(msg: str) -> None:
    with _PRINT_LOCK:
        _CONSOLE.print(msg, markup=False)


def configure_console(
    no_color: bool = False,
    *,
    file: Any | None = None,
    width: int | None = None,
) -> None:
    global _CONSOLE
    options: dict[str, Any] = {"no_color": no_color}
    if file is not None:
        options.update(file=file, force_terminal=False)
    if width is not None:
        options["width"] = width
    _CONSOLE = Console(**options)


def print_header(candidate_count: int, destination: str) -> None:
    subtitle = (
        f"{candidate_count} candidate{'s' if candidate_count != 1 else ''}  •  "
        f"output: {destination}"
    )
    title = Text(APP_NAME, style="bold cyan")
    title.append("  spectral candidate selector", style="dim")
    _CONSOLE.print(
        Panel(
            Text.assemble(title, "\n", Text(subtitle, style="dim")),
            border_style="cyan",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


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
    _CONSOLE.print(
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
        source = _clean_source_input(_CONSOLE.input(prompt))
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
            console=_CONSOLE,
        )
    )
    args.dest = os.path.abspath(os.path.expandvars(os.path.expanduser(output.strip())))
    args.spectrogram = Confirm.ask(
        "Сохранить спектрограмму победителя?",
        default=HAS_MPL,
        console=_CONSOLE,
    )
    save_report = Confirm.ask(
        "Сохранить подробный JSON-отчёт?",
        default=False,
        console=_CONSOLE,
    )
    args.json_report = "auto" if save_report else None

    summary = Table(box=box.SIMPLE, show_header=False)
    summary.add_column(style="bold cyan")
    summary.add_column(overflow="fold")
    summary.add_row("Источников", str(len(sources)))
    summary.add_row("Результат", Text(args.dest))
    summary.add_row("Спектрограмма", "да" if args.spectrogram else "нет")
    summary.add_row("JSON", "да" if save_report else "нет")
    _CONSOLE.print(summary)
    return Confirm.ask("Начать сравнение?", default=True, console=_CONSOLE)


def _tool_filename(tool: str) -> str:
    return f"{tool}.exe" if sys.platform == "win32" else tool


def _packaged_tool_roots() -> list[Path]:
    roots: list[Path] = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent / "tools")
        bundle_root = getattr(sys, "_MEIPASS", None)
        if bundle_root:
            roots.append(Path(bundle_root) / "tools")
    else:
        roots.append(Path(__file__).resolve().parents[2] / "tools")
    return roots


def find_packaged_tool(tool: str) -> str | None:
    filename = _tool_filename(tool)
    for root in _packaged_tool_roots():
        candidate = root / filename
        if candidate.is_file():
            return str(candidate)
    return None


def find_external_tool(tool: str) -> str | None:
    filename = _tool_filename(tool)
    configured_root = os.environ.get("TRACKJUDGE_TOOL_DIR")
    if configured_root:
        configured = Path(configured_root) / filename
        if configured.is_file():
            return str(configured)

    if tool == "yt-dlp" and updater.auto_update_supported():
        managed = updater.managed_ytdlp_path()
        if managed.is_file():
            return str(managed)

    packaged = find_packaged_tool(tool)
    if packaged:
        return packaged
    return shutil.which(tool)


def prepare_ytdlp(force: bool = False) -> updater.UpdateResult | None:
    if not updater.auto_update_supported():
        return None
    packaged = find_packaged_tool("yt-dlp")
    if not packaged:
        return None
    result = updater.ensure_current_ytdlp(packaged, force=force)
    if result.message:
        log(result.message)
    return result


def external_tool(tool: str) -> str:
    resolved = find_external_tool(tool)
    if resolved is None:
        raise FileNotFoundError(f"Не найден внешний инструмент: {tool}")
    return resolved


def check_external_tools(require_downloader: bool = True) -> list[str]:
    tools = ["ffmpeg", "ffprobe"]
    if require_downloader:
        tools.insert(0, "yt-dlp")
    return [tool for tool in tools if find_external_tool(tool) is None]


def run_command(cmd: list[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    windows_options: dict[str, Any] = {}
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        windows_options = {
            "startupinfo": startupinfo,
            "creationflags": subprocess.CREATE_NO_WINDOW,
        }
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **windows_options,
    )


_BROWSER_LABELS = {
    "brave": "Brave",
    "chrome": "Google Chrome",
    "chromium": "Chromium",
    "edge": "Microsoft Edge",
    "firefox": "Firefox",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
}


def _windows_default_browser() -> str | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        key_path = (
            r"Software\Microsoft\Windows\Shell\Associations"
            r"\UrlAssociations\https\UserChoice"
        )
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            prog_id = str(winreg.QueryValueEx(key, "ProgId")[0]).lower()
    except OSError:
        return None

    if "firefox" in prog_id:
        return "firefox"
    if "brave" in prog_id:
        return "brave"
    if "vivaldi" in prog_id:
        return "vivaldi"
    if "opera" in prog_id:
        return "opera"
    if "chrome" in prog_id:
        return "chrome"
    if "edge" in prog_id:
        return "edge"
    return None


def detected_cookie_browsers() -> list[str]:
    """Return installed browsers in the order most likely to contain the active session."""
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", home))
    roaming = Path(os.environ.get("APPDATA", home))
    profile_roots = {
        "brave": local / "BraveSoftware" / "Brave-Browser" / "User Data",
        "chrome": local / "Google" / "Chrome" / "User Data",
        "chromium": local / "Chromium" / "User Data",
        "edge": local / "Microsoft" / "Edge" / "User Data",
        "firefox": roaming / "Mozilla" / "Firefox" / "Profiles",
        "opera": roaming / "Opera Software" / "Opera Stable",
        "vivaldi": local / "Vivaldi" / "User Data",
    }
    installed = [name for name, root in profile_roots.items() if root.exists()]
    preferred = _windows_default_browser()
    if preferred in installed:
        installed.remove(preferred)
        installed.insert(0, preferred)

    # Firefox usually allows reliable cookie extraction while Chromium is running.
    if "firefox" in installed and preferred != "firefox":
        installed.remove("firefox")
        installed.insert(1 if preferred in installed else 0, "firefox")
    return installed


def browser_cookie_candidates(mode: str | None) -> list[str]:
    if not mode or mode == "off":
        return []
    if mode != "auto":
        return [mode]
    return detected_cookie_browsers()[:3]


def _is_youtube_auth_block(stderr: str) -> bool:
    lowered = stderr.lower()
    return (
        "sign in to confirm" in lowered
        or "confirm you're not a bot" in lowered
        or "confirm you’re not a bot" in lowered
    )


def _summarize_downloader_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    error_lines = [line for line in lines if line.upper().startswith("ERROR:")]
    summary = error_lines[-1] if error_lines else (lines[-1] if lines else "неизвестная ошибка")
    if "Sign in to confirm" in summary:
        return "YouTube запросил подтверждение входа"
    if len(summary) > 360:
        return summary[:357] + "..."
    return summary


def _run_downloader(cmd: list[str], browser: str | None = None) -> subprocess.CompletedProcess[str]:
    command = list(cmd)
    if browser:
        command[-1:-1] = ["--cookies-from-browser", browser]
    return run_command(command)


def _is_youtube_url(url: str) -> bool:
    lowered = url.lower()
    return "youtube.com/" in lowered or "youtu.be/" in lowered


def download_audio(
    url: str,
    work_dir: str | None = None,
    cookies_path: str | None = None,
    remote_components: str | None = None,
    browser_cookies: str | None = None,
    preferred_browser: str | None = None,
) -> tuple[str | None, dict[str, str]]:
    log(f"Скачивание: {url}")
    if work_dir is None:
        work_dir = os.getcwd()
    os.makedirs(work_dir, exist_ok=True)

    if os.path.isfile(url):
        log(f"Использование локального файла: {url}")
        dest = os.path.join(work_dir, os.path.basename(url))
        shutil.copy2(url, dest)
        return dest, {}

    output_template = os.path.join(work_dir, "%(title).200B.%(ext)s")
    cmd = [
        external_tool("yt-dlp"),
        "--ignore-config",
        "-f",
        "bestaudio/best",
        "--no-playlist",
        "--no-progress",
        "--no-colors",
    ]
    if "soundcloud.com" in url.lower():
        cmd.append("--embed-thumbnail")
    if sys.platform == "win32":
        cmd += ["--windows-filenames"]
    if cookies_path:
        cmd += ["--cookies", cookies_path]
    if remote_components:
        cmd += ["--remote-components", remote_components]
    cmd += [
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--extractor-retries",
        "1",
        "--socket-timeout",
        "20",
        "--retry-sleep",
        "1",
        "--concurrent-fragments",
        "4",
        "--sleep-requests",
        "0.1",
        "-o",
        output_template,
        "--print",
        "%(title)s",
        "--print",
        "%(channel)s",
        "--print",
        "after_move:filepath",
        "--no-warnings",
        url,
    ]
    active_browser: str | None = None
    try:
        if preferred_browser and _is_youtube_url(url) and not cookies_path:
            label = _BROWSER_LABELS.get(preferred_browser, preferred_browser)
            log(f"Используем подтверждённый вход из {label}…")
            res = _run_downloader(cmd, preferred_browser)
            if res.returncode == 0:
                active_browser = preferred_browser
            else:
                log(f"{label}: {_summarize_downloader_error(res.stderr)}.")
                res = _run_downloader(cmd)
        else:
            res = _run_downloader(cmd)
    except subprocess.TimeoutExpired:
        log("yt-dlp превысил лимит ожидания в 5 минут.")
        return None, {"_error": "yt-dlp превысил лимит ожидания в 5 минут"}
    except OSError as exc:
        log(f"Не удалось запустить yt-dlp: {exc}")
        return None, {"_error": f"не удалось запустить yt-dlp: {exc}"}

    if (
        res.returncode != 0
        and not cookies_path
        and _is_youtube_auth_block(res.stderr)
        and browser_cookies not in (None, "off")
    ):
        candidates = browser_cookie_candidates(browser_cookies)
        if candidates:
            log("YouTube запросил подтверждение. Пробуем активный вход из браузера…")
        else:
            log("YouTube запросил вход, но подходящий профиль браузера не найден.")
        for browser in candidates:
            label = _BROWSER_LABELS.get(browser, browser)
            log(f"Проверка через {label}…")
            try:
                retry = _run_downloader(cmd, browser)
            except (OSError, subprocess.TimeoutExpired) as exc:
                log(f"{label}: не удалось прочитать сессию ({exc}).")
                continue
            if retry.returncode == 0:
                res = retry
                active_browser = browser
                log(f"Вход из {label} принят.")
                break
            concise_error = _summarize_downloader_error(retry.stderr)
            log(f"{label}: {concise_error}.")
            res = retry

    if res.returncode != 0:
        concise_error = _summarize_downloader_error(res.stderr)
        log(f"Не удалось скачать: {concise_error}.")
        if _is_youtube_auth_block(res.stderr):
            concise_error = (
                "YouTube потребовал вход; откройте YouTube в выбранном браузере или укажите cookies"
            )
        return None, {"_error": concise_error}

    lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]

    # Парсим filepath с конца stdout: ищем первую строку с конца, которая похожа на путь к файлу.
    # yt-dlp может вклинить лишние строки (мерж форматов, [info] и т.д.) даже с --no-warnings.
    filename: str | None = None
    filepath_idx: int | None = None
    for i in range(len(lines) - 1, -1, -1):
        candidate = lines[i]
        # Абсолютный путь или файл в work_dir с аудио-расширением
        if os.path.isabs(candidate):
            resolved = candidate
        else:
            resolved = os.path.abspath(os.path.join(work_dir, candidate))
        if os.path.isfile(resolved) and os.path.getsize(resolved) > 0:
            filename = resolved
            filepath_idx = i
            break

    # Metadata: title и artist — две строки непосредственно перед filepath.
    metadata: dict[str, str] = {}
    if filepath_idx is not None and filepath_idx >= 2:
        metadata = {"title": lines[filepath_idx - 2], "artist": lines[filepath_idx - 1]}
    elif filepath_idx is not None and filepath_idx >= 1:
        metadata = {"title": lines[filepath_idx - 1]}
    elif len(lines) >= 3:
        # Fallback: предполагаем классический порядок.
        metadata = {"title": lines[-3], "artist": lines[-2]}
    elif len(lines) >= 2:
        metadata = {"title": lines[-2]}

    if filename:
        if active_browser:
            metadata["_browser_cookies_used"] = active_browser
        return filename, metadata

    # Fallback: ищем файл в work_dir. При нескольких (напр. после retry) берём новейший.
    downloaded_files = [
        os.path.join(work_dir, name)
        for name in os.listdir(work_dir)
        if os.path.isfile(os.path.join(work_dir, name))
        and not name.endswith((".part", ".ytdl", ".temp", ".tmp", ".png"))
        and os.path.getsize(os.path.join(work_dir, name)) > 0
    ]
    if downloaded_files:
        # Выбираем самый новый файл (mtime) — это результат последней успешной попытки.
        best = max(downloaded_files, key=os.path.getmtime)
        if active_browser:
            metadata["_browser_cookies_used"] = active_browser
        return os.path.abspath(best), metadata

    log(f"yt-dlp не создал ожидаемый файл: {filename or '<пустой путь>'}")
    return None, metadata


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def get_audio_details(filepath: str) -> dict[str, Any]:
    cmd = [
        external_tool("ffprobe"),
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        filepath,
    ]
    res = run_command(cmd)
    details: dict[str, Any] = {
        "codec": "unknown",
        "bitrate": 0,
        "sample_rate": 0,
        "channels": 0,
        "duration": 0.0,
    }
    if res.returncode != 0:
        log(f"Ошибка ffprobe для {filepath} (код {res.returncode}): {res.stderr.strip()}")
        return details

    try:
        data = json.loads(res.stdout)
    except Exception as exc:
        log(f"Не удалось разобрать ffprobe JSON для {filepath}: {exc}")
        return details

    for stream in data.get("streams", []):
        if stream.get("codec_type") != "audio":
            continue
        details["codec"] = stream.get("codec_name", "unknown")
        details["sample_rate"] = _safe_int(stream.get("sample_rate"))
        details["channels"] = _safe_int(stream.get("channels"))
        details["duration"] = _safe_float(stream.get("duration"))
        bitrate = _safe_int(stream.get("bit_rate"))
        if bitrate > 0:
            details["bitrate"] = bitrate // 1000
        break

    fmt = data.get("format", {})
    if not details["duration"]:
        details["duration"] = _safe_float(fmt.get("duration"))
    if not details["bitrate"]:
        format_bitrate = _safe_int(fmt.get("bit_rate"))
        if format_bitrate > 0:
            details["bitrate"] = format_bitrate // 1000
        else:
            duration = _safe_float(fmt.get("duration"))
            size = _safe_int(fmt.get("size"))
            if duration > 0 and size > 0:
                details["bitrate"] = int((size * 8) / (duration * 1000))

    return details


def convert_to_wav(
    filepath: str,
    duration: float = 0.0,
    channels: int = 0,
) -> str | None:
    """Извлекает PCM в WAV. Длинные треки обрезаются по центру до ANALYSIS_MAX_SECONDS,
    чтобы ограничить RAM/диск и не упереться в 4 ГБ лимит классического WAV.

    Args:
        filepath: путь к исходному аудио-файлу.
        duration: длительность в секундах (если уже известна из ffprobe).
        channels: число каналов исходника. Многоканальный звук сводится в стерео.
    """
    wav_path = filepath + ".wav"
    cmd = [external_tool("ffmpeg"), "-y", "-v", "error"]

    # Если длительность не передана — узнаём через ffprobe (fallback).
    if not duration:
        duration = get_audio_details(filepath).get("duration", 0.0)
    if duration and duration > ANALYSIS_MAX_SECONDS:
        start = max(0.0, (duration - ANALYSIS_MAX_SECONDS) / 2.0)
        cmd += ["-ss", f"{start:.3f}", "-t", f"{ANALYSIS_MAX_SECONDS:.3f}"]

    cmd += [
        "-i",
        filepath,
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-acodec",
        "pcm_f32le",
        "-ar",
        str(ANALYSIS_SAMPLE_RATE),
        wav_path,
    ]
    if channels > 2:
        cmd[-1:-1] = ["-ac", "2"]
    res = run_command(cmd)
    if res.returncode != 0:
        log(f"Ошибка ffmpeg для {filepath} (код {res.returncode}): {res.stderr.strip()}")
        return None
    if not os.path.exists(wav_path) or os.path.getsize(wav_path) == 0:
        log(f"ffmpeg не создал пригодный WAV для {filepath}")
        return None
    return wav_path


def empty_metrics(reason: str | None = None) -> dict[str, Any]:
    warnings = [reason] if reason else []
    return {
        "duration": 0.0,
        "cutoff": 0.0,
        "raw_cutoff": 0.0,
        "cliff_db_per_khz": 0.0,
        "flatness": 0.0,
        "hf_db": -120.0,
        "hf_ratio": 0.0,
        "modulation": 0.0,
        "env_corr": None,
        "correlation": None,
        "authenticity": 0.0,
        "fake_noise": False,
        "score": 0.0,
        "raw_score": 0.0,
        "reliable": False,
        "valid": False,
        "warnings": warnings,
        "spectrogram": None,
    }


def audio_to_float(data: np.ndarray) -> np.ndarray:
    arr = np.asarray(data)
    if np.issubdtype(arr.dtype, np.integer):
        info = np.iinfo(arr.dtype)
        scale = float(max(abs(info.min), abs(info.max)))
        arr = arr.astype(np.float32) / scale
    else:
        arr = arr.astype(np.float32, copy=False)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    return arr


def spectral_flatness(psd: np.ndarray) -> float:
    psd = np.asarray(psd, dtype=float)
    psd = psd[np.isfinite(psd)]
    if psd.size == 0:
        return 0.0
    psd = np.maximum(psd, EPS)
    arithmetic = float(np.mean(psd))
    if arithmetic <= EPS:
        return 0.0
    geometric = float(np.exp(np.mean(np.log(psd))))
    return float(np.clip(geometric / arithmetic, 0.0, 1.0))


def apply_duration_cap(score: float, duration: float, min_reliable_duration: float) -> float:
    if duration >= min_reliable_duration:
        return score
    if duration <= MIN_HARD_DURATION:
        cap = 35.0
    else:
        span = max(min_reliable_duration - MIN_HARD_DURATION, 1.0)
        cap = 35.0 + np.clip((duration - MIN_HARD_DURATION) / span, 0.0, 1.0) * 40.0
    return float(min(score, cap))


def safe_correlation(first: np.ndarray, second: np.ndarray) -> float | None:
    first_std = float(np.std(first))
    second_std = float(np.std(second))
    if (
        not math.isfinite(first_std)
        or not math.isfinite(second_std)
        or first_std <= 1e-12
        or second_std <= 1e-12
    ):
        return None
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = float(np.corrcoef(first, second)[0, 1])
    if not math.isfinite(correlation):
        return None
    return float(np.clip(correlation, -1.0, 1.0))


def _stereo_hf_correlation(
    left: np.ndarray, right: np.ndarray, fs: float, nyq: float
) -> float | None:
    """Корреляция L/R в полосе 14–20 кГц. Независимо подмешанный шум => ~0."""
    if nyq <= 14000.0 or len(left) <= 128 or len(right) <= 128:
        return None
    try:
        upper_hz = min(20000.0, 0.95 * nyq)
        if upper_hz <= 14000.0:
            return None
        sos = butter(4, [14000.0 / nyq, upper_hz / nyq], btype="bandpass", output="sos")
        lhf = sosfiltfilt(sos, left)
        rhf = sosfiltfilt(sos, right)
        return safe_correlation(lhf, rhf)
    except Exception:
        return None


def analyze_file(
    wav_path: str,
    spectrogram_path: str | None,
    min_reliable_duration: float = MIN_RELIABLE_DURATION,
    track_label: str = "",
) -> dict[str, Any]:
    """Спектральный анализ через STFT по суб-полосам.

    Ключевая идея против фейковых ВЧ: реальный музыкальный верх МОДУЛИРУЕТСЯ во времени
    (транзиенты тарелок/хэтов), а подмешанный шум стационарен. "Эффективный срез" считается
    по последней суб-полосе с живым (модулированным) сигналом, шумовой хвост игнорируется.
    """
    try:
        fs, raw_data = wavfile.read(wav_path)
    except Exception as exc:
        return empty_metrics(f"не удалось прочитать WAV: {exc}")

    data = audio_to_float(raw_data)
    if data.size == 0 or fs <= 0:
        return empty_metrics("пустой или некорректный PCM")

    if data.ndim > 1 and data.shape[1] > 1:
        left = data[:, 0].astype(np.float32, copy=False)
        right = data[:, 1].astype(np.float32, copy=False)
        mono = np.mean(data, axis=1, dtype=np.float32)
        is_stereo = True
    else:
        mono = data.reshape(-1).astype(np.float32, copy=False)
        left = mono
        right = mono
        is_stereo = False

    mono = np.nan_to_num(mono - np.mean(mono), nan=0.0)
    left = np.nan_to_num(left - np.mean(left), nan=0.0)
    right = np.nan_to_num(right - np.mean(right), nan=0.0)

    duration = float(len(mono) / fs)
    warnings: list[str] = []
    if len(mono) < STFT_NPERSEG:
        metrics = empty_metrics("слишком мало PCM-сэмплов для STFT")
        metrics["duration"] = duration
        return metrics
    if duration < min_reliable_duration:
        warnings.append(
            f"короткий файл: {duration:.2f} с, надежный анализ требует примерно "
            f"{min_reliable_duration:.0f} с"
        )

    nyq = 0.5 * fs
    if nyq <= 16000.0:
        warnings.append(
            "частота дискретизации не дает проверить полосу выше 16 kHz; "
            "probe-анализ ВЧ отключён, authenticity = 50 (нейтраль)"
        )

    # --- STFT ------------------------------------------------------------
    nperseg = min(STFT_NPERSEG, len(mono))
    f, t, Sxx = spectrogram(
        mono,
        fs,
        window="hann",
        nperseg=nperseg,
        noverlap=nperseg // 2,
        detrend="constant",
        mode="psd",
    )
    if Sxx.size == 0 or not np.any(np.isfinite(Sxx)):
        metrics = empty_metrics("STFT не дал пригодный спектр")
        metrics["duration"] = duration
        return metrics
    Sxx = np.nan_to_num(Sxx, nan=0.0, posinf=0.0, neginf=0.0)

    psd_med = np.median(Sxx, axis=1)  # устойчивый усреднённый спектр

    ref_mask = (f >= 1000.0) & (f <= 5000.0)
    if not np.any(ref_mask):
        ref_mask = (f >= 200.0) & (f <= min(6000.0, 0.5 * nyq))
    ref_level = (
        float(np.median(psd_med[ref_mask])) if np.any(ref_mask) else float(np.median(psd_med))
    )
    if ref_level <= EPS:
        metrics = empty_metrics("сигнал близок к цифровой тишине")
        metrics["duration"] = duration
        return metrics

    # Сглаженный спектр и dB-кривая относительно опоры.
    psd_s = np.convolve(psd_med, np.ones(5) / 5.0, mode="same") if len(psd_med) >= 5 else psd_med
    db_curve = 10.0 * np.log10(np.maximum(psd_s, EPS) / ref_level)

    # --- Энергетический срез (вся полоса, включая возможный шум) ---------
    # Метод "dB ниже опоры" (как в Spek): квантизационный пол сидит ниже -55 дБ
    # и отсекается сам, а настоящий тихий ВЧ — нет. Доп. абсолютный пол страхует
    # от цифровой тишины.
    present_thr = ref_level * 10 ** (PRESENCE_DB / 10.0)
    abs_floor = float(np.max(psd_s)) * 1e-7
    valid = (psd_s > present_thr) & (psd_s > abs_floor) & (f > 1000.0)
    valid_idx = np.where(valid)[0]
    raw_cutoff = float(f[valid_idx[-1]]) if len(valid_idx) else 1000.0

    # --- Probe-полоса 16.5..20 кГц: тут живёт шум "раздутого MP3" --------
    probe_lo = 16500.0
    probe_hi = min(20000.0, 0.95 * nyq)
    p_level_db = -120.0
    p_flatness = 0.0
    p_modulation = 0.0
    p_env_corr: float | None = None
    if probe_hi > probe_lo:
        probe_mask = (f >= probe_lo) & (f <= probe_hi)
        if np.any(probe_mask):
            p_energy = float(np.mean(psd_med[probe_mask]))
            p_level_db = 10.0 * np.log10(max(p_energy, EPS) / ref_level)
            p_flatness = spectral_flatness(psd_med[probe_mask])
            mid_env_mask = (f >= 500.0) & (f <= 4000.0)
            if Sxx.shape[1] >= 8 and np.any(mid_env_mask):
                probe_env = Sxx[probe_mask, :].mean(axis=0)
                mid_env = Sxx[mid_env_mask, :].mean(axis=0)
                if np.mean(probe_env) > EPS:
                    p_modulation = float(np.std(probe_env) / (np.mean(probe_env) + EPS))
                    lp = np.log10(probe_env + EPS)
                    lm = np.log10(mid_env + EPS)
                    p_env_corr = safe_correlation(lp, lm)

    # Корреляция каналов строго в probe-полосе (независимый шум => ~0).
    p_lr_corr = None
    if is_stereo and probe_hi > probe_lo:
        try:
            sos = butter(
                4,
                [probe_lo / nyq, probe_hi / nyq],
                btype="bandpass",
                output="sos",
            )
            lhf = sosfiltfilt(sos, left)
            rhf = sosfiltfilt(sos, right)
            p_lr_corr = safe_correlation(lhf, rhf)
        except Exception:
            p_lr_corr = None

    # Полноценная корреляция/модуляция для отчёта (полоса 14..20 кГц).
    lr_corr = _stereo_hf_correlation(left, right, fs, nyq) if is_stereo else None

    # --- Классификация probe-полосы: пусто / настоящее / шум -------------
    probe_has_energy = p_level_db > -50.0
    # L/R-корреляция одна не достаточна: коррелированный шум (L==R) даёт
    # p_lr_corr ≈ 1.0, но модуляция будет низкой. Требуем либо env_corr,
    # либо L/R + модуляцию совместно.
    genuine_hf = (
        (p_env_corr is not None and p_env_corr > 0.20)
        or (p_lr_corr is not None and p_lr_corr > 0.40 and p_modulation > 0.25)
        or (p_modulation > 0.45 and p_flatness < 0.50)
    )
    noiselike_hf = (
        probe_has_energy
        and p_flatness > 0.50
        and p_modulation < 0.35
        and (p_env_corr is None or p_env_corr < 0.20)
        # L/R корреляция снимает подозрение в шуме, НО только если сигнал
        # хоть немного модулирован (> 0.15). Коррелированный шум (L==R)
        # даёт p_lr_corr ≈ 1.0, но остаётся стационарным (modulation < 0.15).
        and (p_lr_corr is None or abs(p_lr_corr) < 0.25 or p_modulation < 0.15)
    )
    fake_noise = bool(noiselike_hf and not genuine_hf and raw_cutoff > 16000.0)

    # --- Честный срез: при фейке игнорируем шумовую "полку" --------------
    if fake_noise:
        below_idx = np.where(valid & (f < probe_lo))[0]
        eff_cutoff = float(f[below_idx[-1]]) if len(below_idx) else 1000.0
        eff_cutoff = min(eff_cutoff, 16500.0)
    else:
        eff_cutoff = raw_cutoff

    # --- Крутизна обрыва (brick-wall lossy) -----------------------------
    cliff_db_per_khz = 0.0
    if 1000.0 < eff_cutoff < nyq - 1000.0:
        i_lo = int(np.argmin(np.abs(f - (eff_cutoff - 300.0))))
        i_hi = int(np.argmin(np.abs(f - (eff_cutoff + 1000.0))))
        if i_hi > i_lo:
            cliff_db_per_khz = float((db_curve[i_lo] - db_curve[i_hi]) / 1.3)

    # --- Метрики ВЧ-зоны 16..20 кГц для отчёта ---------------------------
    hf_lo = 16000.0
    hf_hi = min(20000.0, 0.95 * nyq)
    hf_db = -120.0
    hf_ratio = 0.0
    flatness = p_flatness
    if hf_hi > hf_lo:
        hf_mask = (f >= hf_lo) & (f <= hf_hi)
        if np.any(hf_mask):
            hf_energy = float(np.mean(psd_med[hf_mask]))
            hf_ratio = float(np.clip(hf_energy / (ref_level + EPS), 0.0, 1.0))
            hf_db = 10.0 * np.log10(max(hf_energy, EPS) / ref_level)

    modulation = p_modulation
    env_corr = p_env_corr

    # --- Authenticity (уверенность, что верх настоящий) 0..100 ----------
    # Эвристические веса разделяют модулированный музыкальный верх и стационарный
    # шум. Они не доказывают происхождение файла и требуют проверки на размеченном
    # корпусе перед использованием в форензике.
    #   AUTH_BASE       = 60.0  — нейтральная точка отсчёта
    #   W_ENV_CORR      = 25.0  — корреляция ВЧ-огибающей с музыкой (важнейший признак)
    #   W_LR_CORR       = 20.0  — стерео-согласованность L/R в probe-полосе
    #   LR_CORR_OFFSET  = 0.3   — сдвиг L/R: случайный шум даёт ~0.3, живой верх > 0.6
    #   W_MODULATION    = 15.0  — вес временно́й модуляции ВЧ (транзиенты тарелок)
    #   FLAT_SENS       = 60.0  — чувствительность к спектральной плоскости
    #   FLAT_THRESHOLD  = 0.50  — порог, выше которого спектр «слишком плоский» (шум)
    AUTH_BASE = 60.0
    W_ENV_CORR = 25.0
    W_LR_CORR = 20.0
    LR_CORR_OFFSET = 0.3
    W_MODULATION = 15.0
    FLAT_SENS = 60.0
    FLAT_THRESHOLD = 0.50

    auth = AUTH_BASE
    if p_env_corr is not None:
        auth += float(np.clip(p_env_corr, -1, 1)) * W_ENV_CORR
    if p_lr_corr is not None:
        auth += (float(np.clip(abs(p_lr_corr), 0, 1)) - LR_CORR_OFFSET) * W_LR_CORR
    auth += float(np.clip(p_modulation, 0.0, 1.0)) * W_MODULATION
    auth -= float(np.clip((p_flatness - FLAT_THRESHOLD) * FLAT_SENS, 0.0, 40.0))
    if not probe_has_energy:
        auth = 50.0  # нет ВЧ для оценки достоверности — нейтрально
    authenticity = float(np.clip(auth, 0.0, 100.0))

    # --- Итоговый скоринг ------------------------------------------------
    # Базис — честная полоса (эффективный срез).
    cutoff_score = float(
        np.clip((eff_cutoff - CUTOFF_LOW_HZ) / (CUTOFF_HIGH_HZ - CUTOFF_LOW_HZ) * 100.0, 0.0, 100.0)
    )
    raw_score = cutoff_score

    # Очень крутой обрыв на средних частотах — подпись lossy-кодека.
    if eff_cutoff < 17500.0 and cliff_db_per_khz > 40.0:
        raw_score *= 0.90

    if fake_noise:
        raw_score = min(raw_score, 22.0)
        warnings.append(
            f"обнаружены фейковые ВЧ: живой сигнал до ~{eff_cutoff / 1000:.1f} кГц, "
            f"выше — стационарный шум до ~{raw_cutoff / 1000:.1f} кГц"
        )

    total_score = apply_duration_cap(raw_score, duration, min_reliable_duration)
    reliable = duration >= min_reliable_duration and eff_cutoff > 1500.0

    metrics = {
        "duration": duration,
        "cutoff": eff_cutoff,
        "raw_cutoff": raw_cutoff,
        "cliff_db_per_khz": cliff_db_per_khz,
        "flatness": flatness,
        "hf_db": hf_db,
        "hf_ratio": hf_ratio,
        "modulation": modulation,
        "env_corr": env_corr,
        "correlation": lr_corr,
        "authenticity": authenticity,
        "fake_noise": fake_noise,
        "score": total_score,
        "raw_score": raw_score,
        "reliable": reliable,
        "valid": True,
        "warnings": warnings,
        "spectrogram": None,
    }

    # --- Спектрограмма ---------------------------------------------------
    if spectrogram_path and HAS_MPL:
        try:
            render_spectrogram(
                f,
                t,
                Sxx,
                ref_level,
                nyq,
                eff_cutoff,
                raw_cutoff,
                fake_noise,
                spectrogram_path,
                track_label,
            )
            metrics["spectrogram"] = spectrogram_path
        except Exception as exc:
            warnings.append(f"не удалось построить спектрограмму: {exc}")

    return metrics


def render_spectrogram(
    f: np.ndarray,
    t: np.ndarray,
    Sxx: np.ndarray,
    ref_level: float,
    nyq: float,
    eff_cutoff: float,
    raw_cutoff: float,
    fake_noise: bool,
    out_path: str,
    title: str,
) -> None:
    # Децимация по времени, чтобы PNG был лёгким.
    max_cols = 1600
    if Sxx.shape[1] > max_cols:
        step = Sxx.shape[1] // max_cols + 1
        Sxx = Sxx[:, ::step]
        t = t[::step]

    db = 10.0 * np.log10(np.maximum(Sxx, EPS) / max(ref_level, EPS))

    colors = build_theme_colors()
    heading_size = abs(FONTS["heading"]["size"]) * 72 / 96
    label_size = abs(FONTS["label"]["size"]) * 72 / 96
    spectrum_map = LinearSegmentedColormap.from_list(
        "trackjudge-spectrum",
        (
            colors["canvas"],
            blend(colors["accent"], colors["surface"], 0.14),
            colors["accent"],
            colors["ink"],
        ),
    )

    fig = Figure(figsize=(11, 5), dpi=110, facecolor=colors["surface"])
    ax = fig.add_subplot(111)
    ax.set_facecolor(colors["surface"])
    mesh = ax.pcolormesh(
        t,
        f / 1000.0,
        db,
        shading="auto",
        cmap=spectrum_map,
        vmin=-90.0,
        vmax=10.0,
    )
    ax.axhline(
        eff_cutoff / 1000.0,
        color=colors["accent"],
        lw=2.0,
        ls="--",
        label=f"живой срез {eff_cutoff / 1000:.1f} кГц",
    )
    if raw_cutoff - eff_cutoff > FAKE_GAP_HZ:
        ax.axhline(
            raw_cutoff / 1000.0,
            color=blend(colors["accent"], colors["surface"], 0.38),
            lw=2.0,
            ls=":",
            label=f"край энергии {raw_cutoff / 1000:.1f} кГц",
        )
    ax.set_ylim(0, nyq / 1000.0)
    ax.set_xlabel("Время, с", color=colors["ink"])
    ax.set_ylabel("Частота, кГц", color=colors["ink"])
    ax.yaxis.set_major_locator(MultipleLocator(2))
    ax.grid(color=colors["border"], linewidth=1.0)
    ax.tick_params(colors=colors["muted"])
    for spine in ax.spines.values():
        spine.set_color(colors["border"])
    suffix = "  [ФЕЙКОВЫЕ ВЧ]" if fake_noise else ""
    ax.set_title(
        f"{title}{suffix}",
        fontsize=heading_size,
        color=colors["critical"] if fake_noise else colors["ink"],
    )
    legend = ax.legend(
        loc="upper right",
        fontsize=label_size,
        facecolor=colors["surface"],
        edgecolor=colors["border"],
        framealpha=1.0,
        labelcolor=colors["ink"],
    )
    legend.get_frame().set_linewidth(1.0)
    colorbar = fig.colorbar(mesh, ax=ax)
    colorbar.set_label("дБ отн. опоры", color=colors["ink"])
    colorbar.ax.tick_params(colors=colors["muted"])
    colorbar.outline.set_edgecolor(colors["border"])
    fig.tight_layout()
    fig.savefig(out_path, facecolor=colors["surface"])


def quality_label(score: float, fake_noise: bool = False) -> str:
    if fake_noise:
        return "фейковые ВЧ (подмешан шум)"
    if score >= 70.0:
        return "хорошее качество"
    if score >= 45.0:
        return "подозрительно"
    return "вероятный апскейл"


def unique_dest_path(src_path: str, dest_folder: str, ext_override: str | None = None) -> str:
    filename = os.path.basename(src_path)
    root, ext = os.path.splitext(filename)
    if ext_override:
        ext = ext_override
        filename = f"{root}{ext}"
    dest = os.path.join(dest_folder, filename)
    if not os.path.exists(dest):
        return dest
    for index in range(1, 10000):
        candidate = os.path.join(dest_folder, f"{root}_{index}{ext}")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError(f"Не удалось подобрать свободное имя файла для {filename}")


def should_remux_to_opus(result: dict[str, Any]) -> bool:
    _, ext = os.path.splitext(result["orig_file"])
    return ext.lower() == ".webm" and str(result.get("codec", "")).lower() == "opus"


def remux_webm_opus_to_opus(
    src_path: str, dest_path: str, metadata: dict[str, str] | None = None
) -> str:
    cmd = [
        external_tool("ffmpeg"),
        "-y",
        "-v",
        "error",
        "-i",
        src_path,
        "-map",
        "0:a:0",
        "-vn",
        "-sn",
        "-dn",
        "-c:a",
        "copy",
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
    ]
    for key, value in (metadata or {}).items():
        cmd += ["-metadata", f"{key}={value}"]
    cmd.append(dest_path)
    res = run_command(cmd)
    if res.returncode != 0:
        cleanup_files([dest_path])
        raise RuntimeError(f"ffmpeg не смог перепаковать WebM Opus в .opus: {res.stderr.strip()}")
    if not os.path.exists(dest_path) or os.path.getsize(dest_path) == 0:
        cleanup_files([dest_path])
        raise RuntimeError("ffmpeg не создал пригодный .opus файл")

    details = get_audio_details(dest_path)
    if details["codec"] != "opus":
        cleanup_files([dest_path])
        raise RuntimeError(f"после перепаковки получился неожиданный кодек: {details['codec']}")

    try:
        stat = os.stat(src_path)
        os.utime(dest_path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    except Exception:
        pass
    os.remove(src_path)
    _fix_permissions(dest_path)
    return dest_path


def write_metadata(filepath: str, metadata: dict[str, str]) -> None:
    """Записывает title/artist теги в аудио-файл, убирая мусорные теги."""
    if not metadata:
        return
    ext = os.path.splitext(filepath)[1]
    tmp = filepath + ".tmp_meta" + ext
    cmd = [
        external_tool("ffmpeg"),
        "-y",
        "-v",
        "error",
        "-i",
        filepath,
        "-map",
        "0:a:0",
        "-map",
        "0:v?",
        "-c:a",
        "copy",
        "-c:v",
        "copy",
        "-map_metadata",
        "-1",
        "-fflags",
        "+bitexact",
    ]
    for key, value in metadata.items():
        cmd += ["-metadata", f"{key}={value}"]
    cmd.append(tmp)
    res = run_command(cmd)
    if res.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
        os.replace(tmp, filepath)
    else:
        cleanup_files([tmp])
        log(f"Не удалось записать метаданные в {os.path.basename(filepath)}")


def save_candidate(result: dict[str, Any], dest_folder: str) -> str:
    metadata = result.get("metadata") or {}
    if should_remux_to_opus(result):
        dest = remux_webm_opus_to_opus(
            result["orig_file"],
            unique_dest_path(result["orig_file"], dest_folder, ".opus"),
            metadata,
        )
    else:
        dest = unique_dest_path(result["orig_file"], dest_folder)
        if os.path.abspath(result["orig_file"]) != os.path.abspath(dest):
            shutil.move(result["orig_file"], dest)
        write_metadata(dest, metadata)
    result["saved_file"] = dest
    _fix_permissions(dest)
    return dest


def save_spectrogram(result: dict[str, Any], dest_folder: str) -> str | None:
    source = result.get("spectrogram")
    if not source or not os.path.exists(source):
        return None
    destination = unique_dest_path(source, dest_folder)
    shutil.copy2(source, destination)
    result["saved_spectrogram"] = destination
    _fix_permissions(destination)
    return destination


def cleanup_files(paths: list[str | None]) -> None:
    for path in paths:
        if not path:
            continue
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as exc:
            log(f"Не удалось удалить временный файл {path}: {exc}")


def _fix_permissions(path: str) -> None:
    """Сбрасывает ACL файла, чтобы он унаследовал права родительской папки (Windows)."""
    try:
        if sys.platform == "win32":
            run_command(["icacls", path, "/reset"])
        else:
            os.chmod(path, 0o644)
    except Exception:
        pass


def fmt_optional_float(value: float | None, digits: int = 4) -> str:
    if value is None or not np.isfinite(value):
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
        _CONSOLE.print()
        _CONSOLE.print(table)

    warning_lines: list[str] = []
    for index, result in enumerate(results, 1):
        warning_lines.extend(f"#{index}: {warning}" for warning in result.get("warnings", []))
    if warning_lines:
        _CONSOLE.print(
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
        _CONSOLE.print(failed)


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
    temporary_path = report_path + ".tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8", newline="\n") as report_file:
            json.dump(payload, report_file, ensure_ascii=False, indent=2)
            report_file.write("\n")
        os.replace(temporary_path, report_path)
    except Exception:
        cleanup_files([temporary_path])
        raise
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


def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
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
            orig_file, metadata = download_audio(
                url,
                candidate_dir,
                cookies_path,
                remote_components,
                browser_cookies,
                preferred_browser,
            )
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

        current_successes = len(downloaded)
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
            wav_file = None
            try:
                details = get_audio_details(orig_file)
                wav_file = convert_to_wav(
                    orig_file,
                    duration=details.get("duration", 0.0),
                    channels=details.get("channels", 0),
                )
                if not wav_file:
                    cleanup_files([orig_file])
                    return url, None, "PCM-извлечение не удалось"

                spectro_path = None
                if make_spectrogram and HAS_MPL:
                    spectro_path = orig_file + ".spectrogram.png"

                metrics = analyze_file(
                    wav_file,
                    spectro_path,
                    args.min_reliable_duration,
                    track_label=os.path.basename(orig_file),
                )
                if not metrics.get("valid"):
                    cleanup_files([orig_file, wav_file, metrics.get("spectrogram")])
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
                        "wav_file": wav_file,
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
                return url, metrics, None
            except Exception as exc:
                cleanup_files([orig_file, wav_file])
                return url, None, str(exc)

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
            cleanup_files([item.get("orig_file") for item in results])
            cleanup_files([item.get("wav_file") for item in results])
            cleanup_files([item.get("spectrogram") for item in results])
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
        _CONSOLE.print(
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
        _CONSOLE.print(
            Panel(
                Text("\n".join(summary_lines)),
                title="Готово",
                border_style="cyan",
                box=box.ROUNDED,
            )
        )

        # Оригинал победителя уже перемещён в папку результата.
        for item in results:
            if item is winner:
                cleanup_files([item["wav_file"], item.get("spectrogram")])
            else:
                cleanup_files([item["orig_file"], item["wav_file"], item.get("spectrogram")])

    return 1 if report_failed else 0


def run_analysis(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser | None = None,
) -> int:
    """Run one configured comparison without invoking argument parsing."""
    return _run(args, parser or build_parser())


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
        _CONSOLE.print("\nОперация отменена.", style="yellow")
        exit_code = 130
        return exit_code
    except EOFError:
        _CONSOLE.print("\nНе удалось прочитать интерактивный ввод.", style="red")
        exit_code = 2
        return exit_code
    finally:
        if sys.stdin.isatty():
            with suppress(KeyboardInterrupt, EOFError):
                _CONSOLE.input(Text("\nНажмите Enter, чтобы закрыть TrackJudge…", style="dim"))


if __name__ == "__main__":
    raise SystemExit(main())
