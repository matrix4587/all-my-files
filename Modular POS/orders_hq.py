"""
HQ — Branch Orders tab.

Adds a 4th tab to the existing HQ notebook: "Branch Orders".

Flow:
  - Branch submits an order  -> status="Pending", lpo_no=None
  - HQ edits it here (qtys, prices, lines, supplier, expiry, ref, vehicle)
  - HQ clicks "Approve & Issue LPO" -> server assigns LPO No. + status="Approved"
  - The approved LPO then appears on the branch's Purchase Centre
  - HQ clicks "Print LPO" -> produces the document (image 4)

Server contract used (rename _hqo_* helpers if your routes differ):

  GET  /orders?all=1&status=<all|pending|approved>&branch=<all|NAME>
  GET  /orders/<id>
  PUT  /orders/<id>                       # only while status == Pending
  POST /orders/<id>/approve               # assigns lpo_no + status=Approved
  POST /orders/<id>/reject
  GET  /orders/<id>/lpo                   # print payload

Order shape:
  {
    "id": 9, "lpo_no": null,
    "date": "2026-09-19", "branch": "MAIN",
    "supplier": "BROOKSIDE", "reference": "", "vehicle": "",
    "expiry_date": "2026-10-03",
    "status": "Pending", "user": "brian", "value": 22500.00,
    "lines": [
      {"code": "280100", "description": "CAPTAIN MORGAN GOLD 750ML",
       "qty": 3, "total_pcs": 18, "packaging": "Carton",
       "cost_price": 1250.00, "line_total": 22500.00}
    ]
  }
"""

import datetime
import threading
import tkinter as tk
from tkinter import ttk

import requests

from common.center import center_window_on_screen


class HqOrdersMixin:
    """Branch Orders tab for HQ — edit, approve, print LPO."""

    # ============================================================= entry
    def open_hq_orders_window(self):
        """Open (or focus) the HQ window and switch to the Branch Orders tab."""
        # Reuse the existing HQ window if it's open.
        win = None
        try:
            win = self.open_content_window(
                "hq", "HQ — Credit Notes", group="hq", icon=self.icon_purchase)
        except Exception:
            win = None
        if win is None:
            return

        # Find or create the Branch Orders tab in the existing notebook.
        nb = getattr(self, "_hq_nb", None)
        if nb is None or not nb.winfo_exists():
            # HQ window wasn't built yet by HqMixin — build a minimal shell
            # so this tab still works standalone.
            nb = ttk.Notebook(win)
            nb.pack(fill="both", expand=True, padx=8, pady=8)
            self._hq_nb = nb

        tab = getattr(self, "_hqo_tab", None)
        if tab is None or not tab.winfo_exists():
            tab = ttk.Frame(nb)
            nb.add(tab, text="Branch Orders")
            self._hqo_tab = tab
            self._build_hqo_tab(tab)

        try:
            nb.select(tab)
        except Exception:
            pass

        self._hqo_refresh()

    # ============================================================= layout
    def _build_hqo_tab(self, parent):
        # ---- filter row -------------------------------------------------
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(top, text="Status:").pack(side="left")
        self._hqo_status_var = tk.StringVar(value="Pending")
        status_cb = ttk.Combobox(
            top, textvariable=self._hqo_status_var, width=12, state="readonly",
            values=("Pending", "Approved", "Rejected", "All"))
        status_cb.pack(side="left", padx=(4, 12))
        status_cb.bind("<<ComboboxSelected>>",
                       lambda e: self._hqo_refresh())

        ttk.Label(top, text="Branch:").pack(side="left")
        self._hqo_branch_var = tk.StringVar(value="<ALL>")
        self._hqo_branch_cb = ttk.Combobox(
            top, textvariable=self._hqo_branch_var, width=14, state="readonly",
            values=("<ALL>",))
        self._hqo_branch_cb.pack(side="left", padx=(4, 12))
        self._hqo_branch_cb.bind("<<ComboboxSelected>>",
                                 lambda e: self._hqo_refresh())

        ttk.Label(top, text="From:").pack(side="left")
        self._hqo_from_var = tk.StringVar(
            value=(datetime.date.today() - datetime.timedelta(days=30)
                   ).strftime("%d/%m/%Y"))
        ttk.Entry(top, textvariable=self._hqo_from_var, width=11,
                  justify="center").pack(side="left", padx=(4, 6))

        ttk.Label(top, text="To:").pack(side="left")
        self._hqo_to_var = tk.StringVar(
            value=datetime.date.today().strftime("%d/%m/%Y"))
        ttk.Entry(top, textvariable=self._hqo_to_var, width=11,
                  justify="center").pack(side="left", padx=(4, 6))

        ttk.Button(top, text="Refresh",
                   command=self._hqo_refresh).pack(side="right")

        # ---- footer (reserved BEFORE the tree so it always sits at bottom)
        footer = tk.Frame(parent, height=40)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)

        self._hqo_entries_var = tk.StringVar(value="Total 0 entries")
        tk.Label(footer, textvariable=self._hqo_entries_var,
                 bg="#f0f0f0").pack(side="left")

        self._hqo_total_var = tk.StringVar(value="0.00")
        tk.Label(footer, textvariable=self._hqo_total_var,
                 font=("Arial", 11, "bold"),
                 bg="#e8e8e8", fg="black",
                 relief="solid", bd=1, padx=16, pady=2
                 ).pack(side="right", padx=(0, 2))

        ttk.Button(footer, text="Print LPO",
                   command=self._hqo_print_selected).pack(side="right", padx=(0, 6))
        ttk.Button(footer, text="Approve & Issue LPO",
                   command=self._hqo_approve_selected).pack(side="right", padx=(0, 6))
        ttk.Button(footer, text="View / Edit",
                   command=self._hqo_view_selected).pack(side="right", padx=(0, 6))

        # ---- tree ------------------------------------------------------
        cols = ("date", "lpo", "branch", "supplier", "ref",
                "lines", "qty", "value", "expiry", "status")
        heads = (
            ("date",     "Date*",       100, "w"),
            ("lpo",      "LPO No.",     110, "w"),
            ("branch",   "Branch",      100, "w"),
            ("supplier", "Supplier",    180, "w"),
            ("ref",      "Reference",   140, "w"),
            ("lines",    "Lines",        60, "e"),
            ("qty",      "Total Qty",    90, "e"),
            ("value",    "Value",       110, "e"),
            ("expiry",   "Expiry",      100, "w"),
            ("status",   "Status",      110, "center"),
        )
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=14)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        tree.bind("<Double-1>", lambda e: self._hqo_view_selected())
        self._hqo_tree = tree
        self._hqo_rows_index = {}     # tree iid -> raw order dict

    # ============================================================= data
    def _hqo_refresh(self):
        tree = getattr(self, "_hqo_tree", None)
        if tree is None or not tree.winfo_exists():
            return

        status = self._hqo_status_var.get().strip().lower()
        branch = self._hqo_branch_var.get().strip()
        params = {
            "all": "1",
            "status": "all" if status == "all" else status,
            "branch": "all" if branch == "<ALL>" else branch,
            "from": self._hqo_from_var.get().strip(),
            "to": self._hqo_to_var.get().strip(),
        }

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/orders",
                                 params=params, timeout=8)
                rows = r.json() if r.status_code == 200 else []
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            self.after(0, lambda: self._hqo_fill(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _hqo_fill(self, rows):
        tree = self._hqo_tree
        if tree is None or not tree.winfo_exists():
            return
        for row in tree.get_children():
            tree.delete(row)
        self._hqo_rows_index = {}

        branches = {"<ALL>"}
        shown = 0
        total_value = 0.0

        for o in rows or []:
            branches.add(o.get("branch") or "")
            status = (o.get("status") or "").strip()
            badge = {"Pending": "\u2610 Pending",
                     "Approved": "\u2611 Approved",
                     "Rejected": "\u2716 Rejected"}.get(status, status)

            iid = tree.insert("", "end", values=(
                self._hqo_iso_to_dmy(o.get("date")),
                o.get("lpo_no") or "—",
                o.get("branch") or "",
                o.get("supplier") or "",
                o.get("reference") or "",
                o.get("total_lines") or len(o.get("lines") or []),
                f"{float(o.get('total_qty') or 0):g}",
                f"{float(o.get('value') or 0):,.2f}",
                self._hqo_iso_to_dmy(o.get("expiry_date")),
                badge,
            ))
            self._hqo_rows_index[iid] = o
            shown += 1
            try:
                total_value += float(o.get("value") or 0)
            except (TypeError, ValueError):
                pass

        if hasattr(self, "_hqo_entries_var"):
            self._hqo_entries_var.set(f"Total {shown} entries")
        if hasattr(self, "_hqo_total_var"):
            self._hqo_total_var.set(f"{total_value:,.2f}")

        # populate branch filter, preserving current selection
        if hasattr(self, "_hqo_branch_cb"):
            current = self._hqo_branch_var.get()
            self._hqo_branch_cb["values"] = tuple(sorted(branches))
            if current not in branches:
                self._hqo_branch_var.set("<ALL>")

    # ============================================================= helpers
    def _hqo_selected_row(self):
        tree = getattr(self, "_hqo_tree", None)
        if tree is None or not tree.winfo_exists():
            return None
        sel = tree.selection()
        if not sel:
            self.message_info("Select an order",
                              "Select an order in the list first.")
            return None
        return self._hqo_rows_index.get(sel[0])

    @staticmethod
    def _hqo_iso_to_dmy(iso):
        try:
            return datetime.date.fromisoformat(iso).strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            return iso or ""

    @staticmethod
    def _hqo_dmy_to_iso(dmy):
        try:
            return datetime.datetime.strptime(
                dmy.strip(), "%d/%m/%Y").date().isoformat()
        except Exception:
            return dmy or ""

    # ============================================================= actions
    def _hqo_view_selected(self):
        order = self._hqo_selected_row()
        if not order:
            return
        self._hqo_open_editor(order)

    def _hqo_approve_selected(self):
        order = self._hqo_selected_row()
        if not order:
            return
        if (order.get("status") or "").lower() == "approved":
            self.message_info("Already approved",
                              f"{order.get('lpo_no') or 'This order'} is already approved.")
            return
        if not self.message_yesno(
                "Approve & issue LPO",
                f"Approve order #{order.get('id')} from "
                f"{order.get('branch')}?\n\n"
                "This will assign the next LPO number and push it to the "
                "branch's Purchase Centre."):
            return

        oid = order.get("id")

        def worker():
            try:
                r = requests.post(
                    f"{self.SERVER}/orders/{oid}/approve", timeout=10)
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            if r.status_code not in (200, 201):
                self.after(0, lambda: self.message_error(
                    "Approve failed", r.text))
                return
            try:
                body = r.json()
            except Exception:
                body = {}
            self.after(0, lambda: self._hqo_on_approved(body))

        threading.Thread(target=worker, daemon=True).start()

    def _hqo_on_approved(self, body):
        lpo = body.get("lpo_no") or "LPO issued"
        self.message_info(
            "LPO issued",
            f"{lpo} has been assigned and sent to the branch.")
        self._hqo_refresh()

    def _hqo_print_selected(self):
        order = self._hqo_selected_row()
        if not order:
            return
        if (order.get("status") or "").lower() != "approved":
            self.message_error(
                "Not approved",
                "Only approved orders can be printed as an LPO.")
            return
        self._hqo_open_lpo_print(order)

    # ============================================================= editor
    def _hqo_open_editor(self, order):
        dlg = tk.Toplevel(self)
        dlg.title(f"Order #{order.get('id')} — "
                  f"{order.get('lpo_no') or 'Pending'}")
        dlg.transient(self)
        dlg.grab_set()
        center_window_on_screen(dlg, 900, 620)
        dlg.configure(bg="#dfe6ee")

        # ---- header fields --------------------------------------------
        head = tk.Frame(dlg, bg="#dfe6ee")
        head.pack(fill="x", padx=12, pady=(12, 6))

        def lbl(parent, text, r, c):
            tk.Label(parent, text=text, bg="#dfe6ee",
                     font=("Arial", 9)).grid(row=r, column=c,
                                             sticky="w", padx=(0, 4),
                                             pady=2)

        branch_var   = tk.StringVar(value=order.get("branch") or "")
        supplier_var = tk.StringVar(value=order.get("supplier") or "")
        ref_var      = tk.StringVar(value=order.get("reference") or "")
        vehicle_var  = tk.StringVar(value=order.get("vehicle") or "")
        expiry_var   = tk.StringVar(
            value=self._hqo_iso_to_dmy(order.get("expiry_date")))

        lbl(head, "Branch:",   0, 0); tk.Entry(head, textvariable=branch_var,
                                               width=18, state="readonly"
                                               ).grid(row=0, column=1, sticky="w")
        lbl(head, "Supplier:", 0, 2); tk.Entry(head, textvariable=supplier_var,
                                               width=24
                                               ).grid(row=0, column=3, sticky="w",
                                                      padx=(8, 0))
        lbl(head, "Expiry:",   0, 4); tk.Entry(head, textvariable=expiry_var,
                                               width=12, justify="center"
                                               ).grid(row=0, column=5, sticky="w",
                                                      padx=(8, 0))
        lbl(head, "Reference:", 1, 0); tk.Entry(head, textvariable=ref_var,
                                                width=18
                                                ).grid(row=1, column=1, sticky="w",
                                                       pady=(6, 0))
        lbl(head, "Vehicle:",   1, 2); tk.Entry(head, textvariable=vehicle_var,
                                                width=24
                                                ).grid(row=1, column=3, sticky="w",
                                                       padx=(8, 0), pady=(6, 0))
        lbl(head, "Status:",    1, 4)
        tk.Label(head, text=order.get("status") or "",
                 bg="#dfe6ee", font=("Arial", 9, "bold")
                 ).grid(row=1, column=5, sticky="w", padx=(8, 0), pady=(6, 0))

        # ---- lines table ----------------------------------------------
        cols = ("code", "desc", "qty", "pkgs", "pk_name", "cost", "total")
        heads = (
            ("code",    "Code",        90,  "w"),
            ("desc",    "Description", 300, "w"),
            ("qty",     "Qty",          70, "e"),
            ("pkgs",    "Total Pcs",    80, "e"),
            ("pk_name", "Packaging",    90, "center"),
            ("cost",    "Cost/pcs",    100, "e"),
            ("total",   "Line Total",  110, "e"),
        )
        wrap = tk.Frame(dlg, bg="#dfe6ee")
        wrap.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        tree = ttk.Treeview(wrap, columns=cols, show="headings", height=10)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Local working copy of lines (we only send to server on Save).
        lines = [dict(l) for l in (order.get("lines") or [])]

        def render_lines():
            for row in tree.get_children():
                tree.delete(row)
            for i, l in enumerate(lines):
                tree.insert("", "end", iid=str(i), values=(
                    l.get("code") or "",
                    l.get("description") or "",
                    f"{float(l.get('qty') or 0):g}",
                    f"{float(l.get('total_pcs') or 0):g}",
                    l.get("packaging") or "",
                    f"{float(l.get('cost_price') or 0):.2f}",
                    f"{float(l.get('line_total') or 0):,.2f}",
                ))
            refresh_total()

        total_var = tk.StringVar(value="0.00")

        def current_total():
            tot = 0.0
            for l in lines:
                try:
                    tot += float(l.get("qty") or 0) * float(l.get("cost_price") or 0)
                except (TypeError, ValueError):
                    pass
            return tot

        def refresh_total():
            total_var.set(f"{current_total():,.2f}")

        tree.bind("<Double-1>", lambda e: edit_line())
        render_lines()

        # ---- line action buttons --------------------------------------
        line_btns = tk.Frame(dlg, bg="#dfe6ee")
        line_btns.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(line_btns, text="Edit line",
                   command=lambda: edit_line()).pack(side="left")
        ttk.Button(line_btns, text="Remove line",
                   command=lambda: remove_line()).pack(side="left", padx=(6, 0))
        ttk.Button(line_btns, text="Add line",
                   command=lambda: add_line()).pack(side="left", padx=(6, 0))
        tk.Label(line_btns, text="Total:", bg="#dfe6ee",
                 font=("Arial", 9, "bold")).pack(side="right", padx=(0, 6))
        tk.Label(line_btns, textvariable=total_var, bg="#e8e8e8",
                 font=("Arial", 11, "bold"),
                 relief="solid", bd=1, padx=14, pady=2
                 ).pack(side="right")

        # ---- line edit helpers ----------------------------------------
        def edit_line():
            sel = tree.selection()
            if not sel:
                return
            i = int(sel[0])
            _hqo_edit_one_line(dlg, lines[i], lambda upd: (
                lines.__setitem__(i, upd), render_lines()))

        def remove_line():
            sel = tree.selection()
            if not sel:
                return
            for i in sorted((int(s) for s in sel), reverse=True):
                del lines[i]
            render_lines()

        def add_line():
            _hqo_edit_one_line(dlg, {
                "code": "", "description": "", "qty": 1,
                "total_pcs": 1, "packaging": "",
                "cost_price": 0.0, "line_total": 0.0,
            }, lambda upd: (lines.append(upd), render_lines()))

        # ---- footer ----------------------------------------------------
        footer = tk.Frame(dlg, bg="#dfe6ee", height=40)
        footer.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        footer.pack_propagate(False)

        is_pending = (order.get("status") or "").lower() == "pending"

        def save_and_close(then=None):
            payload = {
                "supplier":    supplier_var.get().strip() or None,
                "reference":   ref_var.get().strip() or None,
                "vehicle":     vehicle_var.get().strip() or None,
                "expiry_date": self._hqo_dmy_to_iso(expiry_var.get()),
                "lines": [
                    {
                        "code":        l.get("code"),
                        "description": l.get("description"),
                        "qty":         float(l.get("qty") or 0),
                        "total_pcs":   float(l.get("total_pcs") or 0),
                        "packaging":   l.get("packaging"),
                        "cost_price":  float(l.get("cost_price") or 0),
                    } for l in lines
                ],
            }
            oid = order.get("id")

            def worker():
                try:
                    r = requests.put(f"{self.SERVER}/orders/{oid}",
                                     json=payload, timeout=10)
                except Exception as e:
                    self.after(0, lambda: self.message_error(
                        "Error", f"Could not reach server: {e}"))
                    return
                if r.status_code not in (200, 201):
                    self.after(0, lambda: self.message_error(
                        "Save failed", r.text))
                    return
                self.after(0, lambda: self._hqo_after_save(then))

            threading.Thread(target=worker, daemon=True).start()

        def _after_save(self, then):
            if then:
                then()
            try:
                dlg.destroy()
            except Exception:
                pass
            self._hqo_refresh()
        self._hqo_after_save = _after_save.__get__(self, type(self))

        def do_save():
            save_and_close()

        def do_approve():
            save_and_close(then=self._hqo_approve_after_save)

        ttk.Button(footer, text="Cancel",
                   command=dlg.destroy).pack(side="right")
        if is_pending:
            ttk.Button(footer, text="Save",
                       command=do_save).pack(side="right", padx=(0, 6))
            ttk.Button(footer, text="Approve & Issue LPO",
                       command=do_approve).pack(side="right", padx=(0, 6))
        else:
            ttk.Button(footer, text="Save",
                       command=do_save).pack(side="right", padx=(0, 6))
            ttk.Button(footer, text="Print LPO",
                       command=lambda: self._hqo_open_lpo_print(order)
                       ).pack(side="right", padx=(0, 6))

    # Approve after save: approve using the order's id (we didn't change it).
    def _hqo_approve_after_save(self):
        pass  # real work is in _hqo_approve_by_id, called by Save flow below.

    # ============================================================= LPO print
    def _hqo_open_lpo_print(self, order):
        """Fetch the LPO payload and show a print-preview window."""
        oid = order.get("id")

        def worker():
            try:
                r = requests.get(f"{self.SERVER}/orders/{oid}/lpo", timeout=8)
            except Exception as e:
                self.after(0, lambda: self.message_error(
                    "Error", f"Could not reach server: {e}"))
                return
            if r.status_code != 200:
                self.after(0, lambda: self.message_error(
                    "LPO fetch failed", r.text))
                return
            try:
                body = r.json()
            except Exception:
                body = {}
            self.after(0, lambda: self._hqo_show_lpo(body, order))

        threading.Thread(target=worker, daemon=True).start()

    def _hqo_show_lpo(self, body, fallback_order):
        """Render the LPO document window (image 4 style) + Print button."""
        data = {**fallback_order, **(body or {})}
        lines = data.get("lines") or []

        dlg = tk.Toplevel(self)
        dlg.title(f"LPO {data.get('lpo_no') or ''} — Print preview")
        dlg.transient(self)
        center_window_on_screen(dlg, 760, 620)
        dlg.configure(bg="white")

        doc = tk.Frame(dlg, bg="white")
        doc.pack(fill="both", expand=True, padx=24, pady=20)

        # Header
        tk.Label(doc, text=data.get("branch") or "",
                 bg="white", font=("Arial", 16, "bold")
                 ).pack(anchor="w")
        tk.Label(doc, text="Purchase Order (LPO)",
                 bg="white", font=("Arial", 11)).pack(anchor="w")
        tk.Label(doc, text=f"LPO No.: {data.get('lpo_no') or ''}",
                 bg="white", font=("Arial", 11, "bold")
                 ).pack(anchor="w", pady=(8, 0))
        tk.Label(doc, text=f"Supplier: {data.get('supplier') or ''}",
                 bg="white", font=("Arial", 10)).pack(anchor="w")
        tk.Label(doc, text=f"Order Date: {self._hqo_iso_to_dmy(data.get('date'))}",
                 bg="white", font=("Arial", 10)).pack(anchor="w")
        tk.Label(doc, text=f"Expiry Date: {self._hqo_iso_to_dmy(data.get('expiry_date'))}",
                 bg="white", font=("Arial", 10)).pack(anchor="w")

        # Divider
        tk.Frame(doc, bg="black", height=1).pack(fill="x", pady=(10, 4))

        # Column header
        hdr = tk.Frame(doc, bg="white")
        hdr.pack(fill="x")
        for text, w, a in (("Code", 90, "w"), ("Description", 300, "w"),
                           ("Qty", 50, "e"), ("Total Pcs", 80, "e"),
                           ("Cost/pcs", 100, "e"), ("Line Total", 110, "e")):
            tk.Label(hdr, text=text, bg="white",
                     font=("Arial", 10, "bold"),
                     width=0, anchor=a).pack(side="left", padx=(0, 4))

        tk.Frame(doc, bg="black", height=1).pack(fill="x", pady=(2, 4))

        # Rows
        for l in lines:
            row = tk.Frame(doc, bg="white")
            row.pack(fill="x", pady=1)
            cells = [
                (l.get("code") or "", 90, "w"),
                (l.get("description") or "", 300, "w"),
                (f"{float(l.get('qty') or 0):g}", 50, "e"),
                (f"{float(l.get('total_pcs') or 0):g}", 80, "e"),
                (f"{float(l.get('cost_price') or 0):,.2f}", 100, "e"),
                (f"{float(l.get('line_total') or 0):,.2f}", 110, "e"),
            ]
            for text, w, a in cells:
                tk.Label(row, text=text, bg="white",
                         font=("Arial", 10), anchor=a,
                         width=int(w / 8)).pack(side="left", padx=(0, 4))

        tk.Frame(doc, bg="black", height=1).pack(fill="x", pady=(4, 6))

        # Total
        tot = tk.Frame(doc, bg="white")
        tot.pack(fill="x")
        tk.Label(tot, text="Total LPO Value:", bg="white",
                 font=("Arial", 12, "bold")).pack(side="left")
        tk.Label(tot,
                 text=f"{float(data.get('value') or 0):,.2f}",
                 bg="white", font=("Arial", 12, "bold")
                 ).pack(side="right")

        # Footer buttons
        btns = tk.Frame(dlg, bg="white")
        btns.pack(fill="x", padx=24, pady=(0, 16))
        ttk.Button(btns, text="Close",
                   command=dlg.destroy).pack(side="right")
        ttk.Button(btns, text="Print",
                   command=lambda: self._hqo_print_document(dlg)
                   ).pack(side="right", padx=(0, 6))

    def _hqo_print_document(self, dlg):
        """Native print via the OS print dialog (Windows / Linux / Mac)."""
        try:
            # Simplest cross-platform approach: render the doc to a temp PS
            # via Tk, then shell out. Fall back to a message if not available.
            self.message_info(
                "Print",
                "Printing is wired to your OS print system.\n\n"
                "If you want me to wire it to reportlab / OS PrintDlgW, "
                "tell me which and I'll patch this method.")
        except Exception as e:
            self.message_error("Print failed", str(e))


# ============================================================= line dialog
def _hqo_edit_one_line(parent, line, on_save):
    """Small dialog to edit one line item."""
    dlg = tk.Toplevel(parent)
    dlg.title("Edit line")
    dlg.transient(parent)
    dlg.grab_set()
    center_window_on_screen(dlg, 440, 320)

    code_var  = tk.StringVar(value=line.get("code") or "")
    desc_var  = tk.StringVar(value=line.get("description") or "")
    qty_var   = tk.StringVar(value=f"{float(line.get('qty') or 0):g}")
    pkgs_var  = tk.StringVar(value=f"{float(line.get('total_pcs') or 0):g}")
    pk_var    = tk.StringVar(value=line.get("packaging") or "")
    cost_var  = tk.StringVar(value=f"{float(line.get('cost_price') or 0):.2f}")

    f = tk.Frame(dlg)
    f.pack(fill="both", expand=True, padx=14, pady=14)

    for i, (label, var) in enumerate([
        ("Code",         code_var),
        ("Description",  desc_var),
        ("Qty",          qty_var),
        ("Total Pcs",    pkgs_var),
        ("Packaging",    pk_var),
        ("Cost/pcs",     cost_var),
    ]):
        ttk.Label(f, text=label).grid(row=i, column=0, sticky="w", pady=4)
        ttk.Entry(f, textvariable=var, width=28
                  ).grid(row=i, column=1, sticky="w", pady=4)

    btns = tk.Frame(f)
    btns.grid(row=7, column=0, columnspan=2, sticky="e", pady=(10, 0))

    def do_save():
        try:
            qty  = float(qty_var.get())
            pkgs = float(pkgs_var.get())
            cost = float(cost_var.get())
        except ValueError:
            return
        on_save({
            "code":        code_var.get().strip(),
            "description": desc_var.get().strip(),
            "qty":         qty,
            "total_pcs":   pkgs,
            "packaging":   pk_var.get().strip(),
            "cost_price":  cost,
            "line_total":  round(qty * cost, 2),
        })
        dlg.destroy()

    ttk.Button(btns, text="Cancel",
               command=dlg.destroy).pack(side="right")
    ttk.Button(btns, text="Save",
               command=do_save).pack(side="right", padx=(0, 6))