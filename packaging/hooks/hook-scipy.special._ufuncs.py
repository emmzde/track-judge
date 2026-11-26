"""Collect the companion extensions shipped by the installed SciPy wheel."""

from importlib.util import find_spec

hiddenimports = [
    name
    for name in (
        "scipy.special._ufuncs_cxx",
        "scipy.special._cdflib",
        "scipy.special._special_ufuncs",
    )
    if find_spec(name) is not None
]
