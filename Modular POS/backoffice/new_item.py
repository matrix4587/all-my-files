"""
New Item screen mixin for BackOffice.

Contains the Purchase > New Item screen where an authorised user creates
a brand new product, and the "Add Supplier" dialog shared by several
screens.

Role gating:
    - Opening the screen and submitting both require self.can("new_item")
      (manager+).
    - The existing admin password prompt is kept for backwards
      compatibility, but a manager who is not admin can still create
      products because their role grants the new_item permission.
"""

import threading
import tkinter as tk
from tkinter import ttk

import requests

from common.center import center_window_on_screen
from common.titlebar import apply_green_titlebar


class NewItemMixin:
    """New Item screen and shared Add Supplier dialog."""

    def build_new_item_content(self):
        if not self.can("new_item"):
            self.message_error(
                "Not allowed",
                "You do not have permission to add or edit products.")
            return

        win = self.open_content_window("new_item", "New Item",
                                       group="purchase", icon=self.icon_products)
        if win is None:
            return

        if not self.prompt_admin_login(
                parent=win,
                reason="Adding a new item to the system requires admin authorization."):
            win.destroy()
            self.open_windows.pop("new_item", None)
            self.window_groups.pop("new_item", None)
            return

        self.new_item_status_var = tk.StringVar(value="")

        form = ttk.Frame(win)
        form.pack(fill="both", expand=True, padx=15, pady=15)

        supplier_row = ttk.Frame(form)
        supplier_row.pack(fill="x", pady=(0, 12))
        ttk.Label(supplier_row, text="Supplier:").pack(side="left", padx=(0, 5))
        self.new_item_supplier_var = tk.StringVar()
        self.new_item_supplier_combo = ttk.Combobox(
            supplier_row, textvariable=self.new_item_supplier_var, width=28)
        self.new_item_supplier_combo.pack(side="left")
        ttk.Button(
            supplier_row, text="+ New Supplier",
            command=lambda: self.open_add_supplier_dialog(
                target_var=self.new_item_supplier_var,
                on_added=self.fetch_new_item_suppliers)
        ).pack(side="left", padx=(8, 0))
        self.fetch_new_item_suppliers()

        fields_frame = ttk.Frame(form)
        fields_frame.pack(fill="x", pady=(0, 10))

        self.new_item_barcode_var = tk.StringVar()
        self.new_item_code_var = tk.StringVar()
        self.new_item_name_var = tk.StringVar()
        self.new_item_category_var = tk.StringVar()
        self.new_item_packaging_var = tk.StringVar()
        self.new_item_pack_size_var = tk.StringVar(value="1")
        self.new_item_cost_var = tk.StringVar()
        self.new_item_markup_var = tk.StringVar()
        self.new_item_markup_type_var = tk.StringVar(value="%")
        self.new_item_selling_var = tk.StringVar(value="-")

        def add_row(row, label_text, var, combo_values=None):
            ttk.Label(fields_frame, text=label_text).grid(
                row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            if combo_values is not None:
                widget = ttk.Combobox(fields_frame, textvariable=var,
                                      values=combo_values, width=26)
            else:
                widget = ttk.Entry(fields_frame, textvariable=var, width=28)
            widget.grid(row=row, column=1, sticky="w", pady=4)
            return widget

        add_row(0, "Barcode (long, scanned):", self.new_item_barcode_var)
        add_row(1, "Short Code (internal, optional):", self.new_item_code_var)
        add_row(2, "Description / Name:", self.new_item_name_var)
        add_row(3, "Department / Category:", self.new_item_category_var)
        add_row(4, "Packaging:", self.new_item_packaging_var,
                combo_values=["Pcs", "Dozen", "Carton", "Box", "Pack",
                              "Bale", "Bag", "Case", "Crate"])
        add_row(5, "Pcs per unit (e.g. 12 for 1ctn x 12pcs):",
                self.new_item_pack_size_var)
        add_row(6, "Initial Cost Price (per pcs):", self.new_item_cost_var)

        ttk.Label(fields_frame, text="Markup:").grid(row=7, column=0, sticky="w",
                                                     padx=(0, 8), pady=4)
        markup_input_frame = ttk.Frame(fields_frame)
        markup_input_frame.grid(row=7, column=1, sticky="w", pady=4)
        ttk.Entry(markup_input_frame, textvariable=self.new_item_markup_var,
                  width=10).pack(side="left")
        ttk.Combobox(markup_input_frame, textvariable=self.new_item_markup_type_var,
                     values=["%", "Amount"], width=7,
                     state="readonly").pack(side="left", padx=(6, 0))

        ttk.Label(fields_frame, text="Selling Price (per pcs):").grid(
            row=8, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(fields_frame, textvariable=self.new_item_selling_var, width=28,
                  state="readonly").grid(row=8, column=1, sticky="w", pady=4)

        self.new_item_cost_var.trace_add("write", self.recompute_new_item_selling_price)
        self.new_item_markup_var.trace_add("write", self.recompute_new_item_selling_price)
        self.new_item_markup_type_var.trace_add("write", self.recompute_new_item_selling_price)

        ttk.Label(form, textvariable=self.new_item_status_var,
                  foreground="#006600", wraplength=680).pack(fill="x", pady=(0, 5))

        button_row = ttk.Frame(form)
        button_row.pack(fill="x")
        ttk.Button(button_row, text="Clear",
                   command=self.clear_new_item_form).pack(side="right", padx=(8, 0))
        ttk.Button(button_row, text="Save Item",
                   command=self.submit_new_item).pack(side="right")
        ttk.Button(button_row, text="Logout",
                   command=self.logout_admin).pack(side="right", padx=(0, 8))

    def fetch_new_item_suppliers(self):
        def worker():
            try:
                r = requests.get(f"{self.SERVER}/suppliers", timeout=3)
                suppliers = r.json()
            except Exception as e:
                print("Could not fetch suppliers:", e)
                return
            self.after(0, lambda: self._apply_new_item_suppliers(suppliers))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_new_item_suppliers(self, suppliers):
        if not hasattr(self, "new_item_supplier_combo") or not self.new_item_supplier_combo.winfo_exists():
            return
        names = [s["name"] if isinstance(s, dict) else s for s in suppliers]
        self.new_item_supplier_combo["values"] = names

    def recompute_new_item_selling_price(self, *args):
        try:
            cost = float(self.new_item_cost_var.get())
            markup = float(self.new_item_markup_var.get())
        except ValueError:
            self.new_item_selling_var.set("-")
            return
        if self.new_item_markup_type_var.get() == "Amount":
            selling_price = cost + markup
        else:
            selling_price = cost + (cost * markup / 100)
        self.new_item_selling_var.set(f"{selling_price:.2f}")

    def clear_new_item_form(self):
        self.new_item_barcode_var.set("")
        self.new_item_code_var.set("")
        self.new_item_name_var.set("")
        self.new_item_category_var.set("")
        self.new_item_packaging_var.set("")
        self.new_item_pack_size_var.set("1")
        self.new_item_cost_var.set("")
        self.new_item_markup_var.set("")
        self.new_item_markup_type_var.set("%")
        self.new_item_selling_var.set("-")

    def submit_new_item(self):
        if not self.can("new_item"):
            self.message_error(
                "Not allowed",
                "You do not have permission to add or edit products.")
            return

        if not self.admin_credentials:
            if not self.prompt_admin_login(
                    reason="Adding a new item requires admin authorization."):
                return

        supplier = self.new_item_supplier_var.get().strip()
        if not supplier:
            self.message_error("Error", "Select a supplier (or add a new one)")
            return

        barcode = self.new_item_barcode_var.get().strip()
        short_code = self.new_item_code_var.get().strip() or barcode
        name = self.new_item_name_var.get().strip()

        if not barcode or not name:
            self.message_error("Error", "Barcode and Description are required")
            return

        if self.find_product_by_code(barcode) or self.find_product_by_code(short_code):
            self.message_error(
                "Error",
                f"A product with code or barcode '{barcode}' already exists")
            return

        try:
            pack_size = float(self.new_item_pack_size_var.get()) if self.new_item_pack_size_var.get().strip() else 1
            if pack_size <= 0:
                raise ValueError
        except ValueError:
            self.message_error("Error", "Pcs per unit must be a positive number (e.g. 12)")
            return

        try:
            cost_price = float(self.new_item_cost_var.get()) if self.new_item_cost_var.get().strip() else 0.0
            if cost_price < 0:
                raise ValueError
        except ValueError:
            self.message_error("Error", "Enter a valid cost price (per pcs)")
            return

        try:
            markup = float(self.new_item_markup_var.get()) if self.new_item_markup_var.get().strip() else 0.0
        except ValueError:
            self.message_error("Error", "Enter a valid markup")
            return

        markup_type = self.new_item_markup_type_var.get()
        if markup_type == "Amount":
            selling_price = cost_price + markup
        else:
            selling_price = cost_price + (cost_price * markup / 100)

        payload = {
            "barcode": barcode,
            "code": short_code,
            "name": name,
            "category": self.new_item_category_var.get().strip(),
            "packaging": self.new_item_packaging_var.get().strip(),
            "pack_size": pack_size,
            "supplier": supplier,
            "cost_price": cost_price,
            "markup": markup,
            "markup_type": markup_type,
            "selling_price": round(selling_price, 2),
            "price": round(selling_price, 2),
            "stock": 0,
        }

        def worker():
            try:
                u, p = self.admin_credentials
                headers = {"X-Admin-User": u, "X-Admin-Pass": p}
                r = requests.post(f"{self.SERVER}/products", json=payload,
                                  headers=headers, timeout=5)
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return

            def apply():
                if r.status_code in (200, 201):
                    self.refresh_products_cache()
                    self.new_item_status_var.set(
                        f"Saved '{name}' (code: {short_code}, {pack_size:g} pcs/unit). "
                        f"It's now available in GRN and elsewhere.")
                    self.clear_new_item_form()
                elif r.status_code == 401:
                    self.message_error("Error",
                                       "Authorization failed. Please log in again.")
                    self.logout_admin()
                else:
                    self.message_error("Error", r.text)
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    # ---------------- Shared Add Supplier dialog ----------------

    def open_add_supplier_dialog(self, target_var=None, on_added=None):
        if target_var is None and hasattr(self, "grn_supplier_var"):
            target_var = self.grn_supplier_var
        if on_added is None and hasattr(self, "fetch_grn_suppliers"):
            on_added = self.fetch_grn_suppliers

        dialog = tk.Toplevel(self)
        dialog.title("Add New Supplier")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()
        center_window_on_screen(dialog, 320, 180)
        dialog.after(150, lambda w=dialog: apply_green_titlebar(w))

        ttk.Label(dialog, text="Supplier Name:").pack(anchor="w", padx=12, pady=(15, 2))
        name_var = tk.StringVar()
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=32)
        name_entry.pack(padx=12)
        name_entry.focus_set()

        ttk.Label(dialog, text="Phone (optional):").pack(anchor="w", padx=12, pady=(10, 2))
        phone_var = tk.StringVar()
        ttk.Entry(dialog, textvariable=phone_var, width=32).pack(padx=12)

        button_row = ttk.Frame(dialog)
        button_row.pack(fill="x", padx=12, pady=15)
        ttk.Button(button_row, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(
            button_row, text="Save",
            command=lambda: self.submit_new_supplier(
                dialog, name_var, phone_var, target_var, on_added)
        ).pack(side="right", padx=(0, 8))

    def submit_new_supplier(self, dialog, name_var, phone_var,
                             target_var=None, on_added=None):
        name = name_var.get().strip()
        if not name:
            self.message_error("Error", "Enter a supplier name", parent=dialog)
            return

        payload = {"name": name}
        phone = phone_var.get().strip()
        if phone:
            payload["phone"] = phone

        def worker():
            try:
                r = requests.post(f"{self.SERVER}/suppliers", json=payload, timeout=5)
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}", parent=dialog))
                return

            def apply():
                if r.status_code in (200, 201):
                    if on_added:
                        on_added()
                    if target_var is not None:
                        target_var.set(name)
                    dialog.destroy()
                else:
                    self.message_error("Error", r.text, parent=dialog)
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()