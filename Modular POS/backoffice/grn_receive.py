"""
Branch Purchase Centre.

Tabs:
  1. LPOs for this Branch      — approved, unreceived LPOs. Select a row and
                                 click Receive to open the receive editor.
  2. GRNs at Warehouse         — placeholder.
  3. Internal Branch Invoices  — placeholder.
  4. On Transit                — placeholder.
  5. GRNs at Branch            — read-only record of received GRNs.

Filter row (From Warehouse / Via Vehicle / Quick Search / From / To / ↻)
is shared and sits above the notebook. Only tabs 1 and 5 react to it.

Role gating:
  - The Receive button is drawn only if self.can("receive_grn").
  - The View / Print buttons are drawn only if self.can("print_grn").
  - Tabs are still shown; placeholders don't gate anything.
"""

import datetime
import threading
import tkinter as tk
from tkinter import ttk

import requests
from tkcalendar import DateEntry

from common.center import center_window_on_screen


class GrnReceiveMixin:
    """Branch Purchase Centre."""

    # ============================================================ entry

    def open_grn_window(self):
        win = self.open_content_window("grn", "Branch Purchase Centre",
                                       group="inventory", icon=self.icon_stock)
        if win is None:
            return
        try:
            win.minsize(900, 520)
        except Exception:
            pass

        # ---- state ----
        self._bp_lpo_rows = []
        self._bp_grn_rows = []
        self._bp_lpo_index = {}
        self._bp_grn_index = {}
        self._bp_lpo_tree = None
        self._bp_grn_tree = None
        self._bp_lpo_entries_var = None
        self._bp_lpo_total_var = None
        self._bp_grn_entries_var = None
        self._bp_grn_total_var = None

        # ---- shared filter row (above the notebook) ----
        filt = ttk.Frame(win)
        filt.pack(fill="x", padx=10, pady=(10, 4))

        ttk.Label(filt, text="From Warehouse:").pack(side="left", padx=(0, 2))
        self._bp_warehouse_var = tk.StringVar(value="<ALL>")
        ttk.Combobox(filt, textvariable=self._bp_warehouse_var,
                     width=14, state="readonly",
                     values=["<ALL>"]).pack(side="left", padx=(0, 12))

        ttk.Label(filt, text="Via Vehicle:").pack(side="left", padx=(0, 2))
        self._bp_vehicle_var = tk.StringVar(value="<ALL>")
        ttk.Combobox(filt, textvariable=self._bp_vehicle_var,
                     width=12, state="readonly",
                     values=["<ALL>"]).pack(side="left", padx=(0, 12))

        ttk.Label(filt, text="Quick Search:").pack(side="left", padx=(0, 2))
        self._bp_search_var = tk.StringVar()
        se = ttk.Entry(filt, textvariable=self._bp_search_var, width=18)
        se.pack(side="left", padx=(0, 12))
        self._bp_search_var.trace_add("write",
                                      lambda *a: self._bp_apply_filter())

        filt2 = ttk.Frame(win)
        filt2.pack(fill="x", padx=10, pady=(0, 6))

        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)

        ttk.Label(filt2, text="From:").pack(side="left", padx=(0, 2))
        self._bp_from_var = tk.StringVar()
        self._bp_from_picker = DateEntry(
            filt2, width=11, date_pattern="dd/mm/yyyy",
            textvariable=self._bp_from_var, showweeknumbers=False)
        self._bp_from_picker.pack(side="left", padx=(0, 12))
        self._bp_from_picker.set_date(yesterday)
        self._bp_from_picker.bind(
            "<<DateEntrySelected>>", lambda e: self._bp_apply_filter())

        ttk.Label(filt2, text="To:").pack(side="left", padx=(0, 2))
        self._bp_to_var = tk.StringVar()
        self._bp_to_picker = DateEntry(
            filt2, width=11, date_pattern="dd/mm/yyyy",
            textvariable=self._bp_to_var, showweeknumbers=False)
        self._bp_to_picker.pack(side="left", padx=(0, 12))
        self._bp_to_picker.set_date(today)
        self._bp_to_picker.bind(
            "<<DateEntrySelected>>", lambda e: self._bp_apply_filter())

        ttk.Button(filt2, text="\u21BB", width=3,
                   command=self._bp_refresh_current).pack(side="left")

        # ---- notebook ----
        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._bp_nb = nb

        self._grn_tab_lpos    = ttk.Frame(nb)
        self._grn_tab_wh_grns = ttk.Frame(nb)
        self._grn_tab_inter   = ttk.Frame(nb)
        self._grn_tab_transit = ttk.Frame(nb)
        self._grn_tab_br_grns = ttk.Frame(nb)

        nb.add(self._grn_tab_lpos,    text="LPOs for this Branch")
        nb.add(self._grn_tab_wh_grns, text="GRNs at Warehouse")
        nb.add(self._grn_tab_inter,   text="Internal Branch Invoices")
        nb.add(self._grn_tab_transit, text="On Transit")
        nb.add(self._grn_tab_br_grns, text="GRNs at Branch")

        self._build_lpo_tab(self._grn_tab_lpos)
        self._build_grn_history_tab(self._grn_tab_br_grns)

        self._build_grn_placeholder(self._grn_tab_wh_grns,
                                    "GRNs at Warehouse",
                                    "Warehouse-side receipts will appear here.")
        self._build_grn_placeholder(self._grn_tab_inter,
                                    "Internal Branch Invoices",
                                    "Inter-branch invoices will appear here.")
        self._build_grn_placeholder(self._grn_tab_transit,
                                    "On Transit",
                                    "Transfers from HQ or other branches "
                                    "to this branch will appear here.")

        nb.bind("<<NotebookTabChanged>>",
                lambda e: self._bp_on_tab_changed())

        self._refresh_lpo_list()
        self._refresh_grn_history()

    # ==================================================== placeholders

    def _build_grn_placeholder(self, frame, title, message):
        box = ttk.Frame(frame)
        box.pack(fill="both", expand=True, padx=30, pady=30)
        ttk.Label(box, text=title,
                  font=("Arial", 14, "bold")).pack(anchor="w")
        ttk.Label(box, text=message,
                  foreground="#555555").pack(anchor="w", pady=(6, 0))
        ttk.Label(box, text="(coming soon)",
                  foreground="#888888",
                  font=("Arial", 9, "italic")).pack(anchor="w", pady=(2, 0))

    # ==================================================== tab dispatch

    def _bp_current_tab(self):
        try:
            return self._bp_nb.index(self._bp_nb.select())
        except Exception:
            return 0

    def _bp_on_tab_changed(self):
        idx = self._bp_current_tab()
        if idx in (0, 4):
            self._bp_apply_filter()

    def _bp_refresh_current(self):
        idx = self._bp_current_tab()
        if idx == 0:
            self._refresh_lpo_list()
        elif idx == 4:
            self._refresh_grn_history()

    # =================================================== tab 1: LPOs

    def _build_lpo_tab(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=10, pady=(10, 6), side="top")

        can_receive = self.can("receive_grn")
        can_print   = self.can("print_grn")

        if can_receive:
            self._bp_receive_btn = ttk.Button(bar, text="Receive",
                                               command=self._bp_receive_selected)
            self._bp_receive_btn.pack(side="left")
        else:
            self._bp_receive_btn = None

        if can_print:
            ttk.Button(bar, text="View",
                       command=lambda: self._bp_view_selected("lpo")
                       ).pack(side="left", padx=(6, 0))
            ttk.Button(bar, text="Print",
                       command=lambda: self._bp_print_selected("lpo")
                       ).pack(side="left", padx=(6, 0))

        footer = tk.Frame(parent, height=34)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)
        self._bp_lpo_entries_var = tk.StringVar(value="Total 0 entries")
        tk.Label(footer, textvariable=self._bp_lpo_entries_var,
                 bg="#f0f0f0").pack(side="left")
        self._bp_lpo_total_var = tk.StringVar(value="0.00")
        tk.Label(footer, textvariable=self._bp_lpo_total_var,
                 font=("Arial", 11, "bold"),
                 bg="#e8e8e8", fg="black",
                 relief="solid", bd=1, padx=16, pady=2
                 ).pack(side="right", padx=(0, 2))

        cols = ("date", "no", "supplier", "ref", "vehicle",
                "amount", "user", "rcvd", "brgrn")
        heads = (
            ("date",     "Date*",      90,  "w"),
            ("no",       "Order #",    90,  "e"),
            ("supplier", "Supplier",   210, "w"),
            ("ref",      "Reference",  110, "w"),
            ("vehicle",  "Vehicle",    80,  "w"),
            ("amount",   "Amount",     110, "e"),
            ("user",     "User",       110, "w"),
            ("rcvd",     "Rcvd?",      60,  "center"),
            ("brgrn",    "BrGRN #",    90,  "e"),
        )

        tree = ttk.Treeview(parent, columns=cols, show="headings", height=14)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 4))

        if self._bp_receive_btn is not None:
            tree.bind("<<TreeviewSelect>>",
                      lambda e: self._bp_receive_btn.state(["!disabled"]))
            tree.bind("<Double-1>",
                      lambda e: self._bp_receive_selected())
            self._bp_receive_btn.state(["disabled"])

        self._bp_lpo_tree = tree

    def _refresh_lpo_list(self):
        tree = self._bp_lpo_tree
        if tree is None or not tree.winfo_exists():
            return

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/purchase_orders",
                                 params={"receivable": 1}, timeout=5)
                rows = r.json() if r.status_code == 200 else []
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            self.after(0, lambda: self._fill_lpo_list(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_lpo_list(self, rows):
        self._bp_lpo_rows = list(rows or [])
        self._bp_apply_filter()

    # =================================================== tab 5: GRNs

    def _build_grn_history_tab(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", padx=10, pady=(10, 6), side="top")

        if self.can("print_grn"):
            ttk.Button(bar, text="View",
                       command=lambda: self._bp_view_selected("grn")
                       ).pack(side="left")
            ttk.Button(bar, text="Print",
                       command=lambda: self._bp_print_selected("grn")
                       ).pack(side="left", padx=(6, 0))

        footer = tk.Frame(parent, height=34)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)
        self._bp_grn_entries_var = tk.StringVar(value="Total 0 entries")
        tk.Label(footer, textvariable=self._bp_grn_entries_var,
                 bg="#f0f0f0").pack(side="left")
        self._bp_grn_total_var = tk.StringVar(value="0.00")
        tk.Label(footer, textvariable=self._bp_grn_total_var,
                 font=("Arial", 11, "bold"),
                 bg="#e8e8e8", fg="black",
                 relief="solid", bd=1, padx=16, pady=2
                 ).pack(side="right", padx=(0, 2))

        cols = ("date", "no", "supplier", "ref", "vehicle",
                "amount", "user", "rcvd", "brgrn")
        heads = (
            ("date",     "Date*",      90,  "w"),
            ("no",       "GRN #",      90,  "e"),
            ("supplier", "Supplier",   210, "w"),
            ("ref",      "Reference",  110, "w"),
            ("vehicle",  "Vehicle",    80,  "w"),
            ("amount",   "Amount",     110, "e"),
            ("user",     "User",       110, "w"),
            ("rcvd",     "Rcvd?",      60,  "center"),
            ("brgrn",    "BrGRN #",    90,  "e"),
        )

        tree = ttk.Treeview(parent, columns=cols, show="headings", height=14)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 4))
        tree.bind("<Double-1>",
                  lambda e: self._bp_view_selected("grn"))

        self._bp_grn_tree = tree

    def _refresh_grn_history(self):
        tree = self._bp_grn_tree
        if tree is None or not tree.winfo_exists():
            return

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/grns", timeout=5)
                rows = r.json() if r.status_code == 200 else []
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            self.after(0, lambda: self._fill_grn_history(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_grn_history(self, rows):
        self._bp_grn_rows = list(rows or [])
        self._bp_apply_filter()

    # =================================================== filtering

    def _parse_dmy(self, s):
        try:
            return datetime.datetime.strptime((s or "").strip(),
                                              "%d/%m/%Y").date()
        except (ValueError, TypeError):
            return None

    def _bp_apply_filter(self):
        needle = (self._bp_search_var.get() or "").strip().lower()
        frm = self._parse_dmy(self._bp_from_var.get())
        to = self._parse_dmy(self._bp_to_var.get())

        self._apply_lpo_filter(needle, frm, to)
        self._apply_grn_filter(needle, frm, to)

    def _row_in_range(self, date_str, frm, to):
        try:
            d = datetime.date.fromisoformat(date_str or "")
        except (ValueError, TypeError):
            return True
        if frm and d < frm:
            return False
        if to and d > to:
            return False
        return True

    def _apply_lpo_filter(self, needle, frm, to):
        tree = self._bp_lpo_tree
        if tree is None or not tree.winfo_exists():
            return
        for row in tree.get_children():
            tree.delete(row)
        self._bp_lpo_index = {}

        shown = 0
        total = 0.0
        for lpo in self._bp_lpo_rows:
            if not self._row_in_range(lpo.get("date"), frm, to):
                continue
            if needle:
                haystack = " ".join(str(lpo.get(k) or "") for k in
                                    ("lpo_no", "supplier", "id")).lower()
                if needle not in haystack:
                    continue
            item = tree.insert("", "end",
                               values=self._lpo_row_values(lpo))
            self._bp_lpo_index[item] = lpo
            shown += 1
            try:
                total += float(lpo.get("value") or 0)
            except (TypeError, ValueError):
                pass

        if self._bp_lpo_entries_var is not None:
            self._bp_lpo_entries_var.set(f"Total {shown} entries")
        if self._bp_lpo_total_var is not None:
            self._bp_lpo_total_var.set(f"{total:,.2f}")

    def _lpo_row_values(self, lpo):
        no = str(lpo.get("lpo_no") or "")
        if no.upper().startswith("LPO-"):
            no = no[4:]
        return (
            self._iso_to_dmy(lpo.get("date")),
            no,
            lpo.get("supplier") or "",
            "-",
            "-",
            f"{float(lpo.get('value') or 0):,.2f}",
            "",
            "\u2611" if lpo.get("approved") else "\u2610",
            "-",
        )

    def _apply_grn_filter(self, needle, frm, to):
        tree = self._bp_grn_tree
        if tree is None or not tree.winfo_exists():
            return
        for row in tree.get_children():
            tree.delete(row)
        self._bp_grn_index = {}

        shown = 0
        total = 0.0
        for g in self._bp_grn_rows:
            if not self._row_in_range(g.get("date"), frm, to):
                continue
            if needle:
                haystack = " ".join(str(g.get(k) or "") for k in
                                    ("id", "supplier",
                                     "purchase_order_id", "user")).lower()
                if needle not in haystack:
                    continue
            item = tree.insert("", "end",
                               values=self._grn_row_values(g))
            self._bp_grn_index[item] = g
            shown += 1
            try:
                total += float(g.get("total") or 0)
            except (TypeError, ValueError):
                pass

        if self._bp_grn_entries_var is not None:
            self._bp_grn_entries_var.set(f"Total {shown} entries")
        if self._bp_grn_total_var is not None:
            self._bp_grn_total_var.set(f"{total:,.2f}")

    def _grn_row_values(self, g):
        po = g.get("purchase_order_id")
        ref = "-"
        if isinstance(po, int):
            ref = f"{po:05d}"
        return (
            self._iso_to_dmy(g.get("date")),
            g.get("id") or "",
            g.get("supplier") or "",
            ref,
            "-",
            f"{float(g.get('total') or 0):,.2f}",
            g.get("user") or "",
            "\u2611",
            f"BR{int(g.get('id') or 0):05d}",
        )

    @staticmethod
    def _iso_to_dmy(iso):
        try:
            d = datetime.date.fromisoformat(iso)
            return d.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            return iso or ""

    # =================================================== toolbar actions

    def _bp_view_selected(self, which):
        if which == "lpo":
            tree = self._bp_lpo_tree
            index = self._bp_lpo_index
        else:
            tree = self._bp_grn_tree
            index = self._bp_grn_index
        if tree is None or not tree.winfo_exists():
            return
        sel = tree.selection()
        if not sel:
            self.message_info("Select a row", "Select a row first.")
            return
        row = index.get(sel[0])
        if not row:
            return
        if which == "lpo":
            lines = row.get("lines") or []
            self._show_order_detail_local(row, lines)
        else:
            self._open_grn_detail_async(row.get("id"))

    def _bp_print_selected(self, which):
        if which == "lpo":
            tree = self._bp_lpo_tree
            index = self._bp_lpo_index
        else:
            tree = self._bp_grn_tree
            index = self._bp_grn_index
        if tree is None or not tree.winfo_exists():
            return
        sel = tree.selection()
        if not sel:
            self.message_info("Select a row", "Select a row first.")
            return
        row = index.get(sel[0])
        if not row:
            return
        if which == "lpo":
            lines = row.get("lines") or []
            self.print_purchase_order(row, lines)
        else:
            self._print_grn_async(row.get("id"))

    # --------------------------------------------------- LPO detail view

    def _show_order_detail_local(self, order_data, lines):
        win = tk.Toplevel(self)
        win.title(f"LPO Detail - {order_data.get('lpo_no', '')}")
        win.geometry("900x480")
        win.resizable(True, True)
        try:
            from common.titlebar import apply_green_titlebar
            win.after(150, lambda w=win: apply_green_titlebar(w))
        except Exception:
            pass

        header = ttk.Frame(win)
        header.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Label(header, text=f"Supplier: {order_data.get('supplier', '-')}",
                  font=("Arial", 10, "bold")).pack(anchor="w")
        ttk.Label(header, text=f"LPO No.: {order_data.get('lpo_no', '-')}").pack(anchor="w")
        ttk.Label(header, text=f"Date: {self._iso_to_dmy(order_data.get('date'))}").pack(anchor="w")
        ttk.Label(header, text=f"Expiry: {self._iso_to_dmy(order_data.get('expiry_date'))}").pack(anchor="w")

        tree = ttk.Treeview(win,
                            columns=("code", "desc", "qty", "total_qty",
                                     "packaging", "cost", "total"),
                            show="headings")
        for c, h, w in (("code", "Code", 100),
                        ("desc", "Description", 240),
                        ("qty", "Qty", 70),
                        ("total_qty", "Total Pcs", 90),
                        ("packaging", "Packaging", 90),
                        ("cost", "Cost/pcs", 90),
                        ("total", "Total", 100)):
            tree.heading(c, text=h)
            tree.column(c, width=w,
                        anchor="e" if c in ("qty", "total_qty", "cost", "total")
                        else "w")
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        running = 0.0
        for line in lines:
            try:
                running += float(line.get("subtotal") or 0)
            except (TypeError, ValueError):
                pass
            tree.insert("", "end", values=(
                line.get("code") or line.get("barcode") or "-",
                line.get("name", "-"),
                f"{float(line.get('qty') or 0):g}",
                f"{float(line.get('total_qty') or 0):g}",
                line.get("packaging") or "-",
                f"{float(line.get('unit_cost') or 0):.2f}",
                f"{float(line.get('subtotal') or 0):.2f}",
            ))

        footer = ttk.Frame(win)
        footer.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(footer, text=f"Total:  {running:,.2f}",
                  font=("Arial", 11, "bold"),
                  foreground="#006600").pack(side="left")
        ttk.Button(footer, text="Close",
                   command=win.destroy).pack(side="right")

    # --------------------------------------------------- GRN detail view

    def _open_grn_detail_async(self, grn_id):
        def worker():
            try:
                r = requests.get(f"{self.SERVER}/grns/{grn_id}", timeout=5)
                detail = r.json() if r.status_code == 200 else None
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            if not detail:
                self.after(0, lambda: self.message_error(
                    "Error", "GRN not found."))
                return
            self.after(0, lambda: self._show_grn_detail(detail))
        threading.Thread(target=worker, daemon=True).start()

    def _show_grn_detail(self, grn):
        win = tk.Toplevel(self)
        win.title(f"GRN #{grn.get('id')} - {grn.get('supplier', '-')}")
        win.geometry("900x480")
        win.resizable(True, True)
        try:
            from common.titlebar import apply_green_titlebar
            win.after(150, lambda w=win: apply_green_titlebar(w))
        except Exception:
            pass

        header = ttk.Frame(win)
        header.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Label(header, text=f"Supplier: {grn.get('supplier', '-')}",
                  font=("Arial", 10, "bold")).pack(anchor="w")
        ttk.Label(header, text=f"GRN No.: {grn.get('id', '-')}").pack(anchor="w")
        ttk.Label(header, text=f"Date: {self._iso_to_dmy(grn.get('date'))}").pack(anchor="w")
        po = grn.get("purchase_order_id")
        ttk.Label(header, text=f"From LPO: {'#' + str(po) if po else '-'}").pack(anchor="w")
        ttk.Label(header, text=f"User: {grn.get('user') or '-'}").pack(anchor="w")

        tree = ttk.Treeview(win,
                            columns=("code", "desc", "qty", "total_qty",
                                     "packaging", "cost", "total"),
                            show="headings")
        for c, h, w in (("code", "Code", 100),
                        ("desc", "Description", 240),
                        ("qty", "Qty", 70),
                        ("total_qty", "Total Pcs", 90),
                        ("packaging", "Packaging", 90),
                        ("cost", "Cost/pcs", 90),
                        ("total", "Total", 100)):
            tree.heading(c, text=h)
            tree.column(c, width=w,
                        anchor="e" if c in ("qty", "total_qty", "cost", "total")
                        else "w")
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        running = 0.0
        for line in grn.get("lines", []):
            try:
                running += float(line.get("subtotal") or 0)
            except (TypeError, ValueError):
                pass
            tree.insert("", "end", values=(
                line.get("code") or line.get("barcode") or "-",
                line.get("name", "-"),
                f"{float(line.get('qty') or 0):g}",
                f"{float(line.get('total_qty') or 0):g}",
                line.get("packaging") or "-",
                f"{float(line.get('unit_cost') or 0):.2f}",
                f"{float(line.get('subtotal') or 0):.2f}",
            ))

        footer = ttk.Frame(win)
        footer.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(footer, text=f"Total:  {running:,.2f}",
                  font=("Arial", 11, "bold"),
                  foreground="#006600").pack(side="left")
        if self.can("print_grn"):
            ttk.Button(footer, text="Print",
                       command=lambda: self._print_grn_detail_shaped(grn)
                       ).pack(side="right", padx=(0, 6))
        ttk.Button(footer, text="Close",
                   command=win.destroy).pack(side="right")

    def _print_grn_async(self, grn_id):
        def worker():
            try:
                r = requests.get(f"{self.SERVER}/grns/{grn_id}", timeout=5)
                detail = r.json() if r.status_code == 200 else None
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            if not detail:
                self.after(0, lambda: self.message_error(
                    "Error", "GRN not found."))
                return
            self.after(0, lambda: self._print_grn_detail_shaped(detail))
        threading.Thread(target=worker, daemon=True).start()

    def _print_grn_detail_shaped(self, grn):
        shaped = {
            "lpo_no": f"GRN-{grn.get('id')}",
            "supplier": grn.get("supplier"),
            "date": self._iso_to_dmy(grn.get("date")),
            "expiry_date": "-",
        }
        lines = [{
            "code": l.get("code"),
            "barcode": l.get("barcode"),
            "name": l.get("name", "-"),
            "qty": l.get("qty", 0),
            "total_qty": l.get("total_qty", 0),
            "packaging": l.get("packaging"),
            "unit_cost": l.get("unit_cost", 0),
            "subtotal": l.get("subtotal", 0),
        } for l in grn.get("lines", [])]
        self.print_purchase_order(shaped, lines)

    # =================================================== receive editor

    def _bp_receive_selected(self):
        if not self.can("receive_grn"):
            self.message_error("Not allowed",
                               "You do not have permission to receive GRNs.")
            return
        tree = self._bp_lpo_tree
        if tree is None or not tree.winfo_exists():
            return
        sel = tree.selection()
        if not sel:
            self.message_info("Select an LPO",
                              "Select an LPO in the list first.")
            return
        lpo = self._bp_lpo_index.get(sel[0])
        if not lpo:
            return
        lines = lpo.get("lines") or []
        if not lines:
            self.message_error("Empty LPO", "This LPO has no lines.")
            return
        self._open_receive_editor(lpo)

    def _open_receive_editor(self, po):
        win = tk.Toplevel(self)
        win.title(f"Receiving — {po.get('lpo_no', '')} — "
                  f"{po.get('supplier', '')}")
        win.geometry("900x600")
        win.minsize(700, 480)
        win.resizable(True, True)
        win.transient(self)
        try:
            from common.titlebar import apply_green_titlebar
            win.after(150, lambda w=win: apply_green_titlebar(w))
        except Exception:
            pass

        self._re_po = po
        self._re_pending = list(po.get("lines") or [])
        self._re_confirmed = []
        self._re_index = 0
        self._re_amend = False

        # ---- header ----
        header = ttk.Frame(win)
        header.pack(fill="x", padx=12, pady=(10, 4), side="top")
        ttk.Label(header, text=f"LPO: {po.get('lpo_no', '-')}",
                  font=("Arial", 11, "bold")).pack(side="left")
        ttk.Label(header, text=f"Supplier: {po.get('supplier', '-')}"
                  ).pack(side="left", padx=(12, 0))

        # ---- footer (reserved BEFORE anything else that could expand) ----
        footer = ttk.Frame(win)
        footer.pack(fill="x", padx=12, pady=(0, 12), side="bottom")
        self._re_progress_var = tk.StringVar(value="0 / 0 lines confirmed")
        ttk.Label(footer, textvariable=self._re_progress_var).pack(side="left")
        self._re_grand_total_var = tk.StringVar(value="0.00")
        tk.Label(footer, textvariable=self._re_grand_total_var,
                 font=("Arial", 12, "bold"),
                 bg="#d8e8d8", fg="#004d00",
                 relief="solid", bd=1, padx=16, pady=4
                 ).pack(side="left", padx=(16, 0))
        ttk.Button(footer, text="Cancel",
                   command=win.destroy).pack(side="right")
        self._re_receive_btn = ttk.Button(footer, text="RECEIVE",
                                           state="disabled",
                                           command=self._re_receive_all)
        self._re_receive_btn.pack(side="right", padx=(0, 8))

        # ---- current line ----
        current = ttk.LabelFrame(win, text="Current line")
        current.pack(fill="x", expand=False, padx=12, pady=(6, 4), side="top")

        r1 = ttk.Frame(current)
        r1.pack(fill="x", padx=8, pady=(6, 2))
        ttk.Label(r1, text="Code:").grid(row=0, column=0, sticky="w")
        self._re_code_var = tk.StringVar(value="-")
        ttk.Entry(r1, textvariable=self._re_code_var, width=16,
                  state="readonly").grid(row=0, column=1, sticky="w", padx=(2, 12))
        ttk.Label(r1, text="Description:").grid(row=0, column=2, sticky="w")
        self._re_desc_var = tk.StringVar(value="-")
        ttk.Entry(r1, textvariable=self._re_desc_var,
                  state="readonly").grid(row=0, column=3, sticky="ew", padx=(2, 12))
        r1.columnconfigure(3, weight=1)

        r2 = ttk.Frame(current)
        r2.pack(fill="x", padx=8, pady=(2, 2))
        ttk.Label(r2, text="LPO Qty (packagings):").grid(row=0, column=0, sticky="w")
        self._re_lpo_qty_var = tk.StringVar(value="-")
        ttk.Entry(r2, textvariable=self._re_lpo_qty_var, width=10,
                  state="readonly").grid(row=0, column=1, sticky="w", padx=(2, 14))
        ttk.Label(r2, text="Pack size:").grid(row=0, column=2, sticky="w")
        self._re_pack_size_var = tk.StringVar(value="-")
        ttk.Entry(r2, textvariable=self._re_pack_size_var, width=8,
                  state="readonly").grid(row=0, column=3, sticky="w", padx=(2, 14))
        ttk.Label(r2, text="Cost/pcs (LPO):").grid(row=0, column=4, sticky="w")
        self._re_cost_var = tk.StringVar(value="-")
        ttk.Entry(r2, textvariable=self._re_cost_var, width=10,
                  state="readonly").grid(row=0, column=5, sticky="w", padx=(2, 0))

        r3 = ttk.Frame(current)
        r3.pack(fill="x", padx=8, pady=(6, 6))
        ttk.Label(r3, text="Invoice Qty (packagings):").grid(row=0, column=0, sticky="w")
        self._re_inv_qty_var = tk.StringVar()
        e = ttk.Entry(r3, textvariable=self._re_inv_qty_var, width=10)
        e.grid(row=0, column=1, sticky="w", padx=(2, 14))
        e.focus_set()
        ttk.Label(r3, text="Invoice Cost/pcs:").grid(row=0, column=2, sticky="w")
        self._re_inv_cost_var = tk.StringVar()
        ttk.Entry(r3, textvariable=self._re_inv_cost_var, width=10).grid(
            row=0, column=3, sticky="w", padx=(2, 14))
        ttk.Button(r3, text="Confirm Line",
                   command=self._re_confirm_line).grid(row=0, column=4, sticky="w")

        # ---- confirmed lines ----
        recv_box = ttk.LabelFrame(win, text="Confirmed lines (ready to receive)")
        recv_box.pack(fill="both", expand=True, padx=12, pady=(4, 4), side="top")

        cols = ("code", "desc", "inv_qty", "pack_size", "total_pcs",
                "cost", "total")
        heads = (("code", "Code", 100, "w"),
                 ("desc", "Description", 240, "w"),
                 ("inv_qty", "Inv Qty", 80, "e"),
                 ("pack_size", "Pack", 60, "e"),
                 ("total_pcs", "Total Pcs", 90, "e"),
                 ("cost", "Cost/pcs", 90, "e"),
                 ("total", "Line Total", 110, "e"))

        wrap = ttk.Frame(recv_box)
        wrap.pack(fill="both", expand=True, padx=5, pady=5)

        self._re_tree = ttk.Treeview(wrap, columns=cols,
                                      show="headings", height=6)
        for c, h, w, a in heads:
            self._re_tree.heading(c, text=h)
            self._re_tree.column(c, width=w, anchor=a)
        vsb = ttk.Scrollbar(wrap, orient="vertical",
                            command=self._re_tree.yview)
        self._re_tree.configure(yscrollcommand=vsb.set)
        self._re_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self._re_show_current_line()

    def _re_show_current_line(self):
        if self._re_index >= len(self._re_pending):
            self._re_code_var.set("-")
            self._re_desc_var.set("-")
            self._re_lpo_qty_var.set("-")
            self._re_pack_size_var.set("-")
            self._re_cost_var.set("-")
            self._re_inv_qty_var.set("")
            self._re_inv_cost_var.set("")
            self._re_update_progress()
            return

        line = self._re_pending[self._re_index]

        def _num(v, default=0.0):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        barcode = line.get("barcode") or ""
        short_code = (line.get("code")
                      or self._short_code_for_barcode(barcode)
                      or barcode
                      or "-")
        name = line.get("name") or line.get("description") or "-"
        qty = _num(line.get("qty"))
        pack = _num(line.get("pack_size") or 1)
        cost = _num(line.get("unit_cost") or 0)

        self._re_code_var.set(short_code)
        self._re_desc_var.set(name)
        self._re_lpo_qty_var.set(f"{qty:g}")
        self._re_pack_size_var.set(f"{pack:g}")
        self._re_cost_var.set(f"{cost:.2f}")
        self._re_inv_cost_var.set(f"{cost:.2f}")
        self._re_inv_qty_var.set("")
        self._re_update_progress()

    def _re_confirm_line(self):
        if self._re_index >= len(self._re_pending):
            return
        line = self._re_pending[self._re_index]

        try:
            inv_qty = float(self._re_inv_qty_var.get())
            if inv_qty <= 0:
                raise ValueError
        except ValueError:
            self.message_error("Invalid", "Invoice qty must be a number > 0.")
            return
        try:
            inv_cost = float(self._re_inv_cost_var.get())
            if inv_cost < 0:
                raise ValueError
        except ValueError:
            self.message_error("Invalid", "Cost/pcs must be a number >= 0.")
            return

        try:
            lpo_qty = float(line.get("qty") or 0)
        except (TypeError, ValueError):
            lpo_qty = 0

        if abs(inv_qty - lpo_qty) > 1e-9:
            self._re_amend = True
            self.message_warn(
                "LPO does not balance",
                f"LPO qty: {lpo_qty:g}\nInvoice qty: {inv_qty:g}\n\n"
                "Request HQ to amend the LPO to match the invoice, then "
                "start over. This line is skipped.")
            self._re_index += 1
            self._re_show_current_line()
            return

        try:
            pack = float(line.get("pack_size") or 1)
        except (TypeError, ValueError):
            pack = 1
        total_pcs = inv_qty * pack
        line_total = total_pcs * inv_cost

        self._re_confirmed.append({
            "barcode": line.get("barcode"),
            "code": line.get("code"),
            "qty": inv_qty,
            "packaging": line.get("packaging"),
            "pack_size": pack,
            "unit_cost": inv_cost,
            "notes": line.get("notes", ""),
        })

        barcode = line.get("barcode") or ""
        short_code = (line.get("code")
                      or self._short_code_for_barcode(barcode)
                      or barcode
                      or "-")
        self._re_tree.insert("", "end", values=(
            short_code,
            line.get("name", "-"),
            f"{inv_qty:g}",
            f"{pack:g}",
            f"{total_pcs:g}",
            f"{inv_cost:.2f}",
            f"{line_total:.2f}",
        ))
        self._re_index += 1
        self._re_show_current_line()

    def _re_update_progress(self):
        total = len(self._re_pending)
        done = len(self._re_confirmed)
        self._re_progress_var.set(f"{done} / {total} lines confirmed")

        gt = 0.0
        for l in self._re_confirmed:
            try:
                gt += float(l["qty"]) * float(l["pack_size"]) * float(l["unit_cost"])
            except (KeyError, TypeError, ValueError):
                pass
        self._re_grand_total_var.set(f"GRAND TOTAL:  {gt:,.2f}")

        if done == total and total > 0 and not self._re_amend:
            self._re_receive_btn.configure(state="normal")
        else:
            self._re_receive_btn.configure(state="disabled")

    def _re_receive_all(self):
        if not self.can("receive_grn"):
            self.message_error("Not allowed",
                               "You do not have permission to receive GRNs.")
            return
        po = self._re_po
        lines = list(self._re_confirmed)
        if not po or not lines:
            return
        today = datetime.date.today().isoformat()
        user = ""
        try:
            creds = getattr(self, "admin_credentials", None)
            if creds and len(creds) >= 1:
                user = creds[0] or ""
        except Exception:
            user = ""

        payload = {
            "supplier": po.get("supplier"),
            "date": today,
            "purchase_order_id": po.get("id"),
            "user": user,
            "lines": lines,
        }

        def worker():
            try:
                r = requests.post(f"{self.SERVER}/grn", json=payload, timeout=10)
                if r.status_code not in (200, 201):
                    self.after(0, lambda: self.message_error("GRN failed", r.text))
                    return
                requests.patch(
                    f"{self.SERVER}/purchase_orders/{po['id']}/receive",
                    timeout=5)
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            self.after(0, self._re_on_success)

        threading.Thread(target=worker, daemon=True).start()

    def _re_on_success(self):
        self.message_info("Received",
                          "GRN saved. Stock updated. LPO marked as received.")
        try:
            self._re_tree.winfo_toplevel().destroy()
        except Exception:
            pass
        self._refresh_lpo_list()
        self._refresh_grn_history()