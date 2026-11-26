"""Read the same palette used by the desktop stylesheet."""

import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def build_theme_colors() -> dict[str, str]:
    sheet = Path(__file__).with_name("tokens.css").read_text(encoding="utf-8")
    return {
        key.replace("-", "_"): value
        for key, value in re.findall(r"--([\w-]+):\s*(#[\da-fA-F]{6});", sheet)
    }
