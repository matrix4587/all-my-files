"""
Main BackOffice class.

Assembles every mixin into a single class, sets up the ribbon UI and
shared state (SERVER URL, products cache, session caches), and provides
the small utility methods used everywhere.

Role-based access:
    self.can(action) checks whether the logged-in user has permission
    for `action`. Ribbon buttons, tabs, and dialogs are wrapped in
    `if self.can(...):` so unpermitted controls are simply not drawn.

Role order: staff < supervisor < manager < admin.

Server-side enforcement is separate — see _require_role() in server.py.
"""

import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from common.center import center_window_on_screen, install_centering_hook
from common.icons import load_icon, make_button_icon
from common.titlebar import apply_green_titlebar, install_green_titlebar_hook
from common.paths import APP_DIR

from backoffice.admin_auth import AdminAuthMixin
from backoffice.grn_receive import GrnReceiveMixin
from backoffice.grns import GrnsMixin
from backoffice.helpers import HelpersMixin
from backoffice.labels import LabelsMixin
from backoffice.new_item import NewItemMixin
from backoffice.orders import OrdersMixin
from backoffice.products import ProductsMixin
from backoffice.stocks import StocksMixin
from backoffice.stub_screens import StubScreensMixin
from backoffice.summaries import SummariesMixin
from backoffice.window_manager import WindowManagerMixin


# ---------------------------------------------------------------------------
# Role -> permitted actions
# ---------------------------------------------------------------------------

ROLE_RANK = {
    "staff": 1,
    "supervisor": 2,
    "manager": 3,
    "admin": 4,
}

# Named actions and the minimum role they require.
ACTION_MIN_ROLE = {
    # Viewing / reading — everyone
    "view_stocks":              "staff",
    "view_products":            "staff",
    "view_orders":              "staff",
    "view_reports":             "staff",
    "view_shelfs":              "staff",
    "view_labels":              "staff",

    # Day-to-day operations — staff
    "create_lpo":               "staff",
    "receive_grn":              "staff",
    "receive_crn":              "staff",
    "print_lpo":                "staff",
    "print_grn":                "staff",
    "print_crn":                "staff",

    # New Item / product editing — manager
    "new_item":                 "manager",
    "products_edit":            "manager",

    # Admin-only
    "approve_lpo":              "admin",
    "post_crn":                 "admin",
    "launch_admin_panel":       "admin",
    "manage_users":             "admin",
}


class BackOffice(
    HelpersMixin,
    WindowManagerMixin,
    AdminAuthMixin,
    StocksMixin,
    GrnReceiveMixin,
    SummariesMixin,
    ProductsMixin,
    LabelsMixin,
    GrnsMixin,
    NewItemMixin,
    OrdersMixin,
    StubScreensMixin,
    tk.Tk,
):
    RIBBON_BG = "#a9c9a4"

    SERVER = "http://localhost:5000"
    SHOP_NAME = "Evans Shop"
    APP_DIR = APP_DIR

    SUBWINDOW_WIDTH = 750
    SUBWINDOW_HEIGHT = 450

    RIBBON_ICON_SIZE = 24

    def __init__(self):
        install_green_titlebar_hook()
        install_centering_hook()

        super().__init__()
        self.title("Back Office - Electronics Shop")
        self.minsize(800, 500)

        # ---- Session state ----
        self.last_sale_id_seen = 0
        self.products_cache = []
        self.open_windows = {}
        self.window_groups = {}
        self.current_group = None
        self.admin_credentials = None
        self.known_departments = set()

        # ---- Logged-in user ----
        self.current_user = {
            "username": None,
            "full_name": None,
            "branch": None,
            "role": "staff",
            "kind": "user",
        }

        # ---- Orders state ----
        self._po_order_ids = {}
        self.order_lines = []
        self.order_printer_name = None

        # ---- Flag guards ----
        self._stock_filter_after_id = None
        self._product_filter_after_id = None

        self._grn_code_normalizing = False
        self._stock_code_normalizing = False
        self._product_code_normalizing = False

        self._reclamping = False
        self._main_configuring = False

        # ---- Label screen state ----
        self.label_mode_var = None
        self.label_mode_buttons = {}
        self.label_printer_name = None
        self._label_code_normalizing = False
        self._label_bottom_built = False
        self._label_current_area = None
        self._label_win = None
        self._label_body = None

        # ---- Icons ----
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

        def _small(photo):
            if photo is None:
                return photo
            try:
                factor = max(1, photo.width() // self.RIBBON_ICON_SIZE)
                if factor <= 1:
                    return photo
                return photo.subsample(factor, factor)
            except Exception:
                return photo

        self.button_icon_stock     = make_button_icon(_small(self.icon_stock))
        self.button_icon_products  = make_button_icon(_small(self.icon_products))
        self.button_icon_labels    = make_button_icon(_small(self.icon_labels))
        self.button_icon_purchase  = make_button_icon(_small(self.icon_purchase))
        self.button_icon_orders    = make_button_icon(_small(self.icon_orders))
        self.button_icon_inventory = make_button_icon(_small(self.icon_inventory))
        self.button_icon_pos       = make_button_icon(_small(self.icon_pos))
        self.button_icon_shelfs    = make_button_icon(_small(self.icon_shelfs))
        self.button_icon_grn       = make_button_icon(_small(self.icon_grn))
        self.button_icon_crn       = make_button_icon(_small(self.icon_crn))

        # ---- Style + ribbon layout ----
        self.setup_dark_style()

        top_ribbon = ttk.Frame(self, style="Ribbon.TFrame")
        top_ribbon.pack(fill="x", padx=5, pady=2)

        # Top ribbon is visible to all roles — it only shows groups the
        # user can reach, and the sub-ribbon further filters.
        ttk.Button(top_ribbon, text="Inventory", image=self.button_icon_inventory,
                   compound="top",
                   command=self.show_inventory_ribbon).pack(side="left", padx=2)
        ttk.Button(top_ribbon, text="Purchase", image=self.button_icon_purchase,
                   compound="top",
                   command=self.show_purchase_ribbon).pack(side="left", padx=2)
        ttk.Button(top_ribbon, text="Orders", image=self.button_icon_orders,
                   compound="top",
                   command=self.show_orders_ribbon).pack(side="left", padx=2)
        ttk.Button(top_ribbon, text="POS", image=self.button_icon_pos,
                   compound="top",
                   command=self.show_pos_ribbon).pack(side="left", padx=2)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        self.sub_ribbon = ttk.Frame(self, style="Ribbon.TFrame")
        self.sub_ribbon.pack(fill="x", padx=5, pady=2)

        ttk.Separator(self, orient="horizontal").pack(fill="x")

        # ---- Status line ----
        self.user_status_var = tk.StringVar(value="Not signed in")
        status_bar = tk.Frame(self, bg="#d4e6d4")
        status_bar.pack(fill="x", side="bottom")
        tk.Label(status_bar, textvariable=self.user_status_var,
                 bg="#d4e6d4", fg="#1f3d1f",
                 font=("Arial", 9), anchor="w").pack(
            side="left", padx=10, pady=3)

        # ---- Cache and periodic refresh ----
        self.refresh_products_cache()
        self.periodic_cache_refresh()

        # ---- Maximize immediately ----
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                w = self.winfo_screenwidth()
                h = self.winfo_screenheight()
                self.geometry(f"{w}x{h}+0+0")
            except tk.TclError:
                pass

        # ---- Window behaviour ----
        self.after(50, self.maximize_main_window)
        self.after(200, lambda: apply_green_titlebar(self))
        self.bind("<Configure>", self.on_main_configure, add="+")
        self.bind("<FocusIn>", self.raise_all_subwindows, add="+")

        self._update_user_status()

    # ---------------------------------------------------- Permissions

    def _current_role(self):
        u = getattr(self, "current_user", None) or {}
        if (u.get("kind") or "user") == "admin":
            return "admin"
        r = (u.get("role") or "staff").lower()
        if r not in ROLE_RANK:
            return "staff"
        return r

    def can(self, action):
        """Return True if the current user is allowed to perform `action`."""
        need = ACTION_MIN_ROLE.get(action)
        if need is None:
            # Unknown actions are treated as staff-visible by default.
            need = "staff"
        have = self._current_role()
        return ROLE_RANK.get(have, 0) >= ROLE_RANK.get(need, 0)

    # ---------------------------------------------------- Status line

    def _update_user_status(self):
        if not hasattr(self, "user_status_var"):
            return
        u = getattr(self, "current_user", None) or {}
        username = u.get("username")
        if not username:
            self.user_status_var.set("Not signed in")
            return
        full_name = u.get("full_name") or username
        branch = u.get("branch") or "-"
        role = self._current_role().capitalize()
        self.user_status_var.set(
            f"Signed in: {full_name}   ·   Branch: {branch}   ·   Role: {role}")

    # ---------------------------------------------------- Ribbon setup

    def show_inventory_ribbon(self):
        self.clear_sub_ribbon()

        if self.can("view_stocks"):
            ttk.Button(self.sub_ribbon, text="Stocks",
                       image=self.button_icon_stock,
                       compound="top", command=self.build_stocks_content
                       ).pack(side="left", padx=2)

        if self.can("view_products"):
            ttk.Button(self.sub_ribbon, text="Products",
                       image=self.button_icon_products,
                       compound="top", command=self.build_products_content
                       ).pack(side="left", padx=2)

        if self.can("view_labels"):
            ttk.Button(self.sub_ribbon, text="Labels",
                       image=self.button_icon_labels,
                       compound="top", command=self.build_labels_content
                       ).pack(side="left", padx=2)

        if self.can("view_shelfs"):
            ttk.Button(self.sub_ribbon, text="Shelfs",
                       image=self.button_icon_shelfs,
                       compound="top", command=self.build_shelfs_content
                       ).pack(side="left", padx=2)

        if self.can("launch_admin_panel"):
            ttk.Button(self.sub_ribbon, text="Admin Panel",
                       compound="top", command=self.open_admin_panel
                       ).pack(side="left", padx=2)

        self.switch_group("inventory")

    def show_purchase_ribbon(self):
        self.clear_sub_ribbon()

        if self.can("receive_grn"):
            ttk.Button(self.sub_ribbon, text="GRNs",
                       image=self.button_icon_grn,
                       compound="top", command=self.build_grns_content
                       ).pack(side="left", padx=2)

        if self.can("receive_grn"):
            ttk.Button(self.sub_ribbon, text="GRN - Receive",
                       image=self.button_icon_grn,
                       compound="top", command=self.open_grn_window
                       ).pack(side="left", padx=2)

        if self.can("receive_crn"):
            ttk.Button(self.sub_ribbon, text="CRNs",
                       image=self.button_icon_crn,
                       compound="top", command=self.build_crns_content
                       ).pack(side="left", padx=2)

        if self.can("new_item"):
            ttk.Button(self.sub_ribbon, text="New Item",
                       image=self.button_icon_products,
                       compound="top", command=self.build_new_item_content
                       ).pack(side="left", padx=2)

        self.switch_group("purchase")

    def show_orders_ribbon(self):
        self.clear_sub_ribbon()
        self.switch_group("orders")
        self.build_orders_content()

    def show_pos_ribbon(self):
        self.clear_sub_ribbon()
        self.switch_group("pos")
        self.build_pos_content()

    def clear_sub_ribbon(self):
        for widget in self.sub_ribbon.winfo_children():
            widget.destroy()

    # ----------------------------------------------- Admin Panel launcher

    def open_admin_panel(self):
        if not self.can("launch_admin_panel"):
            self.message_error("Not allowed",
                               "Only admins can open the Admin Panel.")
            return
        panel_path = os.path.join(APP_DIR, "admin_panel.py")
        if not os.path.exists(panel_path):
            self.message_error("Missing file",
                               f"admin_panel.py not found at:\n{panel_path}")
            return
        try:
            subprocess.Popen([sys.executable, panel_path])
        except Exception as e:
            self.message_error("Error", f"Could not launch admin panel:\n{e}")

    # ------------------------------------------------ Window maximize

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

    # ----------------------------------------------------- Styling

    def setup_dark_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Treeview", background="black", foreground="white",
                        fieldbackground="black", bordercolor="black")
        style.configure("Dark.Treeview.Heading", background="#222222",
                        foreground="white")
        style.map("Dark.Treeview", background=[("selected", "#333333")])
        style.configure("Ribbon.TFrame", background=self.RIBBON_BG)

    # ------------------------------------------- Small message helpers

    def message_error(self, title, text, parent=None):
        messagebox.showerror(title, text, parent=parent or self)

    def message_info(self, title, text, parent=None):
        messagebox.showinfo(title, text, parent=parent or self)

    def message_warn(self, title, text, parent=None):
        messagebox.showwarning(title, text, parent=parent or self)

    def message_yesno(self, title, text, parent=None):
        return messagebox.askyesno(title, text, parent=parent or self)

    # ---------------------------------------- Open a file with OS

    def open_with_default_app(self, path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self.message_error("Could not open file",
                               f"Saved to:\n{path}\n\n"
                               f"But could not open it automatically:\n{e}")