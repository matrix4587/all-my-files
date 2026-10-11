"""Temporary test — verifies the common package imports cleanly."""

from common.paths import APP_DIR
from common.titlebar import apply_green_titlebar
from common.center import center_window_on_screen
from common.icons import load_icon, make_button_icon
from common.code128 import code128_encode

print("APP_DIR =", APP_DIR)

# Test the code128 encoder with a known input.
bits = code128_encode("1001")
print("code128('1001') length =", len(bits))
print("first 40 bits:", bits[:40])
print("last 20 bits: ", bits[-20:])

# Test that titlebar + center import without any side effect.
print("Imports OK")

# Quick Tk smoke test — open a window, center it, close it.
import tkinter as tk
root = tk.Tk()
root.title("common package smoke test")
center_window_on_screen(root, 400, 200)
apply_green_titlebar(root)
root.after(800, root.destroy)
root.mainloop()
print("Tk smoke test OK")