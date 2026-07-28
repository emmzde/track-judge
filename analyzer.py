"""Backward-compatible entry point for the original single-file script."""

import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
    from trackjudge.app import main as package_main

    return package_main()


if __name__ == "__main__":
    raise SystemExit(main())
