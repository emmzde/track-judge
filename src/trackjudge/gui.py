from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser

from . import __version__
from .desktop.model import GuiRunConfig as GuiRunConfig
from .desktop.model import build_gui_namespace as build_gui_namespace
from .desktop.model import candidate_explanation as candidate_explanation
from .desktop.model import extract_sources
from .desktop.model import shorten_path as shorten_path


class DesktopAPI:
    def __init__(self, session, sources):
        self._session = session
        self._sources = sources
        self._window = None
        self._chrome = None

    def initialize(self):
        return {
            "sources": self._sources,
            "folder": self._session.folder,
            "version": __version__,
            "custom_caption": bool(self._chrome and self._chrome.enabled),
            "maximized": bool(self._chrome and self._chrome.is_maximized()),
        }

    def window_action(self, action):
        if self._chrome:
            self._chrome.perform(action)

    def status(self):
        return self._session.snapshot()

    def start(self, sources, folder, spectrum, report, cookies):
        self._session.start(sources, folder, spectrum, report, cookies)

    def links(self, text):
        return extract_sources(text)

    def choose(self, kind):
        from webview import FileDialog

        if kind == "folder":
            paths = self._window.create_file_dialog(FileDialog.FOLDER)
        else:
            paths = self._window.create_file_dialog(
                FileDialog.OPEN,
                allow_multiple=True,
                file_types=(
                    "Audio (*.wav;*.flac;*.mp3;*.m4a;*.opus;*.ogg;*.aif;*.aiff;*.webm;*.aac;*.wma)",
                    "All files (*.*)",
                ),
            )
        return list(paths or ())

    def open_output(self, kind, rank=0):
        path = self._session.output_path(kind, rank)
        if not path or not path.exists():
            raise FileNotFoundError("Файл недоступен.")
        if kind == "winner" and path.suffix.lower() not in {
            ".wav",
            ".flac",
            ".mp3",
            ".m4a",
            ".opus",
            ".ogg",
            ".aif",
            ".aiff",
            ".webm",
            ".aac",
            ".wma",
            ".mp4",
            ".mka",
            ".mkv",
            ".ape",
            ".alac",
            ".wv",
            ".caf",
            ".aifc",
            ".oga",
        }:
            path = path.parent
        if os.name == "nt":
            os.startfile(path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])

    def save_spectrum(self, rank):
        return self._session.save_image(rank)

    def project(self):
        webbrowser.open("https://github.com/emmzde/track-judge")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] in (["--headless"], ["--help"], ["-h"], ["--version"]):
        from .app import main as cli_main

        return cli_main(arguments[1:] if arguments[0] == "--headless" else arguments)

    from .desktop.dpi import enable_per_monitor_dpi

    enable_per_monitor_dpi()
    import webview

    from .desktop.server import STATIC, application
    from .desktop.session import ComparisonSession
    from .theme import build_theme_colors

    if not (STATIC / "index.html").is_file():
        raise RuntimeError("Соберите интерфейс командой npm --prefix frontend run build.")
    smoke = (
        arguments[0]
        if arguments and arguments[0].startswith("--gui-") and arguments[0].endswith("-smoke-test")
        else ""
    )
    if arguments == ["--gui-smoke-test"]:
        smoke = arguments[0]
    session = ComparisonSession()
    api = DesktopAPI(session, [] if smoke else arguments)
    webview.settings["ALLOW_FILE_URLS"] = False
    window = webview.create_window(
        "TrackJudge",
        application(session),
        js_api=api,
        width=1220,
        height=820,
        min_size=(460, 500),
        background_color=build_theme_colors()["canvas"],
        text_select=True,
        easy_drag=False,
    )
    api._window = window
    if os.name == "nt":
        from .desktop.window_chrome import WindowsChrome

        api._chrome = WindowsChrome(window)
    window.events.closing += session.allow_close
    passed = threading.Event()

    def smoke_test():
        try:
            for _ in range(160):
                if window.evaluate_js("Boolean(document.querySelector('[data-ready]'))"):
                    break
                time.sleep(0.1)
            else:
                return
            if smoke == "--gui-paste-smoke-test":
                window.evaluate_js("""document.querySelector('[data-links]').click()""")
                for _ in range(30):
                    if window.evaluate_js("Boolean(document.querySelector('textarea'))"):
                        break
                    time.sleep(0.1)
                window.evaluate_js("""const t=document.querySelector('textarea');
                    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(t,'https://one.test/https://two.test/');
                    t.dispatchEvent(new Event('input',{bubbles:true}));""")
                window.evaluate_js("document.querySelector('[data-add-links]').click()")
                for _ in range(50):
                    if window.evaluate_js("document.querySelectorAll('[data-source]').length===2"):
                        break
                    time.sleep(0.1)
                else:
                    return
            passed.set()
        finally:
            window.destroy()

    try:
        webview.start(
            smoke_test if smoke else None,
            gui="edgechromium" if os.name == "nt" else None,
            icon=str(
                STATIC / "brand" / ("trackjudge.ico" if os.name == "nt" else "trackjudge.png")
            ),
        )
    finally:
        session.close()
    return int(bool(smoke) and not passed.is_set())


if __name__ == "__main__":
    raise SystemExit(main())
