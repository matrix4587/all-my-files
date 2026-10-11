"""
Admin Panel - HQ multi-branch stock adjustments.

Picks a branch from a dropdown, then sends +/- stock adjustments to that
branch's server over HTTP.

Flow:
    1. Pick branch.
    2. Enter product code.
    3. Pick Add / Remove.
    4. Enter a positive quantity.
    5. Pick a reason.
    6. Optional notes.
    7. Apply.

The server receives a signed delta: +qty for Add, -qty for Remove.

Run with:
    python admin_panel.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import requests
import datetime
import threading
import sys
import ctypes

# ---------------------------------------------------------------------------
# Branch list - EDIT THIS to match your real hostnames or IPs
# ---------------------------------------------------------------------------

BRANCHES = [
    ("Main",       "http://main:5000"),
    ("Westlands",  "http://westlands:5000"),
    ("Karen",      "http://karen:5000"),
]

TITLEBAR_COLOR_RGB = (0xA9, 0xC9, 0xA4)


def apply_green_titlebar(win):
    if not sys.platform.startswith("win"):
        return
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        color = ctypes.c_int(
            (TITLEBAR_COLOR_RGB[2] << 16) | (TITLEBAR_COLOR_RGB[1] << 8) | TITLEBAR_COLOR_RGB[0]
        )
        res = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(color), ctypes.sizeof(color)
        )
        if res != 0:
            dark = ctypes.c_int(0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark)
            )
    except Exception:
        pass


class AdminPanel(tk.Tk):
    RIBBON_BG = "#a9c9a4"

    REASONS = ["Damage", "Expense", "Adjustment", "Lost", "Correction", "Other"]

    def __init__(self):
        super().__init__()
        self.title("Admin Panel - HQ Multi-Branch Stock Adjustments")
        self.geometry("840x640")
        self.minsize(800, 600)
        self.configure(bg=self.RIBBON_BG)

        self.admin_credentials = None
        self.products_cache = []
        self.current_product = None
        self.current_branch_name = None
        self.current_branch_url = None

        self._code_normalizing = False

        self._build_ui()

        self.after(200, lambda: apply_green_titlebar(self))
        self.after(100, self.prompt_admin_login)

    def _build_ui(self):
        # --- Header ---
        header = tk.Frame(self, bg=self.RIBBON_BG)
        header.pack(fill="x", padx=10, pady=(10, 4))

        tk.Label(header, text="HQ Admin Panel", font=("Arial", 16, "bold"),
                 bg=self.RIBBON_BG).pack(side="left")

        self.logged_in_var = tk.StringVar(value="Not logged in")
        tk.Label(header, textvariable=self.logged_in_var,
                 bg=self.RIBBON_BG, fg="#003300",
                 font=("Arial", 10, "bold")).pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=10)

        # --- Branch picker ---
        branch_row = ttk.LabelFrame(self, text="Branch")
        branch_row.pack(fill="x", padx=10, pady=(10, 4))

        inner = ttk.Frame(branch_row)
        inner.pack(fill="x", padx=8, pady=8)

        ttk.Label(inner, text="Adjusting at:",
                  font=("Arial", 10, "bold")).pack(side="left", padx=(0, 8))

        self.branch_var = tk.StringVar()
        self.branch_combo = ttk.Combobox(
            inner, textvariable=self.branch_var,
            values=[name for name, _ in BRANCHES],
            state="readonly", width=20
        )
        self.branch_combo.pack(side="left")
        if BRANCHES:
            self.branch_combo.current(0)
        self.branch_combo.bind("<<ComboboxSelected>>", self.on_branch_change)

        self.branch_url_var = tk.StringVar(value="")
        ttk.Label(inner, textvariable=self.branch_url_var,
                  foreground="#555555").pack(side="left", padx=(12, 0))

        # --- Adjustment form ---
        form = ttk.LabelFrame(self, text="Stock adjustment")
        form.pack(fill="x", padx=10, pady=6)

        # Row 1: Code + Description
        row1 = ttk.Frame(form)
        row1.pack(fill="x", padx=8, pady=6)

        ttk.Label(row1, text="Code / Barcode:",
                  font=("Arial", 10, "bold")).pack(side="left", padx=(0, 6))
        self.code_var = tk.StringVar()
        self.code_entry = ttk.Entry(row1, textvariable=self.code_var, width=24)
        self.code_entry.pack(side="left", padx=(0, 12))
        self.code_entry.focus_set()
        self.code_var.trace_add("write", self.on_code_change)

        ttk.Label(row1, text="Description:").pack(side="left", padx=(0, 6))
        self.desc_var = tk.StringVar(value="-")
        ttk.Entry(row1, textvariable=self.desc_var, width=40,
                  state="readonly").pack(side="left", fill="x", expand=True)

        # Row 2: Current stock + Adjustment type
        row2 = ttk.Frame(form)
        row2.pack(fill="x", padx=8, pady=6)

        ttk.Label(row2, text="Current stock:",
                  font=("Arial", 10, "bold")).pack(side="left", padx=(0, 6))
        self.current_var = tk.StringVar(value="-")
        ttk.Label(row2, textvariable=self.current_var,
                  foreground="#003366",
                  font=("Arial", 11, "bold")).pack(side="left", padx=(0, 24))

        ttk.Label(row2, text="Adjustment type:",
                  font=("Arial", 10, "bold")).pack(side="left", padx=(0, 6))

        self.adjust_type_var = tk.StringVar(value="Add")
        ttk.Radiobutton(row2, text="Add (+)",
                        variable=self.adjust_type_var, value="Add",
                        command=self._update_preview).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(row2, text="Remove (-)",
                        variable=self.adjust_type_var, value="Remove",
                        command=self._update_preview).pack(side="left")

        # Row 3: Quantity + Reason
        row3 = ttk.Frame(form)
        row3.pack(fill="x", padx=8, pady=6)

        ttk.Label(row3, text="Quantity:",
                  font=("Arial", 10, "bold")).pack(side="left", padx=(0, 6))
        self.qty_var = tk.StringVar()
        ttk.Entry(row3, textvariable=self.qty_var, width=10).pack(side="left", padx=(0, 24))

        ttk.Label(row3, text="Reason:",
                  font=("Arial", 10, "bold")).pack(side="left", padx=(0, 6))
        self.reason_var = tk.StringVar(value="Damage")
        ttk.Combobox(row3, textvariable=self.reason_var,
                     values=self.REASONS, width=14, state="readonly").pack(side="left")

        # Row 4: Notes
        row4 = ttk.Frame(form)
        row4.pack(fill="x", padx=8, pady=6)

        ttk.Label(row4, text="Notes (optional):").pack(side="left", padx=(0, 6))
        self.notes_var = tk.StringVar()
        ttk.Entry(row4, textvariable=self.notes_var).pack(side="left", fill="x", expand=True)

        self.qty_var.trace_add("write", lambda *a: self._update_preview())
        self.adjust_type_var.trace_add("write", lambda *a: self._update_preview())

        # --- Preview ---
        preview = ttk.LabelFrame(self, text="Preview")
        preview.pack(fill="x", padx=10, pady=(0, 10))

        self.preview_var = tk.StringVar(value="Fill in the fields above to see the preview.")
        ttk.Label(preview, textvariable=self.preview_var,
                  foreground="#006600", font=("Arial", 10, "bold"),
                  anchor="w", justify="left",
                  wraplength=800).pack(fill="x", padx=8, pady=8)

        # --- Buttons ---
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=10, pady=(4, 10))

        ttk.Button(btns, text="Clear", command=self.clear_form).pack(side="left")
        ttk.Button(btns, text="Apply Adjustment",
                   command=self.apply_adjustment).pack(side="right", ipadx=16, ipady=4)

        # --- Session history ---
        hist_frame = ttk.LabelFrame(self, text="Session history (this run only)")
        hist_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.history_tree = ttk.Treeview(
            hist_frame,
            columns=("time", "branch", "code", "name", "type", "qty", "reason", "new_stock"),
            show="headings",
            height=10
        )
        for c, label in zip(
            ("time", "branch", "code", "name", "type", "qty", "reason", "new_stock"),
            ("Time", "Branch", "Code", "Description", "Type", "Qty", "Reason", "New Stock")
        ):
            self.history_tree.heading(c, text=label)

        self.history_tree.column("time", width=70, anchor="w")
        self.history_tree.column("branch", width=90, anchor="w")
        self.history_tree.column("code", width=80, anchor="w")
        self.history_tree.column("name", width=170, anchor="w")
        self.history_tree.column("type", width=70, anchor="w")
        self.history_tree.column("qty", width=60, anchor="e")
        self.history_tree.column("reason", width=90, anchor="w")
        self.history_tree.column("new_stock", width=80, anchor="e")

        self.history_tree.pack(fill="both", expand=True, padx=5, pady=5)

        # Initialise URL + cache for the first branch in the list.
        self.after(50, self.on_branch_change)

    # ---------- Branch ----------

    def on_branch_change(self, event=None):
        name = self.branch_var.get()
        url = None
        for n, u in BRANCHES:
            if n == name:
                url = u
                break
        self.current_branch_name = name
        self.current_branch_url = url
        self.branch_url_var.set(url or "")

        self.products_cache = []
        self.current_product = None
        self.desc_var.set("-")
        self.current_var.set("-")
        self._update_preview()

        if url:
            self.refresh_products_cache()

    # ---------- Admin login ----------

    def prompt_admin_login(self):
        if self.admin_credentials is not None:
            return True

        dialog = tk.Toplevel(self)
        dialog.title("HQ Admin Authorization")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("380x270+{}+{}".format(
            (self.winfo_screenwidth() - 380) // 2,
            (self.winfo_screenheight() - 270) // 2
        ))
        dialog.after(150, lambda w=dialog: apply_green_titlebar(w))

        result = {"ok": False}

        ttk.Label(dialog, text="Stock adjustments require HQ admin authorization.",
                  wraplength=320, justify="left").pack(anchor="w", padx=14, pady=(14, 6))

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

        btn_row = ttk.Frame(dialog)
        btn_row.pack(fill="x", padx=14, pady=14)

        def do_cancel():
            dialog.destroy()

        def do_login():
            username = user_var.get().strip()
            password = pass_var.get().strip()
            if not username or not password:
                status_var.set("Enter both username and password")
                return

            branch_url = self.current_branch_url
            if not branch_url:
                status_var.set("No branch selected")
                return

            def worker():
                try:
                    r = requests.post(f"{branch_url}/login",
                                      json={"username": username, "password": password},
                                      timeout=5)
                except Exception as e:
                    self.after(0, lambda: status_var.set(f"Server not reachable: {e}"))
                    return

                def apply():
                    if r.status_code == 200:
                        self.admin_credentials = (username, password)
                        self.logged_in_var.set(f"Logged in as: {username}")
                        result["ok"] = True
                        dialog.destroy()
                        self.on_branch_change()
                    else:
                        try:
                            msg = r.json().get("message", r.text)
                        except Exception:
                            msg = r.text
                        status_var.set(msg or "Invalid credentials")
                self.after(0, apply)
            threading.Thread(target=worker, daemon=True).start()

        ttk.Button(btn_row, text="Cancel",
                   command=do_cancel).pack(side="right")
        ttk.Button(btn_row, text="Authorize",
                   command=do_login).pack(side="right", padx=(0, 8))

        dialog.bind("<Return>", lambda e: do_login())
        dialog.bind("<Escape>", lambda e: do_cancel())
        dialog.wait_window()

        if not result["ok"]:
            self.after(50, self.destroy)

        return result["ok"]

    # ---------- Product cache ----------

    def refresh_products_cache(self):
        if not self.current_branch_url:
            return
        branch_url = self.current_branch_url

        def worker():
            try:
                r = requests.get(f"{branch_url}/products", timeout=4)
                data = r.json()
            except Exception as e:
                print(f"Could not refresh products for {self.current_branch_name}: {e}")
                return

            def apply():
                if branch_url == self.current_branch_url:
                    self.products_cache = data
                    self.on_code_change()
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    def find_product_by_code(self, code):
        if not code:
            return None
        code = str(code).strip()
        return next(
            (p for p in self.products_cache
             if str(p.get("barcode", "")).strip() == code
             or str(p.get("code", "")).strip() == code),
            None
        )

    def get_short_code(self, product):
        short = product.get("code")
        if short:
            return str(short).strip()
        return str(product.get("barcode", "")).strip()

    # ---------- Code lookup ----------

    def on_code_change(self, *args):
        if self._code_normalizing:
            return
        code = self.code_var.get().strip()
        self.current_product = None

        if not code:
            self.desc_var.set("-")
            self.current_var.set("-")
            self._update_preview()
            return

        match = self.find_product_by_code(code)
        if match:
            short = self.get_short_code(match)
            if short and short != code:
                self._code_normalizing = True
                self.code_var.set(short)
                self._code_normalizing = False
            self.current_product = match
            self.desc_var.set(match.get("name", "-"))
            self.current_var.set(str(match.get("stock", 0)))
        else:
            self.desc_var.set("Not found on this branch")
            self.current_var.set("-")

        self._update_preview()

    # ---------- Preview ----------

    def _signed_delta(self):
        """Returns (delta, error_message). delta is +qty for Add, -qty for Remove."""
        try:
            qty = float(self.qty_var.get())
        except (TypeError, ValueError):
            return None, "Enter a positive quantity."
        if qty <= 0:
            return None, "Quantity must be a positive number."
        if self.adjust_type_var.get() == "Remove":
            return -qty, None
        return qty, None

    def _update_preview(self):
        if not self.current_product:
            self.preview_var.set("Fill in the fields above to see the preview.")
            return

        delta, err = self._signed_delta()
        if delta is None:
            self.preview_var.set(err)
            return

        current = self.current_product.get("stock", 0)
        new_stock = current + delta
        if new_stock < 0:
            self.preview_var.set(
                f"Not allowed - would make stock negative.\n"
                f"Branch: {self.current_branch_name}\n"
                f"Current: {current}, delta: {delta:+g}, result: {new_stock}"
            )
            return

        reason = self.reason_var.get() or "Adjustment"
        verb = "ADD" if delta > 0 else "REMOVE"
        self.preview_var.set(
            f"Branch: {self.current_branch_name}\n"
            f"{self.current_product.get('name', '')}\n"
            f"Current: {current}  ->  After: {new_stock}   ({verb} {abs(delta):g})\n"
            f"Reason: {reason}"
        )

    # ---------- Apply ----------

    def apply_adjustment(self):
        if self.admin_credentials is None:
            if not self.prompt_admin_login():
                return

        if not self.current_branch_url:
            messagebox.showerror("Error", "No branch selected")
            return

        if not self.current_product:
            messagebox.showerror("Error", "Enter a valid product code for this branch")
            return

        delta, err = self._signed_delta()
        if delta is None:
            messagebox.showerror("Error", err)
            return

        current = self.current_product.get("stock", 0)
        new_stock = current + delta
        if new_stock < 0:
            messagebox.showerror(
                "Error",
                f"Removing {abs(delta)} would make stock negative.\n"
                f"Current: {current}, after removal: {new_stock}"
            )
            return

        reason = self.reason_var.get().strip() or "Adjustment"
        notes = self.notes_var.get().strip()
        branch_name = self.current_branch_name
        branch_url = self.current_branch_url

        payload = {
            "barcode": self.current_product.get("barcode"),
            "qty_delta": delta,
            "reason": reason,
            "notes": notes,
        }

        def worker():
            try:
                u, p = self.admin_credentials
                headers = {"X-Admin-User": u, "X-Admin-Pass": p}
                r = requests.post(f"{branch_url}/stock_adjust",
                                  json=payload, headers=headers, timeout=8)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Error", f"Could not reach branch '{branch_name}': {e}"))
                return

            def apply():
                if r.status_code == 200:
                    result = r.json()
                    self._log_history(branch_name, result)
                    self._clear_after_apply()
                    self.refresh_products_cache()
                elif r.status_code == 401:
                    messagebox.showerror("Error",
                                         f"Admin authorization failed at {branch_name}")
                    self.admin_credentials = None
                    self.logged_in_var.set("Not logged in")
                else:
                    try:
                        msg = r.json().get("message", r.text)
                    except Exception:
                        msg = r.text
                    messagebox.showerror("Error", f"{branch_name}: {msg}")
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    def _log_history(self, branch_name, result):
        when = datetime.datetime.now().strftime("%H:%M:%S")
        delta = result.get("qty_delta", 0)
        try:
            delta = float(delta)
        except (TypeError, ValueError):
            delta = 0
        if delta == 0:
            type_str = "-"
        else:
            type_str = "Add" if delta > 0 else "Remove"
        qty_str = f"{abs(delta):g}"

        self.history_tree.insert(
            "", "end",
            values=(
                when,
                branch_name,
                result.get("short_code", ""),
                result.get("name", ""),
                type_str,
                qty_str,
                result.get("reason", ""),
                result.get("new_stock", ""),
            )
        )
        children = self.history_tree.get_children()
        if children:
            self.history_tree.see(children[-1])

    def _clear_after_apply(self):
        self.code_var.set("")
        self.qty_var.set("")
        self.notes_var.set("")
        self.reason_var.set("Damage")
        self.adjust_type_var.set("Add")
        self.desc_var.set("-")
        self.current_var.set("-")
        self.current_product = None
        self._update_preview()
        self.code_entry.focus_set()

    def clear_form(self):
        self.code_var.set("")
        self.qty_var.set("")
        self.notes_var.set("")
        self.reason_var.set("Damage")
        self.adjust_type_var.set("Add")
        self.desc_var.set("-")
        self.current_var.set("-")
        self.current_product = None
        self._update_preview()
        self.code_entry.focus_set()


if __name__ == "__main__":
    AdminPanel().mainloop()