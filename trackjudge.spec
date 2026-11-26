from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


PROJECT_ROOT = Path(SPECPATH)

analysis = Analysis(
    [str(PROJECT_ROOT / "packaging" / "portable_entry.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=collect_data_files("webview", subdir="js") + [
        (str(PROJECT_ROOT / "src/trackjudge/tokens.css"), "trackjudge"),
        (str(PROJECT_ROOT / "src/trackjudge/desktop/static"), "trackjudge/desktop/static"),
        (str(PROJECT_ROOT / "README.md"), "."),
        (str(PROJECT_ROOT / "LICENSE"), "."),
        (str(PROJECT_ROOT / "THIRD_PARTY_NOTICES.md"), "."),
    ],
    hiddenimports=collect_submodules("rich._unicode_data"),
    hookspath=[str(PROJECT_ROOT / "packaging" / "hooks")],
    hooksconfig={"matplotlib": {"backends": ["Agg"]}},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "tkinter",
        "webview.platforms.android",
        "webview.platforms.cef",
        "webview.platforms.cocoa",
        "webview.platforms.gtk",
        "webview.platforms.qt",
        "jupyter",
        "lxml",
        "notebook",
        "pandas",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "pytest",
        "sqlalchemy",
    ],
    noarchive=False,
    optimize=1,
)

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="TrackJudge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    icon=str(PROJECT_ROOT / "frontend" / "public" / "brand" / "trackjudge.ico"),
    version=str(PROJECT_ROOT / "packaging" / "windows-version.txt"),
    manifest=str(PROJECT_ROOT / "packaging" / "trackjudge.manifest"),
    uac_admin=False,
    contents_directory="_internal",
)

bundle = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TrackJudge",
)
