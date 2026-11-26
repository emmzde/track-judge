from __future__ import annotations

import json
import shutil
import tempfile
import threading
from collections import deque
from pathlib import Path
from uuid import uuid4

import numpy as np
from scipy.io import wavfile

from ..app import MAX_URLS, default_dest_folder, run_analysis
from ..console import configure_console
from ..media import copy_artifact, unique_dest_path
from .model import GuiRunConfig, build_gui_namespace, candidate_explanation


class LogBuffer:
    """Line-oriented Rich sink with bounded storage, shared by DSP workers."""

    def __init__(self):
        self._lines = deque(maxlen=600)
        self._partial = ""
        self._lock = threading.Lock()

    def write(self, value: str) -> int:
        with self._lock:
            *lines, self._partial = (self._partial + value.replace("\r", "")).split("\n")
            self._lines.extend(line.rstrip() for line in lines if line.strip())
        return len(value)

    def flush(self):
        with self._lock:
            if self._partial.strip():
                self._lines.append(self._partial)
            self._partial = ""

    def lines(self):
        with self._lock:
            return list(self._lines)


class ComparisonSession:
    def __init__(self):
        self.folder = default_dest_folder()
        self._lock = threading.RLock()
        self._temp = tempfile.TemporaryDirectory(prefix="trackjudge-desktop-")
        self._job = None
        self._worker = None
        self._closing = False
        self._files = {}
        self._log = LogBuffer()
        self._state = "idle"
        self._error = ""
        self._result = None
        self._report = None

    def snapshot(self):
        with self._lock:
            return dict(
                status=self._state,
                error=self._error,
                result=self._result,
                log=self._log.lines(),
                folder=self.folder,
            )

    def start(self, sources: list[str], folder: str, spectrum: bool, report: bool, cookies: bool):
        if not 1 <= len(sources) <= MAX_URLS or not folder.strip():
            raise ValueError("Укажите папку и от одного до пяти источников.")
        if any(
            not (source.lower().startswith(("https://", "http://")) or Path(source).is_file())
            for source in sources
        ):
            raise ValueError("Источник должен быть веб-ссылкой или существующим файлом.")
        with self._lock:
            if self._state == "running" or self._closing:
                raise RuntimeError("Сравнение уже запущено.")
            self.folder = str(Path(folder).expanduser().resolve())
            self._files.clear()
            if self._job:
                # A media range response can briefly retain a handle on Windows.
                shutil.rmtree(self._job, ignore_errors=True)
            self._job = Path(tempfile.mkdtemp(dir=self._temp.name))
            self._log = LogBuffer()
            self._state, self._error, self._result, self._report = "running", "", None, None
            config = GuiRunConfig(
                tuple(sources),
                self.folder,
                spectrum,
                report,
                cookies,
                self.folder if report else str(self._job),
            )
            self._worker = threading.Thread(target=self._compare, args=(config,), name="comparison")
            self._worker.start()

    def _register(self, path: Path) -> str:
        key = uuid4().hex
        with self._lock:
            self._files[key] = path
        return "/media/" + key

    def media(self, key):
        with self._lock:
            return self._files.get(key)

    def _compare(self, config: GuiRunConfig):
        previews = {}
        previews_lock = threading.Lock()

        def retain_preview(source, wav, duration):
            # Read peaks from the existing analysis PCM in small blocks.
            _, pcm = wavfile.read(wav, mmap=True)
            buckets = min(1600, len(pcm))
            peaks = [float(np.abs(block).max()) for block in np.array_split(pcm, buckets)]
            del pcm
            path = self._job / (uuid4().hex + ".wav")
            shutil.move(wav, path)
            with previews_lock:
                previews[source] = {
                    "url": self._register(path),
                    "duration": duration,
                    "peaks": peaks,
                }

        state = "error"
        try:
            Path(self.folder).mkdir(parents=True, exist_ok=True)
            report_dir = self.folder if config.save_json_report else str(self._job)
            path = unique_dest_path("trackjudge-report.json", report_dir)
            args = build_gui_namespace(config, path)
            configure_console(True, file=self._log, width=100)
            code = run_analysis(args, preview=retain_preview)
            if code:
                lines = self._log.lines()
                raise RuntimeError(lines[-1] if lines else f"Код завершения {code}")
            result = json.loads(Path(path).read_text(encoding="utf-8"))
            for candidate in result["candidates"]:
                candidate["preview"] = previews.get(candidate["source"])
                candidate["explanation"] = {
                    lang: candidate_explanation(candidate, lang) for lang in ("en", "de", "ru")
                }
                spectrum = candidate.get("saved_spectrogram")
                candidate["image"] = self._register(Path(spectrum)) if spectrum else None
            self._report = path if config.save_json_report else None
            result["report"] = self._report
            self._result = result
            state = "done"
        except Exception as exc:
            self._error = str(exc)
        finally:
            self._log.flush()
            configure_console()
            with self._lock:
                self._state = state

    def allow_close(self) -> bool:
        with self._lock:
            if self._state == "running":
                return False
            self._closing = True
            return True

    def output_path(self, kind: str, rank: int = 0) -> Path | None:
        with self._lock:
            if self._state != "done":
                return None
            paths = {
                "winner": self._result["winner"]["saved_file"],
                "folder": self.folder,
                "report": self._report,
            }
            if kind == "spectrum" and 1 <= rank <= len(self._result["candidates"]):
                paths["spectrum"] = self._result["candidates"][rank - 1]["saved_spectrogram"]
            path = paths.get(kind)
            return Path(path) if path else None

    def save_image(self, rank: int) -> str:
        with self._lock:
            if self._state != "done" or not 1 <= rank <= len(self._result["candidates"]):
                raise ValueError("Спектрограмма недоступна.")
            source = self._result["candidates"][rank - 1]["saved_spectrogram"]
            if not source:
                raise ValueError("Спектрограмма недоступна.")
            return copy_artifact(source, self.folder)

    def close(self):
        with self._lock:
            self._closing = True
            worker = self._worker
        if worker:
            worker.join()
        self._temp.cleanup()
