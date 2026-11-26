"""PLY-based pycparser wheels include parser tables. The recursive-descent parser does not."""

from importlib.util import find_spec

hiddenimports = [name for name in ("pycparser.lextab", "pycparser.yacctab") if find_spec(name)]
