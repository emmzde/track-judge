from __future__ import annotations

import multiprocessing
import os
import sys


def _redirect_unstable_standard_streams() -> None:
    arguments = sys.argv[1:]
    detached_cli = bool(
        arguments
        and (arguments[0] == "--headless" or arguments[0] in {"--help", "--version", "-h"})
    )
    if detached_cli or sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if detached_cli or sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


_redirect_unstable_standard_streams()


def run() -> int:
    from trackjudge.gui import main

    return main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(run())
