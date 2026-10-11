"""
Windows-only helper that gives Tk windows a faded-green title bar.

Exposes:
    apply_green_titlebar(win)     — apply the color to one specific window.
    install_green_titlebar_hook() — patch Tk so EVERY future Toplevel and
                                    Tk root automatically gets the green
                                    bar the moment it's created. Call once
                                    at app startup.
"""

import sys
import ctypes


TITLEBAR_COLOR_RGB = (0xA9, 0xC9, 0xA4)   # #A9C9A4 (faded green)


def _rgb_to_bgr_int(rgb):
    r, g, b = rgb
    return (b << 16) | (g << 8) | r


def apply_green_titlebar(win):
    """Apply the faded-green caption color if the OS supports it.

    Only uses DWMWA_CAPTION_COLOR (35) and DWMWA_TEXT_COLOR (36), which
    are available on Windows 11 (build 22000+) and Windows 10 19045+.
    On older builds, the calls silently do nothing and the bar keeps
    the OS default (light) color.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if not hwnd:
            hwnd = win.winfo_id()

        color = ctypes.c_int(_rgb_to_bgr_int(TITLEBAR_COLOR_RGB))

        # 35 = DWMWA_CAPTION_COLOR
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 35, ctypes.byref(color), ctypes.sizeof(color))
        except Exception:
            pass

        # 36 = DWMWA_TEXT_COLOR — dark text for readability
        try:
            text = ctypes.c_int(_rgb_to_bgr_int((0x00, 0x00, 0x00)))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 36, ctypes.byref(text), ctypes.sizeof(text))
        except Exception:
            pass

        # Force a redraw of the non-client area.
        try:
            ctypes.windll.user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                0x0002 | 0x0004 | 0x0020)
        except Exception:
            pass
    except Exception:
        pass


_HOOK_INSTALLED = False


def install_green_titlebar_hook():
    """Patch tkinter so every new Toplevel and Tk root gets the green bar.

    Safe to call multiple times — installs the hook only once.
    """
    global _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    if not sys.platform.startswith("win"):
        _HOOK_INSTALLED = True
        return

    try:
        import tkinter as tk
    except Exception:
        return

    # ---- patch Toplevel ----
    original_toplevel_init = tk.Toplevel.__init__

    def patched_toplevel_init(self, *args, **kwargs):
        original_toplevel_init(self, *args, **kwargs)
        try:
            self.after(120, lambda w=self: apply_green_titlebar(w))
        except Exception:
            pass

    tk.Toplevel.__init__ = patched_toplevel_init

    # ---- patch Tk root ----
    original_tk_init = tk.Tk.__init__

    def patched_tk_init(self, *args, **kwargs):
        original_tk_init(self, *args, **kwargs)
        try:
            self.after(120, lambda w=self: apply_green_titlebar(w))
        except Exception:
            pass

    tk.Tk.__init__ = patched_tk_init

    _HOOK_INSTALLED = True