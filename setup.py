"""Build the offline frontend for wheels produced directly from a source checkout."""

import shutil
import subprocess
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
CLIENT = ROOT / "frontend"
STATIC = ROOT / "src" / "trackjudge" / "desktop" / "static"


class DesktopBuild(build_py):
    def run(self):
        entry = STATIC / "index.html"
        sources = [
            CLIENT / name
            for name in ("package.json", "package-lock.json", "index.html", "vite.config.js")
        ]
        sources.extend(
            p
            for directory in ("src", "public")
            for p in (CLIENT / directory).rglob("*")
            if p.is_file()
        )
        sources.append(ROOT / "src" / "trackjudge" / "tokens.css")
        if not entry.exists() or any(p.stat().st_mtime > entry.stat().st_mtime for p in sources):
            npm = shutil.which("npm.cmd") or shutil.which("npm")
            if not npm:
                raise RuntimeError("Building the desktop interface requires Node.js 24 and npm.")
            subprocess.run([npm, "ci"], cwd=CLIENT, check=True)
            subprocess.run([npm, "run", "build"], cwd=CLIENT, check=True)
        super().run()


setup(cmdclass={"build_py": DesktopBuild})
