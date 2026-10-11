"""
GRN screen mixin for BackOffice.

Contains everything related to Goods Received Notes:
  - The GRNs screen (supplier selection, line entry, receive)
  - The GRN List window

Qty is entered in packagings (e.g. 20 cartons). The server converts to pcs
using the product's pack_size. Cost is per pcs.
"""

import datetime
import threading
import tkinter as tk
from tkinter import ttk

import requests


class GrnsMixin:
    """GRNs screen and GRN List."""

    def build_grns_content(self):
        win = self.open_content_window("grns", "GRNs", group="purchase", icon=self.icon_grn)
        if win is None:
            return

        self.grn_lines = []
        self.grn_supplier_locked = False

        supplier_frame = ttk.Frame(win)
        supplier_frame.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Button(supplier_frame, text="GRN List",
                   command=self.open_grn_list_window).pack(side="right")

        ttk.Label(supplier_frame, text="Select Supplier:").pack(side="left", padx=(0, 5))
        self.grn_supplier_var = tk.StringVar()
        self.grn_supplier_combo = ttk.Combobox(supplier_frame,
                                                textvariable=self.grn_supplier_var,
                                                width=30)
        self.grn_supplier_combo.pack(side="left")
        self.fetch_grn_suppliers()

        self.grn_new_supplier_btn = ttk.Button(
            supplier_frame, text="+ New Supplier",
            command=lambda: self.open_add_supplier_dialog(
                target_var=self.grn_supplier_var,
                on_added=self.fetch_grn_suppliers))
        self.grn_new_supplier_btn.pack(side="left", padx=(8, 0))

        self.grn_supplier_lock_btn = ttk.Button(
            supplier_frame, text="Lock Supplier",
            command=self.toggle_grn_supplier_lock)
        self.grn_supplier_lock_btn.pack(side="left", padx=(8, 0))

        self.grn_locked_supplier_var = tk.StringVar(value="")
        ttk.Label(supplier_frame, textvariable=self.grn_locked_supplier_var,
                  foreground="#006600", font=("Arial", 9, "bold")).pack(side="left", padx=(10, 0))

        line_frame = ttk.Frame(win)
        line_frame.pack(fill="x", padx=10, pady=10)

        qty_pack_frame = ttk.Frame(line_frame)
        qty_pack_frame.pack(side="right")
        ttk.Label(qty_pack_frame, text="Quantity (in packagings):").grid(row=0, column=0, sticky="w", padx=(0, 2))
        ttk.Label(qty_pack_frame, text="Packaging:").grid(row=0, column=1, sticky="w", padx=(10, 2))
        self.grn_qty_var = tk.StringVar()
        self.grn_packaging_var = tk.StringVar()
        ttk.Entry(qty_pack_frame, textvariable=self.grn_qty_var,
                  width=8).grid(row=1, column=0, sticky="w")
        self.grn_packaging_combo = ttk.Combobox(qty_pack_frame,
                                                 textvariable=self.grn_packaging_var,
                                                 width=16)
        self.grn_packaging_combo.grid(row=1, column=1, sticky="w", padx=(10, 0))

        code_col = ttk.Frame(line_frame)
        code_col.pack(side="left", padx=(0, 10))
        ttk.Label(code_col, text="Code / Barcode:").pack(anchor="w")
        self.grn_code_var = tk.StringVar()
        ttk.Entry(code_col, textvariable=self.grn_code_var, width=12).pack()

        desc_col = ttk.Frame(line_frame)
        desc_col.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(desc_col, text="Description:").pack(anchor="w")
        self.grn_desc_var = tk.StringVar(value="-")
        ttk.Entry(desc_col, textvariable=self.grn_desc_var,
                  state="readonly").pack(fill="x", expand=True)

        # Live preview of the pcs count.
        self.grn_expected_var = tk.StringVar(value="")
        ttk.Label(win, textvariable=self.grn_expected_var,
                  foreground="#555555").pack(anchor="w", padx=12)

        pricing_row = ttk.Frame(win)
        pricing_row.pack(fill="x", padx=10, pady=(5, 10))
        ttk.Button(pricing_row, text="Delete",
                   command=self.remove_grn_line).pack(side="right", padx=(5, 8))
        ttk.Button(pricing_row, text="Add",
                   command=self.add_grn_line).pack(side="right", pady=8)

        self.grn_code_var.trace_add("write", self.on_grn_code_change)
        self.grn_qty_var.trace_add("write", lambda *a: self._update_grn_preview())
        self.grn_packaging_var.trace_add("write", lambda *a: self._update_grn_preview())

        bottom_frame = ttk.Frame(win)
        bottom_frame.pack(side="bottom", fill="x", padx=10, pady=10)

        self.grn_total_var = tk.StringVar(value="Value of all delivery: 0.00")
        total_label = tk.Label(
            bottom_frame, textvariable=self.grn_total_var,
            font=("Arial", 12, "bold"), bg="#e8a0a0", fg="black",
            relief="raised", bd=2, padx=14, pady=4)
        total_label.pack(side="left")

        receive_button = tk.Label(
            bottom_frame, text="RECEIVE", font=("Arial", 11, "bold"),
            bg="#8fd08f", fg="black", relief="raised", bd=2, padx=16, pady=6,
            cursor="hand2")
        receive_button.pack(side="right")
        receive_button.bind("<Button-1>", lambda e: self.receive_grn())

        ttk.Button(bottom_frame, text="Clear",
                   command=self.clear_grn_form).pack(side="right", padx=(0, 10))

        lines_frame = ttk.LabelFrame(win, text="Items fed but not yet added to system stock")
        lines_frame.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 5))

        tree_container = ttk.Frame(lines_frame)
        tree_container.pack(fill="both", expand=True, padx=5, pady=5)

        self.grn_tree = ttk.Treeview(
            tree_container,
            columns=("code", "desc", "qty", "total_qty", "cost", "total"),
            show="headings", height=6)
        self.grn_tree.heading("code", text="Code")
        self.grn_tree.heading("desc", text="Description")
        self.grn_tree.heading("qty", text="Qty (packagings)")
        self.grn_tree.heading("total_qty", text="Total Pcs")
        self.grn_tree.heading("cost", text="Cost/pcs")
        self.grn_tree.heading("total", text="Total")

        grn_scrollbar = ttk.Scrollbar(tree_container, orient="vertical",
                                       command=self.grn_tree.yview)
        self.grn_tree.configure(yscrollcommand=grn_scrollbar.set)

        self.grn_tree.pack(side="left", fill="both", expand=True)
        grn_scrollbar.pack(side="right", fill="y")

        self.make_columns_responsive(win, self.grn_tree, [2, 4, 1, 1, 1, 1])

    def fetch_grn_suppliers(self):
        def worker():
            try:
                r = requests.get(f"{self.SERVER}/suppliers", timeout=3)
                suppliers = r.json()
            except Exception as e:
                print("Could not fetch suppliers:", e)
                return
            self.after(0, lambda: self._apply_grn_suppliers(suppliers))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_grn_suppliers(self, suppliers):
        if not hasattr(self, "grn_supplier_combo") or not self.grn_supplier_combo.winfo_exists():
            return
        names = [s["name"] if isinstance(s, dict) else s for s in suppliers]
        self.grn_supplier_combo["values"] = names

    def toggle_grn_supplier_lock(self):
        if not self.grn_supplier_locked:
            supplier = self.grn_supplier_var.get().strip()
            if not supplier:
                self.message_error("Error", "Select a supplier first")
                return
            self.grn_supplier_locked = True
            self.grn_supplier_combo.configure(state="disabled")
            self.grn_new_supplier_btn.configure(state="disabled")
            self.grn_supplier_lock_btn.configure(text="Change Supplier")
            self.grn_locked_supplier_var.set(f"Locked to: {supplier}")
        else:
            self._reset_grn_supplier_lock()

    def _reset_grn_supplier_lock(self):
        self.grn_supplier_locked = False
        if hasattr(self, "grn_supplier_combo") and self.grn_supplier_combo.winfo_exists():
            self.grn_supplier_combo.configure(state="normal")
        if hasattr(self, "grn_new_supplier_btn") and self.grn_new_supplier_btn.winfo_exists():
            self.grn_new_supplier_btn.configure(state="normal")
        if hasattr(self, "grn_supplier_lock_btn") and self.grn_supplier_lock_btn.winfo_exists():
            self.grn_supplier_lock_btn.configure(text="Lock Supplier")
        if hasattr(self, "grn_locked_supplier_var"):
            self.grn_locked_supplier_var.set("")

    def on_grn_code_change(self, *args):
        if self._grn_code_normalizing:
            return
        code = self.grn_code_var.get().strip()
        if not code:
            self.grn_desc_var.set("-")
            self._update_grn_preview()
            return
        match = self.find_product_by_code(code)
        if match:
            short_code = self.get_short_code(match)
            if short_code and short_code != code:
                self._grn_code_normalizing = True
                self.grn_code_var.set(short_code)
                self._grn_code_normalizing = False
            self.grn_desc_var.set(match["name"])

            packaging_options = []
            existing_packaging = match.get("packaging")
            if existing_packaging:
                packaging_options.append(existing_packaging)
            for generic in ("Pcs", "Dozen", "Carton", "Box", "Pack",
                            "Bale", "Bag", "Case", "Crate"):
                if generic not in packaging_options:
                    packaging_options.append(generic)
            self.grn_packaging_combo["values"] = packaging_options
            if existing_packaging and not self.grn_packaging_var.get().strip():
                self.grn_packaging_var.set(existing_packaging)
        else:
            self.grn_desc_var.set("Not found — add it via Purchase > New Item")
        self._update_grn_preview()

    def _update_grn_preview(self, *args):
        if not hasattr(self, "grn_expected_var"):
            return
        code = self.grn_code_var.get().strip()
        if not code:
            self.grn_expected_var.set("")
            return
        match = self.find_product_by_code(code)
        if not match:
            self.grn_expected_var.set("")
            return
        try:
            qty = float(self.grn_qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            self.grn_expected_var.set("")
            return
        pack_size = float(match.get("pack_size") or 1)
        total_pcs = qty * pack_size
        cost_per_pcs = float(match.get("cost_price") or 0)
        line_value = total_pcs * cost_per_pcs
        self.grn_expected_var.set(
            f"{qty:g} × {pack_size:g} pcs = {total_pcs:g} pcs "
            f"× {cost_per_pcs:.2f}/pcs = {line_value:.2f}"
        )

    def add_grn_line(self):
        if not self.grn_supplier_locked:
            self.message_error(
                "Error",
                "Select a supplier and click 'Lock Supplier' before adding items")
            return

        code = self.grn_code_var.get().strip()
        if not code:
            self.message_error("Error", "Enter a product code")
            return

        match = self.find_product_by_code(code)
        if not match:
            self.message_error("Error", f"No product found for code '{code}'")
            return

        try:
            qty = float(self.grn_qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            self.message_error("Error", "Enter a valid quantity greater than 0")
            return

        def to_float(value, default=0.0):
            try:
                return float(value)
            except (TypeError, ValueError):
                return default

        pack_size = to_float(match.get("pack_size"), 1) or 1
        total_qty = qty * pack_size
        unit_cost = to_float(match.get("cost_price", match.get("price")))
        markup = to_float(match.get("markup"))
        markup_type = match.get("markup_type", "%")
        selling_price = to_float(match.get("selling_price", match.get("price")))
        packaging = self.grn_packaging_var.get().strip()
        line_total = total_qty * unit_cost

        self.grn_lines.append({
            "barcode": match["barcode"],
            "name": match["name"],
            "qty": qty,
            "pack_size": pack_size,
            "total_qty": total_qty,
            "packaging": packaging,
            "unit_cost": unit_cost,
            "markup": markup,
            "markup_type": markup_type,
            "selling_price": selling_price,
            "line_total": line_total,
        })

        self.grn_tree.insert(
            "", "end",
            values=(match["barcode"], match["name"], f"{qty:g}",
                    f"{total_qty:g}", f"{unit_cost:.2f}", f"{line_total:.2f}"))

        self.recompute_grn_total()

        self.grn_code_var.set("")
        self.grn_qty_var.set("")
        self.grn_packaging_var.set("")
        self.grn_desc_var.set("-")
        self.grn_expected_var.set("")

    def remove_grn_line(self):
        selected = self.grn_tree.selection()
        if not selected:
            return
        for item_id in selected:
            index = self.grn_tree.index(item_id)
            self.grn_tree.delete(item_id)
            if 0 <= index < len(self.grn_lines):
                del self.grn_lines[index]
        self.recompute_grn_total()

    def recompute_grn_total(self):
        total = sum(line["line_total"] for line in self.grn_lines)
        self.grn_total_var.set(f"Value of all delivery: {total:.2f}")

    def clear_grn_form(self):
        self.grn_lines = []
        if hasattr(self, "grn_tree") and self.grn_tree.winfo_exists():
            for row in self.grn_tree.get_children():
                self.grn_tree.delete(row)
        self.grn_code_var.set("")
        self.grn_qty_var.set("")
        self.grn_packaging_var.set("")
        self.grn_desc_var.set("-")
        if hasattr(self, "grn_expected_var"):
            self.grn_expected_var.set("")
        self._reset_grn_supplier_lock()
        self.grn_supplier_var.set("")
        self.recompute_grn_total()

    def receive_grn(self):
        if not self.grn_lines:
            self.message_error("Error", "Add at least one item before receiving")
            return

        supplier = self.grn_supplier_var.get().strip()
        if not supplier:
            self.message_error("Error", "Select a supplier")
            return

        payload = {
            "supplier": supplier,
            "date": datetime.date.today().isoformat(),
            "lines": [{
                "barcode": line["barcode"], "qty": line["qty"],
                "packaging": line["packaging"], "unit_cost": line["unit_cost"],
                "markup": line["markup"], "markup_type": line["markup_type"],
                "selling_price": line["selling_price"],
            } for line in self.grn_lines],
        }

        def worker():
            try:
                r = requests.post(f"{self.SERVER}/grn", json=payload, timeout=5)
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return

            def apply():
                if r.status_code in (200, 201):
                    self.message_info("Success", "Stock received and prices updated")
                    self.refresh_products_cache()
                    self.clear_grn_form()
                else:
                    self.message_error("Error", r.text)
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    def open_grn_list_window(self):
        win = self.open_content_window("grn_list", "GRN List",
                                       group="purchase", icon=self.icon_grn)
        if win is None:
            return
        win.minsize(400, 300)

        tree = ttk.Treeview(win, columns=("id", "supplier", "date", "total"),
                            show="headings")
        tree.heading("id", text="GRN #")
        tree.heading("supplier", text="Supplier")
        tree.heading("date", text="Date")
        tree.heading("total", text="Total")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.make_columns_responsive(win, tree, [1, 3, 2, 1])

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/grns", timeout=3)
                grns = r.json()
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return

            def apply():
                if not tree.winfo_exists():
                    return
                for g in grns:
                    tree.insert("", "end",
                                values=(g.get("id"), g.get("supplier"),
                                        g.get("date"), g.get("total")))
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()