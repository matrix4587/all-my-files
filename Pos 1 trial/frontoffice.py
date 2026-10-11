import tkinter as tk
from tkinter import ttk, messagebox
from database import get_products, checkout

class FrontOffice:
    def __init__(self, root, user):
        self.root = root
        self.user = user
        self.cart = {}   # product_id -> {product, qty}

        self.root.title(f"POS - Front Office ({user['username']})")
        self.root.geometry("1100x650")
        self.root.configure(bg="#f3f4f6")

        self.build()
        self.load_products()

    def build(self):
        # Top bar
        top = tk.Frame(self.root, bg="#1e293b", height=50)
        top.pack(fill="x")
        tk.Label(top, text=f"👤 {self.user['username']}", bg="#1e293b",
                 fg="white", font=("Segoe UI", 11)).pack(side="left", padx=15, pady=10)
        tk.Button(top, text="Logout", command=self.logout, bg="#ef4444",
                  fg="white", relief="flat", padx=12).pack(side="right", padx=10, pady=10)
        if self.user["role"] == "admin":
            tk.Button(top, text="→ Back Office", command=self.goto_backoffice,
                      bg="#3b82f6", fg="white", relief="flat",
                      padx=12).pack(side="right", pady=10)

        # Main split
        main = tk.Frame(self.root, bg="#f3f4f6")
        main.pack(fill="both", expand=True, padx=10, pady=10)

        # LEFT: products
        left = tk.Frame(main, bg="#f3f4f6")
        left.pack(side="left", fill="both", expand=True)

        search_frame = tk.Frame(left, bg="#f3f4f6")
        search_frame.pack(fill="x", pady=(0, 8))
        tk.Label(search_frame, text="🔍 Search:", bg="#f3f4f6").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *a: self.load_products())
        tk.Entry(search_frame, textvariable=self.search_var,
                 font=("Segoe UI", 11)).pack(side="left", fill="x", expand=True, padx=6)

        # Products canvas + scrollbar
        canvas_frame = tk.Frame(left, bg="#f3f4f6")
        canvas_frame.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_frame, bg="#f3f4f6", highlightthickness=0)
        scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.products_frame = tk.Frame(self.canvas, bg="#f3f4f6")
        self.canvas.create_window((0, 0), window=self.products_frame, anchor="nw")
        self.products_frame.bind("<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

        # RIGHT: cart
        right = tk.Frame(main, bg="white", width=340)
        right.pack(side="right", fill="y", padx=(10, 0))
        right.pack_propagate(False)

        tk.Label(right, text="🛒 Cart", bg="white",
                 font=("Segoe UI", 14, "bold")).pack(pady=10)

        # Cart treeview
        cols = ("name", "price", "qty", "sub")
        self.cart_tree = ttk.Treeview(right, columns=cols, show="headings", height=14)
        for c, w in zip(cols, (110, 55, 45, 70)):
            self.cart_tree.heading(c, text=c.title())
            self.cart_tree.column(c, width=w, anchor="center")
        self.cart_tree.pack(fill="x", padx=8)
        self.cart_tree.bind("<Double-1>", self.edit_qty)

        # Qty buttons
        qty_frame = tk.Frame(right, bg="white")
        qty_frame.pack(fill="x", padx=8, pady=6)
        tk.Button(qty_frame, text="+", width=4, command=lambda: self.change_sel(1)).pack(side="left")
        tk.Button(qty_frame, text="-", width=4, command=lambda: self.change_sel(-1)).pack(side="left", padx=4)
        tk.Button(qty_frame, text="Remove", command=self.remove_sel,
                  bg="#ef4444", fg="white", relief="flat").pack(side="left", padx=4)
        tk.Button(qty_frame, text="Clear", command=self.clear_cart,
                  relief="flat").pack(side="right")

        # Totals
        totals = tk.Frame(right, bg="white")
        totals.pack(fill="x", padx=12, pady=8)

        self.total_var = tk.StringVar(value="$0.00")
        self.change_var = tk.StringVar(value="$0.00")

        tk.Label(totals, text="Total:", bg="white",
                 font=("Segoe UI", 12)).grid(row=0, column=0, sticky="w")
        tk.Label(totals, textvariable=self.total_var, bg="white",
                 font=("Segoe UI", 14, "bold"), fg="#10b981").grid(row=0, column=1, sticky="e")

        tk.Label(totals, text="Payment:", bg="white").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.payment_entry = tk.Entry(totals, font=("Segoe UI", 12), width=10)
        self.payment_entry.grid(row=1, column=1, sticky="e", pady=(10, 0))
        self.payment_entry.bind("<KeyRelease>", lambda e: self.update_change())

        tk.Label(totals, text="Change:", bg="white").grid(row=2, column=0, sticky="w", pady=(6, 0))
        tk.Label(totals, textvariable=self.change_var, bg="white",
                 font=("Segoe UI", 12, "bold")).grid(row=2, column=1, sticky="e", pady=(6, 0))

        totals.columnconfigure(1, weight=1)

        # Checkout button
        tk.Button(right, text="💳 CHECKOUT", bg="#10b981", fg="white",
                  font=("Segoe UI", 13, "bold"), relief="flat",
                  command=self.do_checkout).pack(fill="x", padx=12, pady=15, ipady=10)

        self.root.bind("<F2>", lambda e: self.payment_entry.focus_set())
        self.root.bind("<Return>", lambda e: self.do_checkout())

    # ---------- Products ----------
    def load_products(self):
        for w in self.products_frame.winfo_children():
            w.destroy()
        products = get_products(self.search_var.get())
        cols = 4
        for idx, p in enumerate(products):
            r, c = divmod(idx, cols)
            card = tk.Frame(self.products_frame, bg="white", bd=1,
                            relief="solid", padx=10, pady=10, cursor="hand2")
            card.grid(row=r, column=c, padx=6, pady=6, sticky="nsew")
            self.products_frame.columnconfigure(c, weight=1)

            tk.Label(card, text=p["name"], bg="white",
                     font=("Segoe UI", 11, "bold")).pack(anchor="w")
            tk.Label(card, text=f"${p['price']:.2f}", bg="white",
                     fg="#10b981", font=("Segoe UI", 11)).pack(anchor="w")
            tk.Label(card, text=f"Stock: {p['stock']}", bg="white",
                     fg="#64748b", font=("Segoe UI", 9)).pack(anchor="w")

            for widget in (card,) + tuple(card.winfo_children()):
                widget.bind("<Button-1>", lambda e, prod=p: self.add_to_cart(prod))

    # ---------- Cart ----------
    def add_to_cart(self, p):
        if p["stock"] <= 0:
            messagebox.showwarning("Stock", "Out of stock")
            return
        pid = p["id"]
        if pid not in self.cart:
            self.cart[pid] = {"product": p, "qty": 0}
        if self.cart[pid]["qty"] >= p["stock"]:
            messagebox.showwarning("Stock", "Not enough stock")
            return
        self.cart[pid]["qty"] += 1
        self.refresh_cart()

    def refresh_cart(self):
        for row in self.cart_tree.get_children():
            self.cart_tree.delete(row)
        total = 0
        for pid, item in self.cart.items():
            p = item["product"]; q = item["qty"]
            sub = p["price"] * q
            total += sub
            self.cart_tree.insert("", "end", iid=str(pid),
                values=(p["name"], f"${p['price']:.2f}", q, f"${sub:.2f}"))
        self.total_var.set(f"${total:.2f}")
        self.update_change()

    def update_change(self):
        total = sum(i["product"]["price"] * i["qty"] for i in self.cart.values())
        try:
            pay = float(self.payment_entry.get() or 0)
        except ValueError:
            pay = 0
        ch = pay - total
        self.change_var.set(f"${ch:.2f}" if ch > 0 else "$0.00")

    def change_sel(self, delta):
        sel = self.cart_tree.selection()
        if not sel: return
        pid = int(sel[0])
        if pid not in self.cart: return
        new_qty = self.cart[pid]["qty"] + delta
        if new_qty <= 0:
            del self.cart[pid]
        elif new_qty > self.cart[pid]["product"]["stock"]:
            messagebox.showwarning("Stock", "Not enough stock")
            return
        else:
            self.cart[pid]["qty"] = new_qty
        self.refresh_cart()

    def remove_sel(self):
        sel = self.cart_tree.selection()
        if not sel: return
        del self.cart[int(sel[0])]
        self.refresh_cart()

    def edit_qty(self, event):
        """Double-click to edit qty inline."""
        sel = self.cart_tree.selection()
        if not sel: return
        pid = int(sel[0])
        from tkinter import simpledialog
        q = simpledialog.askinteger("Qty", "New quantity:",
                                     initialvalue=self.cart[pid]["qty"], minvalue=1)
        if q and q <= self.cart[pid]["product"]["stock"]:
            self.cart[pid]["qty"] = q
            self.refresh_cart()

    def clear_cart(self):
        self.cart.clear()
        self.payment_entry.delete(0, "end")
        self.refresh_cart()

    # ---------- Checkout ----------
    def do_checkout(self):
        if not self.cart:
            messagebox.showwarning("Cart", "Cart is empty")
            return
        try:
            payment = float(self.payment_entry.get() or 0)
        except ValueError:
            messagebox.showerror("Payment", "Invalid payment amount")
            return

        items = [{"id": i["product"]["id"], "name": i["product"]["name"],
                  "price": i["product"]["price"], "qty": i["qty"]}
                 for i in self.cart.values()]
        try:
            sale_id, total, change = checkout(items, payment, self.user["username"])
        except ValueError as e:
            messagebox.showerror("Checkout", str(e))
            return

        receipt = self.build_receipt(sale_id, items, total, payment, change)
        self.show_receipt(receipt)

        self.clear_cart()
        self.load_products()

    def build_receipt(self, sale_id, items, total, payment, change):
        lines = []
        lines.append("=" * 34)
        lines.append("        SIMPLE POS STORE")
        lines.append("=" * 34)
        lines.append(f"Sale #: {sale_id}")
        lines.append(f"Cashier: {self.user['username']}")
        from datetime import datetime
        lines.append(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("-" * 34)
        for i in items:
            lines.append(f"{i['name'][:15]:<15} {i['qty']:>3} x {i['price']:>6.2f}")
            lines.append(f"{'':>24} ${i['qty']*i['price']:>6.2f}")
        lines.append("-" * 34)
        lines.append(f"TOTAL:               ${total:>8.2f}")
        lines.append(f"PAYMENT:             ${payment:>8.2f}")
        lines.append(f"CHANGE:              ${change:>8.2f}")
        lines.append("=" * 34)
        lines.append("      Thank you, come again!")
        return "\n".join(lines)

    def show_receipt(self, text):
        win = tk.Toplevel(self.root)
        win.title("Receipt")
        win.geometry("380x520")
        txt = tk.Text(win, font=("Courier New", 11), bg="#fffef5")
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        tk.Button(win, text="Print (Save to file)", command=lambda: self.save_receipt(text),
                  bg="#3b82f6", fg="white", relief="flat").pack(pady=5, ipadx=10)
        tk.Button(win, text="Close", command=win.destroy,
                  relief="flat").pack(pady=(0, 10), ipadx=10)

    def save_receipt(self, text):
        from tkinter import filedialog
        from datetime import datetime
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=f"receipt_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        if path:
            with open(path, "w") as f:
                f.write(text)
            messagebox.showinfo("Saved", f"Receipt saved:\n{path}")

    # ---------- Navigation ----------
    def logout(self):
        self.root.destroy()
        import main  # restart app

    def goto_backoffice(self):
        self.root.destroy()
        import backoffice
        backoffice.start(self.user)