from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import updater
from .console import log

ANALYSIS_SAMPLE_RATE = 48000
ANALYSIS_MAX_SECONDS = 300.0


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
        command[-2:-2] = ["--cookies-from-browser", browser]
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
        "--",
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
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else default
    except (TypeError, ValueError):
        return default


def get_audio_details(filepath: str) -> dict[str, Any]:
    cmd = [
        external_tool("ffprobe"),
        "-v",
        "error",
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
    duration: float | None = None,
    channels: int = 0,
    sample_rate: int = 0,
    output_path: str | None = None,
) -> str | None:
    """Decode the central analysis window, retaining mono and the native bandwidth."""
    if duration is None or not (channels and sample_rate):
        details = get_audio_details(filepath)
        if duration is None:
            duration = details["duration"]
        channels = channels or details["channels"]
        sample_rate = sample_rate or details["sample_rate"]
    if channels <= 0 or sample_rate <= 0:
        raise ValueError(f"Нет пригодной аудиодорожки: {os.path.basename(filepath)}")

    wav_path = output_path or filepath + ".wav"
    cmd = [external_tool("ffmpeg"), "-nostdin", "-y", "-v", "error"]
    if duration and duration > ANALYSIS_MAX_SECONDS:
        cmd.extend(["-ss", f"{(duration - ANALYSIS_MAX_SECONDS) / 2:.6f}"])
    cmd.extend(
        [
            "-i",
            filepath,
            "-map",
            "0:a:0",
            "-t",
            str(ANALYSIS_MAX_SECONDS),
            "-c:a",
            "pcm_f32le",
            "-ar",
            str(min(sample_rate, ANALYSIS_SAMPLE_RATE)),
            "-ac",
            str(min(channels, 2)),
            wav_path,
        ]
    )
    res = run_command(cmd)
    if res.returncode != 0:
        cleanup_files([wav_path])
        raise ValueError(res.stderr.strip() or f"FFmpeg: {os.path.basename(filepath)}")
    if not os.path.exists(wav_path) or os.path.getsize(wav_path) == 0:
        log(f"ffmpeg не создал пригодный WAV для {filepath}")
        return None
    return wav_path


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
    source = Path(result["orig_file"])
    remux = should_remux_to_opus(result)
    filename = source.with_suffix(".opus").name if remux else source.name
    with tempfile.TemporaryDirectory(dir=dest_folder, prefix=".trackjudge-") as staging:
        staged = str(Path(staging, filename))
        if remux:
            remux_webm_opus_to_opus(str(source), staged, metadata)
        else:
            shutil.copyfile(source, staged)
            shutil.copystat(source, staged)
            write_metadata(staged, metadata)
        dest = publish_file(staged, os.path.join(dest_folder, filename), unique=True)
    result["saved_file"] = dest
    _fix_permissions(dest)
    return dest


def publish_file(staged: str, destination: str, *, unique: bool = False) -> str:
    """Reserve an unused name exclusively and publish the completed sibling file."""
    folder, filename = os.path.split(destination)
    while True:
        path = unique_dest_path(filename, folder) if unique else destination
        try:
            with open(path, "xb"):
                pass
        except FileExistsError:
            if not unique:
                raise
        else:
            break
    try:
        os.replace(staged, path)
    except OSError:
        os.unlink(path)
        raise
    return path


def copy_artifact(source: str, folder: str) -> str:
    with tempfile.TemporaryDirectory(dir=folder, prefix=".trackjudge-") as staging:
        name = os.path.basename(source)
        staged = shutil.copy2(source, os.path.join(staging, name))
        return publish_file(staged, os.path.join(folder, name), unique=True)


def save_spectrogram(result: dict[str, Any], dest_folder: str) -> str | None:
    source = result.get("spectrogram")
    if not source or not os.path.exists(source):
        return None
    destination = copy_artifact(source, dest_folder)
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
