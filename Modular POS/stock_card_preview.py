"""
Stock Card window - matches the Stock Controller layout.

Layout:
  - Top toolbar: two icon-ish buttons (Stock List, Stock Card)
  - Item Code entry + magnifier + yellow Description entry
  - Notebook: [Stock Card] [Serial Numbers]
      Stock Card tab:
        - Date filter row: from date, to date, filter button
        - Treeview: Stock Movement history
        - Two bottom panels: Stock Movement (7/14/30 days), Stock Position (Shelf/Storey/Global)
"""

import datetime
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

from common.center import center_window_on_screen


# ---- palette pulled from the screenshot -------------------------------
HEADER_BG      = "#c8d6e5"   # bluish header strip
PANEL_BG       = "#dfe6ee"   # light panel background
YELLOW_FIELD   = "#fdf5a0"   # description background
ROW_NORMAL     = "#eef2f7"
ROW_LIVE       = "#f5b7b1"   # reddish LIVE POS SALES
ROW_BAL        = "#eef2f7"
TITLEBAR_GREEN = "#1f6b2e"


class StockCardWindow(tk.Toplevel):
    """Standalone stock-card viewer."""

    def __init__(self, master, server=None, find_product_by_code=None,
                 icon_stock=None):
        super().__init__(master)
        self.SERVER = server
        self.find_product_by_code = find_product_by_code or (lambda c: None)

        self.title("Stock Controller")
        self.geometry("980x620")
        self.minsize(900, 560)
        self.configure(bg=PANEL_BG)

        try:
            from common.titlebar import apply_green_titlebar
            self.after(150, lambda w=self: apply_green_titlebar(w))
        except Exception:
            pass

        self._build_toolbar()
        self._build_item_row()
        self._build_tabs()
        self._build_stock_card_tab()

        # center after widgets exist
        self.after(50, lambda: center_window_on_screen(self, 980, 620))

    # ----------------------------------------------------------- toolbar
    def _build_toolbar(self):
        bar = tk.Frame(self, bg=HEADER_BG, height=64)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        # fake icon buttons using large emoji-ish glyphs + labels underneath
        def icon_button(parent, glyph, label, cmd=None):
            f = tk.Frame(parent, bg=HEADER_BG)
            f.pack(side="left", padx=(10, 4), pady=4)
            lbl_icon = tk.Label(f, text=glyph, bg=HEADER_BG,
                                font=("Segoe UI Emoji", 18))
            lbl_icon.pack()
            lbl_txt = tk.Label(f, text=label, bg=HEADER_BG,
                               font=("Arial", 8))
            lbl_txt.pack()
            for w in (f, lbl_icon, lbl_txt):
                w.bind("<Button-1>", lambda e, c=cmd: c() if c else None)
                w.configure(cursor="hand2")
            return f

        icon_button(bar, "\U0001F4CB", "Stock List",
                    cmd=lambda: self._show_placeholder("Stock List"))
        icon_button(bar, "\U0001F4DD", "Stck Card",   # exactly as in shot
                    cmd=lambda: self._show_placeholder("Stock Card"))

    # -------------------------------------------------- item code + desc
    def _build_item_row(self):
        row = tk.Frame(self, bg=PANEL_BG)
        row.pack(fill="x", padx=12, pady=(8, 4))

        tk.Label(row, text="Item Code", bg=PANEL_BG,
                 font=("Arial", 9)).grid(row=0, column=0, sticky="w")
        tk.Label(row, text="Description", bg=PANEL_BG,
                 font=("Arial", 9)).grid(row=0, column=2, sticky="w",
                                         padx=(14, 0))

        self.item_code_var = tk.StringVar(value="241600")
        self.item_desc_var = tk.StringVar(value="KASUKU FINE PEN-BLUE")

        code_entry = tk.Entry(row, textvariable=self.item_code_var,
                              width=14, font=("Arial", 10),
                              bg="#dbe9ff", relief="solid", bd=1)
        code_entry.grid(row=1, column=0, sticky="w", pady=(2, 0))

        mag = tk.Label(row, text="\U0001F50D", bg=PANEL_BG,
                       font=("Segoe UI Emoji", 14), cursor="hand2")
        mag.grid(row=1, column=1, padx=(4, 0))
        mag.bind("<Button-1>", lambda e: self._open_product_picker())

        desc_entry = tk.Entry(row, textvariable=self.item_desc_var,
                              font=("Arial", 10), bg=YELLOW_FIELD,
                              relief="solid", bd=1)
        desc_entry.grid(row=1, column=2, sticky="ew", padx=(14, 0),
                        pady=(2, 0))

        row.columnconfigure(2, weight=1)

        # live lookup as user types the code
        self.item_code_var.trace_add("write", self._on_code_change)

    # ---------------------------------------------------------- tabs
    def _build_tabs(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("Stock.TNotebook.Tab", padding=(14, 4),
                        font=("Arial", 9))
        self.nb = ttk.Notebook(self, style="Stock.TNotebook")
        self.nb.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self.tab_card = tk.Frame(self.nb, bg=PANEL_BG)
        self.tab_serial = tk.Frame(self.nb, bg=PANEL_BG)
        self.nb.add(self.tab_card, text="Stock Card")
        self.nb.add(self.tab_serial, text="Serial Numbers")

    # --------------------------------------------------- stock card tab
    def _build_stock_card_tab(self):
        parent = self.tab_card

        # ---- date filter row ----
        filt = tk.Frame(parent, bg=PANEL_BG)
        filt.pack(fill="x", padx=6, pady=(8, 4))

        today = datetime.date.today()
        week_ago = today - datetime.timedelta(days=1)

        self.from_date_var = tk.StringVar(
            value=week_ago.strftime("%d/%m/%Y"))
        self.to_date_var = tk.StringVar(
            value=today.strftime("%d/%m/%Y"))

        tk.Label(filt, text="Stock Movement history", bg=HEADER_BG,
                 font=("Arial", 9, "bold"), padx=8, pady=2
                 ).pack(side="left")

        # right-aligned controls
        right = tk.Frame(filt, bg=PANEL_BG)
        right.pack(side="right")
        tk.Entry(right, textvariable=self.from_date_var, width=11,
                 justify="center", relief="solid", bd=1).pack(side="left")
        tk.Label(right, text="to", bg=PANEL_BG).pack(side="left", padx=4)
        tk.Entry(right, textvariable=self.to_date_var, width=11,
                 justify="center", relief="solid", bd=1).pack(side="left")
        btn = tk.Label(right, text="\U0001F50D", bg=PANEL_BG,
                       font=("Segoe UI Emoji", 12), cursor="hand2")
        btn.pack(side="left", padx=(6, 0))
        btn.bind("<Button-1>", lambda e: self._reload_movements())

        # ---- movement tree ----
        cols = ("date", "trn", "doc", "unit", "in", "out", "bal")
        heads = {
            "date": "Date", "trn": "Trn Type", "doc": "Doc #",
            "unit": "Unit", "in": "In", "out": "Out", "bal": "Bal",
        }
        widths = {"date": 100, "trn": 170, "doc": 110, "unit": 70,
                  "in": 90, "out": 90, "bal": 90}

        wrap = tk.Frame(parent, bg=PANEL_BG)
        wrap.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        self.mv_tree = ttk.Treeview(wrap, columns=cols, show="headings",
                                    height=10)
        for c in cols:
            self.mv_tree.heading(c, text=heads[c])
            self.mv_tree.column(c, width=widths[c],
                                anchor="e" if c in ("in", "out", "bal")
                                else "w")
        # right-align numeric columns per screenshot
        for c in ("doc", "unit", "in", "out", "bal"):
            self.mv_tree.column(c, anchor="e")

        vsb = ttk.Scrollbar(wrap, orient="vertical",
                            command=self.mv_tree.yview)
        self.mv_tree.configure(yscrollcommand=vsb.set)

        self.mv_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # row tags for coloring
        self.mv_tree.tag_configure("live", background=ROW_LIVE,
                                   foreground="#7a1f1f")
        self.mv_tree.tag_configure("normal", background=ROW_NORMAL)

        # ---- bottom panels ----
        bottom = tk.Frame(parent, bg=PANEL_BG)
        bottom.pack(fill="x", padx=6, pady=(0, 8))

        self._build_stock_movement_panel(bottom)
        self._build_stock_position_panel(bottom)

    def _build_stock_movement_panel(self, parent):
        box = tk.LabelFrame(parent, text="Stock Movement",
                            bg=PANEL_BG, font=("Arial", 8, "bold"),
                            labelanchor="nw", bd=1, relief="solid")
        box.pack(side="left", fill="x", expand=True, padx=(0, 6))

        inner = tk.Frame(box, bg=HEADER_BG)
        inner.pack(fill="x", padx=6, pady=6)

        for i, label in enumerate(("7 Days", "14 Days", "30 Days")):
            tk.Label(inner, text=label, bg=HEADER_BG,
                     font=("Arial", 8, "bold")).grid(
                row=0, column=i, sticky="w", padx=6)
        self.d7_var = tk.StringVar(value="25 PCS")
        self.d14_var = tk.StringVar(value="91 PCS")
        self.d30_var = tk.StringVar(value="1478 PCS")
        for i, var in enumerate((self.d7_var, self.d14_var, self.d30_var)):
            tk.Label(inner, textvariable=var, bg=HEADER_BG,
                     font=("Arial", 9)).grid(
                row=1, column=i, sticky="w", padx=6)

    def _build_stock_position_panel(self, parent):
        box = tk.LabelFrame(parent, text="Stock Position",
                            bg=PANEL_BG, font=("Arial", 8, "bold"),
                            labelanchor="nw", bd=1, relief="solid")
        box.pack(side="left", fill="x", expand=True)

        inner = tk.Frame(box, bg=HEADER_BG)
        inner.pack(fill="x", padx=6, pady=6)

        for i, label in enumerate(("Shelf", "Storey", "Global")):
            tk.Label(inner, text=label, bg=HEADER_BG,
                     font=("Arial", 8, "bold")).grid(
                row=0, column=i, sticky="e", padx=14)
        self.shelf_var = tk.StringVar(value="0.00")
        self.storey_var = tk.StringVar(value="4,920.00")
        self.global_var = tk.StringVar(value="4,920.00")
        for i, var in enumerate((self.shelf_var, self.storey_var,
                                 self.global_var)):
            tk.Label(inner, textvariable=var, bg=HEADER_BG,
                     font=("Arial", 9)).grid(
                row=1, column=i, sticky="e", padx=14)

    # ------------------------------------------------------- behaviour
    def _on_code_change(self, *_):
        code = self.item_code_var.get().strip()
        if not code:
            self.item_desc_var.set("")
            return
        match = self.find_product_by_code(code)
        if match:
            self.item_desc_var.set(match.get("name", ""))

    def _open_product_picker(self):
        # hook this up to your existing product picker if you have one
        self._show_placeholder("Product picker")

    def _reload_movements(self):
        """Replace with a real API call. For now, seeds sample rows that
        match the screenshot so you can see the layout."""
        for row in self.mv_tree.get_children():
            self.mv_tree.delete(row)

        sample = [
            ("13/09/2026", "Bal Bf",           "0",       "",    "4,929.00", "0.00", "4,929.00", "normal"),
            ("14/09/2026", "POS SALES",        "6.2158",  "PCS", "0.00",     "3.00", "4,926.00", "normal"),
            ("15/09/2026", "POS SALES",        "5.2402",  "PCS", "0.00",     "1.00", "4,925.00", "normal"),
            ("15/09/2026", "LIVE POS SALES",   "16:10:21","PCS", "0.00",     "5.00", "4,920.00", "live"),
        ]
        for d, t, doc, unit, i, o, b, tag in sample:
            self.mv_tree.insert("", "end",
                                values=(d, t, doc, unit, i, o, b),
                                tags=(tag,))

    def _show_placeholder(self, name):
        from tkinter import messagebox
        messagebox.showinfo(name, f"{name} - hook this up to your screen.")