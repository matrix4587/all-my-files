"""
Orders screen for BackOffice.

Purchase orders to suppliers - a lighter GRN. No cost / markup / selling
price and no stock update here (nothing has arrived yet); that happens
later on the GRN screen when the delivery is actually received.

Qty is entered in packagings. The server converts to pcs using the
product's pack_size. Cost is per pcs, so line total = total_pcs × cost/pcs.

Two sub-screens:
    - New Order form (build_orders_content)
    - Placed Orders list (open_purchase_orders_list_window)

Role gating:
    - Approve (clicking the Status cell) requires self.can("approve_lpo")
      — admin only. Non-admins see the status as a read-only label.

Async safety:
    - Every background worker schedules its apply() with self.after(0, ...)
      and every apply() first checks that its widgets still exist, so a
      callback that arrives after the user closed the window silently
      does nothing instead of leaving the app in a bad state.
"""

import datetime
import os
import subprocess
import sys
import tempfile
import threading
import traceback
import tkinter as tk
from tkinter import ttk

import requests

from common.center import center_window_on_screen

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    _REPORTLAB_OK = True
except Exception:
    _REPORTLAB_OK = False


PACKAGING_FORMS = [
    "Pcs", "Dozen", "Carton", "Box", "Pack", "Bale", "Bag", "Case", "Crate",
]


def _alive(widget):
    """True if widget exists and Tk still knows about it."""
    try:
        return widget is not None and widget.winfo_exists()
    except Exception:
        return False


class OrdersMixin:
    """Orders entry screen + Placed Orders list."""

    # ------------------------------------------------------- New order form

    def build_orders_content(self):
        win = self.open_content_window("orders", "Orders",
                                       group="orders", icon=self.icon_orders)
        if win is None:
            return

        self.order_lines = []
        self._po_order_ids = {}
        self._order_pack_size = 1
        if not hasattr(self, "order_suppliers_cache"):
            self.order_suppliers_cache = []

        top_button_frame = ttk.Frame(win)
        top_button_frame.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Button(top_button_frame, text="New Order",
                   command=self.clear_order_form).pack(side="left")
        ttk.Button(top_button_frame, text="Placed Orders",
                   command=self.open_purchase_orders_list_window).pack(side="left", padx=(5, 0))

        supplier_frame = ttk.Frame(win)
        supplier_frame.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(supplier_frame, text="Supplier:").pack(side="left", padx=(0, 5))
        self.order_supplier_var = tk.StringVar()
        self.order_supplier_entry = ttk.Entry(supplier_frame,
                                              textvariable=self.order_supplier_var,
                                              width=32)
        self.order_supplier_entry.pack(side="left")
        self.order_supplier_search_btn = ttk.Button(
            supplier_frame, text="\U0001F50D", width=3,
            command=self.open_order_supplier_picker)
        self.order_supplier_search_btn.pack(side="left", padx=(4, 0))
        self.fetch_order_suppliers()

        line_frame = ttk.Frame(win)
        line_frame.pack(fill="x", padx=10, pady=10)

        qty_pack_frame = ttk.Frame(line_frame)
        qty_pack_frame.pack(side="right")

        ttk.Label(qty_pack_frame, text="Set Packaging:").grid(row=0, column=0, sticky="w", padx=(0, 2))
        ttk.Label(qty_pack_frame, text="Quantity:").grid(row=0, column=1, sticky="w", padx=(10, 2))
        ttk.Label(qty_pack_frame, text="Packaging:").grid(row=0, column=2, sticky="w", padx=(10, 2))

        self.order_set_packaging_var = tk.StringVar(value="-")
        self.order_qty_var = tk.StringVar()
        self.order_packaging_var = tk.StringVar()

        ttk.Entry(qty_pack_frame, textvariable=self.order_set_packaging_var,
                  width=12, state="readonly").grid(row=1, column=0, sticky="w")
        ttk.Entry(qty_pack_frame, textvariable=self.order_qty_var,
                  width=8).grid(row=1, column=1, sticky="w", padx=(10, 0))
        self.order_packaging_combo = ttk.Combobox(
            qty_pack_frame, textvariable=self.order_packaging_var,
            width=16, state="readonly", values=PACKAGING_FORMS)
        self.order_packaging_combo.grid(row=1, column=2, sticky="w", padx=(10, 0))

        code_col = ttk.Frame(line_frame)
        code_col.pack(side="left", padx=(0, 10))
        ttk.Label(code_col, text="Code:").pack(anchor="w")
        self.order_code_var = tk.StringVar()
        ttk.Entry(code_col, textvariable=self.order_code_var, width=12).pack()

        desc_col = ttk.Frame(line_frame)
        desc_col.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(desc_col, text="Description:").pack(anchor="w")
        self.order_desc_var = tk.StringVar(value="-")
        ttk.Entry(desc_col, textvariable=self.order_desc_var,
                  state="readonly").pack(fill="x", expand=True)

        self.order_expected_var = tk.StringVar(value="")
        ttk.Label(win, textvariable=self.order_expected_var,
                  foreground="#555555").pack(anchor="w", padx=12)

        notes_row = ttk.Frame(win)
        notes_row.pack(fill="x", padx=10, pady=(5, 10))
        ttk.Label(notes_row, text="Notes:").pack(side="left", padx=(0, 5))
        self.order_notes_var = tk.StringVar()
        ttk.Entry(notes_row, textvariable=self.order_notes_var
                  ).pack(side="left", fill="x", expand=True, padx=(0, 15))
        ttk.Button(notes_row, text="Delete",
                   command=self.remove_order_line).pack(side="right", padx=(5, 0))
        ttk.Button(notes_row, text="Add",
                   command=self.add_order_line).pack(side="right")

        self.order_code_var.trace_add("write", self.on_order_code_change)
        self.order_qty_var.trace_add("write", lambda *a: self._update_order_preview())

        bottom_frame = ttk.Frame(win)
        bottom_frame.pack(side="bottom", fill="x", padx=10, pady=10)
        self.order_count_var = tk.StringVar(value="Items ordered: 0")
        tk.Label(bottom_frame, textvariable=self.order_count_var,
                 font=("Arial", 12, "bold"), bg="#e8a0a0", fg="black",
                 relief="raised", bd=2, padx=14, pady=4).pack(side="left")

        send_button = tk.Label(bottom_frame, text="SEND ORDER",
                                font=("Arial", 11, "bold"), bg="#8fd08f", fg="black",
                                relief="raised", bd=2, padx=16, pady=6, cursor="hand2")
        send_button.pack(side="right")
        send_button.bind("<Button-1>", lambda e: self.send_order())
        ttk.Button(bottom_frame, text="Clear",
                   command=self.clear_order_form).pack(side="right", padx=(0, 10))

        lines_frame = ttk.LabelFrame(win, text="Items to order (not yet sent)")
        lines_frame.pack(side="top", fill="both", expand=True, padx=10, pady=(0, 5))
        self.order_tree = ttk.Treeview(
            lines_frame,
            columns=("code", "desc", "qty", "total_qty", "packaging", "notes"),
            show="headings")
        self.order_tree.heading("code", text="Code")
        self.order_tree.heading("desc", text="Description")
        self.order_tree.heading("qty", text="Qty (packagings)")
        self.order_tree.heading("total_qty", text="Total Pcs")
        self.order_tree.heading("packaging", text="Packaging")
        self.order_tree.heading("notes", text="Notes")
        self.order_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.make_columns_responsive(win, self.order_tree, [1, 3, 1, 1, 1, 2])

    def fetch_order_suppliers(self):
        def worker():
            try:
                r = requests.get(f"{self.SERVER}/suppliers", timeout=4)
                suppliers = r.json()
            except Exception as e:
                print("Could not fetch suppliers:", e)
                return
            self.after(0, lambda: self._apply_order_suppliers(suppliers))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_order_suppliers(self, suppliers):
        self.order_suppliers_cache = [
            s["name"] if isinstance(s, dict) else str(s) for s in suppliers
        ]

    def open_order_supplier_picker(self):
        if not hasattr(self, "order_suppliers_cache"):
            self.order_suppliers_cache = []

        dialog = tk.Toplevel(self)
        dialog.title("Select Supplier")
        dialog.resizable(False, False)
        center_window_on_screen(dialog, 420, 380)

        top = ttk.Frame(dialog)
        top.pack(fill="x", padx=10, pady=(10, 5))
        ttk.Label(top, text="Filter:").pack(side="left", padx=(0, 5))
        filter_var = tk.StringVar(value=self.order_supplier_var.get().strip())
        filter_entry = ttk.Entry(top, textvariable=filter_var, width=32)
        filter_entry.pack(side="left", fill="x", expand=True)
        filter_entry.focus_set()

        list_frame = ttk.Frame(dialog)
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        tree = ttk.Treeview(list_frame, columns=("name",), show="headings")
        tree.heading("name", text="Supplier")
        tree.pack(side="left", fill="both", expand=True)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")

        def populate(*_):
            if not _alive(tree):
                return
            for row in tree.get_children():
                tree.delete(row)
            needle = filter_var.get().strip().lower()
            for name in self.order_suppliers_cache:
                if not needle or needle in name.lower():
                    tree.insert("", "end", values=(name,))
            children = tree.get_children()
            if children:
                tree.selection_set(children[0])
                tree.focus(children[0])

        filter_var.trace_add("write", populate)
        populate()

        def do_ok():
            if not _alive(tree):
                dialog.destroy()
                return
            sel = tree.selection()
            if not sel:
                self.message_error("Error", "Select a supplier first", parent=dialog)
                return
            name = tree.item(sel[0], "values")[0]
            self.order_supplier_var.set(name)
            dialog.destroy()

        def do_cancel():
            dialog.destroy()

        bottom = ttk.Frame(dialog)
        bottom.pack(fill="x", padx=10, pady=(5, 10))
        ttk.Button(bottom, text="Cancel", command=do_cancel).pack(side="right")
        ttk.Button(bottom, text="OK", command=do_ok).pack(side="right", padx=(0, 8))

        tree.bind("<Double-1>", lambda e: do_ok())
        tree.bind("<Return>", lambda e: do_ok())
        filter_entry.bind("<Return>", lambda e: do_ok())
        dialog.bind("<Escape>", lambda e: do_cancel())

    def on_order_code_change(self, *args):
        code = self.order_code_var.get().strip()
        if not code:
            self.order_desc_var.set("-")
            self.order_set_packaging_var.set("-")
            self.order_packaging_combo["values"] = PACKAGING_FORMS
            self.order_packaging_var.set("")
            self._order_pack_size = 1
            self._update_order_preview()
            return
        match = self.find_product_by_code(code)
        if match:
            self.order_desc_var.set(match["name"])
            existing = (match.get("packaging") or "").strip()
            self.order_set_packaging_var.set(existing or "-")
            try:
                self._order_pack_size = float(match.get("pack_size") or 1)
            except (TypeError, ValueError):
                self._order_pack_size = 1
            options = list(PACKAGING_FORMS)
            if existing:
                if existing in options:
                    options.remove(existing)
                options.insert(0, existing)
            self.order_packaging_combo["values"] = options
            self.order_packaging_var.set(existing or options[0])
        else:
            self.order_desc_var.set("Not found")
            self.order_set_packaging_var.set("-")
            self.order_packaging_combo["values"] = PACKAGING_FORMS
            self.order_packaging_var.set("")
            self._order_pack_size = 1
        self._update_order_preview()

    def _update_order_preview(self, *args):
        if not hasattr(self, "order_expected_var"):
            return
        code = self.order_code_var.get().strip()
        if not code:
            self.order_expected_var.set("")
            return
        match = self.find_product_by_code(code)
        if not match:
            self.order_expected_var.set("")
            return
        try:
            qty = float(self.order_qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            self.order_expected_var.set("")
            return
        pack_size = float(match.get("pack_size") or 1)
        total_pcs = qty * pack_size
        cost_per_pcs = float(match.get("cost_price") or 0)
        line_value = total_pcs * cost_per_pcs
        self.order_expected_var.set(
            f"{qty:g} × {pack_size:g} pcs = {total_pcs:g} pcs "
            f"× {cost_per_pcs:.2f}/pcs = {line_value:.2f}"
        )

    def add_order_line(self):
        code = self.order_code_var.get().strip()
        if not code:
            self.message_error("Error", "Enter a product code")
            return
        match = self.find_product_by_code(code)
        if not match:
            self.message_error("Error", f"No product found for code '{code}'")
            return
        try:
            qty = float(self.order_qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            self.message_error("Error", "Enter a valid quantity greater than 0")
            return
        packaging = self.order_packaging_var.get().strip()
        if not packaging:
            self.message_error("Error", "Select a packaging form")
            return
        notes = self.order_notes_var.get().strip()

        try:
            pack_size = float(match.get("pack_size") or 1)
        except (TypeError, ValueError):
            pack_size = 1
        total_qty = qty * pack_size

        self.order_lines.append({
            "barcode": match["barcode"],
            "name": match["name"],
            "qty": qty,
            "pack_size": pack_size,
            "total_qty": total_qty,
            "packaging": packaging,
            "notes": notes,
        })
        self.order_tree.insert(
            "", "end",
            values=(self.get_short_code(match), match["name"], f"{qty:g}",
                    f"{total_qty:g}", packaging, notes))
        self.recompute_order_count()

        self.order_code_var.set("")
        self.order_qty_var.set("")
        self.order_packaging_var.set("")
        self.order_notes_var.set("")
        self.order_desc_var.set("-")
        self.order_set_packaging_var.set("-")
        self.order_expected_var.set("")
        self._order_pack_size = 1

    def remove_order_line(self):
        if not _alive(self.order_tree):
            return
        selected = self.order_tree.selection()
        if not selected:
            return
        for item_id in selected:
            index = self.order_tree.index(item_id)
            self.order_tree.delete(item_id)
            if 0 <= index < len(self.order_lines):
                del self.order_lines[index]
        self.recompute_order_count()

    def recompute_order_count(self):
        self.order_count_var.set(f"Items ordered: {len(self.order_lines)}")

    def clear_order_form(self):
        self.order_lines = []
        if hasattr(self, "order_tree") and _alive(self.order_tree):
            for row in self.order_tree.get_children():
                self.order_tree.delete(row)
        self.order_code_var.set("")
        self.order_qty_var.set("")
        self.order_packaging_var.set("")
        self.order_notes_var.set("")
        self.order_desc_var.set("-")
        self.order_supplier_var.set("")
        if hasattr(self, "order_set_packaging_var"):
            self.order_set_packaging_var.set("-")
        if hasattr(self, "order_expected_var"):
            self.order_expected_var.set("")
        if hasattr(self, "order_packaging_combo") and _alive(self.order_packaging_combo):
            self.order_packaging_combo["values"] = PACKAGING_FORMS
        self.recompute_order_count()

    def send_order(self):
        if not self.order_lines:
            self.message_error("Error", "Add at least one item before sending")
            return
        supplier = self.order_supplier_var.get().strip()
        if not supplier:
            self.message_error("Error", "Select a supplier")
            return

        payload = {
            "supplier": supplier,
            "date": datetime.date.today().isoformat(),
            "lines": [{
                "barcode": line["barcode"],
                "qty": line["qty"],
                "packaging": line["packaging"],
                "notes": line["notes"],
            } for line in self.order_lines],
        }

        def worker():
            try:
                r = requests.post(f"{self.SERVER}/purchase_orders", json=payload, timeout=5)
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return

            def apply():
                if r.status_code in (200, 201):
                    self.message_info("Success", "Order sent to supplier")
                    self.clear_order_form()
                else:
                    self.message_error("Error", r.text)
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------ Placed Orders list

    def open_purchase_orders_list_window(self):
        win = self.open_content_window("orders_list", "Placed Orders",
                                       group="orders", icon=self.icon_orders)
        if win is None:
            return

        top_frame = ttk.Frame(win)
        top_frame.pack(fill="x", padx=10, pady=10)

        tree = ttk.Treeview(
            win,
            columns=("date", "lpo", "supplier", "value", "expiry", "status"),
            show="headings")
        ttk.Button(top_frame, text="Refresh",
                   command=lambda: self.refresh_purchase_orders_list(tree)).pack(side="left")
        ttk.Button(top_frame, text="View",
                   command=lambda: self.view_selected_purchase_order(tree)).pack(side="left", padx=(5, 0))

        tree.heading("date", text="Order Date")
        tree.heading("lpo", text="LPO No.")
        tree.heading("supplier", text="Supplier")
        tree.heading("value", text="Order Value")
        tree.heading("expiry", text="Expiry Date")
        tree.heading("status", text="Status")
        tree.pack(fill="both", expand=True, padx=10, pady=10)
        tree.tag_configure("expired", foreground="red")
        self.make_columns_responsive(win, tree, [1, 1, 2, 1, 1, 1])

        can_approve = self.can("approve_lpo")

        def on_tree_click(event):
            if not can_approve:
                return
            if not _alive(tree):
                return
            region = tree.identify_region(event.x, event.y)
            if region != "cell":
                return
            col = tree.identify_column(event.x)
            row_id = tree.identify_row(event.y)
            if not row_id:
                return
            if col != "#6":
                return
            self.toggle_order_approval(tree, row_id)

        if can_approve:
            tree.bind("<Button-1>", on_tree_click)
        tree.bind("<Double-1>", lambda e: self.view_selected_purchase_order(tree))

        self.refresh_purchase_orders_list(tree)

    def refresh_purchase_orders_list(self, tree):
        if not _alive(tree):
            return

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/purchase_orders", timeout=5)
                orders = r.json()
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return

            def apply():
                # Window may have been closed while the request was in flight.
                if not _alive(tree):
                    return
                try:
                    for row in tree.get_children():
                        tree.delete(row)
                    today = datetime.date.today()
                    self._po_order_ids = {}
                    for o in orders:
                        order_id = o.get("id")
                        expiry_str = o.get("expiry_date")
                        approved = o.get("approved", False)
                        is_expired = False
                        if expiry_str:
                            try:
                                is_expired = datetime.date.fromisoformat(expiry_str) < today
                            except ValueError:
                                pass
                        checkbox = "\u2611 Approved" if approved else "\u2610 Pending"
                        tags = ("expired",) if is_expired else ()
                        item_id = tree.insert(
                            "", "end",
                            values=(o.get("date"), o.get("lpo_no"), o.get("supplier"),
                                    f"{o.get('value', 0):.2f}", expiry_str, checkbox),
                            tags=tags)
                        self._po_order_ids[item_id] = (order_id, approved, o)
                except Exception as e:
                    print("refresh_purchase_orders_list apply error:", e)
                    traceback.print_exc()

            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    def toggle_order_approval(self, tree, row_id):
        if not self.can("approve_lpo"):
            self.message_error("Not allowed",
                               "Only admins can approve LPOs.")
            return
        if not _alive(tree):
            return

        info = getattr(self, "_po_order_ids", {}).get(row_id)
        if not info:
            return
        order_id, current_approved, order_data = info
        new_approved = not current_approved

        def worker():
            try:
                u, p = self.admin_credentials if self.admin_credentials else ("", "")
                if not u or not p:
                    self.after(0, lambda: self.message_error(
                        "Admin required",
                        "Approve requires an admin login.\n\n"
                        "Open the New Item screen once and log in as admin."))
                    return
                headers = {"X-User": u, "X-Pass": p}
                r = requests.patch(
                    f"{self.SERVER}/purchase_orders/{order_id}/approve",
                    json={"approved": new_approved}, headers=headers, timeout=5)
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return

            def apply():
                if not _alive(tree):
                    return
                try:
                    if r.status_code == 200:
                        checkbox = "\u2611 Approved" if new_approved else "\u2610 Pending"
                        tree.set(row_id, "status", checkbox)
                        self._po_order_ids[row_id] = (order_id, new_approved, order_data)
                    elif r.status_code == 401:
                        self.message_error("Error",
                                           "Authorization failed. Log in as admin.")
                        self.admin_credentials = None
                    else:
                        self.message_error("Error", r.text)
                except Exception as e:
                    print("toggle_order_approval apply error:", e)
                    traceback.print_exc()

            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    # --------------------------------------------- Order detail / view / print

    def _short_code_for_barcode(self, barcode):
        if not barcode:
            return ""
        match = self.find_product_by_code(barcode)
        if match:
            return self.get_short_code(match)
        return barcode

    def view_selected_purchase_order(self, tree):
        if not _alive(tree):
            return
        selected = tree.selection()
        if not selected:
            self.message_info("Select an order", "Select an order in the list first")
            return
        row_id = selected[0]
        info = getattr(self, "_po_order_ids", {}).get(row_id)
        if not info:
            return
        order_id, approved, order_data = info
        self.open_order_detail_window(order_id, order_data)

    def open_order_detail_window(self, order_id, order_data):
        lines = order_data.get("lines")
        if lines:
            self._show_order_detail(order_data, lines)
            return

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/purchase_orders/{order_id}", timeout=5)
                detail = r.json() if r.status_code == 200 else None
            except Exception as e:
                detail = None
                print("Could not fetch order detail:", e)
            self.after(0, lambda: self._apply_order_detail(order_data, detail))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_order_detail(self, order_data, detail):
        lines = (detail or {}).get("lines")
        if not lines:
            self.message_info(
                "No line items",
                "This order has no line items in the server response.")
            return
        merged = dict(order_data)
        merged.update(detail)
        self._show_order_detail(merged, lines)

    def _show_order_detail(self, order_data, lines):
        win = tk.Toplevel(self)
        win.title(f"Order Detail - LPO {order_data.get('lpo_no', order_data.get('id', ''))}")
        win.geometry("950x520")
        try:
            from common.titlebar import apply_green_titlebar
            win.after(150, lambda w=win: apply_green_titlebar(w))
        except Exception:
            pass

        top_row = ttk.Frame(win)
        top_row.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Button(top_row, text="Change Printer",
                   command=self.change_order_printer).pack(side="left")

        self.order_printer_name_var = tk.StringVar(
            value=f"Printer: {self.order_printer_name or '(default)'}"
        )
        ttk.Label(top_row, textvariable=self.order_printer_name_var,
                  foreground="#333333").pack(side="left", padx=(10, 0))

        header = ttk.Frame(win)
        header.pack(fill="x", padx=10, pady=(10, 10))
        ttk.Label(header, text=f"Supplier: {order_data.get('supplier', '-')}",
                  font=("Arial", 10, "bold")).pack(anchor="w")
        ttk.Label(header, text=f"LPO No.: {order_data.get('lpo_no', '-')}").pack(anchor="w")
        ttk.Label(header, text=f"Order Date: {order_data.get('date', '-')}").pack(anchor="w")
        ttk.Label(header, text=f"Expiry Date: {order_data.get('expiry_date', '-')}").pack(anchor="w")

        tree = ttk.Treeview(
            win,
            columns=("code", "desc", "qty", "total_qty", "packaging", "cost", "total"),
            show="headings")
        tree.heading("code", text="Short Code")
        tree.heading("desc", text="Description")
        tree.heading("qty", text="Qty")
        tree.heading("total_qty", text="Total Pcs")
        tree.heading("packaging", text="Packaging")
        tree.heading("cost", text="Cost/pcs")
        tree.heading("total", text="Total")
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        def fmt_money(v):
            try:
                return f"{float(v):.2f}"
            except (TypeError, ValueError):
                return str(v)

        running_total = 0.0
        for line in lines:
            unit_cost = line.get("unit_cost", 0)
            total_qty = line.get("total_qty")
            if total_qty is None:
                total_qty = line.get("qty", 0)
            subtotal = line.get("subtotal")
            if subtotal is None:
                try:
                    subtotal = float(total_qty or 0) * float(unit_cost or 0)
                except (TypeError, ValueError):
                    subtotal = 0
            try:
                running_total += float(subtotal)
            except (TypeError, ValueError):
                pass

            barcode = line.get("barcode") or ""
            display_code = (line.get("code")
                            or self._short_code_for_barcode(barcode)
                            or barcode
                            or "-")

            tree.insert(
                "", "end",
                values=(
                    display_code,
                    line.get("name", line.get("description", "-")),
                    f"{float(line.get('qty', 0)):g}",
                    f"{float(total_qty or 0):g}",
                    line.get("packaging", "-"),
                    fmt_money(unit_cost),
                    fmt_money(subtotal),
                ))

        self.make_columns_responsive(win, tree, [1, 3, 1, 1, 1, 1, 1])

        footer = ttk.Frame(win)
        footer.pack(fill="x", padx=10, pady=(0, 5))
        ttk.Label(footer, text=f"Total LPO Value:  {running_total:.2f}",
                  font=("Arial", 12, "bold"),
                  foreground="#006600").pack(side="left")

        bottom = ttk.Frame(win)
        bottom.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bottom, text="Print",
                   command=lambda: self.print_purchase_order(order_data, lines)
                   ).pack(side="right")

    def change_order_printer(self):
        if not sys.platform.startswith("win"):
            self.message_info(
                "Change printer",
                "Printer selection uses the OS print dialog when you click "
                "Print on this platform.")
            return
        try:
            from ctypes import wintypes

            class PRINTDLGW(ctypes.Structure):
                _fields_ = [
                    ("lStructSize", wintypes.DWORD),
                    ("hwndOwner", wintypes.HWND),
                    ("hDevMode", wintypes.HANDLE),
                    ("hDevNames", wintypes.HANDLE),
                    ("hDC", wintypes.HDC),
                    ("Flags", wintypes.DWORD),
                    ("nFromPage", wintypes.WORD),
                    ("nToPage", wintypes.WORD),
                    ("nMinPage", wintypes.WORD),
                    ("nMaxPage", wintypes.WORD),
                    ("nCopies", wintypes.WORD),
                    ("hInstance", wintypes.HANDLE),
                    ("lCustData", ctypes.c_void_p),
                    ("lpfnPrintHook", ctypes.c_void_p),
                    ("lpfnSetupHook", ctypes.c_void_p),
                    ("lpPrintTemplateName", wintypes.LPCWSTR),
                    ("lpSetupTemplateName", wintypes.LPCWSTR),
                    ("hPrintTemplate", wintypes.HANDLE),
                    ("hSetupTemplate", wintypes.HANDLE),
                ]

            PD_RETURNDC = 0x00000100
            PD_USEDEVMODECOPIESANDCOLLATE = 0x00040000
            PD_NOSELECTION = 0x00000004
            PD_NOPAGENUMS = 0x00000008

            self.update_idletasks()
            hwnd_int = int(self.winfo_id())
            real_hwnd = ctypes.windll.user32.GetParent(hwnd_int) or hwnd_int

            pd = PRINTDLGW()
            pd.lStructSize = ctypes.sizeof(PRINTDLGW)
            pd.hwndOwner = real_hwnd
            pd.Flags = (PD_RETURNDC
                        | PD_USEDEVMODECOPIESANDCOLLATE
                        | PD_NOSELECTION
                        | PD_NOPAGENUMS)
            pd.nMinPage = 1
            pd.nMaxPage = 1

            comdlg32 = ctypes.windll.comdlg32
            comdlg32.PrintDlgW.argtypes = [ctypes.POINTER(PRINTDLGW)]
            comdlg32.PrintDlgW.restype = wintypes.BOOL

            ok = comdlg32.PrintDlgW(ctypes.byref(pd))
            if not ok:
                return

            if pd.hDevNames:
                kernel32 = ctypes.windll.kernel32
                kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
                kernel32.GlobalLock.restype = ctypes.c_void_p
                kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
                kernel32.GlobalUnlock.restype = wintypes.BOOL

                ptr = kernel32.GlobalLock(pd.hDevNames)
                try:
                    if ptr:
                        offsets = ctypes.cast(
                            ctypes.c_void_p(ptr),
                            ctypes.POINTER(ctypes.c_ushort))
                        device_offset = offsets[1]
                        device_addr = ptr + device_offset
                        device_name = ctypes.cast(
                            ctypes.c_void_p(device_addr),
                            ctypes.c_wchar_p).value
                        if device_name:
                            self.order_printer_name = device_name
                finally:
                    kernel32.GlobalUnlock(pd.hDevNames)

            if pd.hDC:
                ctypes.windll.gdi32.DeleteDC(pd.hDC)

            self.message_info(
                "Printer selected",
                f"Selected printer:\n{self.order_printer_name or '(unknown)'}")

            if hasattr(self, "order_printer_name_var"):
                try:
                    self.order_printer_name_var.set(
                        f"Printer: {self.order_printer_name or '(default)'}")
                except Exception:
                    pass

        except Exception as e:
            self.message_warn(
                "Couldn't open printer dialog",
                f"{e}\n\nYou can still print using the Print button.")

    # ------------------------------------------------------- PDF printing

    def print_purchase_order(self, order_data, lines):
        if not _REPORTLAB_OK:
            self.message_error(
                "Print unavailable",
                "reportlab is not installed.\n\n"
                "Install it with:\n    pip install reportlab")
            return

        try:
            tmp = tempfile.NamedTemporaryFile(
                prefix="LPO_", suffix=".pdf", delete=False)
            pdf_path = tmp.name
            tmp.close()
        except Exception as e:
            self.message_error("Print error",
                               f"Could not create temp file:\n{e}")
            return

        try:
            self._build_order_pdf(pdf_path, order_data, lines)
        except Exception as e:
            self.message_error("Print error",
                               f"Could not build PDF:\n{e}")
            return

        self._send_pdf_to_printer(pdf_path)

    def _build_order_pdf(self, path, order_data, lines):
        c = canvas.Canvas(path, pagesize=A4)
        width, height = A4
        left = 15 * mm
        right = width - 15 * mm
        y = height - 20 * mm

        c.setFont("Helvetica-Bold", 14)
        c.drawString(left, y, getattr(self, "SHOP_NAME", "Purchase Order"))
        c.setFont("Helvetica", 10)
        y -= 6 * mm
        c.drawString(left, y, "Purchase Order (LPO)")
        y -= 6 * mm

        c.setFont("Helvetica-Bold", 11)
        c.drawString(left, y, f"LPO No.: {order_data.get('lpo_no', '-')}")
        y -= 5 * mm
        c.setFont("Helvetica", 10)
        c.drawString(left, y, f"Supplier: {order_data.get('supplier', '-')}")
        y -= 5 * mm
        c.drawString(left, y, f"Order Date: {order_data.get('date', '-')}")
        y -= 5 * mm
        c.drawString(left, y, f"Expiry Date: {order_data.get('expiry_date', '-')}")
        y -= 8 * mm

        col_code  = left
        col_desc  = left + 30 * mm
        col_qty   = right - 70 * mm
        col_total = right - 55 * mm
        col_cost  = right - 35 * mm
        col_line  = right - 20 * mm

        c.setFont("Helvetica-Bold", 9)
        c.drawString(col_code,  y, "Code")
        c.drawString(col_desc,  y, "Description")
        c.drawRightString(col_qty,   y, "Qty")
        c.drawRightString(col_total, y, "Total Pcs")
        c.drawRightString(col_cost,  y, "Cost/pcs")
        c.drawRightString(col_line,  y, "Line Total")
        y -= 2 * mm
        c.line(left, y, right, y)
        y -= 4 * mm

        c.setFont("Helvetica", 9)
        running = 0.0
        for line in lines:
            if y < 25 * mm:
                c.showPage()
                y = height - 20 * mm
                c.setFont("Helvetica", 9)

            unit_cost = line.get("unit_cost") or 0
            total_qty = line.get("total_qty")
            if total_qty is None:
                total_qty = line.get("qty", 0)
            subtotal = line.get("subtotal")
            if subtotal is None:
                try:
                    subtotal = float(total_qty or 0) * float(unit_cost or 0)
                except (TypeError, ValueError):
                    subtotal = 0
            try:
                running += float(subtotal)
            except (TypeError, ValueError):
                pass

            barcode = line.get("barcode") or ""
            display_code = (line.get("code")
                            or self._short_code_for_barcode(barcode)
                            or barcode
                            or "-")

            c.drawString(col_code, y, str(display_code))
            desc = str(line.get("name", "-"))
            if len(desc) > 34:
                desc = desc[:33] + "\u2026"
            c.drawString(col_desc, y, desc)
            c.drawRightString(col_qty,   y, f"{float(line.get('qty', 0)):g}")
            c.drawRightString(col_total, y, f"{float(total_qty or 0):g}")
            c.drawRightString(col_cost,  y, f"{float(unit_cost or 0):.2f}")
            c.drawRightString(col_line,  y, f"{float(subtotal):.2f}")
            y -= 5 * mm

        y -= 2 * mm
        c.line(left, y, right, y)
        y -= 6 * mm
        c.setFont("Helvetica-Bold", 11)
        c.drawString(left, y, "Total LPO Value:")
        c.drawRightString(col_line, y, f"{running:.2f}")

        c.showPage()
        c.save()

    def _send_pdf_to_printer(self, pdf_path):
        try:
            if sys.platform.startswith("win"):
                self.open_with_default_app(pdf_path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", pdf_path])
            else:
                subprocess.Popen(["xdg-open", pdf_path])
        except Exception as e:
            self.message_error("Print error",
                               f"Could not open the PDF:\n{e}\n\n"
                               f"It was saved to:\n{pdf_path}")