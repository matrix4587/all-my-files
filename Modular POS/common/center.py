"""
Centering helpers.

Exposes:
    center_window_on_screen(win, width, height)
        Center a Tk window to a specific pixel size.

    install_centering_hook()
        Patch tkinter so every new Toplevel and every new Tk root is
        automatically centered on the screen once it has been laid out.
"""

import tkinter as tk


_CENTER_HOOK_INSTALLED = False


def center_window_on_screen(win, width, height):
    """Center a window on the primary screen at the given size."""
    try:
        win.update_idletasks()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw - width) // 2)
        y = max(0, (sh - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")
    except Exception:
        pass


def _center_preserving_size(win, attempts_left=40):
    """Move a window to the screen center without changing its size.

    Waits until the window reports a real size (>= 2 px in each direction)
    before centering. Retries every 60 ms up to `attempts_left` times.
    """
    try:
        win.update_idletasks()
    except Exception:
        return

    # Skip maximized / fullscreen windows.
    try:
        if win.state() == "zoomed":
            return
    except Exception:
        pass
    try:
        if win.attributes("-fullscreen"):
            return
    except Exception:
        pass

    w = win.winfo_width()
    h = win.winfo_height()

    # Not laid out yet — try again shortly.
    if (w <= 2 or h <= 2) and attempts_left > 0:
        try:
            win.after(60, lambda: _center_preserving_size(
                win, attempts_left - 1))
        except Exception:
            pass
        return

    try:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        win.geometry(f"+{x}+{y}")
    except Exception:
        pass


def install_centering_hook():
    """Patch tkinter so every new Toplevel and Tk root is centered.

    Safe to call multiple times — installs once.
    """
    global _CENTER_HOOK_INSTALLED
    if _CENTER_HOOK_INSTALLED:
        return
    _CENTER_HOOK_INSTALLED = True

    # --- patch Toplevel ---
    original_toplevel_init = tk.Toplevel.__init__

    def patched_toplevel_init(self, *args, **kwargs):
        original_toplevel_init(self, *args, **kwargs)
        try:
            # Defer so the caller has a chance to set geometry() first;
            # _center_preserving_size will wait until the window has a
            # real size before moving it.
            self.after(60, lambda w=self: _center_preserving_size(w))
        except Exception:
            pass

    tk.Toplevel.__init__ = patched_toplevel_init

    # --- patch Tk root ---
    original_tk_init = tk.Tk.__init__

    def patched_tk_init(self, *args, **kwargs):
        original_tk_init(self, *args, **kwargs)
        try:
            self.after(60, lambda w=self: _center_preserving_size(w))
        except Exception:
            pass

    tk.Tk.__init__ = patched_tk_init