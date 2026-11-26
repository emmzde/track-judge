from __future__ import annotations

from importlib.util import find_spec
from threading import Lock

import numpy as np

from .theme import build_theme_colors

HAS_MPL = find_spec("matplotlib") is not None
_RENDER_LOCK = Lock()
FAKE_GAP_HZ = 1500.0


def render_spectrogram(*args, **kwargs) -> None:
    # Matplotlib font and layout caches are shared between worker threads.
    with _RENDER_LOCK:
        _render(*args, **kwargs)


def _render(
    f: np.ndarray,
    t: np.ndarray,
    Sxx: np.ndarray,
    ref_level: float,
    nyq: float,
    eff_cutoff: float,
    raw_cutoff: float,
    fake_noise: bool,
    out_path: str,
    title: str,
) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.figure import Figure
    from matplotlib.ticker import MultipleLocator

    # Децимация по времени, чтобы PNG был лёгким.
    max_cols = 1600
    if Sxx.shape[1] > max_cols:
        step = Sxx.shape[1] // max_cols + 1
        Sxx = Sxx[:, ::step]
        t = t[::step]

    db = 10.0 * np.log10(np.maximum(Sxx, 1e-20) / max(ref_level, 1e-20))

    colors = build_theme_colors()
    heading_size = 12
    label_size = 9
    spectrum_map = LinearSegmentedColormap.from_list(
        "trackjudge-spectrum",
        (
            colors["canvas"],
            colors["spectrum_low"],
            colors["accent"],
            colors["ink"],
        ),
    )

    fig = Figure(figsize=(11, 5), dpi=220, facecolor=colors["surface"])
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.set_facecolor(colors["surface"])
    half_bin = (f[1] - f[0]) / 2000
    dt = (t[1] - t[0]) / 2 if len(t) > 1 else t[0]
    mesh = ax.imshow(
        db,
        origin="lower",
        aspect="auto",
        interpolation="nearest",
        extent=(t[0] - dt, t[-1] + dt, f[0] / 1000 - half_bin, f[-1] / 1000 + half_bin),
        cmap=spectrum_map,
        vmin=-90.0,
        vmax=10.0,
    )
    ax.axhline(
        eff_cutoff / 1000.0,
        color=colors["accent"],
        lw=2.0,
        ls="--",
        label=f"живой срез {eff_cutoff / 1000:.1f} кГц",
    )
    if raw_cutoff - eff_cutoff > FAKE_GAP_HZ:
        ax.axhline(
            raw_cutoff / 1000.0,
            color=colors["muted"],
            lw=2.0,
            ls=":",
            label=f"край энергии {raw_cutoff / 1000:.1f} кГц",
        )
    ax.set_ylim(0, nyq / 1000.0)
    ax.set_xlabel("Время, с", color=colors["ink"])
    ax.set_ylabel("Частота, кГц", color=colors["ink"])
    ax.yaxis.set_major_locator(MultipleLocator(2))
    ax.grid(color=colors["border"], linewidth=1.0)
    ax.tick_params(colors=colors["muted"])
    for spine in ax.spines.values():
        spine.set_color(colors["border"])
    suffix = "  [ФЕЙКОВЫЕ ВЧ]" if fake_noise else ""
    ax.set_title(
        f"{title}{suffix}",
        fontsize=heading_size,
        color=colors["critical"] if fake_noise else colors["ink"],
    )
    legend = ax.legend(
        loc="upper right",
        fontsize=label_size,
        facecolor=colors["surface"],
        edgecolor=colors["border"],
        framealpha=1.0,
        labelcolor=colors["ink"],
    )
    legend.get_frame().set_linewidth(1.0)
    colorbar = fig.colorbar(mesh, ax=ax)
    colorbar.set_label("дБ отн. опоры", color=colors["ink"])
    colorbar.ax.tick_params(colors=colors["muted"])
    colorbar.outline.set_edgecolor(colors["border"])
    fig.tight_layout()
    fig.savefig(out_path, facecolor=colors["surface"])
