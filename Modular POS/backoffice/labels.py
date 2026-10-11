"""
Labels screen mixin for BackOffice.

Contains everything related to label printing:
  - The Labels window with mode buttons (Product / Shelf / Test)
  - The live preview canvas
  - The "Change (select printer)" dialog
  - The PDF generation for both Product and Shelf labels
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog

from common.center import center_window_on_screen
from common.code128 import code128_encode
from common.titlebar import apply_green_titlebar


class LabelsMixin:
    """Labels screen, preview, printer selection, and PDF output."""

    # Label mode and printer
    label_mode_var = None
    label_mode_buttons = None
    label_printer_name = None
    _label_code_normalizing = False
    _label_bottom_built = False
    _label_current_area = None
    _label_win = None
    _label_body = None

    # ---------------------------------------------------- Window / layout

    def build_labels_content(self):
        win = self.open_content_window("labels", "Labels",
                                       group="inventory", icon=self.icon_labels)
        if win is None:
            return

        self._label_win = win
        self.label_mode_var = tk.StringVar(value="Product Label")
        self.label_mode_buttons = {}
        self._label_code_normalizing = False
        self._label_bottom_built = False
        self._label_current_area = None

        try:
            win.minsize(720, 360)
            center_window_on_screen(win, 760, 400)
        except Exception:
            pass

        mode_row = ttk.Frame(win)
        mode_row.pack(fill="x", padx=10, pady=(10, 6), side="top")

        def make_mode_button(label):
            btn = ttk.Button(mode_row, text=label,
                             command=lambda l=label: self.set_label_mode(l))
            btn.pack(side="left", padx=(0, 4))
            self.label_mode_buttons[label] = btn

        make_mode_button("Product Label")
        make_mode_button("Shelf Label")
        make_mode_button("Test Barcode")

        self._label_body = ttk.Frame(win)
        self._label_body.pack(fill="both", expand=True, padx=0, pady=0, side="top")

        btn_row = ttk.Frame(win)
        btn_row.pack(fill="x", padx=10, pady=(6, 10), side="bottom")
        ttk.Button(btn_row, text="Change (select printer)",
                   command=self.change_label_printer).pack(side="left")
        ttk.Button(btn_row, text="Print",
                   command=self.print_labels).pack(side="right", ipadx=24, ipady=4)
        self._label_bottom_built = True

        self.set_label_mode("Product Label")

    def _build_label_print_area(self):
        if self._label_current_area == "label":
            return
        for w in self._label_body.winfo_children():
            w.destroy()

        row_code = ttk.Frame(self._label_body)
        row_code.pack(fill="x", padx=10, pady=(4, 4))

        ttk.Label(row_code, text="Code:", font=("Arial", 10, "bold")).pack(side="left", padx=(0, 6))
        self.label_barcode_var = tk.StringVar()
        self.label_barcode_entry = ttk.Entry(row_code, textvariable=self.label_barcode_var, width=22)
        self.label_barcode_entry.pack(side="left", padx=(0, 16))
        self.label_barcode_entry.focus_set()

        ttk.Label(row_code, text="Description:", font=("Arial", 10, "bold")).pack(side="left", padx=(0, 6))
        self.label_desc_var = tk.StringVar(value="")
        ttk.Entry(row_code, textvariable=self.label_desc_var,
                  width=42).pack(side="left", fill="x", expand=True)

        row_main = ttk.Frame(self._label_body)
        row_main.pack(fill="both", expand=True, padx=10, pady=(4, 4))

        qty_col = ttk.Frame(row_main)
        qty_col.pack(side="left", anchor="n", padx=(0, 16))
        ttk.Label(qty_col, text="Quantity of Labels to print:",
                  font=("Arial", 10, "bold")).pack(anchor="w", pady=(0, 4))
        self.label_qty_var = tk.StringVar(value="1")
        ttk.Entry(qty_col, textvariable=self.label_qty_var, width=8).pack(anchor="w")

        preview_col = ttk.LabelFrame(row_main, text="Label preview")
        preview_col.pack(side="left", fill="both", expand=True)

        self.label_preview_canvas = tk.Canvas(
            preview_col, width=380, height=190,
            bg="white", highlightthickness=0)
        self.label_preview_canvas.pack(padx=8, pady=6)

        self.label_barcode_var.trace_add("write", self.on_label_code_change)
        self.label_desc_var.trace_add("write", lambda *a: self._refresh_label_preview())
        self.label_mode_var.trace_add("write", lambda *a: self._refresh_label_preview())

        self._refresh_label_preview()
        self._label_current_area = "label"

    def _build_label_test_area(self):
        if self._label_current_area == "test":
            return
        for w in self._label_body.winfo_children():
            w.destroy()

        row_code = ttk.Frame(self._label_body)
        row_code.pack(fill="x", padx=10, pady=(4, 6))

        ttk.Label(row_code, text="Code:", font=("Arial", 10, "bold")).pack(side="left", padx=(0, 6))
        self.label_barcode_var = tk.StringVar()
        self.label_barcode_entry = ttk.Entry(row_code, textvariable=self.label_barcode_var, width=22)
        self.label_barcode_entry.pack(side="left")
        self.label_barcode_entry.focus_set()

        table_frame = ttk.LabelFrame(self._label_body, text="Scanned item")
        table_frame.pack(fill="both", expand=True, padx=10, pady=(4, 8))

        self.label_display_tree = ttk.Treeview(
            table_frame,
            columns=("code", "desc", "cost", "selling"),
            show="headings",
            height=8,
            style="Dark.Treeview")
        self.label_display_tree.heading("code", text="Code")
        self.label_display_tree.heading("desc", text="Description")
        self.label_display_tree.heading("cost", text="Cost")
        self.label_display_tree.heading("selling", text="Selling price")
        self.label_display_tree.column("code", width=130, anchor="w")
        self.label_display_tree.column("desc", width=320, anchor="w")
        self.label_display_tree.column("cost", width=110, anchor="e")
        self.label_display_tree.column("selling", width=130, anchor="e")
        self.label_display_tree.pack(fill="both", expand=True, padx=5, pady=5)

        self.label_barcode_var.trace_add("write", self.on_label_code_change)
        self._label_current_area = "test"

    def set_label_mode(self, mode):
        self.label_mode_var.set(mode)
        for label, btn in self.label_mode_buttons.items():
            if label == mode:
                btn.state(["pressed"])
            else:
                btn.state(["!pressed"])
        if mode == "Test Barcode":
            self._build_label_test_area()
        else:
            self._build_label_print_area()

    def on_label_code_change(self, *args):
        if self._label_code_normalizing:
            return
        code = self.label_barcode_var.get().strip()
        mode = self.label_mode_var.get() if self.label_mode_var else "Product Label"

        if mode == "Test Barcode":
            if hasattr(self, "label_display_tree") and self.label_display_tree.winfo_exists():
                for row in self.label_display_tree.get_children():
                    self.label_display_tree.delete(row)
            if not code:
                return
            match = self.find_product_by_code(code)
            if not match:
                self.label_display_tree.insert("", "end",
                                               values=("Not found", "-", "-", "-"))
                return
            short_code = self.get_short_code(match)
            desc = match.get("name", "")
            cost = match.get("cost_price", match.get("price", ""))
            selling = match.get("selling_price", match.get("price", ""))

            def fmt(v):
                try:
                    return f"{float(v):.2f}"
                except (TypeError, ValueError):
                    return str(v)

            self.label_display_tree.insert(
                "", "end", values=(short_code, desc, fmt(cost), fmt(selling)))
        else:
            if not code:
                if hasattr(self, "label_desc_var"):
                    self.label_desc_var.set("")
                self._refresh_label_preview()
                return
            match = self.find_product_by_code(code)
            if hasattr(self, "label_desc_var"):
                self.label_desc_var.set(match.get("name", "") if match else "")
            self._refresh_label_preview()

    # -------------------------------------------------- On-screen preview

    def _refresh_label_preview(self):
        if not hasattr(self, "label_preview_canvas") or not self.label_preview_canvas.winfo_exists():
            return
        c = self.label_preview_canvas
        c.delete("all")

        W = 380
        H = 190
        mode = self.label_mode_var.get() if self.label_mode_var else "Product Label"
        code = self.label_barcode_var.get().strip() if hasattr(self, "label_barcode_var") else ""
        desc = self.label_desc_var.get().strip() if hasattr(self, "label_desc_var") else ""
        product = self.find_product_by_code(code) if code else None

        if mode == "Product Label":
            gap = 8
            label_w = (W - 16 - gap) // 2
            label_h = label_w // 2
            if label_h > H - 16:
                label_h = H - 16
                label_w = label_h * 2
            self._draw_preview_product(c, 8, 8, label_w, label_h, desc, product, code)
            self._draw_preview_product(c, 8 + label_w + gap, 8, label_w, label_h, desc, product, code)
        elif mode == "Shelf Label":
            label_w = 260
            label_h = label_w // 2
            x = (W - label_w) // 2
            y = (H - label_h) // 2
            self._draw_preview_shelf(c, x, y, label_w, label_h, desc, product, code)

        c.create_rectangle(2, 2, W - 2, H - 2, outline="#999999")

    def _draw_preview_product(self, c, x0, y0, w, h, desc, product, code):
        pad = 4
        cx = x0 + w / 2

        banner_h = int(h * 0.20)
        desc_h = int(h * 0.16)
        bc_h = int(h * 0.30)
        code_h = int(h * 0.14)

        y = y0 + pad

        c.create_rectangle(x0 + pad, y, x0 + w - pad, y + banner_h,
                           fill="black", outline="black")
        c.create_text(cx, y + banner_h / 2, text=self.SHOP_NAME,
                      font=("Arial", 9, "bold"), fill="white")
        y += banner_h + 1

        c.create_text(cx, y, text=(desc or "(description)")[:22],
                      font=("Arial", 7, "bold"), fill="black", anchor="n")
        y += desc_h

        short_code = ""
        selling = ""
        if product:
            short_code = self.get_short_code(product)
            selling = product.get("selling_price", product.get("price", ""))

        long_code = code or "0000000000000"
        bits = code128_encode(long_code)
        bc_x0 = x0 + pad + 4
        bc_x1 = x0 + w - pad - 4
        n = max(1, len(bits))
        bw = (bc_x1 - bc_x0) / n
        for i, b in enumerate(bits):
            if b == "1":
                bx = bc_x0 + i * bw
                c.create_rectangle(bx, y, bx + max(bw, 0.4), y + bc_h,
                                   fill="black", outline="")
        y += bc_h + 1

        if short_code:
            c.create_text(cx, y, text=short_code,
                          font=("Courier", 7, "bold"), fill="black", anchor="n")
        y += code_h

        try:
            selling_str = f"KSh {float(selling):.2f}"
        except (TypeError, ValueError):
            selling_str = f"KSh {selling}" if selling else "KSh -"
        c.create_text(cx, y0 + h - pad - 2, text=selling_str,
                      font=("Arial", 11, "bold"), fill="#006600", anchor="s")

    def _draw_preview_shelf(self, c, x0, y0, w, h, desc, product, code):
        pad = 6
        cx = x0 + w / 2

        banner_h = int(h * 0.18)
        desc_h = int(h * 0.16)
        bc_h = int(h * 0.28)
        code_h = int(h * 0.14)

        y = y0 + pad
        c.create_rectangle(x0 + pad, y, x0 + w - pad, y + banner_h,
                           fill="black", outline="black")
        c.create_text(cx, y + banner_h / 2, text=self.SHOP_NAME,
                      font=("Arial", 11, "bold"), fill="white")
        y += banner_h + 2

        c.create_text(cx, y, text=(desc or "(description)")[:30],
                      font=("Arial", 9, "bold"), fill="black", anchor="n")
        y += desc_h

        short_code = ""
        selling = ""
        if product:
            short_code = self.get_short_code(product)
            selling = product.get("selling_price", product.get("price", ""))

        long_code = code or "0000000000000"
        bits = code128_encode(long_code)
        bc_x0 = x0 + pad + 12
        bc_x1 = x0 + w - pad - 12
        n = max(1, len(bits))
        bw = (bc_x1 - bc_x0) / n
        for i, b in enumerate(bits):
            if b == "1":
                bx = bc_x0 + i * bw
                c.create_rectangle(bx, y, bx + max(bw, 0.4), y + bc_h,
                                   fill="black", outline="")
        y += bc_h + 2

        if short_code:
            c.create_text(cx, y, text=f"Code: {short_code}",
                          font=("Courier", 10, "bold"), fill="black", anchor="n")
        y += code_h

        try:
            selling_str = f"KSh {float(selling):.2f}"
        except (TypeError, ValueError):
            selling_str = f"KSh {selling}" if selling else "KSh -"
        c.create_text(cx, y0 + h - pad - 2, text=selling_str,
                      font=("Arial", 14, "bold"), fill="#006600", anchor="s")

    # ------------------------------------------------- Printer selection

    def change_label_printer(self):
        if not sys.platform.startswith("win"):
            self.message_info("Change printer",
                              "Printer selection uses the OS print dialog when "
                              "you click Print on this platform.")
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
            real_hwnd = ctypes.windll.user32.GetParent(hwnd_int)
            if not real_hwnd:
                real_hwnd = hwnd_int

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
                            self.label_printer_name = device_name
                finally:
                    kernel32.GlobalUnlock(pd.hDevNames)

            if pd.hDC:
                ctypes.windll.gdi32.DeleteDC(pd.hDC)

            self.message_info(
                "Printer selected",
                f"Selected printer:\n{self.label_printer_name or '(unknown)'}")

        except Exception as e:
            self.message_warn(
                "Couldn't open printer dialog",
                f"{e}\n\nYou can still print - the Save dialog will let you "
                f"pick a target file and print from your PDF viewer.")

    # ------------------------------------------------------- PDF output

    def _label_sizes(self):
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        return {
            "pagesize": A4,
            "label_w": 50 * mm,
            "label_h": 25 * mm,
            "cols": 2,
            "rows": 7,
            "margin_x": 8 * mm,
            "margin_y": 10 * mm,
            "per_page": 2 * 7,
        }

    def _draw_product_label(self, canvas, x, y, size, product):
        from reportlab.lib import colors

        label_w = size["label_w"]
        label_h = size["label_h"]
        cx = x + label_w / 2

        canvas.saveState()
        banner_h = label_h * 0.22
        y_top = y + label_h

        canvas.setFillColor(colors.black)
        canvas.rect(x, y_top - banner_h, label_w, banner_h, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawCentredString(cx, y_top - banner_h + 5, self.SHOP_NAME)

        canvas.setFillColor(colors.black)
        canvas.setFont("Helvetica-Bold", 7)
        desc = (product.get("name") or "")[:32]
        desc_y = y_top - banner_h - 8
        canvas.drawCentredString(cx, desc_y, desc)

        bc_top = desc_y - 4
        bc_h = label_h * 0.32
        bc_bottom = bc_top - bc_h
        long_code = str(product.get("barcode") or product.get("code") or "")
        bits = code128_encode(long_code)
        bc_x = x + 4
        bc_w = label_w - 8
        n = max(1, len(bits))
        bw = bc_w / n
        canvas.setFillColor(colors.black)
        for i, b in enumerate(bits):
            if b == "1":
                canvas.rect(bc_x + i * bw, bc_bottom, bw + 0.05, bc_h, stroke=0, fill=1)

        canvas.setFillColor(colors.black)
        canvas.setFont("Courier-Bold", 7)
        short = str(product.get("code") or product.get("barcode") or "")
        code_y = bc_bottom - 8
        canvas.drawCentredString(cx, code_y, short)

        selling = product.get("selling_price", product.get("price", ""))
        try:
            selling_str = f"KSh {float(selling):.2f}"
        except (TypeError, ValueError):
            selling_str = f"KSh {selling}"
        canvas.setFillColor(colors.HexColor("#006600"))
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawCentredString(cx, y + 4, selling_str)

        canvas.restoreState()

    def _draw_shelf_label(self, canvas, x, y, size, product):
        from reportlab.lib import colors

        label_w = size["label_w"]
        label_h = size["label_h"]
        cx = x + label_w / 2

        canvas.saveState()
        banner_h = label_h * 0.22
        y_top = y + label_h

        canvas.setFillColor(colors.black)
        canvas.rect(x, y_top - banner_h, label_w, banner_h, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawCentredString(cx, y_top - banner_h + 5, self.SHOP_NAME)

        canvas.setFillColor(colors.black)
        canvas.setFont("Helvetica-Bold", 8)
        desc = (product.get("name") or "")[:28]
        desc_y = y_top - banner_h - 9
        canvas.drawCentredString(cx, desc_y, desc)

        bc_top = desc_y - 4
        bc_h = label_h * 0.32
        bc_bottom = bc_top - bc_h
        long_code = str(product.get("barcode") or product.get("code") or "")
        bits = code128_encode(long_code)
        bc_x = x + 6
        bc_w = label_w - 12
        n = max(1, len(bits))
        bw = bc_w / n
        canvas.setFillColor(colors.black)
        for i, b in enumerate(bits):
            if b == "1":
                canvas.rect(bc_x + i * bw, bc_bottom, bw + 0.05, bc_h, stroke=0, fill=1)

        canvas.setFont("Courier-Bold", 7)
        short = str(product.get("code") or product.get("barcode") or "")
        code_y = bc_bottom - 8
        canvas.drawCentredString(cx, code_y, f"Code: {short}")

        selling = product.get("selling_price", product.get("price", ""))
        try:
            selling_str = f"KSh {float(selling):.2f}"
        except (TypeError, ValueError):
            selling_str = f"KSh {selling}"
        canvas.setFillColor(colors.HexColor("#006600"))
        canvas.setFont("Helvetica-Bold", 13)
        canvas.drawCentredString(cx, y + 4, selling_str)

        canvas.restoreState()

    def print_labels(self):
        mode = self.label_mode_var.get() if self.label_mode_var else "Product Label"

        if mode == "Test Barcode":
            self.message_info(
                "Test Barcode",
                "Test Barcode mode is display-only - it shows the info "
                "resolved from the long code on screen without printing.")
            return

        code = self.label_barcode_var.get().strip()
        if not code:
            self.message_error("Error", "Scan or type the long barcode first")
            return

        product = self.find_product_by_code(code)
        if not product:
            self.message_error("Error", f"No product found for code '{code}'")
            return

        try:
            qty = int(self.label_qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            self.message_error("Error", "Quantity must be a positive whole number")
            return

        try:
            from reportlab.pdfgen import canvas as rl_canvas
            from reportlab.lib.units import mm
        except ImportError:
            self.message_error("Missing library",
                               "Labels need 'reportlab'.\n\n"
                               "Install it with:   pip install reportlab")
            return

        default_name = f"labels_{mode.replace(' ', '_').lower()}_{code}.pdf"
        path = filedialog.asksaveasfilename(
            parent=self,
            title=f"Save {mode} PDF",
            defaultextension=".pdf",
            initialfile=default_name,
            filetypes=[("PDF Document", "*.pdf"), ("All files", "*.*")])
        if not path:
            return

        size = self._label_sizes()
        c = rl_canvas.Canvas(path, pagesize=size["pagesize"])
        page_w, page_h = size["pagesize"]
        origin_x = size["margin_x"]
        origin_y = page_h - size["margin_y"] - size["label_h"]

        if mode == "Product Label":
            total_rows = (qty + 1) // 2
            for r in range(total_rows):
                for col in range(2):
                    if r * 2 + col >= qty:
                        break
                    x = origin_x + col * size["label_w"]
                    y = origin_y - r * size["label_h"]
                    self._draw_product_label(c, x, y, size, product)
                    c.saveState()
                    c.setStrokeColorRGB(0.85, 0.85, 0.85)
                    c.setLineWidth(0.3)
                    c.rect(x, y, size["label_w"], size["label_h"], stroke=1, fill=0)
                    c.restoreState()

                if (r + 1) % size["rows"] == 0 and r < total_rows - 1:
                    c.showPage()
                    origin_y = page_h - size["margin_y"] - size["label_h"]
        else:
            for i in range(qty):
                row = i % size["rows"]
                y = origin_y - row * size["label_h"]
                x = origin_x
                self._draw_shelf_label(c, x, y, size, product)
                c.saveState()
                c.setStrokeColorRGB(0.85, 0.85, 0.85)
                c.setLineWidth(0.3)
                c.rect(x, y, size["label_w"], size["label_h"], stroke=1, fill=0)
                c.restoreState()

                if (i + 1) % size["rows"] == 0 and i < qty - 1:
                    c.showPage()
                    origin_y = page_h - size["margin_y"] - size["label_h"]

        c.save()

        self.message_info("Labels ready", f"Saved {qty} label(s) to:\n{path}")
        self.open_with_default_app(path)