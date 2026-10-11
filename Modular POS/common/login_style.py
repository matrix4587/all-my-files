"""
Shared visual style for login screens.

Draws a soft two-tone background, a white rounded card, and a circular
avatar with a person glyph — all with tk.Canvas primitives so we don't
need Pillow or any new dependency.
"""

import os
import tkinter as tk
from tkinter import ttk


# ---- palette (match the mockup) ---------------------------------------
BG_TOP       = "#e9f3ec"
BG_BOTTOM    = "#dbe6ef"
CARD_BG      = "#ffffff"
FIELD_BG     = "#d9dde3"
FIELD_TEXT   = "#1f2d4a"
PLACEHOLDER  = "#6b7280"
BTN_BG       = "#1f2d4a"
BTN_TEXT     = "#ffffff"
LINK_TEXT    = "#1f2d4a"
AVATAR_BG    = "#1f2d4a"
AVATAR_RING  = "#c7d2dd"
AVATAR_GLYPH = "#ffffff"


def draw_soft_background(canvas, w, h):
    bands = [
        (0.00, BG_TOP),
        (0.45, "#e2ecf0"),
        (1.00, BG_BOTTOM),
    ]
    prev_y = 0
    prev_color = bands[0][1]
    for frac, color in bands[1:]:
        y = int(h * frac)
        canvas.create_rectangle(0, prev_y, w, y,
                                fill=prev_color, outline="",
                                tags=("bg",))
        prev_y = y
        prev_color = color
    canvas.create_rectangle(0, prev_y, w, h,
                            fill=prev_color, outline="", tags=("bg",))


def draw_rounded_card(canvas, x0, y0, x1, y1,
                      radius=18, fill=CARD_BG, outline="",
                      tags=("card",)):
    canvas.create_arc(x0, y0, x0 + 2 * radius, y0 + 2 * radius,
                      start=90, extent=90, fill=fill, outline=outline,
                      style="pieslice", tags=tags)
    canvas.create_arc(x1 - 2 * radius, y0, x1, y0 + 2 * radius,
                      start=0, extent=90, fill=fill, outline=outline,
                      style="pieslice", tags=tags)
    canvas.create_arc(x0, y1 - 2 * radius, x0 + 2 * radius, y1,
                      start=180, extent=90, fill=fill, outline=outline,
                      style="pieslice", tags=tags)
    canvas.create_arc(x1 - 2 * radius, y1 - 2 * radius, x1, y1,
                      start=270, extent=90, fill=fill, outline=outline,
                      style="pieslice", tags=tags)
    canvas.create_rectangle(x0 + radius, y0, x1 - radius, y1,
                            fill=fill, outline="", tags=tags)
    canvas.create_rectangle(x0, y0 + radius, x1, y1 - radius,
                            fill=fill, outline="", tags=tags)


def draw_avatar(canvas, cx, cy, r):
    canvas.create_oval(cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4,
                       fill=AVATAR_RING, outline="")
    canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                       fill=AVATAR_BG, outline="")
    head_r = r * 0.30
    canvas.create_oval(cx - head_r, cy - r * 0.55,
                       cx + head_r, cy - r * 0.55 + 2 * head_r,
                       fill=AVATAR_GLYPH, outline="")
    canvas.create_arc(cx - r * 0.60, cy - r * 0.05,
                      cx + r * 0.60, cy + r * 0.95,
                      start=0, extent=180,
                      fill=AVATAR_GLYPH, outline="",
                      style="pieslice")


class FlatButton(tk.Label):
    """A click-through Label styled like a flat button."""

    def __init__(self, master, text, command,
                 bg=BTN_BG, fg=BTN_TEXT, width=40, height=2,
                 hover_bg=None, **kw):
        super().__init__(master, text=text, bg=bg, fg=fg,
                         font=("Arial", 11, "bold"),
                         width=width, height=height,
                         cursor="hand2", **kw)
        self._bg = bg
        self._hover = hover_bg or self._shift(bg, -10)
        self._command = command
        self.bind("<Button-1>", lambda e: self._command())
        self.bind("<Enter>", lambda e: self.configure(bg=self._hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self._bg))

    @staticmethod
    def _shift(hex_color, delta):
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
        r = max(0, min(255, r + delta))
        g = max(0, min(255, g + delta))
        b = max(0, min(255, b + delta))
        return f"#{r:02x}{g:02x}{b:02x}"


class FieldWithIcon(tk.Frame):
    """Horizontal frame: small icon on the left, then an Entry, styled
    as a grey input bar. `bar_pady` adds vertical padding inside the bar
    so the input reads as a comfortable pill."""

    def __init__(self, master, glyph, show=None,
                 bg=CARD_BG, field_bg=FIELD_BG,
                 placeholder="", bar_pady=6):
        super().__init__(master, bg=bg)

        self.bar = tk.Frame(self, bg=field_bg)
        self.bar.pack(fill="x")

        self.icon = tk.Label(self.bar, text=glyph, bg=field_bg,
                             fg=PLACEHOLDER,
                             font=("Segoe UI Emoji", 12),
                             padx=10)
        self.icon.pack(side="left", pady=bar_pady)

        self.var = tk.StringVar()
        self.entry = tk.Entry(self.bar, textvariable=self.var,
                              bd=0, relief="flat",
                              bg=field_bg, fg=FIELD_TEXT,
                              insertbackground=FIELD_TEXT,
                              font=("Arial", 11),
                              show=show)
        self.entry.pack(side="left", fill="x", expand=True,
                        ipady=bar_pady, padx=(0, 10))

        self._placeholder = placeholder
        if placeholder:
            self._add_placeholder()

    def _add_placeholder(self):
        self._ph_on = False
        if not self.var.get():
            self._show_ph()
        self.entry.bind("<FocusIn>", self._clear_ph)
        self.entry.bind("<FocusOut>", self._restore_ph)

    def _show_ph(self):
        self._ph_on = True
        self.entry.configure(fg=PLACEHOLDER)
        self.var.set(self._placeholder)

    def _clear_ph(self, *_):
        if self._ph_on:
            self._ph_on = False
            self.var.set("")
            self.entry.configure(fg=FIELD_TEXT)

    def _restore_ph(self, *_):
        if not self.var.get():
            self._show_ph()

    def get(self):
        return "" if self._ph_on else self.var.get()

    def set(self, value):
        self._clear_ph()
        self.var.set(value)

    def focus(self):
        self.entry.focus_set()