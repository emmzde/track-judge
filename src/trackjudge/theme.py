from __future__ import annotations

# Single-theme tokens sampled from must.jpg.  Tk does not support alpha
# colours, so every translucent reference state is flattened here and screen
# code consumes semantic names only.
CORE_COLORS = {
    "canvas": "#E5F1FD",
    "surface": "#F7F6F2",
    "surface_muted": "#EFEEE9",
    "ink": "#171717",
    "muted": "#74757D",
    "sidebar": "#222222",
    "sidebar_muted": "#8E8E8E",
    "portfolio": "#E5F1FD",
    "asset_lilac": "#E5DEF0",
    "asset_mint": "#D6EDD9",
    "asset_sand": "#F6F0D8",
    "action": "#A9D7F8",
    "positive": "#278B63",
}


def blend(foreground: str, background: str, opacity: float) -> str:
    foreground_rgb = tuple(int(foreground[index : index + 2], 16) for index in (1, 3, 5))
    background_rgb = tuple(int(background[index : index + 2], 16) for index in (1, 3, 5))
    channels = (
        round(foreground_channel * opacity + background_channel * (1 - opacity))
        for foreground_channel, background_channel in zip(
            foreground_rgb,
            background_rgb,
            strict=True,
        )
    )
    return "#" + "".join(f"{channel:02X}" for channel in channels)


def _darken(color: str, opacity: float) -> str:
    return blend("#000000", color, opacity)


def build_theme_colors() -> dict[str, str]:
    semantic = dict(CORE_COLORS)
    return {
        **semantic,
        "window": semantic["surface"],
        "title_bar": semantic["surface"],
        "surface_raised": semantic["surface_muted"],
        "surface_subtle": semantic["surface_muted"],
        "field": semantic["surface"],
        "field_disabled": blend(semantic["ink"], semantic["surface"], 0.04),
        "border": blend(semantic["ink"], semantic["surface"], 0.10),
        "divider": blend(semantic["ink"], semantic["surface"], 0.08),
        "border_strong": blend(semantic["ink"], semantic["surface"], 0.18),
        "text": semantic["ink"],
        "text_secondary": semantic["muted"],
        "text_muted": semantic["muted"],
        "text_disabled": blend(semantic["muted"], semantic["surface"], 0.48),
        "accent": semantic["ink"],
        "accent_hover": _darken(semantic["ink"], 0.08),
        "accent_pressed": _darken(semantic["ink"], 0.16),
        "accent_text": semantic["surface"],
        "accent_secondary": blend(semantic["ink"], semantic["surface"], 0.48),
        "accent_fill": blend(semantic["action"], semantic["surface"], 0.40),
        "accent_soft": semantic["action"],
        "accent_faint": blend(semantic["action"], semantic["surface"], 0.34),
        "focus": semantic["action"],
        "success": semantic["positive"],
        "success_surface": blend(semantic["positive"], semantic["surface"], 0.10),
        "warning": semantic["ink"],
        "error": semantic["ink"],
        "critical": semantic["ink"],
        "error_surface": semantic["asset_sand"],
        "selection": semantic["action"],
        "overlay": blend("#000000", semantic["surface"], 0.72),
        "overlay_shadow": blend("#000000", semantic["surface"], 0.22),
        "hover": blend(semantic["ink"], semantic["surface"], 0.05),
        "selected": blend(semantic["surface"], semantic["sidebar"], 0.10),
        "table_header": semantic["surface"],
        "result": semantic["sidebar"],
        "result_text": semantic["surface"],
        "result_muted": blend(semantic["surface"], semantic["sidebar"], 0.68),
        "action_hover": _darken(semantic["action"], 0.06),
    }


SPACING = {
    0: 0,
    1: 4,
    2: 8,
    3: 12,
    4: 16,
    5: 24,
    6: 32,
    7: 40,
    8: 48,
    9: 64,
}

RADII = {"sm": 4, "md": 12, "lg": 20, "full": 999}

SIZES = {
    "window_width": 1120,
    "window_height": 720,
    "window_min_width": 980,
    "window_min_height": 660,
    "top_bar": 68,
    "sidebar": 84,
    "button": 36,
    "compact_button": 30,
    "input": 36,
    "icon": 20,
    "compact_icon": 16,
    "status_dot": 8,
    "progress": 4,
    "kpi_min_height": 72,
    "portfolio_height": 194,
    "plot_min_height": 220,
    "analysis_height": 300,
    "analysis_summary_height": 112,
    "table_min_height": 250,
    "table_header": 28,
    "table_row": 42,
    "analysis_breakpoint": 980,
    "language_menu": 160,
    "modal_width": 600,
    "modal_height": 340,
    "source_rows": 4,
    "log_rows": 5,
    "narrow_wrap": 244,
    "analysis_wrap": 820,
    "spectrogram_width": 520,
    "spectrogram_height": 236,
    "focus_ring": 3,
    "stroke": 2,
}

BASE_FONT_METRICS = {
    "screen_title": (22, 28),
    "panel_title": (16, 22),
    "metric": (24, 30),
    "body": (13, 19),
    "label": (10, 14),
}

FONTS = {
    "screen_title": {"size": -22, "weight": "normal", "line_height": 28},
    "panel_title": {"size": -16, "weight": "normal", "line_height": 22},
    "metric": {"size": -24, "weight": "normal", "line_height": 30},
    "body": {"size": -13, "weight": "normal", "line_height": 19},
    "label": {"size": -10, "weight": "normal", "line_height": 14},
}

FONTS.update(
    {
        "display": FONTS["screen_title"],
        "heading": FONTS["panel_title"],
        "app_title": FONTS["screen_title"],
        "section_title": FONTS["panel_title"],
        "result_title": FONTS["panel_title"],
        "body_large": FONTS["body"],
        "control": FONTS["body"],
        "control_strong": FONTS["body"] | {"weight": "bold"},
        "caption": FONTS["label"],
        "technical": FONTS["label"],
    }
)


def apply_font_scale(scale: float) -> None:
    """Apply a deterministic physical-pixel typography scale before rebuilding the UI."""
    safe_scale = max(1.0, min(1.35, float(scale)))
    for role, (base_size, base_line_height) in BASE_FONT_METRICS.items():
        FONTS[role]["size"] = -round(base_size * safe_scale)
        FONTS[role]["line_height"] = round(base_line_height * safe_scale)
    for alias, source in (
        ("display", "screen_title"),
        ("heading", "panel_title"),
        ("app_title", "screen_title"),
        ("section_title", "panel_title"),
        ("result_title", "panel_title"),
        ("body_large", "body"),
        ("control", "body"),
        ("caption", "label"),
        ("technical", "label"),
    ):
        FONTS[alias] = FONTS[source]
    FONTS["control_strong"] = FONTS["body"] | {"weight": "normal"}
