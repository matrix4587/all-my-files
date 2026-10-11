"""
Window management mixin for BackOffice.

Handles every aspect of creating and managing the child windows
(Stocks, Products, Labels, GRNs, etc.): opening them, centering
them, keeping them inside the main window's bounds, grouping them
by ribbon tab, and the large "report" window used by summaries.
"""

import tkinter as tk
from tkinter import ttk

from common.center import center_window_on_screen
from common.titlebar import apply_green_titlebar


class WindowManagerMixin:
    """Window lifecycle, positioning, and grouping."""

    # Subwindow defaults - overridden in the main app if needed.
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
        try:
            if self.state() == "iconic":
                self.deiconify()
                self.lift()
                self.focus_force()
                self.update_idletasks()
        except tk.TclError:
            pass
        self.update_idletasks()
        main_w = self.winfo_width()
        main_h = self.winfo_height()
        width = min(self.SUBWINDOW_WIDTH, main_w)
        height = min(self.SUBWINDOW_HEIGHT, max(300, main_h - 120))
        win = tk.Toplevel(self)
        win.title(title)
        win.resizable(True, True)
        win.minsize(700, 400)
        center_window_on_screen(win, width, height)
        win.transient(self)
        if icon is not None:
            try:
                win.iconphoto(False, icon)
            except Exception:
                pass
        self.constrain_window_to_main(win)

        def on_close():
            if key in self.open_windows:
                del self.open_windows[key]
            self.window_groups.pop(key, None)
            win.destroy()

        win.protocol("WM_DELETE_WINDOW", on_close)
        self.open_windows[key] = win
        win.after(150, lambda w=win: apply_green_titlebar(w))
        return win

    def _open_report_window(self, title, rows, columns, weights, scope_label):
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        screen_w = win.winfo_screenwidth()
        screen_h = win.winfo_screenheight()
        width = max(900, screen_w - 80)
        height = max(600, screen_h - 120)
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        win.geometry(f"{width}x{height}+{x}+{y}")
        win.minsize(800, 500)
        win.lift()
        try:
            win.attributes("-topmost", True)
            win.after(300, lambda w=win: self._unset_topmost(w))
        except tk.TclError:
            pass
        win.focus_force()
        win.after(150, lambda w=win: apply_green_titlebar(w))

        top = ttk.Frame(win)
        top.pack(fill="x", padx=12, pady=(12, 0))
        ttk.Label(top, text=scope_label, font=("Arial", 11, "bold")).pack(side="left")
        ttk.Button(top, text="Export…",
                   command=lambda: self._export_report(win, columns, rows, title)).pack(side="right")
        ttk.Button(top, text="Print",
                   command=lambda: self._print_report(win, columns, rows, title)).pack(side="right", padx=(0, 8))

        table_frame = ttk.Frame(win)
        table_frame.pack(fill="both", expand=True, padx=12, pady=12)
        col_keys = [c[0] for c in columns]
        tree = ttk.Treeview(table_frame, columns=col_keys, show="headings",
                            style="Dark.Treeview")
        for key, heading in columns:
            tree.heading(key, text=heading)
            tree.column(key, anchor="w")
        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        for row in rows:
            tree.insert("", "end", values=row)
        self.make_columns_responsive(win, tree, weights)
        footer = ttk.Frame(win)
        footer.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Label(footer, text=f"Total rows: {len(rows)}").pack(side="left")
        return win

    def _unset_topmost(self, win):
        try:
            if win.winfo_exists():
                win.attributes("-topmost", False)
        except tk.TclError:
            pass

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