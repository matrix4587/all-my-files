import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from database import (get_products, add_product, update_product, delete_product,
                      get_sales, get_dashboard)

class BackOffice:
    def __init__(self, root, user):
        self.root = root
        self.user = user
        self.root.title(f"POS - Back Office ({user['username']})")
        self.root.geometry("1050x650")
        self.root.configure(bg="#f3f4f6")
        self.build()
        self.refresh_all()

    def build(self):
        # Top bar
        top = tk.Frame(self.root, bg="#1e293b", height=50)
        top.pack(fill="x")
        tk.Label(top, text=f"⚙️ Back Office — {self.user['username']}",
                 bg="#1e293b", fg="white",
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=15, pady=10)
        tk.Button(top, text="→ Front Office", command=self.goto_frontoffice,
                  bg="#10b981", fg="white", relief="flat", padx=12).pack(side="right", padx=10, pady=10)
        tk.Button(top, text="Logout", command=self.logout,
                  bg="#ef4444", fg="white", relief="flat", padx=12).pack(side="right", pady=10)

        # Dashboard
        dash = tk.Frame(self.root, bg="#f3f4f6")
        dash.pack(fill="x", padx=15, pady=15)

        self.stat_total = self._stat_card(dash, "Total Sales", "$0", "#3b82f6")
        self.stat_count = self._stat_card(dash, "Transactions", "0", "#10b981")
        self.stat_low = self._stat_card(dash, "Low Stock", "0", "#ef4444")

        # Tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        self.tab_products = tk.Frame(self.notebook, bg="white")
        self.tab_sales = tk.Frame(self.notebook, bg="white")
        self.tab_top = tk.Frame(self.notebook, bg="white")

        self.notebook.add(self.tab_products, text="  Products  ")
        self.notebook.add(self.tab_sales, text="  Sales History  ")
        self.notebook.add(self.tab_top, text="  Top Products  ")

        self.build_products_tab()
        self.build_sales_tab()
        self.build_top_tab()

    def _stat_card(self, parent, label, value, color):
        card = tk.Frame(parent, bg="white", padx=20, pady=15)
        card.pack(side="left", expand=True, fill="x", padx=6)
        v = tk.Label(card, text=value, bg="white", fg=color,
                     font=("Segoe UI", 22, "bold"))
        v.pack()
        tk.Label(card, text=label, bg="white", fg="#64748b").pack()
        return v

    # ---------- Products tab ----------
    def build_products_tab(self):
        form = tk.Frame(self.tab_products, bg="white", pady=10)
        form.pack(fill="x", padx=10)

        tk.Label(form, text="Name:", bg="white").grid(row=0, column=0, padx=4)
        self.p_name = tk.Entry(form, width=20)
        self.p_name.grid(row=0, column=1, padx=4)

        tk.Label(form, text="Price:", bg="white").grid(row=0, column=2, padx=4)
        self.p_price = tk.Entry(form, width=8)
        self.p_price.grid(row=0, column=3, padx=4)

        tk.Label(form, text="Stock:", bg="white").grid(row=0, column=4, padx=4)
        self.p_stock = tk.Entry(form, width=8)
        self.p_stock.grid(row=0, column=5, padx=4)

        tk.Label(form, text="Category:", bg="white").grid(row=0, column=6, padx=4)
        self.p_cat = tk.Entry(form, width=12)
        self.p_cat.grid(row=0, column=7, padx=4)

        tk.Button(form, text="Add Product", bg="#3b82f6", fg="white",
                  relief="flat", command=self.do_add).grid(row=0, column=8, padx=8)

        tk.Button(form, text="Update Selected", command=self.do_update,
                  relief="flat").grid(row=0, column=9, padx=4)
        tk.Button(form, text="Delete Selected", bg="#ef4444", fg="white",
                  relief="flat", command=self.do_delete).grid(row=0, column=10, padx=4)

        # Table
        cols = ("id", "name", "price", "stock", "category")
        self.prod_tree = ttk.Treeview(self.tab_products, columns=cols, show="headings")
        for c, w in zip(cols, (50, 250, 100, 100, 150)):
            self.prod_tree.heading(c, text=c.title())
            self.prod_tree.column(c, width=w, anchor="center")
        self.prod_tree.pack(fill="both", expand=True, padx=10, pady=10)
        self.prod_tree.bind("<<TreeviewSelect>>", self.on_product_select)

    def on_product_select(self, event):
        sel = self.prod_tree.selection()
        if not sel: return
        vals = self.prod_tree.item(sel[0])["values"]
        self.p_name.delete(0, "end"); self.p_name.insert(0, vals[1])
        self.p_price.delete(0, "end"); self.p_price.insert(0, vals[2])
        self.p_stock.delete(0, "end"); self.p_stock.insert(0, vals[3])
        self.p_cat.delete(0, "end"); self.p_cat.insert(0, vals[4])

    def do_add(self):
        try:
            name = self.p_name.get().strip()
            price = float(self.p_price.get())
            stock = int(self.p_stock.get())
            cat = self.p_cat.get().strip()
            if not name: raise ValueError
            add_product(name, price, stock, cat)
            self.clear_form()
            self.refresh_all()
        except ValueError:
            messagebox.showerror("Error", "Please fill valid name/price/stock")

    def do_update(self):
        sel = self.prod_tree.selection()
        if not sel:
            messagebox.showwarning("Update", "Select a product")
            return
        pid = self.prod_tree.item(sel[0])["values"][0]
        try:
            update_product(pid, self.p_name.get().strip(),
                           float(self.p_price.get()),
                           int(self.p_stock.get()),
                           self.p_cat.get().strip())
            self.refresh_all()
        except ValueError:
            messagebox.showerror("Error", "Invalid values")

    def do_delete(self):
        sel = self.prod_tree.selection()
        if not sel: return
        pid = self.prod_tree.item(sel[0])["values"][0]
        if messagebox.askyesno("Delete", "Delete this product?"):
            delete_product(pid)
            self.refresh_all()

    def clear_form(self):
        for e in (self.p_name, self.p_price, self.p_stock, self.p_cat):
            e.delete(0, "end")

    # ---------- Sales tab ----------
    def build_sales_tab(self):
        cols = ("id", "total", "payment", "change", "cashier", "date")
        self.sales_tree = ttk.Treeview(self.tab_sales, columns=cols, show="headings")
        for c, w in zip(cols, (60, 100, 100, 100, 120, 200)):
            self.sales_tree.heading(c, text=c.title())
            self.sales_tree.column(c, width=w, anchor="center")
        self.sales_tree.pack(fill="both", expand=True, padx=10, pady=10)

    # ---------- Top products tab ----------
    def build_top_tab(self):
        self.top_frame = tk.Frame(self.tab_top, bg="white")
        self.top_frame.pack(fill="both", expand=True, padx=20, pady=20)

    # ---------- Refresh ----------
    def refresh_all(self):
        d = get_dashboard()
        self.stat_total.config(text=f"${d['total']:.2f}")
        self.stat_count.config(text=str(d["count"]))
        self.stat_low.config(text=str(d["low_stock"]))

        # Products
        for row in self.prod_tree.get_children():
            self.prod_tree.delete(row)
        for p in get_products():
            self.prod_tree.insert("", "end",
                values=(p["id"], p["name"], f"{p['price']:.2f}", p["stock"], p["category"]))

        # Sales
        for row in self.sales_tree.get_children():
            self.sales_tree.delete(row)
        for s in get_sales():
            self.sales_tree.insert("", "end",
                values=(s["id"], f"${s['total']:.2f}", f"${s['payment']:.2f}",
                        f"${s['change_due']:.2f}", s["cashier"], s["created_at"][:19]))

        # Top products
        for w in self.top_frame.winfo_children():
            w.destroy()
        tk.Label(self.top_frame, text="🏆 Best Sellers",
                 font=("Segoe UI", 16, "bold"), bg="white").pack(anchor="w", pady=(0, 10))
        if not d["top_products"]:
            tk.Label(self.top_frame, text="No sales yet.", bg="white").pack(anchor="w")
        for i, p in enumerate(d["top_products"], 1):
            row = tk.Frame(self.top_frame, bg="white")
            row.pack(fill="x", pady=4)
            tk.Label(row, text=f"{i}. {p['name']}", bg="white",
                     font=("Segoe UI", 12)).pack(side="left")
            tk.Label(row, text=f"{p['q']} sold", bg="white",
                     fg="#10b981", font=("Segoe UI", 12, "bold")).pack(side="right")

    # ---------- Nav ----------
    def goto_frontoffice(self):
        self.root.destroy()
        import frontoffice
        frontoffice.start(self.user)

    def logout(self):
        self.root.destroy()
        import main  # restart app