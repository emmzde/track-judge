from __future__ import annotations

import multiprocessing
import os
import sys

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def run() -> int:
    from trackjudge.gui import main

    return main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(run())
