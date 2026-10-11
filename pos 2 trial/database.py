import tkinter as tk
from tkinter import ttk, messagebox
from tkcalendar import DateEntry
import requests
import datetime
import threading
import os

SERVER = "http://localhost:5000"

# Icons live in the same folder as this script.
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Target pixel size (longest side) for ribbon icons - tiny, toolbar-style.
ICON_MAX_SIZE = 20

# Extra padding (px) added around each icon when it's placed on a white
# background for ribbon buttons - not used for window title-bar icons.
ICON_PADDING = 4
ICON_CANVAS_SIZE = ICON_MAX_SIZE + (ICON_PADDING * 2)


def load_icon(filename, max_size=ICON_MAX_SIZE):
    """Loads a PNG from the app's own directory and shrinks it down to a
    tiny icon (longest side <= max_size px) using Tk's built-in subsample,
    so no extra image library (e.g. Pillow) is required.
    Returns None (and prints a note) if the file is missing so a missing
    icon never crashes the app - the button just falls back to text-only."""
    path = os.path.join(APP_DIR, filename)
    try:
        img = tk.PhotoImage(file=path)
        longest_side = max(img.width(), img.height())
        if longest_side > max_size:
            factor = -(-longest_side // max_size)  # ceil division
            img = img.subsample(factor, factor)
        return img
    except Exception as e:
        print(f"Could not load icon '{filename}':", e)
        return None


def make_button_icon(icon, canvas_size=ICON_CANVAS_SIZE):
    """Takes an already-loaded icon and composites it, centered, onto a
    fixed-size white square. This is what gives every ribbon button icon
    the same white background and the same amount of padding around it,
    regardless of each source PNG's own shape or transparency. Window
    title-bar icons deliberately skip this and use the plain icon as-is."""
    if icon is None:
        return None
    try:
        canvas = tk.PhotoImage(width=canvas_size, height=canvas_size)
        canvas.put("white", to=(0, 0, canvas_size, canvas_size))

        icon_w, icon_h = icon.width(), icon.height()
        x = max(0, (canvas_size - icon_w) // 2)
        y = max(0, (canvas_size - icon_h) // 2)

        canvas.tk.call(canvas, "copy", icon, "-to", x, y, x + icon_w, y + icon_h,
                        "-compositingrule", "overlay")
        return canvas
    except Exception as e:
        print("Could not build padded button icon:", e)
        return icon


class BackOffice(tk.Tk):
    RIBBON_BG = "#a9c9a4"

    def __init__(self):
        super().__init__()
        self.title("Back Office - Electronics Shop")
        self.geometry("950x650")
        self.minsize(800, 500)
        self.configure(bg=self.RIBBON_BG)

        self.last_sale_id_seen = 0
        self.products_cache = []
        self.open_windows = {}
        self.window_groups = {}
        self.current_group = None

        self._stock_filter_after_id = None
        self._product_filter_after_id = None

        self._reclamping = False
        self._main_configuring = False

        self.icon_stock = load_icon("stock.png")
        self.icon_products = load_icon("products.png")
        self.icon_labels = load_icon("label.png")
        self.icon_purchase = load_icon("purchase.png")
        self.icon_orders = load_icon("orders.png")
        self.icon_inventory = load_icon("inventory.png")
        self.icon_pos = load_icon("pos.png")
        self.icon_shelfs = load_icon("shelfs.png")
        self.icon_grn = load_icon("grn.png")
        self.icon_crn = load_icon("crn.png")

        self.button_icon_stock = make_button_icon(self.icon_stock)
        self.button_icon_products = make_button_icon(self.icon_products)
        self.button_icon_labels = make_button_icon(self.icon_labels)
        self.button_icon_purchase = make_button_icon(self.icon_purchase)
        self.button_icon_orders = make_button_icon(self.icon_orders)
        self.button_icon_inventory = make_button_icon(self.icon_inventory)
        self.button_icon_pos = make_button_icon(self.icon_pos)
        self.button_icon_shelfs = make_button_icon(self.icon_shelfs)
        self.button_icon_grn = make_button_icon(self.icon_grn)
        self.button_icon_crn = make_button_icon(self.icon_crn)

        self.setup_dark_style()

        top_ribbon = ttk.Frame(self, style="Ribbon.TFrame")
        top_ribbon.pack(fill="x", padx=5, pady=5)

        ttk.Button(top_ribbon, text="Inventory", image=self.button_icon_inventory, compound="top",
                   command=self.show_inventory_ribbon).pack(side="left", padx=3)
        ttk.Button(top_ribbon, text="Purchase", image=self.button_icon_purchase, compound="top",
                   command=self.show_purchase_ribbon).pack(side="left", padx=3)
        ttk.Button(top_ribbon, text="Orders", image=self.button_icon_orders, compound="top",
                   command=self.show_orders_ribbon).pack(side="left", padx=3)
        ttk.Button(top_ribbon, text="POS", image=self.button_icon_pos, compound="top",
                   command=self.show_pos_ribbon).pack(side="left", padx=3)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        self.sub_ribbon = ttk.Frame(self, style="Ribbon.TFrame")
        self.sub_ribbon.pack(fill="x", padx=5, pady=5)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        self.refresh_products_cache()
        self.periodic_cache_refresh()

        self.after(50, self.maximize_main_window)
        self.bind("<Configure>", self.on_main_configure, add="+")
        self.bind("<FocusIn>", self.raise_all_subwindows, add="+")

    def raise_all_subwindows(self, event=None):
        if event is not None and event.widget != self:
            return
        for key, win in list(self.open_windows.items()):
            if win.winfo_exists() and self.window_groups.get(key) == self.current_group:
                win.lift()

    def switch_group(self, group):
        self.current_group = group
        for key, win in list(self.open_windows.items()):
            if not win.winfo_exists():
                continue
            if self.window_groups.get(key) == group:
                win.deiconify()
                win.lift()
            else:
                win.withdraw()

    def setup_dark_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("Dark.Treeview", background="black", foreground="white",
                         fieldbackground="black", bordercolor="black")
        style.configure("Dark.Treeview.Heading", background="#222222", foreground="white")
        style.map("Dark.Treeview", background=[("selected", "#333333")])

        style.configure("Ribbon.TFrame", background=self.RIBBON_BG)

    def maximize_main_window(self):
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                w = self.winfo_screenwidth()
                h = self.winfo_screenheight()
                self.geometry(f"{w}x{h}+0+0")
            except tk.TclError:
                pass

    def on_main_configure(self, event=None):
        if event is not None and event.widget != self:
            return
        if self._main_configuring:
            return
        self._main_configuring = True
        try:
            for win in list(self.open_windows.values()):
                if win.winfo_exists():
                    self.reclamp_window(win)
        finally:
            self._main_configuring = False

    def make_columns_responsive(self, win, tree, weights):
        columns = tree["columns"]
        total_weight = sum(weights)

        def resize(event=None):
            try:
                width = tree.winfo_width()
                if width <= 1:
                    return
                for col, w in zip(columns, weights):
                    tree.column(col, width=int(width * w / total_weight))
            except tk.TclError:
                pass

        win.bind("<Configure>", resize, add="+")
        win.after(100, resize)

    def reclamp_window(self, win):
        if self._reclamping:
            return
        try:
            main_x = self.winfo_x()
            main_y = self.winfo_y()
            main_w = self.winfo_width()
            main_h = self.winfo_height()
            min_y = self.sub_ribbon.winfo_rooty() + self.sub_ribbon.winfo_height() + 8
            max_x = main_x + main_w
            max_y = main_y + main_h

            x = win.winfo_x()
            y = win.winfo_y()
            w = win.winfo_width()
            h = win.winfo_height()

            new_w = min(w, main_w)
            new_h = min(h, max(150, max_y - min_y))

            new_x = x
            new_y = y

            if new_x < main_x:
                new_x = main_x
            if new_x + new_w > max_x:
                new_x = max_x - new_w
            if new_y < min_y:
                new_y = min_y
            if new_y + new_h > max_y:
                new_y = max_y - new_h
            if new_y < min_y:
                new_y = min_y

            if (new_x, new_y, new_w, new_h) != (x, y, w, h):
                self._reclamping = True
                try:
                    win.geometry(f"{new_w}x{new_h}+{new_x}+{new_y}")
                    win.update_idletasks()
                finally:
                    self._reclamping = False
        except tk.TclError:
            pass

    def constrain_window_to_main(self, win):
        def clamp(event=None):
            if event is not None and event.widget != win:
                return
            self.reclamp_window(win)

        win.bind("<Configure>", clamp, add="+")

    def refresh_products_cache(self):
        def worker():
            try:
                r = requests.get(f"{SERVER}/products", timeout=3)
                data = r.json()
            except Exception as e:
                print("Could not refresh product cache:", e)
                return
            self.after(0, lambda: self._apply_products_cache(data))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_products_cache(self, data):
        self.products_cache = data

    def periodic_cache_refresh(self):
        self.refresh_products_cache()
        self.after(5000, self.periodic_cache_refresh)

    def find_product_by_code(self, code):
        if not code:
            return None
        return next((p for p in self.products_cache if str(p.get("barcode", "")) == code), None)

    def clear_sub_ribbon(self):
        for widget in self.sub_ribbon.winfo_children():
            widget.destroy()

    SUBWINDOW_WIDTH = 750
    SUBWINDOW_HEIGHT = 450

    def open_content_window(self, key, title, group=None, icon=None):
        self.window_groups[key] = group

        existing = self.open_windows.get(key)
        if existing is not None and existing.winfo_exists():
            existing.deiconify()
            existing.lift()
            existing.focus_force()
            return None

        self.update_idletasks()

        main_x = self.winfo_x()
        main_y = self.winfo_y()
        main_w = self.winfo_width()
        main_h = self.winfo_height()

        x = main_x
        y = self.sub_ribbon.winfo_rooty() + self.sub_ribbon.winfo_height() + 8

        width = min(self.SUBWINDOW_WIDTH, main_w)
        height = min(self.SUBWINDOW_HEIGHT, max(300, (main_y + main_h) - y))

        win = tk.Toplevel(self)
        win.title(title)
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.resizable(True, True)
        win.minsize(700, 400)

        if icon is not None:
            try:
                win.iconphoto(False, icon)
            except Exception as e:
                print("Could not set window icon:", e)

        self.constrain_window_to_main(win)

        def on_close():
            if key in self.open_windows:
                del self.open_windows[key]
            self.window_groups.pop(key, None)
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)

        self.open_windows[key] = win
        return win

    def show_inventory_ribbon(self):
        self.clear_sub_ribbon()
        ttk.Button(self.sub_ribbon, text="Stocks", image=self.button_icon_stock,
                   compound="top", command=self.build_stocks_content).pack(side="left", padx=3)
        ttk.Button(self.sub_ribbon, text="Products", image=self.button_icon_products,
                   compound="top", command=self.build_products_content).pack(side="left", padx=3)
        ttk.Button(self.sub_ribbon, text="Labels", image=self.button_icon_labels,
                   compound="top", command=self.build_labels_content).pack(side="left", padx=3)
        ttk.Button(self.sub_ribbon, text="Shelfs", image=self.button_icon_shelfs,
                   compound="top", command=self.build_shelfs_content).pack(side="left", padx=3)
        self.switch_group("inventory")

    def show_purchase_ribbon(self):
        self.clear_sub_ribbon()
        ttk.Button(self.sub_ribbon, text="GRNs", image=self.button_icon_grn,
                   compound="top", command=self.build_grns_content).pack(side="left", padx=3)
        ttk.Button(self.sub_ribbon, text="CRNs", image=self.button_icon_crn,
                   compound="top", command=self.build_crns_content).pack(side="left", padx=3)
        self.switch_group("purchase")

    def show_orders_ribbon(self):
        self.clear_sub_ribbon()
        self.switch_group("orders")
        self.build_orders_content()

    def show_pos_ribbon(self):
        self.clear_sub_ribbon()
        self.switch_group("pos")
        self.build_pos_content()

    def build_stocks_content(self):
        win = self.open_content_window("stocks", "Stocks", group="inventory", icon=self.icon_stock)
        if win is None:
            return

        top_button_frame = ttk.Frame(win)
        top_button_frame.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Button(top_button_frame, text="Stock List", command=self.open_stock_list_window).pack(side="left")

        filter_frame = ttk.Frame(win)
        filter_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(filter_frame, text="Code:").pack(side="left", padx=(0, 2))
        self.stock_code_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=self.stock_code_var, width=12).pack(side="left", padx=(0, 10))

        date_frame = ttk.Frame(filter_frame)
        date_frame.pack(side="right", padx=(10, 0))

        ttk.Label(date_frame, text="From:").pack(side="left", padx=(0, 2))
        self.stock_from_var = tk.StringVar()
        self.from_date_picker = DateEntry(
            date_frame, width=11, date_pattern="yyyy-mm-dd",
            textvariable=self.stock_from_var, showweeknumbers=False
        )
        self.from_date_picker.pack(side="left", padx=(0, 10))
        self.from_date_picker.bind("<<DateEntrySelected>>", self.on_stock_filter_change)

        ttk.Label(date_frame, text="To:").pack(side="left", padx=(0, 2))
        self.stock_to_var = tk.StringVar()
        self.to_date_picker = DateEntry(
            date_frame, width=11, date_pattern="yyyy-mm-dd",
            textvariable=self.stock_to_var, showweeknumbers=False
        )
        self.to_date_picker.pack(side="left")
        self.to_date_picker.bind("<<DateEntrySelected>>", self.on_stock_filter_change)

        today = datetime.date.today()
        yesterday = today - datetime.timedelta(days=1)
        self.from_date_picker.set_date(yesterday)
        self.to_date_picker.set_date(today)

        ttk.Label(filter_frame, text="Desc:").pack(side="left", padx=(0, 2))
        self.matched_desc_var = tk.StringVar(value="-")
        ttk.Label(filter_frame, textvariable=self.matched_desc_var,
                  relief="sunken", background="white", foreground="#006600",
                  anchor="w").pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.stock_code_var.trace_add("write", self.on_stock_filter_change)

        history_frame = ttk.LabelFrame(win, text="Stock Movement History")
        history_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.stock_history_tree = ttk.Treeview(
            history_frame,
            columns=("date", "type", "in", "out", "balance"),
            show="headings",
            style="Dark.Treeview"
        )
        self.stock_history_tree.heading("date", text="Date")
        self.stock_history_tree.heading("type", text="Type")
        self.stock_history_tree.heading("in", text="Stock In")
        self.stock_history_tree.heading("out", text="Stock Out")
        self.stock_history_tree.heading("balance", text="Balance")
        self.stock_history_tree.pack(fill="both", expand=True, padx=5, pady=5)

        self.make_columns_responsive(win, self.stock_history_tree, [2, 1, 1, 1, 1])

        balance_frame = ttk.Frame(win)
        balance_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.live_balance_var = tk.StringVar(value="Bal: -")
        bal_button = tk.Label(
            balance_frame, textvariable=self.live_balance_var,
            font=("Arial", 12, "bold"), bg="#e8a0a0", fg="black",
            relief="raised", bd=2, padx=14, pady=4
        )
        bal_button.pack(side="right")

        self.on_stock_filter_change()

    def on_stock_filter_change(self, *args):
        self.update_live_balance()

        if self._stock_filter_after_id is not None:
            try:
                self.after_cancel(self._stock_filter_after_id)
            except (ValueError, tk.TclError):
                pass
            self._stock_filter_after_id = None

        code = self.stock_code_var.get().strip()
        from_date = self.stock_from_var.get().strip()
        to_date = self.stock_to_var.get().strip()

        if code or from_date or to_date:
            self._stock_filter_after_id = self.after(300, self.search_stock_history)
        else:
            if hasattr(self, "stock_history_tree") and self.stock_history_tree.winfo_exists():
                for row in self.stock_history_tree.get_children():
                    self.stock_history_tree.delete(row)

    def update_live_balance(self, *args):
        if not hasattr(self, "live_balance_var"):
            return
        try:
            code = self.stock_code_var.get().strip()
        except tk.TclError:
            return

        if not code:
            self.live_balance_var.set("Bal: -")
            self.matched_desc_var.set("-")
            return

        match = self.find_product_by_code(code)
        if match:
            self.live_balance_var.set(f"Bal: {match['stock']}")
            self.matched_desc_var.set(match["name"])
        else:
            self.live_balance_var.set("Bal: not found")
            self.matched_desc_var.set("-")

    def search_stock_history(self):
        self._stock_filter_after_id = None

        if not hasattr(self, "stock_history_tree") or not self.stock_history_tree.winfo_exists():
            return

        params = {}
        code = self.stock_code_var.get().strip()
        from_date = self.stock_from_var.get().strip()
        to_date = self.stock_to_var.get().strip()

        if code:
            params["barcode"] = code
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date

        def worker():
            try:
                r = requests.get(f"{SERVER}/stock_ledger", params=params, timeout=3)
                rows = r.json()
            except Exception as e:
                print("Could not reach server:", e)
                return
            self.after(0, lambda: self._apply_stock_history(rows))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_stock_history(self, rows):
        if not hasattr(self, "stock_history_tree") or not self.stock_history_tree.winfo_exists():
            return
        for row in self.stock_history_tree.get_children():
            self.stock_history_tree.delete(row)
        for row in rows:
            self.stock_history_tree.insert(
                "", "end",
                values=(row["date"], row["transaction_type"],
                        row["stock_in"], row["stock_out"], row["balance"])
            )

    def open_stock_list_window(self):
        win = self.open_content_window("stock_list", "Stock List", group="inventory", icon=self.icon_stock)
        if win is None:
            return

        win.minsize(400, 300)

        filter_frame = ttk.Frame(win)
        filter_frame.pack(fill="x", padx=10, pady=10)
        ttk.Label(filter_frame, text="Filter (code or name):").pack(side="left")
        filter_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=filter_var, width=20).pack(side="left", padx=5)

        tree = ttk.Treeview(win, columns=("code", "desc", "stock"), show="headings")
        tree.heading("code", text="Code")
        tree.heading("desc", text="Description")
        tree.heading("stock", text="Current Stock")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        self.make_columns_responsive(win, tree, [1, 3, 1])

        after_id = {"id": None}

        def do_refresh():
            after_id["id"] = None
            query = filter_var.get().strip().lower()
            if not tree.winfo_exists():
                return
            for row in tree.get_children():
                tree.delete(row)
            if not query:
                return

            def worker():
                try:
                    r = requests.get(f"{SERVER}/products", timeout=3)
                    products = r.json()
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror("Error", f"Could not reach server: {e}"))
                    return

                def apply():
                    if not tree.winfo_exists():
                        return
                    for p in products:
                        if query in p["barcode"].lower() or query in p["name"].lower():
                            tree.insert("", "end", values=(p["barcode"], p["name"], p["stock"]))

                self.after(0, apply)

            threading.Thread(target=worker, daemon=True).start()

        def on_filter_change(*args):
            if after_id["id"] is not None:
                try:
                    win.after_cancel(after_id["id"])
                except (ValueError, tk.TclError):
                    pass
            after_id["id"] = win.after(300, do_refresh)

        filter_var.trace_add("write", on_filter_change)

    def build_products_content(self):
        win = self.open_content_window("products", "Products", group="inventory", icon=self.icon_products)
        if win is None:
            return

        top_button_frame = ttk.Frame(win)
        top_button_frame.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Button(top_button_frame, text="Product List", command=self.open_product_list_window).pack(side="left")

        header_frame = ttk.Frame(win)
        header_frame.pack(fill="x", padx=10, pady=10)

        code_desc_frame = ttk.LabelFrame(header_frame, text="")
        code_desc_frame.pack(side="left", fill="x", expand=True)

        ttk.Label(code_desc_frame, text="Code:").pack(side="left", padx=(5, 2), pady=5)
        self.product_code_var = tk.StringVar()
        ttk.Entry(code_desc_frame, textvariable=self.product_code_var, width=14).pack(side="left", padx=(0, 10), pady=5)

        ttk.Label(code_desc_frame, text="Description:").pack(side="left", padx=(0, 2))
        self.product_desc_var = tk.StringVar(value="-")
        ttk.Entry(code_desc_frame, textvariable=self.product_desc_var, width=28,
                  state="readonly").pack(side="left", fill="x", expand=True, padx=(0, 5), pady=5)

        department_frame = ttk.LabelFrame(header_frame, text="Department")
        department_frame.pack(side="left", padx=(15, 0))
        self.product_department_var = tk.StringVar(value="-")
        ttk.Entry(department_frame, textvariable=self.product_department_var, width=16,
                  state="readonly").pack(padx=8, pady=5)

        packaging_frame = ttk.Frame(win)
        packaging_frame.pack(fill="x", padx=10)
        ttk.Label(packaging_frame, text="Packaging:").pack(side="right", padx=(5, 5))
        self.product_packaging_var = tk.StringVar(value="-")
        ttk.Entry(packaging_frame, textvariable=self.product_packaging_var, width=16,
                  state="readonly").pack(side="right")

        pricing_frame = ttk.LabelFrame(win, text="Pricing (fed via GRN - read only here)")
        pricing_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(pricing_frame, text="Cost Price:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.product_cost_var = tk.StringVar(value="-")
        ttk.Entry(pricing_frame, textvariable=self.product_cost_var, width=12,
                  state="readonly").grid(row=0, column=1, sticky="w", padx=5, pady=5)

        ttk.Label(pricing_frame, text="Markup:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.product_markup_var = tk.StringVar(value="-")
        ttk.Entry(pricing_frame, textvariable=self.product_markup_var, width=12,
                  state="readonly").grid(row=1, column=1, sticky="w", padx=5, pady=5)

        ttk.Label(pricing_frame, text="Selling Price:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        self.product_selling_var = tk.StringVar(value="-")
        ttk.Entry(pricing_frame, textvariable=self.product_selling_var, width=12,
                  state="readonly").grid(row=2, column=1, sticky="w", padx=5, pady=5)

        button_frame = ttk.Frame(win)
        button_frame.pack(fill="x", padx=10, pady=(0, 5))

        ttk.Button(button_frame, text="Button A").pack(side="left", padx=3)
        ttk.Button(button_frame, text="Button B").pack(side="left", padx=3)
        ttk.Button(button_frame, text="Button C").pack(side="left", padx=3)
        ttk.Button(button_frame, text="Supplier", command=self.show_product_supplier).pack(side="left", padx=3)
        ttk.Button(button_frame, text="Shelf", command=self.show_product_shelf).pack(side="left", padx=3)

        self.product_lookup_result_var = tk.StringVar(value="")
        ttk.Label(win, textvariable=self.product_lookup_result_var,
                  foreground="#006600").pack(fill="x", padx=10, pady=(0, 10))

        self.product_code_var.trace_add("write", self.on_product_code_change)

    def on_product_code_change(self, *args):
        code = self.product_code_var.get().strip()
        self.product_lookup_result_var.set("")

        if not code:
            self.product_desc_var.set("-")
            self.product_department_var.set("-")
            self.product_packaging_var.set("-")
            self.product_cost_var.set("-")
            self.product_markup_var.set("-")
            self.product_selling_var.set("-")
            return

        match = self.find_product_by_code(code)
        if match:
            self.product_desc_var.set(match.get("name", "-"))
            self.product_department_var.set(match.get("category", "-"))
            self.product_packaging_var.set(match.get("packaging", "-"))
            self.product_cost_var.set(str(match.get("cost_price", match.get("price", "-"))))
            self.product_markup_var.set(str(match.get("markup", "-")))
            self.product_selling_var.set(str(match.get("selling_price", "-")))
        else:
            self.product_desc_var.set("Not found")
            self.product_department_var.set("-")
            self.product_packaging_var.set("-")
            self.product_cost_var.set("-")
            self.product_markup_var.set("-")
            self.product_selling_var.set("-")

    def show_product_supplier(self):
        code = self.product_code_var.get().strip()
        if not code:
            self.product_lookup_result_var.set("Enter a code first")
            return
        match = self.find_product_by_code(code)
        if not match:
            self.product_lookup_result_var.set(f"No product found for code '{code}'")
            return
        supplier = match.get("supplier", "Not set")
        self.product_lookup_result_var.set(f"Supplier: {supplier}")

    def show_product_shelf(self):
        code = self.product_code_var.get().strip()
        if not code:
            self.product_lookup_result_var.set("Enter a code first")
            return
        match = self.find_product_by_code(code)
        if not match:
            self.product_lookup_result_var.set(f"No product found for code '{code}'")
            return
        shelf = match.get("shelf", "Not set")
        self.product_lookup_result_var.set(f"Shelf: {shelf}")

    def open_product_list_window(self):
        win = self.open_content_window("product_list", "Product List", group="inventory", icon=self.icon_products)
        if win is None:
            return

        win.minsize(500, 350)

        filter_frame = ttk.Frame(win)
        filter_frame.pack(fill="x", padx=10, pady=10)
        ttk.Label(filter_frame, text="Quick Find (code or name):").pack(side="left")
        filter_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=filter_var, width=20).pack(side="left", padx=5)

        tree = ttk.Treeview(win, columns=("id", "name", "cat", "price", "stock", "barcode"), show="headings")
        for col in ("id", "name", "cat", "price", "stock", "barcode"):
            tree.heading(col, text=col.capitalize())
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        self.make_columns_responsive(win, tree, [1, 3, 2, 1, 1, 2])

        after_id = {"id": None}

        def do_refresh():
            after_id["id"] = None
            query = filter_var.get().strip().lower()
            if not tree.winfo_exists():
                return
            for row in tree.get_children():
                tree.delete(row)
            if not query:
                return

            def worker():
                try:
                    r = requests.get(f"{SERVER}/products", timeout=3)
                    products = r.json()
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror("Error", f"Could not reach server: {e}"))
                    return

                def apply():
                    if not tree.winfo_exists():
                        return
                    for p in products:
                        if query in p["barcode"].lower() or query in p["name"].lower():
                            tree.insert("", "end", values=(p["id"], p["name"], p["category"], p["price"], p["stock"], p["barcode"]))

                self.after(0, apply)

            threading.Thread(target=worker, daemon=True).start()

        def on_filter_change(*args):
            if after_id["id"] is not None:
                try:
                    win.after_cancel(after_id["id"])
                except (ValueError, tk.TclError):
                    pass
            after_id["id"] = win.after(300, do_refresh)

        filter_var.trace_add("write", on_filter_change)

    def build_labels_content(self):
        win = self.open_content_window("labels", "Labels", group="inventory", icon=self.icon_labels)
        if win is None:
            return
        ttk.Label(win, text="Labels — coming soon", font=("Arial", 14)).pack(pady=40)

    def build_shelfs_content(self):
        win = self.open_content_window("shelfs", "Shelfs", group="inventory", icon=self.icon_shelfs)
        if win is None:
            return
        ttk.Label(win, text="Shelfs — coming soon", font=("Arial", 14)).pack(pady=40)

    # ---------- Purchase > GRNs ----------
    # Layout (per latest request):
    #   Row 1: Code | Description (wide, stretches to fill) ... Quantity | Packaging (pushed to the far right)
    #   Row 2: Cost Price | Markup (+ % / Amount) | Selling Price - all in one row
    #   Row 3: Add | Delete
    #   Staged items table
    #   Bottom: Value of all delivery | Clear | RECEIVE (sends staged lines to
    #   the server - this is what actually adds them to system stock)

    def build_grns_content(self):
        win = self.open_content_window("grns", "GRNs", group="purchase", icon=self.icon_grn)
        if win is None:
            return

        self.grn_lines = []

        top_button_frame = ttk.Frame(win)
        top_button_frame.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Button(top_button_frame, text="GRN List", command=self.open_grn_list_window).pack(side="left")

        # --- Select Supplier ---
        supplier_frame = ttk.Frame(win)
        supplier_frame.pack(fill="x", padx=10, pady=(10, 0))
        ttk.Label(supplier_frame, text="Select Supplier:").pack(side="left", padx=(0, 5))
        self.grn_supplier_var = tk.StringVar()
        self.grn_supplier_combo = ttk.Combobox(supplier_frame, textvariable=self.grn_supplier_var, width=30)
        self.grn_supplier_combo.pack(side="left")
        self.fetch_grn_suppliers()

        # --- Row 1: Code | Description (wide) ... Quantity | Packaging (far right) ---
        line_frame = ttk.Frame(win)
        line_frame.pack(fill="x", padx=10, pady=10)

        # Quantity + Packaging built first and packed to the RIGHT, so
        # Description (packed after, with fill/expand) claims all the
        # remaining middle space - same trick used on the Stocks screen.
        qty_pack_frame = ttk.Frame(line_frame)
        qty_pack_frame.pack(side="right")

        ttk.Label(qty_pack_frame, text="Quantity:").grid(row=0, column=0, sticky="w", padx=(0, 2))
        ttk.Label(qty_pack_frame, text="Packaging:").grid(row=0, column=1, sticky="w", padx=(10, 2))

        self.grn_qty_var = tk.StringVar()
        self.grn_packaging_var = tk.StringVar()

        ttk.Entry(qty_pack_frame, textvariable=self.grn_qty_var, width=8).grid(row=1, column=0, sticky="w")
        self.grn_packaging_combo = ttk.Combobox(qty_pack_frame, textvariable=self.grn_packaging_var, width=16)
        self.grn_packaging_combo.grid(row=1, column=1, sticky="w", padx=(10, 0))

        # Code (fixed width, left)
        code_col = ttk.Frame(line_frame)
        code_col.pack(side="left", padx=(0, 10))
        ttk.Label(code_col, text="Code:").pack(anchor="w")
        self.grn_code_var = tk.StringVar()
        ttk.Entry(code_col, textvariable=self.grn_code_var, width=12).pack()

        # Description (expands into all remaining middle space, lengthened)
        desc_col = ttk.Frame(line_frame)
        desc_col.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ttk.Label(desc_col, text="Description:").pack(anchor="w")
        self.grn_desc_var = tk.StringVar(value="-")
        ttk.Entry(desc_col, textvariable=self.grn_desc_var, state="readonly").pack(fill="x", expand=True)

        # --- Row 2: Cost Price | Markup (+ % / Amount) | Selling Price, all together ---
        pricing_row = ttk.LabelFrame(win, text="Pricing")
        pricing_row.pack(fill="x", padx=10, pady=(0, 10))

        ttk.Label(pricing_row, text="Cost Price:").pack(side="left", padx=(8, 2), pady=8)
        self.grn_unit_cost_var = tk.StringVar()
        ttk.Entry(pricing_row, textvariable=self.grn_unit_cost_var, width=10).pack(side="left", padx=(0, 15))

        ttk.Label(pricing_row, text="Markup:").pack(side="left", padx=(0, 2))
        self.grn_markup_var = tk.StringVar()
        ttk.Entry(pricing_row, textvariable=self.grn_markup_var, width=8).pack(side="left", padx=(0, 5))
        self.grn_markup_type_var = tk.StringVar(value="%")
        ttk.Combobox(pricing_row, textvariable=self.grn_markup_type_var, values=["%", "Amount"],
                     width=7, state="readonly").pack(side="left", padx=(0, 15))

        ttk.Label(pricing_row, text="Selling Price:").pack(side="left", padx=(0, 2))
        self.grn_selling_var = tk.StringVar(value="-")
        ttk.Entry(pricing_row, textvariable=self.grn_selling_var, width=10,
                  state="readonly").pack(side="left", padx=(0, 8))

        # --- Row 3: Add | Delete ---
        action_row = ttk.Frame(win)
        action_row.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(action_row, text="Delete", command=self.remove_grn_line).pack(side="right", padx=(5, 0))
        ttk.Button(action_row, text="Add", command=self.add_grn_line).pack(side="right")

        self.grn_code_var.trace_add("write", self.on_grn_code_change)
        self.grn_unit_cost_var.trace_add("write", self.recompute_grn_selling_price)
        self.grn_markup_var.trace_add("write", self.recompute_grn_selling_price)
        self.grn_markup_type_var.trace_add("write", self.recompute_grn_selling_price)

        # --- Staged line items ---
        lines_frame = ttk.LabelFrame(win, text="Items fed but not yet added to system stock")
        lines_frame.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        self.grn_tree = ttk.Treeview(
            lines_frame, columns=("code", "desc", "qty", "cost", "total"), show="headings"
        )
        self.grn_tree.heading("code", text="Code")
        self.grn_tree.heading("desc", text="Description")
        self.grn_tree.heading("qty", text="Quantity")
        self.grn_tree.heading("cost", text="Cost")
        self.grn_tree.heading("total", text="Total")
        self.grn_tree.pack(fill="both", expand=True, padx=5, pady=5)

        self.make_columns_responsive(win, self.grn_tree, [2, 4, 1, 1, 1])

        # --- Bottom: Value of all delivery | Clear | RECEIVE ---
        bottom_frame = ttk.Frame(win)
        bottom_frame.pack(fill="x", padx=10, pady=10)

        self.grn_total_var = tk.StringVar(value="Value of all delivery: 0.00")
        total_label = tk.Label(
            bottom_frame, textvariable=self.grn_total_var,
            font=("Arial", 12, "bold"), bg="#e8a0a0", fg="black",
            relief="raised", bd=2, padx=14, pady=4
        )
        total_label.pack(side="left")

        # RECEIVE - the action that actually pushes staged lines to the
        # server, updating real system stock and product pricing.
        receive_button = tk.Label(
            bottom_frame, text="RECEIVE", font=("Arial", 11, "bold"),
            bg="#8fd08f", fg="black", relief="raised", bd=2, padx=16, pady=6,
            cursor="hand2"
        )
        receive_button.pack(side="right")
        receive_button.bind("<Button-1>", lambda e: self.receive_grn())

        ttk.Button(bottom_frame, text="Clear", command=self.clear_grn_form).pack(side="right", padx=(0, 10))

    def fetch_grn_suppliers(self):
        def worker():
            try:
                r = requests.get(f"{SERVER}/suppliers", timeout=3)
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

    def on_grn_code_change(self, *args):
        code = self.grn_code_var.get().strip()
        if not code:
            self.grn_desc_var.set("-")
            return

        match = self.find_product_by_code(code)
        if match:
            self.grn_desc_var.set(match["name"])

            packaging_options = []
            existing_packaging = match.get("packaging")
            if existing_packaging:
                packaging_options.append(existing_packaging)
            for generic in ("Loose", "Carton", "Box", "Pack"):
                if generic not in packaging_options:
                    packaging_options.append(generic)
            self.grn_packaging_combo["values"] = packaging_options
            if existing_packaging and not self.grn_packaging_var.get().strip():
                self.grn_packaging_var.set(existing_packaging)

            last_cost = match.get("cost_price", match.get("price"))
            if not self.grn_unit_cost_var.get().strip() and last_cost is not None:
                self.grn_unit_cost_var.set(str(last_cost))
        else:
            self.grn_desc_var.set("Not found")

    def recompute_grn_selling_price(self, *args):
        try:
            unit_cost = float(self.grn_unit_cost_var.get())
            markup = float(self.grn_markup_var.get())
        except ValueError:
            self.grn_selling_var.set("-")
            return

        if self.grn_markup_type_var.get() == "Amount":
            selling_price = unit_cost + markup
        else:
            selling_price = unit_cost + (unit_cost * markup / 100)

        self.grn_selling_var.set(f"{selling_price:.2f}")

    def add_grn_line(self):
        code = self.grn_code_var.get().strip()
        if not code:
            messagebox.showerror("Error", "Enter a product code")
            return

        match = self.find_product_by_code(code)
        if not match:
            messagebox.showerror("Error", f"No product found for code '{code}'")
            return

        try:
            qty = float(self.grn_qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a valid quantity greater than 0")
            return

        try:
            unit_cost = float(self.grn_unit_cost_var.get())
            if unit_cost < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a valid unit cost")
            return

        self.recompute_grn_selling_price()
        if self.grn_selling_var.get() == "-":
            messagebox.showerror("Error", "Enter a valid markup")
            return
        selling_price = float(self.grn_selling_var.get())

        packaging = self.grn_packaging_var.get().strip()
        markup = float(self.grn_markup_var.get())
        markup_type = self.grn_markup_type_var.get()
        line_total = qty * unit_cost

        self.grn_lines.append({
            "barcode": match["barcode"],
            "name": match["name"],
            "qty": qty,
            "packaging": packaging,
            "unit_cost": unit_cost,
            "markup": markup,
            "markup_type": markup_type,
            "selling_price": selling_price,
            "line_total": line_total,
        })

        self.grn_tree.insert(
            "", "end",
            values=(match["barcode"], match["name"], qty, f"{unit_cost:.2f}", f"{line_total:.2f}")
        )

        self.recompute_grn_total()

        self.grn_code_var.set("")
        self.grn_qty_var.set("")
        self.grn_packaging_var.set("")
        self.grn_unit_cost_var.set("")
        self.grn_markup_var.set("")
        self.grn_desc_var.set("-")
        self.grn_selling_var.set("-")

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
        self.grn_unit_cost_var.set("")
        self.grn_markup_var.set("")
        self.grn_desc_var.set("-")
        self.grn_selling_var.set("-")
        self.grn_supplier_var.set("")
        self.recompute_grn_total()

    def receive_grn(self):
        if not self.grn_lines:
            messagebox.showerror("Error", "Add at least one item before receiving")
            return

        supplier = self.grn_supplier_var.get().strip()
        if not supplier:
            messagebox.showerror("Error", "Select a supplier")
            return

        payload = {
            "supplier": supplier,
            "date": datetime.date.today().isoformat(),
            "lines": [
                {
                    "barcode": line["barcode"],
                    "qty": line["qty"],
                    "packaging": line["packaging"],
                    "unit_cost": line["unit_cost"],
                    "markup": line["markup"],
                    "markup_type": line["markup_type"],
                    "selling_price": line["selling_price"],
                }
                for line in self.grn_lines
            ],
        }

        def worker():
            try:
                r = requests.post(f"{SERVER}/grn", json=payload, timeout=5)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Could not reach server: {e}"))
                return

            def apply():
                if r.status_code in (200, 201):
                    messagebox.showinfo("Success", "Stock received and prices updated")
                    self.refresh_products_cache()
                    self.clear_grn_form()
                else:
                    messagebox.showerror("Error", r.text)

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def open_grn_list_window(self):
        win = self.open_content_window("grn_list", "GRN List", group="purchase", icon=self.icon_grn)
        if win is None:
            return

        win.minsize(400, 300)

        tree = ttk.Treeview(win, columns=("id", "supplier", "date", "total"), show="headings")
        tree.heading("id", text="GRN #")
        tree.heading("supplier", text="Supplier")
        tree.heading("date", text="Date")
        tree.heading("total", text="Total")
        tree.pack(fill="both", expand=True, padx=10, pady=10)

        self.make_columns_responsive(win, tree, [1, 3, 2, 1])

        def worker():
            try:
                r = requests.get(f"{SERVER}/grns", timeout=3)
                grns = r.json()
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Could not reach server: {e}"))
                return

            def apply():
                if not tree.winfo_exists():
                    return
                for g in grns:
                    tree.insert("", "end", values=(g.get("id"), g.get("supplier"), g.get("date"), g.get("total")))

            self.after(0, apply)

        threading.Thread(target=worker, daemon=True).start()

    def build_crns_content(self):
        win = self.open_content_window("crns", "CRNs", group="purchase", icon=self.icon_crn)
        if win is None:
            return
        ttk.Label(win, text="CRNs (Credit/Return Notes) — coming soon", font=("Arial", 14)).pack(pady=40)

    def build_orders_content(self):
        win = self.open_content_window("orders", "Orders", group="orders", icon=self.icon_orders)
        if win is None:
            return
        ttk.Label(win, text="Orders — coming soon", font=("Arial", 14)).pack(pady=40)

    def build_pos_content(self):
        win = self.open_content_window("pos", "POS - Live Sales Monitor", group="pos", icon=self.icon_pos)
        if win is None:
            return

        self.sales_list = tk.Listbox(win, font=("Consolas", 11))
        self.sales_list.pack(fill="both", expand=True, padx=10, pady=10)

        self.status_label = ttk.Label(win, text="Monitoring for new sales...")
        self.status_label.pack(pady=5)

        self.poll_sales()

    def poll_sales(self):
        if not hasattr(self, "status_label") or not self.status_label.winfo_exists():
            return

        def worker():
            try:
                r = requests.get(f"{SERVER}/sales", timeout=3)
                sales = r.json()
                error = None
            except Exception as e:
                sales = None
                error = e
            self.after(0, lambda: self._apply_sales_poll(sales, error))

        threading.Thread(target=worker, daemon=True).start()

        self.after(3000, self.poll_sales)

    def _apply_sales_poll(self, sales, error):
        if not hasattr(self, "status_label") or not self.status_label.winfo_exists():
            return

        if error is not None:
            self.status_label.config(text=f"Server not reachable: {error}")
            return

        new_sales = [s for s in sales if s["id"] > self.last_sale_id_seen]
        if new_sales:
            for s in reversed(new_sales):
                line = f"Sale #{s['id']}  |  Total: {s['total']}  |  {s['date']}"
                self.sales_list.insert(0, line)
            self.last_sale_id_seen = max(s["id"] for s in sales)
            self.status_label.config(text="Last update: new sale(s) detected!")
        else:
            self.status_label.config(text="Monitoring for new sales... (no changes)")


if __name__ == "__main__":
    BackOffice().mainloop()