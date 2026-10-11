"""
HQ panel — minimal, for testing the CRN flow.

Three tabs:
  1. Products    — searchable product list; add items to a CRN batch.
  2. New CRN     — build & post a batch (reference, reason, lines).
  3. Posted CRNs — read-only list of every CRN (received or not).

The batch is held in memory on the app instance so it survives tab switches
within the same HQ window. It does not survive app restarts.
"""

import datetime
import threading
import tkinter as tk
from tkinter import ttk

import requests

from common.center import center_window_on_screen


class HqMixin:
    """HQ panel for testing CRNs."""

    def open_hq_window(self):
        win = self.open_content_window("hq", "HQ — Credit Notes",
                                       group="hq", icon=self.icon_purchase)
        if win is None:
            return
        try:
            win.minsize(880, 560)
        except Exception:
            pass

        # ---- batch state (persists across tab switches in this window) ----
        if not hasattr(self, "_hq_batch"):
            self._hq_batch = []          # list of dicts: {barcode, code, name, qty, unit_cost, subtotal}

        # ---- notebook ----
        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._hq_nb = nb

        self._hq_tab_products = ttk.Frame(nb)
        self._hq_tab_new      = ttk.Frame(nb)
        self._hq_tab_posted   = ttk.Frame(nb)

        nb.add(self._hq_tab_products, text="Products")
        nb.add(self._hq_tab_new,      text="New CRN")
        nb.add(self._hq_tab_posted,   text="Posted CRNs")

        self._build_hq_products_tab(self._hq_tab_products)
        self._build_hq_new_tab(self._hq_tab_new)
        self._build_hq_posted_tab(self._hq_tab_posted)

        # Refresh product list and posted list on first open.
        self._hq_refresh_products()
        self._hq_refresh_posted()
        # Sync the batch table with whatever's in memory.
        self._hq_render_batch()

    # ========================================================= Products tab

    def _build_hq_products_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(top, text="Search:").pack(side="left", padx=(0, 4))
        self._hq_search_var = tk.StringVar()
        e = ttk.Entry(top, textvariable=self._hq_search_var, width=32)
        e.pack(side="left")
        e.focus_set()
        self._hq_search_var.trace_add("write",
                                      lambda *a: self._hq_apply_product_filter())

        ttk.Button(top, text="Refresh",
                   command=self._hq_refresh_products).pack(side="right")
        ttk.Button(top, text="Add to CRN batch",
                   command=self._hq_add_selected_to_batch).pack(side="right", padx=(0, 6))

        # footer-reserved
        footer = tk.Frame(parent, height=34)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)
        self._hq_batch_label_var = tk.StringVar(value="Batch: 0 items")
        tk.Label(footer, textvariable=self._hq_batch_label_var,
                 bg="#f0f0f0").pack(side="left")
        self._hq_batch_total_var = tk.StringVar(value="0.00")
        tk.Label(footer, textvariable=self._hq_batch_total_var,
                 font=("Arial", 11, "bold"),
                 bg="#e8e8e8", fg="black",
                 relief="solid", bd=1, padx=16, pady=2
                 ).pack(side="right", padx=(0, 2))

        cols = ("code", "name", "stock", "cost", "price")
        heads = (
            ("code",  "Code",  90,  "w"),
            ("name",  "Name",  320, "w"),
            ("stock", "Stock", 90,  "e"),
            ("cost",  "Cost",  90,  "e"),
            ("price", "Price", 90,  "e"),
        )
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=16)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        tree.bind("<Double-1>", lambda e: self._hq_add_selected_to_batch())
        self._hq_products_tree = tree
        self._hq_products_rows = []
        self._hq_products_index = {}

    def _hq_refresh_products(self):
        tree = self._hq_products_tree
        if tree is None or not tree.winfo_exists():
            return

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/products", timeout=5)
                rows = r.json() if r.status_code == 200 else []
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            self.after(0, lambda: self._hq_fill_products(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _hq_fill_products(self, rows):
        self._hq_products_rows = list(rows or [])
        self._hq_apply_product_filter()

    def _hq_apply_product_filter(self):
        tree = self._hq_products_tree
        if tree is None or not tree.winfo_exists():
            return
        for row in tree.get_children():
            tree.delete(row)
        self._hq_products_index = {}

        needle = (self._hq_search_var.get() or "").strip().lower()
        for p in self._hq_products_rows:
            if needle:
                haystack = " ".join(str(p.get(k) or "") for k in
                                    ("code", "barcode", "name", "category")).lower()
                if needle not in haystack:
                    continue
            item = tree.insert("", "end", values=(
                p.get("code") or p.get("barcode") or "",
                p.get("name") or "",
                f"{float(p.get('stock') or 0):g}",
                f"{float(p.get('cost_price') or 0):.2f}",
                f"{float(p.get('price') or 0):.2f}",
            ))
            self._hq_products_index[item] = p

    def _hq_add_selected_to_batch(self):
        tree = self._hq_products_tree
        if tree is None or not tree.winfo_exists():
            return
        sel = tree.selection()
        if not sel:
            self.message_info("Select a product",
                              "Select a product in the list first.")
            return
        product = self._hq_products_index.get(sel[0])
        if not product:
            return
        self._hq_prompt_qty(product)

    def _hq_prompt_qty(self, product):
        dialog = tk.Toplevel(self)
        dialog.title("Add to CRN batch")
        dialog.transient(self)
        dialog.grab_set()
        center_window_on_screen(dialog, 380, 200)

        frame = ttk.Frame(dialog)
        frame.pack(fill="both", expand=True, padx=14, pady=14)

        ttk.Label(frame, text=f"Code: {product.get('code') or product.get('barcode')}"
                  ).pack(anchor="w")
        ttk.Label(frame, text=f"Name: {product.get('name')}").pack(anchor="w", pady=(2, 0))
        ttk.Label(frame, text=f"Current stock: {float(product.get('stock') or 0):g}"
                  ).pack(anchor="w", pady=(2, 10))

        ttk.Label(frame, text="Qty to deduct:").pack(anchor="w")
        qty_var = tk.StringVar(value="1")
        entry = ttk.Entry(frame, textvariable=qty_var, width=12)
        entry.pack(anchor="w", pady=(2, 12))
        entry.focus_set()
        entry.select_range(0, "end")

        btns = ttk.Frame(frame)
        btns.pack(fill="x")
        ttk.Button(btns, text="Cancel",
                   command=dialog.destroy).pack(side="right")
        ttk.Button(btns, text="Add",
                   command=lambda: self._hq_do_add(product, qty_var.get(), dialog)
                   ).pack(side="right", padx=(0, 6))

        entry.bind("<Return>",
                   lambda e: self._hq_do_add(product, qty_var.get(), dialog))

    def _hq_do_add(self, product, qty_str, dialog):
        try:
            qty = float(qty_str)
            if qty <= 0:
                raise ValueError
        except (TypeError, ValueError):
            self.message_error("Invalid", "Qty must be a number > 0.")
            return

        cost = float(product.get("cost_price") or 0)
        self._hq_batch.append({
            "barcode": product.get("barcode"),
            "code": product.get("code") or product.get("barcode"),
            "name": product.get("name"),
            "qty": qty,
            "unit_cost": cost,
            "subtotal": round(qty * cost, 2),
        })
        dialog.destroy()
        self._hq_render_batch()

    # ========================================================= New CRN tab

    def _build_hq_new_tab(self, parent):
        head = ttk.Frame(parent)
        head.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(head, text="Reference:").grid(row=0, column=0, sticky="w")
        self._hq_ref_var = tk.StringVar()
        ttk.Entry(head, textvariable=self._hq_ref_var, width=32
                  ).grid(row=0, column=1, sticky="w", padx=(4, 16))

        ttk.Label(head, text="Reason:").grid(row=0, column=2, sticky="w")
        self._hq_reason_var = tk.StringVar()
        ttk.Entry(head, textvariable=self._hq_reason_var, width=32
                  ).grid(row=0, column=3, sticky="w", padx=(4, 0))

        ttk.Label(head, text="User:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self._hq_user_var = tk.StringVar()
        ttk.Entry(head, textvariable=self._hq_user_var, width=20
                  ).grid(row=1, column=1, sticky="w", padx=(4, 0), pady=(6, 0))

        # Auto-fill user from admin credentials if available.
        try:
            creds = getattr(self, "admin_credentials", None)
            if creds and len(creds) >= 1:
                self._hq_user_var.set(creds[0] or "")
        except Exception:
            pass

        # Footer (reserved)
        footer = tk.Frame(parent, height=40)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)
        self._hq_new_batch_label_var = tk.StringVar(value="Batch: 0 items")
        tk.Label(footer, textvariable=self._hq_new_batch_label_var,
                 bg="#f0f0f0").pack(side="left")
        ttk.Button(footer, text="Post CRN",
                   command=self._hq_post_crn).pack(side="right")
        ttk.Button(footer, text="Clear batch",
                   command=self._hq_clear_batch).pack(side="right", padx=(0, 6))
        ttk.Button(footer, text="Remove selected",
                   command=self._hq_remove_selected_from_batch
                   ).pack(side="right", padx=(0, 6))

        # Table
        cols = ("code", "name", "qty", "cost", "subtotal")
        heads = (
            ("code",     "Code",        100, "w"),
            ("name",     "Name",        320, "w"),
            ("qty",      "Qty",         80,  "e"),
            ("cost",     "Cost/pcs",    100, "e"),
            ("subtotal", "Line Total",  120, "e"),
        )
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=14)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self._hq_batch_tree = tree

    def _hq_render_batch(self):
        tree = getattr(self, "_hq_batch_tree", None)
        if tree is not None and tree.winfo_exists():
            for row in tree.get_children():
                tree.delete(row)
            for i, line in enumerate(self._hq_batch):
                tree.insert("", "end", iid=str(i), values=(
                    line["code"], line["name"],
                    f"{line['qty']:g}",
                    f"{line['unit_cost']:.2f}",
                    f"{line['subtotal']:.2f}",
                ))

        total = 0.0
        for l in self._hq_batch:
            try:
                total += float(l["subtotal"])
            except (TypeError, ValueError):
                pass
        n = len(self._hq_batch)
        if hasattr(self, "_hq_batch_label_var"):
            self._hq_batch_label_var.set(f"Batch: {n} item{'s' if n != 1 else ''}")
        if hasattr(self, "_hq_batch_total_var"):
            self._hq_batch_total_var.set(f"{total:,.2f}")
        if hasattr(self, "_hq_new_batch_label_var"):
            self._hq_new_batch_label_var.set(
                f"Batch: {n} item{'s' if n != 1 else ''}  —  total {total:,.2f}")

    def _hq_remove_selected_from_batch(self):
        tree = self._hq_batch_tree
        if tree is None or not tree.winfo_exists():
            return
        sel = tree.selection()
        if not sel:
            return
        indexes = sorted((int(i) for i in sel), reverse=True)
        for i in indexes:
            if 0 <= i < len(self._hq_batch):
                del self._hq_batch[i]
        self._hq_render_batch()

    def _hq_clear_batch(self):
        if not self._hq_batch:
            return
        if not self.message_yesno("Clear batch",
                                  "Discard everything currently in the batch?"):
            return
        self._hq_batch = []
        self._hq_render_batch()

    def _hq_post_crn(self):
        if not self._hq_batch:
            self.message_error("Empty batch",
                               "Add at least one item before posting.")
            return

        reference = self._hq_ref_var.get().strip()
        reason = self._hq_reason_var.get().strip()
        user = self._hq_user_var.get().strip()

        payload = {
            "date": datetime.date.today().isoformat(),
            "reference": reference or None,
            "reason": reason or None,
            "user": user or None,
            "lines": [{"barcode": l["barcode"], "qty": l["qty"]}
                      for l in self._hq_batch],
        }

        def worker():
            try:
                r = requests.post(f"{self.SERVER}/crn", json=payload, timeout=10)
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            if r.status_code not in (200, 201):
                self.after(0, lambda: self.message_error("Post failed", r.text))
                return
            try:
                body = r.json()
            except Exception:
                body = {}
            self.after(0, lambda: self._hq_on_posted(body))

        threading.Thread(target=worker, daemon=True).start()

    def _hq_on_posted(self, body):
        crn_id = body.get("id", "?")
        self.message_info(
            "CRN posted",
            f"CRN #{crn_id} created.\n\n"
            "Open the Branch Purchase Centre → CRNs to receive it.")
        self._hq_batch = []
        self._hq_ref_var.set("")
        self._hq_reason_var.set("")
        self._hq_render_batch()
        self._hq_refresh_posted()

    # ========================================================= Posted tab

    def _build_hq_posted_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Button(top, text="Refresh",
                   command=self._hq_refresh_posted).pack(side="left")

        footer = tk.Frame(parent, height=34)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)
        self._hq_posted_entries_var = tk.StringVar(value="Total 0 entries")
        tk.Label(footer, textvariable=self._hq_posted_entries_var,
                 bg="#f0f0f0").pack(side="left")
        self._hq_posted_total_var = tk.StringVar(value="0.00")
        tk.Label(footer, textvariable=self._hq_posted_total_var,
                 font=("Arial", 11, "bold"),
                 bg="#e8e8e8", fg="black",
                 relief="solid", bd=1, padx=16, pady=2
                 ).pack(side="right", padx=(0, 2))

        cols = ("date", "crn", "reference", "lines", "qty", "value", "user", "received")
        heads = (
            ("date",      "Date*",       100, "w"),
            ("crn",       "CRN #",        70, "e"),
            ("reference", "Reference",   180, "w"),
            ("lines",     "Lines",        70, "e"),
            ("qty",       "Total Qty",   100, "e"),
            ("value",     "Value",       110, "e"),
            ("user",      "User",        120, "w"),
            ("received",  "Received",    100, "center"),
        )
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=14)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self._hq_posted_tree = tree

    def _hq_refresh_posted(self):
        tree = getattr(self, "_hq_posted_tree", None)
        if tree is None or not tree.winfo_exists():
            return

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/crns",
                                 params={"all": "1"}, timeout=5)
                rows = r.json() if r.status_code == 200 else []
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            self.after(0, lambda: self._hq_fill_posted(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _hq_fill_posted(self, rows):
        tree = self._hq_posted_tree
        if tree is None or not tree.winfo_exists():
            return
        for row in tree.get_children():
            tree.delete(row)

        shown = 0
        total_value = 0.0
        for c in rows or []:
            received = "\u2611 Yes" if c.get("received") else "\u2610 No"
            tree.insert("", "end", values=(
                self._hq_iso_to_dmy(c.get("date")),
                c.get("id") or "",
                c.get("reference") or "",
                c.get("total_lines") or 0,
                f"{float(c.get('total_qty') or 0):g}",
                f"{float(c.get('value') or 0):,.2f}",
                c.get("user") or "",
                received,
            ))
            shown += 1
            try:
                total_value += float(c.get("value") or 0)
            except (TypeError, ValueError):
                pass

        if hasattr(self, "_hq_posted_entries_var"):
            self._hq_posted_entries_var.set(f"Total {shown} entries")
        if hasattr(self, "_hq_posted_total_var"):
            self._hq_posted_total_var.set(f"{total_value:,.2f}")

    # ========================================================= helpers

    @staticmethod
    def _hq_iso_to_dmy(iso):
        try:
            d = datetime.date.fromisoformat(iso)
            return d.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            return iso or ""