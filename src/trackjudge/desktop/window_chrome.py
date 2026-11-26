"""Windows caption integration for the WebView2 desktop window."""

import ctypes
import logging
from ctypes import wintypes

_GWL_STYLE = -16
_WS_CAPTION = 0x00C00000
_SWP_FRAMECHANGED = 0x0020
_SWP_KEEP_BOUNDS = 0x0017  # NOSIZE | NOMOVE | NOZORDER | NOACTIVATE


class WindowsChrome:
    def __init__(self, window):
        self.enabled = False
        self._window = window
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.GetWindowLongW.restype = ctypes.c_long
        self._user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
        self._user32.SetWindowLongW.restype = ctypes.c_long
        self._user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self._user32.SetWindowPos.restype = wintypes.BOOL
        self._user32.IsZoomed.argtypes = [wintypes.HWND]
        self._user32.IsZoomed.restype = wintypes.BOOL
        window.events.before_show += self._prepare
        window.events.maximized += self._notify_state
        window.events.restored += self._notify_state

    def _prepare(self, window):
        control = window.native.webview
        host_ready = getattr(window.native.browser, "on_webview_ready", None)
        if host_ready and hasattr(control, "CoreWebView2InitializationCompleted"):
            # Region settings apply at navigation time. Set them before the host
            # starts loading the page in its initialization callback.
            control.CoreWebView2InitializationCompleted -= host_ready
            control.CoreWebView2InitializationCompleted += self._on_webview_ready
            control.CoreWebView2InitializationCompleted += host_ready

    def _on_webview_ready(self, sender, args):
        if not args.IsSuccess:
            return
        settings = sender.CoreWebView2.Settings
        try:
            settings.IsNonClientRegionSupportEnabled = True
        except Exception as exc:
            logging.getLogger(__name__).debug("WebView2 caption regions unavailable: %s", exc)
            return

        hwnd = self._window.native.Handle.ToInt64()
        style = self._user32.GetWindowLongW(hwnd, _GWL_STYLE)
        # Keep the sizing border and system commands while removing the caption itself.
        previous_style = self._user32.SetWindowLongW(hwnd, _GWL_STYLE, style & ~_WS_CAPTION)
        if not previous_style:
            return
        if not self._user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0, _SWP_KEEP_BOUNDS | _SWP_FRAMECHANGED
        ):
            self._user32.SetWindowLongW(hwnd, _GWL_STYLE, previous_style)
            return
        self.enabled = True

    def is_maximized(self):
        return self.enabled and bool(self._user32.IsZoomed(self._window.native.Handle.ToInt64()))

    def _notify_state(self):
        if self.enabled and self._window.events.loaded.is_set():
            value = "true" if self.is_maximized() else "false"
            self._window.run_js(
                f"window.dispatchEvent(new CustomEvent('trackjudge:window-state', {{detail: {value}}}))"
            )

    def perform(self, action):
        if not self.enabled:
            return
        if action == "minimize":
            self._window.minimize()
        elif action == "toggle-maximize":
            if self.is_maximized():
                self._window.restore()
            else:
                self._window.maximize()
        elif action == "close":
            self._window.destroy()
