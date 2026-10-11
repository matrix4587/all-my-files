"""
Stocks screen mixin for BackOffice.

Contains the Stocks window (code/barcode lookup + movement history,
live balance + 7/14/21/30-day movement panel), an instant product
search dialog, and the Stock List launcher window.

Movement panel (bottom-left):
  - Renders as a table with gridlines:
      Title row:  "Stock Movement" (centered)
      Header row: 7 days | 14 days | 21 days | 30 days
      Value row:  1pc    | 2pcs    | 4pcs    | 6pcs
"""

import datetime
import threading
import tkinter as tk
from tkinter import ttk

import requests
from tkcalendar import DateEntry

from common.center import center_window_on_screen


class StocksMixin:
    """Stocks window, live balance, movement history, and the Stock List launcher."""

    # ---------- Stocks ----------

    def build_stocks_content(self):
        win = self.open_content_window("stocks", "Stocks",
                                       group="inventory", icon=self.icon_stock)
        if win is None:
            return

        # --- filter state ---
        self._stock_code_normalizing = False
        self._stock_filter_after_id = None
        self._stock_request_seq = 0
        self._stock_ledger_cache = {}
        self._stock_summary_seq = 0

        top_button_frame = ttk.Frame(win)
        top_button_frame.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Button(top_button_frame, text="Stock List",
                   command=self.open_stock_list_window).pack(side="left")

        # ---- filter row: Code [🔍] Desc ... From To ----
        filter_frame = ttk.Frame(win)
        filter_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(filter_frame, text="Code/Barcode:").pack(side="left", padx=(0, 2))
        self.stock_code_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self.stock_code_var,
                  width=12).pack(side="left", padx=(0, 4))

        ttk.Button(filter_frame, text="\U0001F50D", width=3,
                   command=self.open_stock_search_dialog).pack(side="left", padx=(0, 10))

        ttk.Label(filter_frame, text="Desc:").pack(side="left", padx=(0, 2))
        self.matched_desc_var = tk.StringVar(value="-")
        ttk.Label(filter_frame, textvariable=self.matched_desc_var,
                  relief="sunken", background="white", foreground="#006600",
                  anchor="w").pack(side="left", fill="x", expand=True, padx=(0, 10))

        date_frame = ttk.Frame(filter_frame)
        date_frame.pack(side="right", padx=(10, 0))
        ttk.Label(date_frame, text="From:").pack(side="left", padx=(0, 2))
        self.stock_from_var = tk.StringVar()
        self.from_date_picker = DateEntry(
            date_frame, width=11, date_pattern="yyyy-mm-dd",
            textvariable=self.stock_from_var, showweeknumbers=False)
        self.from_date_picker.pack(side="left", padx=(0, 10))
        self.from_date_picker.bind("<<DateEntrySelected>>", self.on_stock_filter_change)
        ttk.Label(date_frame, text="To:").pack(side="left", padx=(0, 2))
        self.stock_to_var = tk.StringVar()
        self.to_date_picker = DateEntry(
            date_frame, width=11, date_pattern="yyyy-mm-dd",
            textvariable=self.stock_to_var, showweeknumbers=False)
        self.to_date_picker.pack(side="left")
        self.to_date_picker.bind("<<DateEntrySelected>>", self.on_stock_filter_change)
        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        self.from_date_picker.set_date(yesterday)
        self.to_date_picker.set_date(today)

        self.stock_code_var.trace_add("write", self.on_stock_filter_change)

        # ---- history ----
        history_frame = ttk.LabelFrame(win, text="Stock Movement History")
        history_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        style = ttk.Style()
        style.configure(
            "Light.Treeview",
            background="white", fieldbackground="white", foreground="black",
            bordercolor="#999999", borderwidth=1, relief="solid")
        style.configure(
            "Light.Treeview.Heading",
            background="#e8e8e8", foreground="black")

        self.stock_history_tree = ttk.Treeview(
            history_frame,
            columns=("date", "code", "type", "reference", "in", "out", "balance"),
            show="headings", style="Light.Treeview")
        self.stock_history_tree.tag_configure("evenrow", background="white")
        self.stock_history_tree.tag_configure("oddrow", background="#f0f0f0")
        self.stock_history_tree.heading("date", text="Date")
        self.stock_history_tree.heading("code", text="Code")
        self.stock_history_tree.heading("type", text="Type")
        self.stock_history_tree.heading("reference", text="Reference")
        self.stock_history_tree.heading("in", text="Stock In")
        self.stock_history_tree.heading("out", text="Stock Out")
        self.stock_history_tree.heading("balance", text="Balance")
        self.stock_history_tree.column("code", anchor="w", width=90)
        self.stock_history_tree.column("reference", anchor="w", width=100)
        self.stock_history_tree.column("in", anchor="e")
        self.stock_history_tree.column("out", anchor="e")
        self.stock_history_tree.column("balance", anchor="e")
        self.stock_history_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.make_columns_responsive(
            win, self.stock_history_tree, [1, 1, 2, 1, 1, 1, 1])

        # ---- bottom bar: movement table + Bal ----
        bottom = ttk.Frame(win)
        bottom.pack(fill="x", padx=10, pady=(0, 10))

        self._build_movement_table(bottom)

        self.live_balance_var = tk.StringVar(value="Bal: -")
        tk.Label(bottom, textvariable=self.live_balance_var,
                 font=("Arial", 12, "bold"), bg="#e8a0a0", fg="black",
                 relief="raised", bd=2, padx=14, pady=4
                 ).pack(side="right", anchor="se")

    # ---------- movement table ----------

    def _build_movement_table(self, parent):
        """Draw the Stock Movement panel as a bordered table with gridlines."""
        BG = "#f0f0f0"
        BORDER = "#808080"      # gridline color

        # Outer frame with solid border.
        outer = tk.Frame(parent, relief="solid", bd=1, bg=BG)
        outer.pack(side="left", anchor="w")

        # --- Title row (spans all columns, centered) ---
        tk.Label(outer, text="Stock Movement",
                 font=("Arial", 10, "bold"),
                 bg=BG).grid(row=0, column=0, columnspan=4,
                             sticky="ew", pady=(4, 2))

        # --- Header row ---
        headers = ("7 days", "14 days", "21 days", "30 days")
        for i, text in enumerate(headers):
            cell = tk.Frame(outer, bg=BG,
                            highlightthickness=0, bd=0)
            cell.grid(row=1, column=i, sticky="nsew")

            # right border (except the last column)
            if i < len(headers) - 1:
                tk.Frame(cell, bg=BORDER, width=1).pack(side="right", fill="y")

            tk.Label(cell, text=text,
                     font=("Arial", 9, "bold"),
                     bg=BG, padx=12, pady=4).pack()

        # Horizontal divider under the header row.
        tk.Frame(outer, bg=BORDER, height=1).grid(
            row=2, column=0, columnspan=4, sticky="ew")

        # --- Value row ---
        self._mv_d7_var  = tk.StringVar(value="0pc")
        self._mv_d14_var = tk.StringVar(value="0pc")
        self._mv_d21_var = tk.StringVar(value="0pc")
        self._mv_d30_var = tk.StringVar(value="0pc")

        values = (self._mv_d7_var, self._mv_d14_var,
                  self._mv_d21_var, self._mv_d30_var)
        for i, var in enumerate(values):
            cell = tk.Frame(outer, bg=BG, bd=0)
            cell.grid(row=3, column=i, sticky="nsew")

            if i < len(values) - 1:
                tk.Frame(cell, bg=BORDER, width=1).pack(side="right", fill="y")

            tk.Label(cell, textvariable=var,
                     font=("Arial", 10),
                     bg=BG, padx=12, pady=4).pack()

        # Equal column widths.
        for i in range(4):
            outer.grid_columnconfigure(i, weight=1, uniform="mvcol")

    # ---------- filter behaviour ----------

    def on_stock_filter_change(self, *args):
        if getattr(self, "_stock_code_normalizing", False):
            return
        self.update_live_balance()

        if self._stock_filter_after_id is not None:
            try:
                self.after_cancel(self._stock_filter_after_id)
            except (ValueError, tk.TclError):
                pass
            self._stock_filter_after_id = None

        code = self.stock_code_var.get().strip()
        if not code:
            if hasattr(self, "stock_history_tree") and self.stock_history_tree.winfo_exists():
                for row in self.stock_history_tree.get_children():
                    self.stock_history_tree.delete(row)
            self._reset_movement_summary()
            return

        self._stock_filter_after_id = self.after(500, self.search_stock_history)
        self._refresh_movement_summary(code)

    def update_live_balance(self, *args):
        if not hasattr(self, "live_balance_var"):
            return
        try:
            code = self.stock_code_var.get().strip()
        except tk.TclError:
            return
        if not code:
            self.live_balance_var.set("Bal: -")
            self.matched_desc_var.set("-")
            return
        match = self.find_product_by_code(code)
        if match:
            short_code = self.get_short_code(match)
            if short_code and short_code != code:
                self._stock_code_normalizing = True
                self.stock_code_var.set(short_code)
                self._stock_code_normalizing = False
            try:
                bal_str = f"{float(match['stock']):.2f}"
            except (TypeError, ValueError):
                bal_str = str(match['stock'])
            self.live_balance_var.set(f"Bal: {bal_str}")
            self.matched_desc_var.set(match["name"])
        else:
            self.live_balance_var.set("Bal: not found")
            self.matched_desc_var.set("-")

    # ---------- movement summary (7/14/21/30) ----------

    def _reset_movement_summary(self):
        self._mv_d7_var.set("0pc")
        self._mv_d14_var.set("0pc")
        self._mv_d21_var.set("0pc")
        self._mv_d30_var.set("0pc")

    def _refresh_movement_summary(self, code):
        self._stock_summary_seq += 1
        my_seq = self._stock_summary_seq

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/stock_movement_summary",
                                 params={"barcode": code}, timeout=5)
                data = r.json() if r.status_code == 200 else None
            except Exception:
                data = None
            self.after(0, lambda: self._apply_movement_summary(data, my_seq))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_movement_summary(self, data, my_seq):
        if my_seq != self._stock_summary_seq:
            return
        if not data or "days7" not in data:
            self._reset_movement_summary()
            return
        self._mv_d7_var.set(f"{data.get('days7', 0):g}pc")
        self._mv_d14_var.set(f"{data.get('days14', 0):g}pc")
        self._mv_d21_var.set(f"{data.get('days21', 0):g}pc")
        self._mv_d30_var.set(f"{data.get('days30', 0):g}pc")

    # ---------- history ----------

    def search_stock_history(self):
        self._stock_filter_after_id = None
        if not hasattr(self, "stock_history_tree") or not self.stock_history_tree.winfo_exists():
            return
        code = self.stock_code_var.get().strip()
        if not code:
            for row in self.stock_history_tree.get_children():
                self.stock_history_tree.delete(row)
            return

        from_date = self.stock_from_var.get().strip()
        to_date = self.stock_to_var.get().strip()
        cache_key = (code, from_date, to_date)

        cached = self._stock_ledger_cache.get(cache_key)
        if cached is not None:
            self._apply_stock_history(cached)
            return

        params = {"barcode": code}
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date

        self._stock_request_seq += 1
        my_seq = self._stock_request_seq

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/stock_ledger",
                                 params=params, timeout=5)
                rows = r.json()
            except Exception as e:
                print("Could not reach server:", e)
                return

            def apply():
                if my_seq != self._stock_request_seq:
                    return
                self._stock_ledger_cache[cache_key] = rows
                self._apply_stock_history(rows)

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_stock_history(self, rows):
        if not hasattr(self, "stock_history_tree") or not self.stock_history_tree.winfo_exists():
            return
        for row in self.stock_history_tree.get_children():
            self.stock_history_tree.delete(row)

        def fmt_num(v):
            try:
                return f"{float(v):.2f}"
            except (TypeError, ValueError):
                return str(v)

        for i, row in enumerate(rows):
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            display_code = row.get("code") or row.get("barcode") or ""
            ref = row.get("reference") or ""
            self.stock_history_tree.insert(
                "", "end",
                values=(
                    row.get("date", ""),
                    display_code,
                    row.get("transaction_type", ""),
                    ref,
                    fmt_num(row.get("stock_in", 0)),
                    fmt_num(row.get("stock_out", 0)),
                    fmt_num(row.get("balance", 0)),
                ),
                tags=(tag,)
            )

    # ---------- search dialog ----------

    def open_stock_search_dialog(self):
        all_products = list(getattr(self, "products_cache", []) or [])
        if not all_products:
            try:
                r = requests.get(f"{self.SERVER}/products", timeout=5)
                if r.status_code == 200:
                    all_products = r.json() or []
            except Exception as e:
                self.message_error("Error", f"Could not load products: {e}")
                return

        dialog = tk.Toplevel(self)
        dialog.title("Search Products")
        dialog.transient(self)
        dialog.grab_set()
        center_window_on_screen(dialog, 760, 480)

        # --- search row ---
        row = ttk.Frame(dialog)
        row.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(row, text="Search:").pack(side="left", padx=(0, 4))
        term1_var = tk.StringVar()
        ttk.Entry(row, textvariable=term1_var, width=26).pack(side="left")

        two_var = tk.BooleanVar(value=False)
        chk = ttk.Checkbutton(row, variable=two_var)     # no text label
        chk.pack(side="left", padx=(10, 4))

        op_var = tk.StringVar(value="AND")
        op_combo = ttk.Combobox(row, textvariable=op_var, width=6,
                                state="disabled", values=["AND", "OR"])
        op_combo.pack(side="left", padx=(0, 6))

        term2_var = tk.StringVar()
        term2_entry = ttk.Entry(row, textvariable=term2_var, width=22)

        # --- results table ---
        cols = ("code", "desc", "qty", "cost", "sell")
        heads = (
            ("code", "Code",        110, "w"),
            ("desc", "Description", 320, "w"),
            ("qty",  "Qty",          80, "e"),
            ("cost", "Cost",        100, "e"),
            ("sell", "Selling",     100, "e"),
        )
        tree = ttk.Treeview(dialog, columns=cols, show="headings", height=14)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        # --- footer ---
        foot = ttk.Frame(dialog)
        foot.pack(fill="x", padx=10, pady=(0, 10))
        count_var = tk.StringVar(value="0 result(s)")
        ttk.Label(foot, textvariable=count_var).pack(side="left")

        picked = {"product": None}

        def refresh(*_):
            needle1 = (term1_var.get() or "").strip().lower()
            needle2 = (term2_var.get() or "").strip().lower()
            use_two = two_var.get()
            op = op_var.get() if use_two else "AND"

            w1 = [w for w in needle1.split() if w]
            w2 = [w for w in needle2.split() if w]
            words = w1 + w2 if use_two else w1

            for r in tree.get_children():
                tree.delete(r)

            shown = 0
            for p in all_products:
                name = (p.get("name") or "").lower()
                if not words:
                    match = True
                elif op == "AND":
                    match = all(w in name for w in words)
                else:
                    match = any(w in name for w in words)
                if not match:
                    continue
                tree.insert("", "end", values=(
                    p.get("code") or p.get("barcode") or "",
                    p.get("name") or "",
                    f"{float(p.get('stock') or 0):g}",
                    f"{float(p.get('cost_price') or 0):.2f}",
                    f"{float(p.get('price') or 0):.2f}",
                ))
                shown += 1
            count_var.set(f"{shown} result(s)")

        def toggle_two():
            if two_var.get():
                op_combo.configure(state="readonly")
                term2_entry.pack(side="left", padx=(0, 6))
            else:
                op_combo.configure(state="disabled")
                term2_entry.pack_forget()
                term2_var.set("")
            refresh()

        chk.configure(command=toggle_two)
        term1_var.trace_add("write", refresh)
        term2_var.trace_add("write", refresh)
        op_var.trace_add("write", refresh)

        def do_ok(*_):
            sel = tree.selection()
            if not sel:
                self.message_info("Select a product",
                                  "Select a product in the list first.")
                return
            vals = tree.item(sel[0], "values")
            picked["product"] = vals[0] if vals else None
            dialog.destroy()
            if picked["product"]:
                self.stock_code_var.set(picked["product"])

        def do_cancel():
            dialog.destroy()

        tree.bind("<Double-1>", do_ok)

        ttk.Button(foot, text="Cancel", command=do_cancel).pack(side="right")
        ttk.Button(foot, text="OK", command=do_ok).pack(side="right", padx=(0, 6))

        refresh()

    # ---------- Stock List launcher ----------

    def open_stock_list_window(self):
        win = self.open_content_window("stock_list", "Stock List",
                                       group="inventory", icon=self.icon_stock)
        if win is None:
            return
        center_window_on_screen(win, 380, 200)
        win.minsize(340, 180)
        win.resizable(False, False)
        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=20, pady=20)
        ttk.Button(body, text="Departmental Summary", width=24,
                   command=self.open_departmental_summary_report).pack(pady=(0, 8))
        ttk.Button(body, text="Departments", width=24,
                   command=self.open_departments_picker).pack(pady=(0, 8))
        ttk.Button(body, text="Suppliers", width=24,
                   command=self.open_suppliers_picker).pack()