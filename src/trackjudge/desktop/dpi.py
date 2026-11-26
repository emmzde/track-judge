import ctypes
import sys


def enable_per_monitor_dpi() -> None:
    """Configure source launches before WinForms creates a window handle."""
    if sys.platform != "win32" or getattr(sys, "frozen", False):
        return
    user32 = ctypes.windll.user32
    set_context = getattr(user32, "SetProcessDpiAwarenessContext", None)
    if set_context and set_context(ctypes.c_void_p(-4)):
        return
    # This call also covers Windows versions predating Per-Monitor V2.
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
