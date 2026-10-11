"""
Summaries and pickers mixin for BackOffice.

Contains the Departmental Summary report, plus the Departments and
Suppliers pickers that open from the Stock List hub. Also includes
the "Add Department" and "Add Supplier" dialogs they use.
"""

import threading
import tkinter as tk
from tkinter import ttk

import requests

from common.center import center_window_on_screen
from common.titlebar import apply_green_titlebar


class SummariesMixin:
    """Departmental Summary, Departments picker, Suppliers picker."""

    # ---------------------------------------------------------------- Summary

    def open_departmental_summary_report(self):
        def worker():
            try:
                r = requests.get(f"{self.SERVER}/products", timeout=5)
                data = r.json()
            except Exception as e:
                self.after(0, lambda: self.message_error("Error", f"Could not reach server: {e}"))
                return

            def apply():
                self.products_cache = data
                self._show_product_report(data, f"Departmental Summary — All items ({len(data)})")
            self.after(0, apply)
        threading.Thread(target=worker, daemon=True).start()

    def _show_product_report(self, products, title):
        columns = [
            ("code", "Short Code"),
            ("name", "Description"),
            ("unit", "Unit of Measure"),
            ("stock", "Current Stock"),
        ]
        rows = []
        for p in products:
            rows.append((
                self.get_short_code(p),
                p.get("name", ""),
                p.get("packaging", "") or "-",
                p.get("stock", 0),
            ))
        self._open_report_window(
            title=title,
            rows=rows,
            columns=columns,
            weights=[1, 4, 2, 1],
            scope_label=title,
        )

    # ------------------------------------------------------------ Departments

    def open_departments_picker(self):
        win = tk.Toplevel(self)
        win.title("Departments")
        win.transient(self)
        center_window_on_screen(win, 460, 400)
        win.minsize(400, 320)
        win.after(150, lambda w=win: apply_green_titlebar(w))

        top = ttk.Frame(win)
        top.pack(fill="x", padx=12, pady=(12, 0))
        ttk.Label(top, text="Select a department, then click OK.").pack(side="left")

        list_frame = ttk.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=12, pady=10)
        tree = ttk.Treeview(list_frame, columns=("name",), show="headings")
        tree.heading("name", text="Department")
        tree.pack(fill="both", expand=True, side="left")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")

        def load_departments():
            for row in tree.get_children():
                tree.delete(row)

            def worker():
                try:
                    r = requests.get(f"{self.SERVER}/departments", timeout=3)
                    depts = r.json()
                except Exception as e:
                    depts = []
                    print("Could not fetch departments:", e)
                names = {d["name"] if isinstance(d, dict) else str(d) for d in depts}
                for p in self.products_cache:
                    c = str(p.get("category", "")).strip()
                    if c:
                        names.add(c)

                def apply():
                    if not tree.winfo_exists():
                        return
                    for n in sorted(names):
                        tree.insert("", "end", values=(n,))
                self.after(0, apply)
            threading.Thread(target=worker, daemon=True).start()

        load_departments()

        button_row = ttk.Frame(win)
        button_row.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(button_row, text="Add Department",
                   command=lambda: self.open_add_department_dialog(
                       parent=win, on_added=load_departments)).pack(side="left")
        ttk.Button(button_row, text="Cancel", command=win.destroy).pack(side="right")

        def do_ok():
            sel = tree.selection()
            if not sel:
                self.message_error("Error", "Select a department first", parent=win)
                return
            name = tree.item(sel[0], "values")[0]
            win.destroy()
            self.open_department_report(name)

        ttk.Button(button_row, text="OK", command=do_ok).pack(side="right", padx=(0, 8))
        tree.bind("<Double-1>", lambda e: do_ok())

    def open_department_report(self, department):
        items = [p for p in self.products_cache
                 if str(p.get("category", "")).strip() == department]
        title = f"Department: {department} — {len(items)} item(s)"
        self._show_product_report(items, title)

    # -------------------------------------------------------------- Suppliers

    def open_suppliers_picker(self):
        win = tk.Toplevel(self)
        win.title("Suppliers")
        win.transient(self)
        center_window_on_screen(win, 460, 400)
        win.minsize(400, 320)
        win.after(150, lambda w=win: apply_green_titlebar(w))

        top = ttk.Frame(win)
        top.pack(fill="x", padx=12, pady=(12, 0))
        ttk.Label(top, text="Select a supplier, then click OK.").pack(side="left")

        list_frame = ttk.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=12, pady=10)
        tree = ttk.Treeview(list_frame, columns=("name",), show="headings")
        tree.heading("name", text="Supplier")
        tree.pack(fill="both", expand=True, side="left")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")

        def load_suppliers():
            for row in tree.get_children():
                tree.delete(row)

            def worker():
                try:
                    r = requests.get(f"{self.SERVER}/suppliers", timeout=3)
                    sups = r.json()
                except Exception as e:
                    sups = []
                    print("Could not fetch suppliers:", e)
                names = {s["name"] if isinstance(s, dict) else str(s) for s in sups}
                for p in self.products_cache:
                    s = str(p.get("supplier", "")).strip()
                    if s:
                        names.add(s)

                def apply():
                    if not tree.winfo_exists():
                        return
                    for n in sorted(names):
                        tree.insert("", "end", values=(n,))
                self.after(0, apply)
            threading.Thread(target=worker, daemon=True).start()

        load_suppliers()

        button_row = ttk.Frame(win)
        button_row.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(button_row, text="Add Supplier",
                   command=lambda: self.open_add_supplier_dialog(
                       on_added=load_suppliers)).pack(side="left")
        ttk.Button(button_row, text="Cancel", command=win.destroy).pack(side="right")

        def do_ok():
            sel = tree.selection()
            if not sel:
                self.message_error("Error", "Select a supplier first", parent=win)
                return
            name = tree.item(sel[0], "values")[0]
            win.destroy()
            self.open_supplier_report(name)

        ttk.Button(button_row, text="OK", command=do_ok).pack(side="right", padx=(0, 8))
        tree.bind("<Double-1>", lambda e: do_ok())

    def open_supplier_report(self, supplier):
        items = [p for p in self.products_cache
                 if str(p.get("supplier", "")).strip() == supplier]
        title = f"Supplier: {supplier} — {len(items)} item(s)"
        self._show_product_report(items, title)

    # -------------------------------------------- Add Department dialog

    def open_add_department_dialog(self, parent=None, target_var=None, on_added=None):
        dialog = tk.Toplevel(parent or self)
        dialog.title("New Department")
        dialog.resizable(False, False)
        dialog.transient(parent or self)
        dialog.grab_set()
        center_window_on_screen(dialog, 340, 180)
        dialog.after(150, lambda w=dialog: apply_green_titlebar(w))

        ttk.Label(dialog, text="Department Name:").pack(anchor="w", padx=12, pady=(15, 2))
        name_var = tk.StringVar()
        name_entry = ttk.Entry(dialog, textvariable=name_var, width=32)
        name_entry.pack(padx=12)
        name_entry.focus_set()

        status_var = tk.StringVar(value="")
        ttk.Label(dialog, textvariable=status_var,
                  foreground="#a00000").pack(anchor="w", padx=12, pady=(6, 0))

        button_row = ttk.Frame(dialog)
        button_row.pack(fill="x", padx=12, pady=15)

        def do_save():
            name = name_var.get().strip()
            if not name:
                status_var.set("Enter a department name")
                return

            def worker():
                try:
                    r = requests.post(f"{self.SERVER}/departments",
                                      json={"name": name}, timeout=5)
                except Exception as e:
                    self.after(0, lambda: status_var.set(f"Server not reachable: {e}"))
                    return

                def apply():
                    if r.status_code in (200, 201) or r.status_code == 409:
                        self.known_departments.add(name)
                        if target_var is not None:
                            target_var.set(name)
                        if on_added:
                            on_added()
                        dialog.destroy()
                    else:
                        status_var.set(r.text or "Could not save department")
                self.after(0, apply)
            threading.Thread(target=worker, daemon=True).start()

        ttk.Button(button_row, text="Cancel", command=dialog.destroy).pack(side="right")
        ttk.Button(button_row, text="Save", command=do_save).pack(side="right", padx=(0, 8))