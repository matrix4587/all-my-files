import tkinter as tk
from tkinter import ttk, messagebox
import requests
import datetime
import subprocess
import sys
import os
import tempfile

SERVER = "http://localhost:5000"


def open_with_default_app(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as e:
        messagebox.showerror("Could not open file",
                             f"Saved to:\n{path}\n\nBut could not open it automatically:\n{e}")


class FrontOffice(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Front Office - Checkout")
        self.geometry("800x650")

        self.products_cache = []
        self.current_product = None
        self.cart_items = []  # dicts: {product_id, barcode, name, price, qty}

        # Track the details of the last completed sale for receipt printing.
        self.last_sale = None

        # --- Cashier info ---
        cashier_frame = ttk.Frame(self)
        cashier_frame.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Label(cashier_frame, text="Cashier Name:").pack(side="left")
        self.cashier_var = tk.StringVar()
        ttk.Entry(cashier_frame, textvariable=self.cashier_var, width=20).pack(side="left", padx=5)

        # --- Barcode entry section ---
        entry_frame = ttk.Frame(self)
        entry_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(entry_frame, text="Barcode/Code:").pack(side="left")

        self.code_var = tk.StringVar()
        self.code_entry = ttk.Entry(entry_frame, textvariable=self.code_var, width=20)
        self.code_entry.pack(side="left", padx=5)

        self.code_var.trace_add("write", self.auto_lookup)
        self.code_entry.bind("<Return>", self.add_to_cart)

        # --- Product info section ---
        info_frame = ttk.LabelFrame(self, text="Product Info")
        info_frame.pack(fill="x", padx=10, pady=10)

        self.code_display_var = tk.StringVar(value="-")
        self.desc_var = tk.StringVar(value="-")
        self.stock_var = tk.StringVar(value="-")
        self.price_var = tk.StringVar(value="-")

        ttk.Label(info_frame, text="Code:").pack(side="left", padx=(10, 2))
        ttk.Label(info_frame, textvariable=self.code_display_var, width=12).pack(side="left", padx=(0, 15))

        ttk.Label(info_frame, text="Description:").pack(side="left", padx=(0, 2))
        ttk.Label(info_frame, textvariable=self.desc_var, width=25).pack(side="left", padx=(0, 15))

        ttk.Label(info_frame, text="Available Stock:").pack(side="left", padx=(0, 2))
        ttk.Label(info_frame, textvariable=self.stock_var, width=8).pack(side="left", padx=(0, 15))

        ttk.Label(info_frame, text="Price:").pack(side="left", padx=(0, 2))
        ttk.Label(info_frame, textvariable=self.price_var, width=10).pack(side="left")

        # --- Staging ---
        staging_frame = ttk.LabelFrame(self, text="Item Ready to Add (press Enter to add to cart)")
        staging_frame.pack(fill="x", padx=10, pady=10)

        self.staging_tree = ttk.Treeview(
            staging_frame,
            columns=("code", "desc", "stock", "price"),
            show="headings",
            height=1
        )
        self.staging_tree.heading("code", text="Code")
        self.staging_tree.heading("desc", text="Description")
        self.staging_tree.heading("stock", text="Available Stock")
        self.staging_tree.heading("price", text="Price")
        self.staging_tree.pack(fill="x", padx=5, pady=5)

        # --- Cart table ---
        cart_frame = ttk.LabelFrame(self, text="Cart")
        cart_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.cart_tree = ttk.Treeview(
            cart_frame,
            columns=("code", "desc", "qty", "price", "subtotal"),
            show="headings"
        )
        self.cart_tree.heading("code", text="Code")
        self.cart_tree.heading("desc", text="Description")
        self.cart_tree.heading("qty", text="Qty")
        self.cart_tree.heading("price", text="Price")
        self.cart_tree.heading("subtotal", text="Subtotal")
        self.cart_tree.pack(fill="both", expand=True, padx=5, pady=5)

        # Right-click a cart line to change qty / remove.
        self.cart_menu = tk.Menu(self, tearoff=0)
        self.cart_menu.add_command(label="Remove item", command=self.remove_selected_cart_item)
        self.cart_tree.bind("<Button-3>", self._show_cart_menu)

        # --- Total ---
        total_frame = ttk.Frame(self)
        total_frame.pack(fill="x", padx=10, pady=5)

        self.total_var = tk.StringVar(value="Total: 0.00")
        ttk.Label(total_frame, textvariable=self.total_var,
                  font=("Arial", 14, "bold")).pack(side="right")

        # --- Buttons ---
        checkout_frame = ttk.Frame(self)
        checkout_frame.pack(fill="x", padx=10, pady=10)

        ttk.Button(checkout_frame, text="Clear Cart",
                   command=self.clear_cart).pack(side="left")

        ttk.Button(checkout_frame, text="CHECKOUT",
                   command=self.open_payment_dialog).pack(side="right", ipadx=20, ipady=5)

        # Load products then keep refreshing quietly in the background.
        self.refresh_products_cache()
        self.periodic_cache_refresh()

    # ---------- Product cache ----------

    def refresh_products_cache(self):
        try:
            r = requests.get(f"{SERVER}/products", timeout=3)
            self.products_cache = r.json()
        except Exception as e:
            print("Could not refresh product cache:", e)

    def periodic_cache_refresh(self):
        self.refresh_products_cache()
        self.after(5000, self.periodic_cache_refresh)

    # ---------- Barcode lookup ----------

    def auto_lookup(self, *args):
        code = self.code_var.get().strip()

        if not code:
            self.clear_product_info()
            return

        match = next(
            (p for p in self.products_cache
             if str(p.get("barcode", "")).strip() == code
             or str(p.get("code", "")).strip() == code),
            None
        )

        if match:
            self.code_display_var.set(match.get("code") or match.get("barcode"))
            self.desc_var.set(match["name"])
            self.stock_var.set(match["stock"])
            self.price_var.set(match["price"])
            self.current_product = match
            self.show_in_staging(match)
        else:
            self.clear_product_info()

    def show_in_staging(self, product):
        for row in self.staging_tree.get_children():
            self.staging_tree.delete(row)
        self.staging_tree.insert(
            "", "end",
            values=(product.get("code") or product["barcode"],
                    product["name"], product["stock"], product["price"])
        )

    def clear_product_info(self):
        self.code_display_var.set("-")
        self.desc_var.set("-")
        self.stock_var.set("-")
        self.price_var.set("-")
        self.current_product = None
        for row in self.staging_tree.get_children():
            self.staging_tree.delete(row)

    # ---------- Cart ----------

    def add_to_cart(self, event=None):
        if not self.current_product:
            return

        product = self.current_product

        if product["stock"] <= 0:
            messagebox.showwarning("Out of Stock", f"{product['name']} has no available stock")
            return

        # How many of this item are already in the cart?
        already = sum(it["qty"] for it in self.cart_items if it["product_id"] == product["id"])
        if already + 1 > product["stock"]:
            messagebox.showwarning(
                "Not Enough Stock",
                f"Only {product['stock']} of '{product['name']}' in stock, "
                f"and {already} already in the cart.")
            return

        self.cart_items.append({
            "product_id": product["id"],
            "barcode": product["barcode"],
            "code": product.get("code") or product["barcode"],
            "name": product["name"],
            "price": product["price"],
            "qty": 1
        })

        self.refresh_cart_display()

        self.code_var.set("")
        self.clear_product_info()
        self.code_entry.focus()

    def _show_cart_menu(self, event):
        row_id = self.cart_tree.identify_row(event.y)
        if row_id:
            self.cart_tree.selection_set(row_id)
            self.cart_menu.tk_popup(event.x_root, event.y_root)

    def remove_selected_cart_item(self):
        sel = self.cart_tree.selection()
        if not sel:
            return
        idx = self.cart_tree.index(sel[0])
        if 0 <= idx < len(self.cart_items):
            del self.cart_items[idx]
        self.refresh_cart_display()

    def clear_cart(self):
        if not self.cart_items:
            return
        if messagebox.askyesno("Clear cart", "Remove all items from the cart?"):
            self.cart_items = []
            self.refresh_cart_display()

    def refresh_cart_display(self):
        for row in self.cart_tree.get_children():
            self.cart_tree.delete(row)

        total = 0
        for item in self.cart_items:
            subtotal = item["qty"] * item["price"]
            total += subtotal
            self.cart_tree.insert(
                "", "end",
                values=(item.get("code") or item["barcode"],
                        item["name"], item["qty"], item["price"], f"{subtotal:.2f}")
            )

        self.total_var.set(f"Total: {total:.2f}")

    # ---------- Payment dialog ----------

    def open_payment_dialog(self):
        if not self.cart_items:
            messagebox.showinfo("Empty Cart", "Cart is empty — nothing to checkout")
            return

        cashier = self.cashier_var.get().strip()
        if not cashier:
            messagebox.showwarning("Cashier Name Required",
                                   "Please enter the cashier's name before checkout")
            return

        total = sum(item["qty"] * item["price"] for item in self.cart_items)

        dialog = tk.Toplevel(self)
        dialog.title("Payment Method")
        dialog.geometry("340x380")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text="Select Payment Method",
                  font=("Arial", 12, "bold")).pack(pady=10)
        ttk.Label(dialog, text=f"Total Due: {total:.2f}",
                  font=("Arial", 11, "bold")).pack(pady=(0, 10))

        payment_method = tk.StringVar(value="Cash")

        ttk.Radiobutton(dialog, text="Cash", variable=payment_method, value="Cash",
                        command=lambda: toggle_fields()).pack(anchor="w", padx=30, pady=3)
        ttk.Radiobutton(dialog, text="Till Number", variable=payment_method, value="Till Number",
                        command=lambda: toggle_fields()).pack(anchor="w", padx=30, pady=3)
        ttk.Radiobutton(dialog, text="Phone (STK Push)", variable=payment_method, value="STK Push",
                        command=lambda: toggle_fields()).pack(anchor="w", padx=30, pady=3)

        cash_frame = ttk.Frame(dialog)
        cash_label = ttk.Label(cash_frame, text="Amount Received:")
        cash_var = tk.StringVar()
        cash_entry = ttk.Entry(cash_frame, textvariable=cash_var, width=15)

        change_var = tk.StringVar(value="Change: 0.00")
        change_label = ttk.Label(dialog, textvariable=change_var,
                                 font=("Arial", 10, "bold"))

        def update_change(*args):
            try:
                received = float(cash_var.get())
                change = received - total
                change_var.set(f"Change: {change:.2f}" if change >= 0 else "Change: (insufficient)")
            except ValueError:
                change_var.set("Change: 0.00")

        cash_var.trace_add("write", update_change)

        phone_frame = ttk.Frame(dialog)
        phone_label = ttk.Label(phone_frame, text="Phone Number:")
        phone_var = tk.StringVar()
        phone_entry = ttk.Entry(phone_frame, textvariable=phone_var, width=20)

        def toggle_fields():
            cash_frame.pack_forget()
            change_label.pack_forget()
            phone_frame.pack_forget()

            if payment_method.get() == "Cash":
                cash_frame.pack(pady=(10, 0))
                cash_label.pack(side="left", padx=5)
                cash_entry.pack(side="left")
                change_label.pack(pady=5)
            elif payment_method.get() == "STK Push":
                phone_frame.pack(pady=10)
                phone_label.pack(side="left", padx=5)
                phone_entry.pack(side="left")

        toggle_fields()

        def confirm():
            method = payment_method.get()
            phone = phone_var.get().strip()
            amount_received = None

            if method == "Cash":
                try:
                    amount_received = float(cash_var.get())
                except ValueError:
                    messagebox.showwarning("Amount Required",
                                           "Please enter a valid amount received")
                    return
                if amount_received < total:
                    messagebox.showwarning("Insufficient Amount",
                                           "Amount received is less than the total due")
                    return

            if method == "STK Push" and not phone:
                messagebox.showwarning("Phone Required",
                                       "Please enter a phone number for STK Push")
                return

            dialog.destroy()
            self.checkout(cashier, method, phone, amount_received)

        def cancel():
            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)
        ttk.Button(button_frame, text="Confirm", command=confirm).pack(side="left", padx=10)
        ttk.Button(button_frame, text="Cancel", command=cancel).pack(side="left", padx=10)

    # ---------- Checkout ----------

    def checkout(self, cashier, payment_method, phone="", amount_received=None):
        # Re-check stock against the server right before committing, so a
        # stale cache can't cause us to oversell. If the server says no,
        # the sale is rejected as a whole - nothing is written.
        try:
            r = requests.get(f"{SERVER}/products", timeout=4)
            fresh_products = r.json()
            self.products_cache = fresh_products
        except Exception as e:
            messagebox.showerror("Error", f"Could not reach server: {e}\nSale NOT completed.")
            return

        by_id = {p["id"]: p for p in fresh_products}
        for item in self.cart_items:
            p = by_id.get(item["product_id"])
            if p is None:
                messagebox.showerror(
                    "Product Missing",
                    f"'{item['name']}' no longer exists on the server. Sale cancelled.")
                return
            if p["stock"] < item["qty"]:
                messagebox.showerror(
                    "Not Enough Stock",
                    f"'{item['name']}' only has {p['stock']} in stock. "
                    f"Cart wanted {item['qty']}. Sale cancelled.")
                return

        payload = {
            "cashier": cashier,
            "payment_method": payment_method,
            "phone": phone,
            "amount_received": amount_received,
            "items": [
                {
                    "product_id": item["product_id"],
                    "quantity": item["qty"],
                    "price_each": item["price"],
                }
                for item in self.cart_items
            ],
        }

        # Snapshot the cart for the receipt (cart_items is cleared on success).
        snapshot_items = [dict(it) for it in self.cart_items]

        try:
            r = requests.post(f"{SERVER}/sales", json=payload, timeout=6)
        except Exception as e:
            messagebox.showerror("Error",
                                 f"Could not reach server: {e}\nCart has NOT been cleared.")
            return

        if r.status_code == 201:
            result = r.json()
            self.last_sale = {
                "sale_id": result["sale_id"],
                "total": result["total"],
                "date": result.get("date"),
                "cashier": cashier,
                "payment_method": payment_method,
                "phone": phone,
                "amount_received": amount_received,
                "items": snapshot_items,
            }
            self.show_receipt(self.last_sale)
            self.cart_items = []
            self.refresh_cart_display()
            self.refresh_products_cache()
        elif r.status_code == 409:
            # Server rejected: not enough stock on at least one line.
            try:
                msg = r.json().get("message", r.text)
            except Exception:
                msg = r.text
            messagebox.showerror("Out of Stock", msg)
            self.refresh_products_cache()
        else:
            try:
                msg = r.json().get("message", r.text)
            except Exception:
                msg = r.text
            messagebox.showerror("Checkout Failed", msg)

    # ---------- Receipt ----------

    def _build_receipt_text(self, sale):
        items = sale["items"]
        total = sale["total"]
        cashier = sale["cashier"]
        method = sale["payment_method"]
        phone = sale.get("phone") or ""
        amount_received = sale.get("amount_received")
        sale_id = sale["sale_id"]

        now = datetime.datetime.now()
        day_name = now.strftime("%A")
        date_str = now.strftime("%d/%m/%Y")
        time_str = now.strftime("%I:%M %p")

        lines = []
        lines.append("     ELECTRONICS SHOP")
        lines.append(f"     Sale #{sale_id}")
        lines.append("-" * 35)
        lines.append(f"Cashier: {cashier}")
        lines.append(f"{day_name}, {date_str}  {time_str}")
        lines.append("-" * 35)
        lines.append(f"{'Item':<18}{'Qty':>4}{'Amt':>10}")
        lines.append("-" * 35)
        for item in items:
            subtotal = item["qty"] * item["price"]
            name = item["name"][:16]
            lines.append(f"{name:<18}{item['qty']:>4}{subtotal:>10.2f}")
        lines.append("-" * 35)
        lines.append(f"{'TOTAL':<22}{total:>10.2f}")
        lines.append("-" * 35)
        lines.append(f"Payment: {method}")
        if method == "Cash" and amount_received is not None:
            change = amount_received - total
            lines.append(f"Amount Received: {amount_received:.2f}")
            lines.append(f"Change: {change:.2f}")
        if method == "STK Push" and phone:
            lines.append(f"Phone: {phone}")
        lines.append("-" * 35)
        lines.append("")
        lines.append("  Thank you for shopping with us!")
        lines.append("  Follow us for the latest deals")
        lines.append("  on phones & accessories!")
        return "\n".join(lines)

    def show_receipt(self, sale):
        receipt = tk.Toplevel(self)
        receipt.title(f"Receipt - Sale #{sale['sale_id']}")
        receipt.geometry("380x600")
        receipt.transient(self)

        text = tk.Text(receipt, font=("Consolas", 10))
        text.pack(fill="both", expand=True, padx=10, pady=10)
        text.insert("end", self._build_receipt_text(sale))
        text.config(state="disabled")

        btns = ttk.Frame(receipt)
        btns.pack(fill="x", pady=10)

        ttk.Button(btns, text="Close", command=receipt.destroy).pack(side="right", padx=10)
        ttk.Button(btns, text="Print", command=lambda: self._print_receipt(sale)).pack(side="right")

    def _print_receipt(self, sale):
        text = self._build_receipt_text(sale)
        try:
            tmp_dir = tempfile.gettempdir()
            path = os.path.join(tmp_dir, f"receipt_{sale['sale_id']}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            messagebox.showerror("Print failed", f"Could not write temp receipt:\n{e}")
            return

        try:
            if sys.platform.startswith("win"):
                os.startfile(path, "print")
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "TextEdit", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror(
                "Print failed",
                f"Could not open the print dialog automatically:\n{e}\n\n"
                f"Receipt saved to:\n{path}")


if __name__ == "__main__":
    FrontOffice().mainloop()