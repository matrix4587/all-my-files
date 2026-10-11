"""
Icon loading and ribbon-button icon preparation.

All PNG icon files live in `common/icons/`, which is a sibling folder
to this file. This keeps image assets separate from the .py source code.
"""

import os
import tkinter as tk

from .paths import APP_DIR

ICON_MAX_SIZE = 20
ICON_PADDING = 4
ICON_CANVAS_SIZE = ICON_MAX_SIZE + (ICON_PADDING * 2)


def icons_dir():
    """Return the folder where icon PNGs live.

    When running from source, this is `<APP_DIR>/common/icons/`.
    When packaged as a .exe, PyInstaller will copy that folder next to
    the .exe (or into _MEIPASS), so we resolve from APP_DIR either way.
    """
    return os.path.join(APP_DIR, "common", "icons")


def load_icon(filename, max_size=ICON_MAX_SIZE):
    path = os.path.join(icons_dir(), filename)
    try:
        img = tk.PhotoImage(file=path)
        longest_side = max(img.width(), img.height())
        if longest_side > max_size:
            factor = -(-longest_side // max_size)  # ceil division
            img = img.subsample(factor, factor)
        return img
    except Exception as e:
        print(f"Could not load icon '{filename}':", e)
        return None


def make_button_icon(icon, canvas_size=ICON_CANVAS_SIZE):
    if icon is None:
        return None
    try:
        canvas = tk.PhotoImage(width=canvas_size, height=canvas_size)
        canvas.put("white", to=(0, 0, canvas_size, canvas_size))

        icon_w, icon_h = icon.width(), icon.height()
        x = max(0, (canvas_size - icon_w) // 2)
        y = max(0, (canvas_size - icon_h) // 2)

        canvas.tk.call(canvas, "copy", icon, "-to", x, y, x + icon_w, y + icon_h,
                        "-compositingrule", "overlay")
        return canvas
    except Exception as e:
        print("Could not build padded button icon:", e)
        return icon