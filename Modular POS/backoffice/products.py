"""
Products screen mixin for BackOffice.

Displays a product's core fields (code, name, price, stock, supplier,
shelf) and launches the various read-only lists (all products, by
supplier, by department). Editing lives in the New Item screen.

Role gating:
    - The "New Item" shortcut on this screen requires self.can("new_item")
      (manager+). Read-only lists are available to all signed-in users.
"""

import threading
import tkinter as tk
from tkinter import ttk

import requests

from common.center import center_window_on_screen


class ProductsMixin:
    """Products entry screen + read-only product lists."""

    def build_products_content(self):
        win = self.open_content_window("products", "Products",
                                       group="inventory", icon=self.icon_products)
        if win is None:
            return

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Button(top, text="Products List",
                   command=self.open_product_list_window).pack(side="left")
        ttk.Button(top, text="By Supplier",
                   command=self.open_products_by_supplier_window).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="By Department",
                   command=self.open_products_by_department_window).pack(side="left", padx=(6, 0))

        if self.can("new_item"):
            ttk.Button(top, text="New Item",
                       command=self.build_new_item_content).pack(side="left", padx=(6, 0))

        # ---- lookup row ----
        row = ttk.Frame(win)
        row.pack(fill="x", padx=10, pady=10)

        ttk.Label(row, text="Code/Barcode:").pack(side="left", padx=(0, 4))
        self.product_code_var = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.product_code_var, width=16)
        e.pack(side="left")
        e.focus_set()
        self.product_code_var.trace_add("write", self.on_product_code_change)

        ttk.Label(row, text="Name:").pack(side="left", padx=(12, 4))
        self.product_name_var = tk.StringVar(value="-")
        ttk.Entry(row, textvariable=self.product_name_var,
                  width=42, state="readonly").pack(side="left")

        # ---- detail fields ----
        box = ttk.LabelFrame(win, text="Details")
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.product_detail_vars = {
            "Code":          tk.StringVar(value="-"),
            "Name":          tk.StringVar(value="-"),
            "Category":      tk.StringVar(value="-"),
            "Packaging":     tk.StringVar(value="-"),
            "Pack Size":     tk.StringVar(value="-"),
            "Cost Price":    tk.StringVar(value="-"),
            "Markup":        tk.StringVar(value="-"),
            "Selling Price": tk.StringVar(value="-"),
            "Stock":         tk.StringVar(value="-"),
            "Supplier":      tk.StringVar(value="-"),
            "Shelf":         tk.StringVar(value="-"),
        }

        grid = ttk.Frame(box)
        grid.pack(fill="both", expand=True, padx=10, pady=10)

        for i, (label, var) in enumerate(self.product_detail_vars.items()):
            r = i // 2
            c = (i % 2) * 2
            ttk.Label(grid, text=f"{label}:", width=14, anchor="w"
                      ).grid(row=r, column=c, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=var, width=28, state="readonly"
                      ).grid(row=r, column=c + 1, sticky="w", pady=3, padx=(0, 16))

    def on_product_code_change(self, *args):
        code = self.product_code_var.get().strip()
        if not code:
            self.product_name_var.set("-")
            for k in self.product_detail_vars:
                self.product_detail_vars[k].set("-")
            return
        match = self.find_product_by_code(code)
        if not match:
            self.product_name_var.set("Not found")
            for k in self.product_detail_vars:
                self.product_detail_vars[k].set("-")
            return

        self.product_name_var.set(match.get("name") or "-")
        v = self.product_detail_vars

        def nz(val, default="-"):
            return default if val in (None, "") else val

        v["Code"].set(nz(match.get("code") or match.get("barcode")))
        v["Name"].set(nz(match.get("name")))
        v["Category"].set(nz(match.get("category")))
        v["Packaging"].set(nz(match.get("packaging")))
        v["Pack Size"].set(str(match.get("pack_size") or 1))
        v["Cost Price"].set(f"{float(match.get('cost_price') or 0):.2f}")
        v["Markup"].set(f"{float(match.get('markup') or 0):.2f} {match.get('markup_type') or '%'}")
        v["Selling Price"].set(f"{float(match.get('selling_price') or match.get('price') or 0):.2f}")
        v["Stock"].set(f"{float(match.get('stock') or 0):g}")
        v["Supplier"].set(nz(match.get("supplier")))
        v["Shelf"].set(nz(match.get("shelf")))

    def show_product_supplier(self):
        code = self.product_code_var.get().strip()
        if not code:
            return
        match = self.find_product_by_code(code)
        if match:
            self.message_info("Supplier",
                              f"{match.get('name', '-')}\n\n"
                              f"Supplier: {match.get('supplier') or '-'}")

    def show_product_shelf(self):
        code = self.product_code_var.get().strip()
        if not code:
            return
        match = self.find_product_by_code(code)
        if match:
            self.message_info("Shelf",
                              f"{match.get('name', '-')}\n\n"
                              f"Shelf: {match.get('shelf') or '-'}")

    # --------------------------------------------------- read-only lists

    def open_product_list_window(self):
        win = self.open_content_window("product_list", "Products",
                                       group="inventory", icon=self.icon_products)
        if win is None:
            return
        try:
            win.minsize(780, 480)
        except Exception:
            pass

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text="Filter:").pack(side="left", padx=(0, 4))
        filter_var = tk.StringVar()
        ttk.Entry(top, textvariable=filter_var, width=36).pack(side="left")
        ttk.Button(top, text="Refresh",
                   command=lambda: do_refresh()).pack(side="right")

        cols = ("code", "name", "category", "stock", "cost", "price", "supplier")
        heads = (
            ("code",     "Code",        100, "w"),
            ("name",     "Name",        300, "w"),
            ("category", "Category",    130, "w"),
            ("stock",    "Stock",        80, "e"),
            ("cost",     "Cost",         90, "e"),
            ("price",    "Price",        90, "e"),
            ("supplier", "Supplier",    160, "w"),
        )
        tree = ttk.Treeview(win, columns=cols, show="headings", height=16)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._product_list_all = []

        def do_refresh():
            def worker():
                try:
                    r = requests.get(f"{self.SERVER}/products", timeout=6)
                    rows = r.json() if r.status_code == 200 else []
                except Exception as e:
                    self.after(0, lambda: self.message_error(
                        "Error", f"Could not reach server: {e}"))
                    return

                def apply():
                    self._product_list_all = list(rows or [])
                    render()
                self.after(0, apply)
            threading.Thread(target=worker, daemon=True).start()

        def render():
            needle = (filter_var.get() or "").strip().lower()
            for row in tree.get_children():
                tree.delete(row)
            for p in self._product_list_all:
                if needle:
                    hay = " ".join(str(p.get(k) or "") for k in
                                   ("code", "barcode", "name", "category", "supplier")).lower()
                    if needle not in hay:
                        continue
                tree.insert("", "end", values=(
                    p.get("code") or p.get("barcode") or "",
                    p.get("name") or "",
                    p.get("category") or "",
                    f"{float(p.get('stock') or 0):g}",
                    f"{float(p.get('cost_price') or 0):.2f}",
                    f"{float(p.get('price') or 0):.2f}",
                    p.get("supplier") or "",
                ))

        filter_var.trace_add("write", lambda *a: render())
        do_refresh()

    def open_products_by_supplier_window(self):
        win = self.open_content_window("product_by_supplier", "Products by Supplier",
                                       group="inventory", icon=self.icon_products)
        if win is None:
            return
        try:
            win.minsize(780, 480)
        except Exception:
            pass

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text="Supplier:").pack(side="left", padx=(0, 4))
        supplier_var = tk.StringVar()
        supplier_combo = ttk.Combobox(top, textvariable=supplier_var,
                                       width=32, state="readonly")
        supplier_combo.pack(side="left")
        ttk.Button(top, text="Refresh",
                   command=lambda: refresh_list()).pack(side="right")

        cols = ("code", "name", "category", "stock", "cost", "price")
        heads = (
            ("code",     "Code",        100, "w"),
            ("name",     "Name",        340, "w"),
            ("category", "Category",    140, "w"),
            ("stock",    "Stock",        80, "e"),
            ("cost",     "Cost",         90, "e"),
            ("price",    "Price",        90, "e"),
        )
        tree = ttk.Treeview(win, columns=cols, show="headings", height=16)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._supplier_products = []

        def refresh_list():
            def worker():
                try:
                    r = requests.get(f"{self.SERVER}/products", timeout=6)
                    rows = r.json() if r.status_code == 200 else []
                except Exception as e:
                    self.after(0, lambda: self.message_error(
                        "Error", f"Could not reach server: {e}"))
                    return

                def apply():
                    self._supplier_products = list(rows or [])
                    names = sorted({(p.get("supplier") or "").strip()
                                    for p in self._supplier_products
                                    if (p.get("supplier") or "").strip()})
                    supplier_combo["values"] = [""] + names
                    if not supplier_var.get() and names:
                        supplier_var.set(names[0])
                    render()
                self.after(0, apply)
            threading.Thread(target=worker, daemon=True).start()

        def render(*_):
            needle = (supplier_var.get() or "").strip().lower()
            for row in tree.get_children():
                tree.delete(row)
            if not needle:
                return
            for p in self._supplier_products:
                if (p.get("supplier") or "").strip().lower() != needle:
                    continue
                tree.insert("", "end", values=(
                    p.get("code") or p.get("barcode") or "",
                    p.get("name") or "",
                    p.get("category") or "",
                    f"{float(p.get('stock') or 0):g}",
                    f"{float(p.get('cost_price') or 0):.2f}",
                    f"{float(p.get('price') or 0):.2f}",
                ))

        supplier_var.trace_add("write", render)
        refresh_list()

    def open_products_by_department_window(self):
        win = self.open_content_window("product_by_department", "Products by Department",
                                       group="inventory", icon=self.icon_products)
        if win is None:
            return
        try:
            win.minsize(780, 480)
        except Exception:
            pass

        top = ttk.Frame(win)
        top.pack(fill="x", padx=10, pady=(10, 4))
        ttk.Label(top, text="Department:").pack(side="left", padx=(0, 4))
        dept_var = tk.StringVar()
        dept_combo = ttk.Combobox(top, textvariable=dept_var,
                                   width=32, state="readonly")
        dept_combo.pack(side="left")
        ttk.Button(top, text="Refresh",
                   command=lambda: _refresh_department_list(dept_combo)
                   ).pack(side="right")

        cols = ("code", "name", "supplier", "stock", "cost", "price")
        heads = (
            ("code",     "Code",        100, "w"),
            ("name",     "Name",        340, "w"),
            ("supplier", "Supplier",    160, "w"),
            ("stock",    "Stock",        80, "e"),
            ("cost",     "Cost",         90, "e"),
            ("price",    "Price",        90, "e"),
        )
        tree = ttk.Treeview(win, columns=cols, show="headings", height=16)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._department_products = []

        def _refresh_department_list(combo):
            def worker():
                try:
                    r = requests.get(f"{self.SERVER}/products", timeout=6)
                    rows = r.json() if r.status_code == 200 else []
                except Exception as e:
                    self.after(0, lambda: self.message_error(
                        "Error", f"Could not reach server: {e}"))
                    return

                def apply():
                    self._department_products = list(rows or [])
                    names = sorted({(p.get("category") or "").strip()
                                    for p in self._department_products
                                    if (p.get("category") or "").strip()})
                    combo["values"] = [""] + names
                    if not dept_var.get() and names:
                        dept_var.set(names[0])
                    render()
                self.after(0, apply)
            threading.Thread(target=worker, daemon=True).start()

        def render(*_):
            needle = (dept_var.get() or "").strip().lower()
            for row in tree.get_children():
                tree.delete(row)
            if not needle:
                return
            for p in self._department_products:
                if (p.get("category") or "").strip().lower() != needle:
                    continue
                tree.insert("", "end", values=(
                    p.get("code") or p.get("barcode") or "",
                    p.get("name") or "",
                    p.get("supplier") or "",
                    f"{float(p.get('stock') or 0):g}",
                    f"{float(p.get('cost_price') or 0):.2f}",
                    f"{float(p.get('price') or 0):.2f}",
                ))

        dept_var.trace_add("write", render)
        _refresh_department_list(dept_combo)