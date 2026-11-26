from __future__ import annotations

import threading

from rich.console import Console

_PRINT_LOCK = threading.Lock()
_CONSOLE = Console()


def log(msg: str) -> None:
    with _PRINT_LOCK:
        _CONSOLE.print(msg, markup=False)


def configure_console(no_color=False, *, file=None, width=None):
    options = {"no_color": no_color}
    if file is not None:
        options.update(file=file, force_terminal=False)
    if width is not None:
        options["width"] = width
    global _CONSOLE
    _CONSOLE = Console(**options)
