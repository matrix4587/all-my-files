"""
HQ — Admin Panel (standalone).

Sections:
  1. Login gate  — admin username/password. Only admin accounts can enter.
  2. Products    — searchable list; add items to a CRN batch.
  3. New CRN     — build and post a batch (reference, reason, lines).
  4. Posted CRNs — read-only list of every CRN (received or not).
  5. Users       — create / edit / deactivate branch staff accounts.

Users can be assigned any of the four roles: staff, supervisor, manager,
admin.

Launch with:   py admin_panel.py
Or via the main app's Inventory → Admin Panel button.
"""

import datetime
import threading
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

import requests

from common.center import center_window_on_screen


SERVER = "http://localhost:5000"
MAX_ROWS = 500


# ============================================================================
# Login screen
# ============================================================================

class LoginScreen:
    def __init__(self, root, on_success):
        self.root = root
        self.on_success = on_success

        self.frame = ttk.Frame(root, padding=24)
        self.frame.pack(fill="both", expand=True)

        ttk.Label(self.frame, text="HQ — Admin Login",
                  font=("Arial", 16, "bold")).pack(pady=(10, 20))

        row1 = ttk.Frame(self.frame)
        row1.pack(fill="x", pady=(0, 8))
        ttk.Label(row1, text="Username:", width=12).pack(side="left")
        self.user_var = tk.StringVar()
        e1 = ttk.Entry(row1, textvariable=self.user_var, width=26)
        e1.pack(side="left", fill="x", expand=True)
        e1.focus_set()

        row2 = ttk.Frame(self.frame)
        row2.pack(fill="x", pady=(0, 16))
        ttk.Label(row2, text="Password:", width=12).pack(side="left")
        self.pass_var = tk.StringVar()
        e2 = ttk.Entry(row2, textvariable=self.pass_var, width=26,
                       show="\u2022")
        e2.pack(side="left", fill="x", expand=True)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self.frame, textvariable=self.status_var,
                  foreground="#990000").pack(pady=(0, 8))

        btn_row = ttk.Frame(self.frame)
        btn_row.pack(fill="x")
        self.login_btn = ttk.Button(btn_row, text="Log in",
                                     command=self._do_login)
        self.login_btn.pack(side="right")

        e1.bind("<Return>", lambda ev: e2.focus_set())
        e2.bind("<Return>", lambda ev: self._do_login())

    def _do_login(self):
        u = self.user_var.get().strip()
        p = self.pass_var.get().strip()
        if not u or not p:
            self.status_var.set("Username and password required.")
            return

        self.login_btn.configure(state="disabled")
        self.status_var.set("Signing in…")

        def worker():
            try:
                r = requests.post(f"{SERVER}/login",
                                  json={"username": u, "password": p},
                                  timeout=8)
                body = r.json() if r.status_code == 200 else None
                err = None if r.status_code == 200 else (
                    r.json().get("message") if r.content else "Login failed")
            except Exception as e:
                body, err = None, str(e)
            self.root.after(0, lambda: self._on_result(u, p, body, err))

        threading.Thread(target=worker, daemon=True).start()

    def _on_result(self, username, password, body, err):
        self.login_btn.configure(state="normal")
        if err or not body or body.get("status") != "ok":
            self.status_var.set(err or "Login failed.")
            return
        if body.get("kind") != "admin":
            self.status_var.set("Only HQ admins can use this panel.")
            return
        self.frame.destroy()
        self.on_success(username, password)


# ============================================================================
# Main panel
# ============================================================================

class HqAdminPanel:
    def __init__(self, root, admin_user, admin_pass):
        self.root = root
        self.admin_user = admin_user
        self.admin_pass = admin_pass

        # guards
        self._user_form_open = False

        self.root.title(f"HQ — Admin Panel — signed in as {admin_user}")
        self.root.geometry("1000x660")
        self.root.minsize(880, 560)

        # ---- state ----
        self.batch = []
        self.products_rows = []
        self.products_index = {}
        self.users_rows = []
        self.users_index = {}

        try:
            style = ttk.Style()
            style.theme_use("clam")
        except Exception:
            pass

        # ---- header with log-out ----
        header = tk.Frame(root, bg="#a9c9a4")
        header.pack(fill="x")
        tk.Label(header, text=f"HQ Admin Panel — {admin_user}",
                 bg="#a9c9a4", font=("Arial", 11, "bold")
                 ).pack(side="left", padx=10, pady=6)
        ttk.Button(header, text="Log out",
                   command=self._logout).pack(side="right", padx=10, pady=4)

        # ---- notebook ----
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_products = ttk.Frame(nb)
        self.tab_new      = ttk.Frame(nb)
        self.tab_posted   = ttk.Frame(nb)
        self.tab_users    = ttk.Frame(nb)

        nb.add(self.tab_products, text="Products")
        nb.add(self.tab_new,      text="New CRN")
        nb.add(self.tab_posted,   text="Posted CRNs")
        nb.add(self.tab_users,    text="Users")

        self._build_products_tab(self.tab_products)
        self._build_new_tab(self.tab_new)
        self._build_posted_tab(self.tab_posted)
        self._build_users_tab(self.tab_users)

        self._render_batch()
        self._refresh_posted()
        self._refresh_users()

    def _logout(self):
        if not messagebox.askyesno("Log out",
                                   "Log out and return to the login screen?",
                                   parent=self.root):
            return
        for child in self.root.winfo_children():
            child.destroy()
        LoginScreen(self.root, on_success=self._relaunch)

    def _relaunch(self, user, password):
        HqAdminPanel(self.root, user, password)

    # ============================================================ Products

    def _build_products_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(top, text="Search:").pack(side="left", padx=(0, 4))
        self.search_var = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.search_var, width=34)
        e.pack(side="left")
        e.focus_set()
        self.search_var.trace_add("write", lambda *a: self._apply_product_filter())

        ttk.Button(top, text="Refresh",
                   command=self._refresh_products).pack(side="right")
        ttk.Button(top, text="Add to CRN batch",
                   command=self._add_selected_to_batch
                   ).pack(side="right", padx=(0, 6))

        footer = tk.Frame(parent, height=34)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)
        self.batch_label_var = tk.StringVar(value="Batch: 0 items")
        tk.Label(footer, textvariable=self.batch_label_var,
                 bg="#f0f0f0").pack(side="left")
        self.batch_total_var = tk.StringVar(value="0.00")
        tk.Label(footer, textvariable=self.batch_total_var,
                 font=("Arial", 11, "bold"),
                 bg="#e8e8e8", fg="black",
                 relief="solid", bd=1, padx=16, pady=2
                 ).pack(side="right", padx=(0, 2))

        hint_frame = tk.Frame(parent)
        hint_frame.pack(side="bottom", fill="x", padx=10, pady=(0, 2))
        self.hint_var = tk.StringVar(value="Click Refresh to load products.")
        tk.Label(hint_frame, textvariable=self.hint_var,
                 fg="#777777").pack(anchor="w")

        cols = ("code", "name", "stock", "cost", "price")
        heads = (
            ("code",  "Code",  100, "w"),
            ("name",  "Name",  340, "w"),
            ("stock", "Stock", 90,  "e"),
            ("cost",  "Cost",  90,  "e"),
            ("price", "Price", 90,  "e"),
        )
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=16)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        tree.bind("<Double-1>", lambda e: self._add_selected_to_batch())
        self.products_tree = tree

    def _refresh_products(self):
        if not self.products_tree.winfo_exists():
            return
        self.hint_var.set("Loading products…")

        def worker():
            try:
                r = requests.get(f"{SERVER}/products", timeout=10)
                rows = r.json() if r.status_code == 200 else []
                err = None
            except Exception as e:
                rows, err = None, e
            self.root.after(0, lambda: self._fill_products(rows, err))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_products(self, rows, err):
        if not self.products_tree.winfo_exists():
            return
        if err is not None:
            self.hint_var.set(f"Could not load products: {err}")
            return
        self.products_rows = list(rows or [])
        n = len(self.products_rows)
        self.hint_var.set(f"Loaded {n} product{'s' if n != 1 else ''}.")
        self._apply_product_filter()

    def _apply_product_filter(self):
        tree = self.products_tree
        if not tree.winfo_exists():
            return
        for row in tree.get_children():
            tree.delete(row)
        self.products_index = {}

        needle = (self.search_var.get() or "").strip().lower()
        shown = 0
        for p in self.products_rows:
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
            self.products_index[item] = p
            shown += 1
            if shown >= MAX_ROWS:
                break

    def _add_selected_to_batch(self):
        tree = self.products_tree
        if not tree.winfo_exists():
            return
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Select a product",
                                "Select a product in the list first.",
                                parent=self.root)
            return
        product = self.products_index.get(sel[0])
        if not product:
            return
        self._prompt_qty(product)

    def _prompt_qty(self, product):
        dlg = tk.Toplevel(self.root)
        dlg.title("Add to CRN batch")

        dlg.geometry("400x240")
        dlg.minsize(400, 240)
        dlg.resizable(False, False)

        f = ttk.Frame(dlg)
        f.pack(fill="both", expand=True, padx=14, pady=14)

        ttk.Label(f, text=f"Code: {product.get('code') or product.get('barcode')}"
                  ).pack(anchor="w")
        ttk.Label(f, text=f"Name: {product.get('name')}").pack(anchor="w", pady=(2, 0))
        ttk.Label(f, text=f"Current stock: {float(product.get('stock') or 0):g}"
                  ).pack(anchor="w", pady=(2, 10))

        ttk.Label(f, text="Qty to deduct:").pack(anchor="w")
        qty_var = tk.StringVar(value="1")
        entry = ttk.Entry(f, textvariable=qty_var, width=12)
        entry.pack(anchor="w", pady=(2, 12))
        entry.focus_set()
        entry.select_range(0, "end")

        btns = ttk.Frame(f)
        btns.pack(fill="x")
        ttk.Button(btns, text="Cancel",
                   command=dlg.destroy).pack(side="right")

        def do_add():
            try:
                qty = float(qty_var.get())
                if qty <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                messagebox.showerror("Invalid", "Qty must be a number > 0.",
                                     parent=dlg)
                return
            cost = float(product.get("cost_price") or 0)
            self.batch.append({
                "barcode": product.get("barcode"),
                "code": product.get("code") or product.get("barcode"),
                "name": product.get("name"),
                "qty": qty,
                "unit_cost": cost,
                "subtotal": round(qty * cost, 2),
            })
            dlg.destroy()
            self._render_batch()

        ttk.Button(btns, text="Add", command=do_add).pack(side="right", padx=(0, 6))
        entry.bind("<Return>", lambda e: do_add())

        dlg.lift()
        dlg.focus_force()

    # ============================================================ New CRN

    def _build_new_tab(self, parent):
        head = ttk.Frame(parent)
        head.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(head, text="Reference:").grid(row=0, column=0, sticky="w")
        self.ref_var = tk.StringVar()
        ttk.Entry(head, textvariable=self.ref_var, width=34
                  ).grid(row=0, column=1, sticky="w", padx=(4, 16))

        ttk.Label(head, text="Reason:").grid(row=0, column=2, sticky="w")
        self.reason_var = tk.StringVar()
        ttk.Entry(head, textvariable=self.reason_var, width=34
                  ).grid(row=0, column=3, sticky="w", padx=(4, 0))

        ttk.Label(head, text="User:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.user_var = tk.StringVar(value=self.admin_user)
        ttk.Entry(head, textvariable=self.user_var, width=22
                  ).grid(row=1, column=1, sticky="w", padx=(4, 0), pady=(6, 0))

        footer = tk.Frame(parent, height=40)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)
        self.new_batch_label_var = tk.StringVar(value="Batch: 0 items")
        tk.Label(footer, textvariable=self.new_batch_label_var,
                 bg="#f0f0f0").pack(side="left")
        ttk.Button(footer, text="Post CRN",
                   command=self._post_crn).pack(side="right")
        ttk.Button(footer, text="Clear batch",
                   command=self._clear_batch).pack(side="right", padx=(0, 6))
        ttk.Button(footer, text="Remove selected",
                   command=self._remove_selected).pack(side="right", padx=(0, 6))

        cols = ("code", "name", "qty", "cost", "subtotal")
        heads = (
            ("code",     "Code",        110, "w"),
            ("name",     "Name",        340, "w"),
            ("qty",      "Qty",         80,  "e"),
            ("cost",     "Cost/pcs",    100, "e"),
            ("subtotal", "Line Total",  120, "e"),
        )
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=14)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        self.batch_tree = tree

    def _render_batch(self):
        if hasattr(self, "batch_tree") and self.batch_tree.winfo_exists():
            for row in self.batch_tree.get_children():
                self.batch_tree.delete(row)
            for i, line in enumerate(self.batch):
                self.batch_tree.insert("", "end", iid=str(i), values=(
                    line["code"], line["name"],
                    f"{line['qty']:g}",
                    f"{line['unit_cost']:.2f}",
                    f"{line['subtotal']:.2f}",
                ))
        total = 0.0
        for l in self.batch:
            try:
                total += float(l["subtotal"])
            except (TypeError, ValueError):
                pass
        n = len(self.batch)
        if hasattr(self, "batch_label_var"):
            self.batch_label_var.set(f"Batch: {n} item{'s' if n != 1 else ''}")
        if hasattr(self, "batch_total_var"):
            self.batch_total_var.set(f"{total:,.2f}")
        if hasattr(self, "new_batch_label_var"):
            self.new_batch_label_var.set(
                f"Batch: {n} item{'s' if n != 1 else ''}  —  total {total:,.2f}")

    def _remove_selected(self):
        tree = self.batch_tree
        if not tree.winfo_exists():
            return
        sel = tree.selection()
        if not sel:
            return
        indexes = sorted((int(i) for i in sel), reverse=True)
        for i in indexes:
            if 0 <= i < len(self.batch):
                del self.batch[i]
        self._render_batch()

    def _clear_batch(self):
        if not self.batch:
            return
        if not messagebox.askyesno("Clear batch",
                                   "Discard everything currently in the batch?",
                                   parent=self.root):
            return
        self.batch = []
        self._render_batch()

    def _post_crn(self):
        if not self.batch:
            messagebox.showerror("Empty batch",
                                 "Add at least one item before posting.",
                                 parent=self.root)
            return
        payload = {
            "date": datetime.date.today().isoformat(),
            "reference": self.ref_var.get().strip() or None,
            "reason": self.reason_var.get().strip() or None,
            "user": self.user_var.get().strip() or self.admin_user,
            "lines": [{"barcode": l["barcode"], "qty": l["qty"]}
                      for l in self.batch],
        }

        def worker():
            try:
                headers = {"X-User": self.admin_user,
                           "X-Pass": self.admin_pass}
                r = requests.post(f"{SERVER}/crn", json=payload,
                                  headers=headers, timeout=10)
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", f"Could not reach server: {e}", parent=self.root))
                return
            if r.status_code not in (200, 201):
                self.root.after(0, lambda: messagebox.showerror(
                    "Post failed", r.text, parent=self.root))
                return
            try:
                body = r.json()
            except Exception:
                body = {}
            self.root.after(0, lambda: self._on_posted(body))

        threading.Thread(target=worker, daemon=True).start()

    def _on_posted(self, body):
        crn_id = body.get("id", "?")
        messagebox.showinfo(
            "CRN posted",
            f"CRN #{crn_id} created.\n\n"
            "Open the Branch Purchase Centre → CRNs to receive it.",
            parent=self.root)
        self.batch = []
        self.ref_var.set("")
        self.reason_var.set("")
        self._render_batch()
        self._refresh_posted()

    # ============================================================ Posted

    def _build_posted_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Button(top, text="Refresh",
                   command=self._refresh_posted).pack(side="left")

        footer = tk.Frame(parent, height=34)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)
        self.posted_entries_var = tk.StringVar(value="Total 0 entries")
        tk.Label(footer, textvariable=self.posted_entries_var,
                 bg="#f0f0f0").pack(side="left")
        self.posted_total_var = tk.StringVar(value="0.00")
        tk.Label(footer, textvariable=self.posted_total_var,
                 font=("Arial", 11, "bold"),
                 bg="#e8e8e8", fg="black",
                 relief="solid", bd=1, padx=16, pady=2
                 ).pack(side="right", padx=(0, 2))

        cols = ("date", "crn", "reference", "lines", "qty", "value", "user", "received")
        heads = (
            ("date",      "Date*",       100, "w"),
            ("crn",       "CRN #",        70, "e"),
            ("reference", "Reference",   200, "w"),
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
        self.posted_tree = tree

    def _refresh_posted(self):
        if not hasattr(self, "posted_tree") or not self.posted_tree.winfo_exists():
            return

        def worker():
            try:
                r = requests.get(f"{SERVER}/crns", params={"all": "1"}, timeout=10)
                rows = r.json() if r.status_code == 200 else []
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", f"Could not reach server: {e}", parent=self.root))
                return
            self.root.after(0, lambda: self._fill_posted(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_posted(self, rows):
        tree = self.posted_tree
        if not tree.winfo_exists():
            return
        for row in tree.get_children():
            tree.delete(row)
        shown = 0
        total_value = 0.0
        for c in rows or []:
            received = "\u2611 Yes" if c.get("received") else "\u2610 No"
            tree.insert("", "end", values=(
                self._iso_to_dmy(c.get("date")),
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
        self.posted_entries_var.set(f"Total {shown} entries")
        self.posted_total_var.set(f"{total_value:,.2f}")

    # ============================================================ Users

    def _build_users_tab(self, parent):
        top = ttk.Frame(parent)
        top.pack(fill="x", padx=10, pady=(10, 6))
        ttk.Button(top, text="Refresh",
                   command=self._refresh_users).pack(side="left")
        ttk.Button(top, text="New User",
                   command=self._new_user_dialog).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Edit",
                   command=self._edit_selected_user).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Deactivate",
                   command=self._deactivate_selected_user).pack(side="left", padx=(6, 0))

        footer = tk.Frame(parent, height=34)
        footer.pack(side="bottom", fill="x", padx=10, pady=(4, 10))
        footer.pack_propagate(False)
        self.users_entries_var = tk.StringVar(value="Total 0 users")
        tk.Label(footer, textvariable=self.users_entries_var,
                 bg="#f0f0f0").pack(side="left")

        cols = ("id", "username", "full_name", "branch", "phone", "email",
                "role", "active", "created_at", "created_by")
        heads = (
            ("id",         "ID",          50,  "e"),
            ("username",   "Username",    120, "w"),
            ("full_name",  "Full Name",   180, "w"),
            ("branch",     "Branch",      140, "w"),
            ("phone",      "Phone",       120, "w"),
            ("email",      "Email",       180, "w"),
            ("role",       "Role",        90,  "w"),
            ("active",     "Active",      70,  "center"),
            ("created_at", "Created",     100, "w"),
            ("created_by", "Created By",  100, "w"),
        )
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=14)
        for c, h, w, a in heads:
            tree.heading(c, text=h)
            tree.column(c, width=w, anchor=a)
        tree.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        tree.bind("<Double-1>", lambda e: self._edit_selected_user())
        self.users_tree = tree

    def _refresh_users(self):
        if not hasattr(self, "users_tree") or not self.users_tree.winfo_exists():
            return

        def worker():
            try:
                r = requests.get(f"{SERVER}/users",
                                 headers={"X-User": self.admin_user,
                                          "X-Pass": self.admin_pass},
                                 timeout=10)
                if r.status_code == 401:
                    self.root.after(0, lambda: messagebox.showerror(
                        "Unauthorized", "Admin login required.",
                        parent=self.root))
                    return
                rows = r.json() if r.status_code == 200 else []
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", f"Could not reach server: {e}", parent=self.root))
                return
            self.root.after(0, lambda: self._fill_users(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_users(self, rows):
        tree = self.users_tree
        if not tree.winfo_exists():
            return
        self.users_rows = list(rows or [])
        for row in tree.get_children():
            tree.delete(row)
        self.users_index = {}

        for u in self.users_rows:
            item = tree.insert("", "end", values=(
                u.get("id") or "",
                u.get("username") or "",
                u.get("full_name") or "",
                u.get("branch") or "",
                u.get("phone") or "",
                u.get("email") or "",
                u.get("role") or "staff",
                "\u2611" if u.get("active") else "\u2610",
                u.get("created_at") or "",
                u.get("created_by") or "",
            ))
            self.users_index[item] = u

        self.users_entries_var.set(f"Total {len(self.users_rows)} users")

    def _selected_user(self):
        tree = self.users_tree
        if not tree.winfo_exists():
            return None
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Select a user",
                                "Select a user in the list first.",
                                parent=self.root)
            return None
        return self.users_index.get(sel[0])

    def _new_user_dialog(self):
        self._user_form(None)

    def _edit_selected_user(self):
        u = self._selected_user()
        if u:
            self._user_form(u)

    # ------------------------------------------------- user form dialog

    def _user_form(self, existing):
        """Open the New/Edit User dialog.

        Guards against double-open, wraps the build in try/except so a
        Tcl error shows a dialog instead of crashing the app.
        """
        if getattr(self, "_user_form_open", False):
            # A dialog is already on screen — bring it to front instead
            # of creating a second one.
            try:
                if getattr(self, "_user_dlg", None) and self._user_dlg.winfo_exists():
                    self._user_dlg.lift()
                    self._user_dlg.focus_force()
            except Exception:
                pass
            return

        self._user_form_open = True

        try:
            self._user_form_inner(existing)
        except Exception as e:
            self._user_form_open = False
            tb = traceback.format_exc()
            try:
                messagebox.showerror(
                    "User form error",
                    f"Could not open the user form:\n{e}\n\n{tb}",
                    parent=self.root)
            except Exception:
                print("User form error:", e)
                print(tb)

    def _user_form_inner(self, existing):
        is_edit = existing is not None

        dlg = tk.Toplevel(self.root)
        dlg.title("Edit User" if is_edit else "New User")

        # Size the dialog BEFORE packing widgets. Centre it on the parent
        # window, not the screen, so it lands on the same monitor.
        dlg.geometry("520x540")
        dlg.minsize(520, 540)
        dlg.resizable(False, False)

        try:
            self.root.update_idletasks()
            px = self.root.winfo_rootx() + max(
                0, (self.root.winfo_width() - 520) // 2)
            py = self.root.winfo_rooty() + max(
                0, (self.root.winfo_height() - 540) // 2)
            dlg.geometry(f"520x540+{px}+{py}")
        except Exception:
            pass

        self._user_dlg = dlg

        f = ttk.Frame(dlg)
        f.pack(fill="both", expand=True, padx=16, pady=16)

        def row(label, var, show=None):
            fr = ttk.Frame(f)
            fr.pack(fill="x", pady=3)
            ttk.Label(fr, text=label, width=14).pack(side="left")
            e = ttk.Entry(fr, textvariable=var, width=36,
                          show=show if show else "")
            e.pack(side="left", fill="x", expand=True)
            return e

        username_var = tk.StringVar(value=(existing or {}).get("username") or "")
        full_name_var = tk.StringVar(value=(existing or {}).get("full_name") or "")
        password_var = tk.StringVar()
        branch_var = tk.StringVar(value=(existing or {}).get("branch") or "")
        phone_var = tk.StringVar(value=(existing or {}).get("phone") or "")
        email_var = tk.StringVar(value=(existing or {}).get("email") or "")
        role_var = tk.StringVar(value=(existing or {}).get("role") or "staff")
        active_var = tk.BooleanVar(value=(existing or {}).get("active", True))

        e_user = row("Username:", username_var)
        row("Full Name:", full_name_var)
        e_pass = row("Password:", password_var, show="\u2022")
        row("Branch:", branch_var)
        row("Phone:", phone_var)
        row("Email:", email_var)

        role_fr = ttk.Frame(f)
        role_fr.pack(fill="x", pady=3)
        ttk.Label(role_fr, text="Role:", width=14).pack(side="left")
        ttk.Combobox(role_fr, textvariable=role_var, width=18,
                     state="readonly",
                     values=["staff", "supervisor", "manager", "admin"]
                     ).pack(side="left")

        if is_edit:
            ttk.Label(f, text="(Leave password blank to keep the current one)",
                      foreground="#666666").pack(anchor="w", pady=(6, 0))
            ttk.Checkbutton(f, text="Active", variable=active_var
                            ).pack(anchor="w", pady=(6, 0))

        status_var = tk.StringVar(value="")
        ttk.Label(f, textvariable=status_var,
                  foreground="#990000").pack(anchor="w", pady=(6, 0))

        btns = ttk.Frame(f)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Cancel",
                   command=dlg.destroy).pack(side="right")

        def do_save():
            u = username_var.get().strip()
            p = password_var.get().strip()
            if not is_edit and (not u or not p):
                status_var.set("Username and password are required.")
                return
            if is_edit and not u:
                status_var.set("Username is required.")
                return

            payload = {
                "username": u,
                "full_name": full_name_var.get().strip() or None,
                "branch": branch_var.get().strip() or None,
                "phone": phone_var.get().strip() or None,
                "email": email_var.get().strip() or None,
                "role": role_var.get().strip() or "staff",
                "active": bool(active_var.get()) if is_edit else True,
            }
            if p:
                payload["password"] = p

            btn_save.configure(state="disabled")
            status_var.set("Saving…")

            def worker():
                try:
                    headers = {"X-User": self.admin_user,
                               "X-Pass": self.admin_pass}
                    if is_edit:
                        r = requests.patch(
                            f"{SERVER}/users/{existing['id']}",
                            json=payload, headers=headers, timeout=10)
                    else:
                        r = requests.post(f"{SERVER}/users",
                                          json=payload, headers=headers,
                                          timeout=10)
                except Exception as e:
                    self.root.after(0, lambda: self._save_result(
                        dlg, btn_save, status_var, None, str(e)))
                    return
                body = None
                try:
                    body = r.json()
                except Exception:
                    pass
                err = None
                if r.status_code not in (200, 201):
                    err = (body or {}).get("message") or r.text or "Save failed"
                self.root.after(0, lambda: self._save_result(
                    dlg, btn_save, status_var, body, err))

            threading.Thread(target=worker, daemon=True).start()

        btn_save = ttk.Button(btns, text="Save", command=do_save)
        btn_save.pack(side="right", padx=(0, 6))

        if not is_edit:
            e_user.focus_set()
        else:
            e_pass.focus_set()

        # Show and focus the dialog, THEN take the modal grab once it is
        # mapped. This is the crucial ordering that stops the window
        # from blinking and vanishing.
        dlg.lift()
        dlg.focus_force()

        def _on_close():
            try:
                dlg.grab_release()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass
            self._user_form_open = False
            self._user_dlg = None

        def _grab_when_ready():
            try:
                dlg.wait_visibility()
            except Exception:
                pass
            try:
                dlg.grab_set()
            except Exception:
                pass

        dlg.protocol("WM_DELETE_WINDOW", _on_close)
        self.root.after(1, _grab_when_ready)

    def _save_result(self, dlg, btn_save, status_var, body, err):
        try:
            if dlg.winfo_exists():
                btn_save.configure(state="normal")
        except Exception:
            pass
        if err:
            try:
                if status_var.winfo_exists():
                    status_var.set(err)
            except Exception:
                pass
            return
        try:
            if dlg.winfo_exists():
                dlg.destroy()
        except Exception:
            pass
        # Clear the "open" flag so the next click can open a fresh dialog.
        self._user_form_open = False
        self._user_dlg = None
        self._refresh_users()

    def _deactivate_selected_user(self):
        u = self._selected_user()
        if not u:
            return
        if not messagebox.askyesno(
                "Deactivate user",
                f"Deactivate '{u.get('username')}'?\n"
                f"They will no longer be able to log in.",
                parent=self.root):
            return

        def worker():
            try:
                r = requests.delete(
                    f"{SERVER}/users/{u['id']}",
                    headers={"X-User": self.admin_user,
                             "X-Pass": self.admin_pass},
                    timeout=10)
                if r.status_code != 200:
                    msg = r.text
                    self.root.after(0, lambda: messagebox.showerror(
                        "Error", msg, parent=self.root))
                    return
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", f"Could not reach server: {e}", parent=self.root))
                return
            self.root.after(0, self._refresh_users)

        threading.Thread(target=worker, daemon=True).start()

    # ============================================================ helpers

    @staticmethod
    def _iso_to_dmy(iso):
        try:
            d = datetime.date.fromisoformat(iso)
            return d.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            return iso or ""


# ============================================================================
# Entry point
# ============================================================================

def main():
    try:
        from common.titlebar import install_green_titlebar_hook, apply_green_titlebar
        install_green_titlebar_hook()
    except Exception:
        apply_green_titlebar = None

    try:
        from common.center import install_centering_hook
        install_centering_hook()
    except Exception:
        pass

    root = tk.Tk()
    root.geometry("1000x660")
    root.minsize(880, 560)

    if apply_green_titlebar is not None:
        root.after(150, lambda: apply_green_titlebar(root))

    def on_login_success(user, password):
        HqAdminPanel(root, user, password)

    LoginScreen(root, on_success=on_login_success)
    root.mainloop()


if __name__ == "__main__":
    main()