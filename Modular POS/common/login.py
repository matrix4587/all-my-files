"""
Login window used at app startup.

Layout:
  - Small soft background.
  - App identity line at the top: "Evans Electronic Shop POSitive".
  - White rounded card hugging its content.
  - Avatar sitting on the top edge of the card.
  - Inside the card: big green "Point of Sale" title.
  - Two grey input bars with icon glyphs.
  - Options row (Remember me / Forgot password?).
  - Navy LOGIN button.
  - Status line under the button.

Calls on_success with {username, password, full_name, branch, role, kind}.
Username field has inline autocomplete against /usernames.
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

import requests

from common.titlebar import apply_green_titlebar
from common import login_style as ls


SERVER = "http://localhost:5000"
USERNAME_DEBOUNCE_MS = 180

REMEMBER_FILE = os.path.join(os.path.expanduser("~"), ".evansshop_login")

APP_TITLE_TOP = "Evans Electronic Shop POSitive"
BRAND_SUB     = "Point of Sale"
BRAND_GREEN   = "#1f6b2e"           # deeper green — readable on white

# ---- geometry knobs ---------------------------------------------------
WIN_W = 480
WIN_H = 500

CARD_W = 360
CARD_H = 300
CARD_X0 = (WIN_W - CARD_W) // 2
CARD_Y0 = 128
CARD_X1 = CARD_X0 + CARD_W
CARD_Y1 = CARD_Y0 + CARD_H

PAD_TOP    = 52
PAD_SIDE   = 26
PAD_BOTTOM = 22


class LoginWindow:
    def __init__(self, on_success, app_title="Login", subtitle=None):
        self.on_success = on_success

        self.root = tk.Tk()
        self.root.title(app_title)
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.resizable(False, False)

        # ---- Canvas base ----
        self.canvas = tk.Canvas(self.root, width=WIN_W, height=WIN_H,
                                 highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        ls.draw_soft_background(self.canvas, WIN_W, WIN_H)

        # ---- Top app title on the background ----
        self.canvas.create_text(
            WIN_W // 2, 34,
            text=APP_TITLE_TOP,
            fill=ls.BTN_BG,
            font=("Arial", 15, "bold"),
            anchor="center")

        # ---- Card + avatar ----
        ls.draw_rounded_card(self.canvas, CARD_X0, CARD_Y0,
                              CARD_X1, CARD_Y1, radius=20)
        ls.draw_avatar(self.canvas, WIN_W // 2, CARD_Y0, r=30)

        try:
            self.root.after(150, lambda: apply_green_titlebar(self.root))
        except Exception:
            pass

        # ---- Content frame inside the card ----
        inner_w = CARD_W - 2 * PAD_SIDE
        content = tk.Frame(self.canvas, bg=ls.CARD_BG)
        self.canvas.create_window(
            CARD_X0 + CARD_W // 2,
            CARD_Y0 + PAD_TOP,
            window=content, width=inner_w, anchor="n")

        # ---- Green brand title ----
        tk.Label(content, text=BRAND_SUB,
                 bg=ls.CARD_BG, fg=BRAND_GREEN,
                 font=("Arial", 14, "bold")).pack(pady=(0, 18))

        # ---- Username ----
        self.user_field = ls.FieldWithIcon(
            content, glyph="\U0001F464", placeholder="Username")
        self.user_field.pack(fill="x", pady=(0, 10))

        # ---- Password ----
        self.pass_field = ls.FieldWithIcon(
            content, glyph="\U0001F512",
            placeholder="Password", show="\u2022")
        self.pass_field.pack(fill="x", pady=(0, 10))

        # ---- Options row ----
        opts = tk.Frame(content, bg=ls.CARD_BG)
        opts.pack(fill="x", pady=(0, 14))

        self.remember_var = tk.BooleanVar(value=False)
        cb = tk.Checkbutton(opts, text="Remember me",
                            variable=self.remember_var,
                            bg=ls.CARD_BG, fg=ls.PLACEHOLDER,
                            activebackground=ls.CARD_BG,
                            selectcolor=ls.CARD_BG,
                            font=("Arial", 9))
        cb.pack(side="left")

        forgot = tk.Label(opts, text="Forgot password?",
                          bg=ls.CARD_BG, fg=ls.LINK_TEXT,
                          font=("Arial", 9, "underline"),
                          cursor="hand2")
        forgot.pack(side="right")
        forgot.bind("<Button-1>", lambda e: self._forgot_password())

        # ---- LOGIN button ----
        self.login_btn = ls.FlatButton(content, text="LOGIN",
                                        command=self._do_login,
                                        width=1, height=2)
        self.login_btn.pack(fill="x")

        # ---- Status line ----
        self.status_var = tk.StringVar(value="")
        tk.Label(content, textvariable=self.status_var,
                 bg=ls.CARD_BG, fg="#990000",
                 font=("Arial", 9)).pack(pady=(8, 0))

        # ---- Autocomplete state ----
        self._typed = ""
        self._suggestion = ""
        self._suggest_seq = 0
        self._suggest_after_id = None

        entry = self.user_field.entry
        entry.bind("<KeyPress>", self._on_keypress)
        entry.bind("<KeyRelease>", self._on_keyrelease)
        entry.bind("<Right>", self._on_right)
        entry.bind("<Return>", lambda e: self._on_enter())
        entry.bind("<Tab>", lambda e: self._on_enter())

        self.pass_field.entry.bind("<Return>", lambda e: self._do_login())

        # ---- Pre-fill remembered username ----
        self._load_remembered()
        self.user_field.focus()

    # ------------------------------------------------- remembered username

    def _load_remembered(self):
        try:
            if os.path.exists(REMEMBER_FILE):
                with open(REMEMBER_FILE, "r", encoding="utf-8") as f:
                    saved = f.read().strip()
                if saved:
                    self.user_field.set(saved)
                    self.remember_var.set(True)
                    self.pass_field.focus()
        except Exception:
            pass

    def _save_remembered(self, username):
        try:
            if self.remember_var.get() and username:
                with open(REMEMBER_FILE, "w", encoding="utf-8") as f:
                    f.write(username)
            else:
                if os.path.exists(REMEMBER_FILE):
                    os.remove(REMEMBER_FILE)
        except Exception:
            pass

    # ------------------------------------------------- autocomplete

    def _on_keypress(self, event):
        keysym = event.keysym
        if len(event.char) == 0 and keysym not in (
                "BackSpace", "Delete", "Right", "Return", "Tab"):
            return None

        entry = self.user_field.entry
        if not entry.selection_present():
            return None

        if keysym in ("BackSpace", "Delete"):
            new_text = self._typed
        elif len(event.char) == 1 and event.char.isprintable():
            new_text = self._typed + event.char
        else:
            return None

        self._typed = new_text
        self._suggestion = ""
        self.user_field.set(new_text)
        entry.icursor("end")
        entry.selection_clear()
        self._schedule_suggestion()
        return "break"

    def _on_keyrelease(self, event):
        keysym = event.keysym
        if keysym in ("Right", "Left", "Up", "Down", "Return", "Tab",
                      "Escape", "Shift_L", "Shift_R",
                      "Control_L", "Control_R", "Alt_L", "Alt_R",
                      "Home", "End", "BackSpace"):
            return
        entry = self.user_field.entry
        if not entry.selection_present():
            self._typed = self.user_field.get()
        self._schedule_suggestion()

    def _schedule_suggestion(self):
        if self._suggest_after_id is not None:
            try:
                self.root.after_cancel(self._suggest_after_id)
            except Exception:
                pass
        self._suggest_after_id = self.root.after(
            USERNAME_DEBOUNCE_MS, self._query_suggestions)

    def _query_suggestions(self):
        self._suggest_after_id = None
        typed = self._typed.strip()
        if not typed:
            self._suggestion = ""
            return

        self._suggest_seq += 1
        my_seq = self._suggest_seq

        def worker():
            try:
                r = requests.get(f"{SERVER}/usernames",
                                 params={"q": typed}, timeout=4)
                names = r.json() if r.status_code == 200 else []
            except Exception:
                names = []
            self.root.after(0, lambda: self._apply_suggestions(
                typed, names, my_seq))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_suggestions(self, typed, names, my_seq):
        if my_seq != self._suggest_seq:
            return
        if self.user_field.get() != typed:
            return

        lower = typed.lower()
        starts = [n for n in (names or []) if n.lower().startswith(lower)]
        rest = [n for n in (names or []) if n not in starts]
        candidates = starts + rest
        if not candidates:
            return

        full = candidates[0]
        if len(full) <= len(typed):
            return

        self._suggestion = full
        self.user_field.set(full)
        entry = self.user_field.entry
        entry.selection_range(len(typed), "end")
        entry.icursor("end")

    def _on_right(self, event):
        entry = self.user_field.entry
        if entry.selection_present():
            entry.selection_clear()
            self._typed = self.user_field.get()
            entry.icursor("end")
            return "break"
        return None

    def _on_enter(self):
        entry = self.user_field.entry
        if entry.selection_present():
            entry.selection_clear()
            self._typed = self.user_field.get()
            entry.icursor("end")
        self.pass_field.focus()
        return "break"

    # ------------------------------------------------- actions

    def _forgot_password(self):
        messagebox.showinfo(
            "Forgot password",
            "Contact HQ / the shop owner to reset your password.",
            parent=self.root)

    def _set_busy(self, busy):
        try:
            self.login_btn.configure(
                text="SIGNING IN…" if busy else "LOGIN")
        except Exception:
            pass

    def _fail(self, message):
        self.status_var.set(message)
        self._set_busy(False)

    def _succeed(self, username, password, full_name, branch, role, kind):
        self._save_remembered(username)
        self.root.destroy()
        self.on_success({
            "username": username,
            "password": password,
            "full_name": full_name or username,
            "branch": branch,
            "role": role,
            "kind": kind,
        })

    def _do_login(self):
        u = self.user_field.get().strip()
        p = self.pass_field.get().strip()
        if not u or not p:
            self._fail("Username and password are required.")
            return
        self._set_busy(True)
        self.status_var.set("")

        def worker():
            try:
                r = requests.post(f"{SERVER}/login",
                                  json={"username": u, "password": p},
                                  timeout=8)
            except Exception as e:
                self.root.after(0, lambda: self._fail(
                    f"Could not reach server: {e}"))
                return

            if r.status_code != 200:
                try:
                    msg = r.json().get("message", "Login failed")
                except Exception:
                    msg = "Login failed"
                self.root.after(0, lambda m=msg: self._fail(m))
                return

            try:
                body = r.json()
            except Exception:
                self.root.after(0, lambda: self._fail("Bad server response"))
                return

            self.root.after(0, lambda: self._succeed(
                body.get("username", u),
                p,
                body.get("full_name"),
                body.get("branch"),
                body.get("role"),
                body.get("kind"),
            ))

        threading.Thread(target=worker, daemon=True).start()

    def mainloop(self):
        self.root.mainloop()