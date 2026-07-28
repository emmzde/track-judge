# Third-party notices

TrackJudge is distributed under the MIT License. Portable builds also contain
third-party software under their respective licenses.

## Python dependencies

- Python — Python Software Foundation License
- NumPy — BSD-3-Clause
- SciPy — BSD-3-Clause
- Rich — MIT
- Matplotlib — PSF-based license
- PyInstaller bootloader — GPL-2.0-or-later with a special exception that
  permits distribution of bundled applications

The corresponding package versions are recorded in `BUILD_INFO.txt` inside
each portable build.

## yt-dlp

Portable Windows builds contain the official `yt-dlp.exe` release
`2026.07.04`.

- Project: https://github.com/yt-dlp/yt-dlp
- Source tag: https://github.com/yt-dlp/yt-dlp/tree/2026.07.04
- License: https://github.com/yt-dlp/yt-dlp/blob/2026.07.04/LICENSE

The executable includes its own compiled third-party license information.

## FFmpeg

Portable Windows builds contain the Gyan release essentials build of
FFmpeg `8.1.2`. That build is licensed under GPLv3.

- Binary build: https://www.gyan.dev/ffmpeg/builds/
- Corresponding FFmpeg source:
  https://github.com/FFmpeg/FFmpeg/commit/38b88335f9
- FFmpeg license information: https://ffmpeg.org/legal.html
- GNU GPL version 3: https://www.gnu.org/licenses/gpl-3.0.html

The portable archive includes the README and license files shipped with the
FFmpeg binary package. TrackJudge invokes FFmpeg as a separate executable.
