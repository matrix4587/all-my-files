"""
Admin authentication mixin for BackOffice.

Provides the modal admin login dialog. Called by any action that
requires admin privileges (New Item, etc.). Caches credentials
on `self.admin_credentials` for the rest of the session.
"""

import threading
import tkinter as tk
from tkinter import ttk

import requests

from common.center import center_window_on_screen
from common.titlebar import apply_green_titlebar


class AdminAuthMixin:
    """Admin login dialog and logout."""

    def prompt_admin_login(self, parent=None,
                            reason="This action requires admin authorization."):
        if self.admin_credentials is not None:
            return True

        dialog = tk.Toplevel(parent or self)
        dialog.title("Admin Authorization")
        dialog.resizable(False, False)
        dialog.transient(parent or self)
        dialog.grab_set()
        result = {"ok": False}

        ttk.Label(dialog, text=reason, wraplength=320,
                  justify="left").pack(anchor="w", padx=14, pady=(14, 6))
        ttk.Label(dialog, text="Admin Username:").pack(anchor="w", padx=14, pady=(6, 2))
        user_var = tk.StringVar()
        user_entry = ttk.Entry(dialog, textvariable=user_var, width=30)
        user_entry.pack(padx=14)
        user_entry.focus_set()

        ttk.Label(dialog, text="Admin Password:").pack(anchor="w", padx=14, pady=(8, 2))
        pass_var = tk.StringVar()
        pass_entry = ttk.Entry(dialog, textvariable=pass_var, show="*", width=30)
        pass_entry.pack(padx=14)

        status_var = tk.StringVar(value="")
        ttk.Label(dialog, textvariable=status_var,
                  foreground="#a00000").pack(anchor="w", padx=14, pady=(6, 0))

        button_row = ttk.Frame(dialog)
        button_row.pack(fill="x", padx=14, pady=14)

        def do_cancel():
            result["ok"] = False
            dialog.destroy()

        def do_login():
            username = user_var.get().strip()
            password = pass_var.get().strip()
            if not username or not password:
                status_var.set("Enter both username and password")
                return

            def worker():
                try:
                    r = requests.post(f"{self.SERVER}/login",
                                      json={"username": username, "password": password},
                                      timeout=5)
                except Exception as e:
                    self.after(0, lambda: status_var.set(f"Server not reachable: {e}"))
                    return

                def apply():
                    if r.status_code == 200:
                        self.admin_credentials = (username, password)
                        result["ok"] = True
                        dialog.destroy()
                    else:
                        try:
                            msg = r.json().get("message", r.text)
                        except Exception:
                            msg = r.text
                        status_var.set(msg or "Invalid credentials")
                self.after(0, apply)
            threading.Thread(target=worker, daemon=True).start()

        ttk.Button(button_row, text="Cancel", command=do_cancel).pack(side="right")
        ttk.Button(button_row, text="Authorize", command=do_login).pack(side="right", padx=(0, 8))
        dialog.bind("<Return>", lambda e: do_login())
        dialog.bind("<Escape>", lambda e: do_cancel())
        center_window_on_screen(dialog, 380, 270)
        dialog.after(150, lambda w=dialog: apply_green_titlebar(w))
        dialog.wait_window()
        return result["ok"]

    def logout_admin(self):
        self.admin_credentials = None