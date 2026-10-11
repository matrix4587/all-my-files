"""
Standalone preview of the HQ Branch Orders tab.
Run from project root:  py hq_orders_preview.py
"""

import tkinter as tk
from tkinter import ttk

try:
    from common.center import center_window_on_screen
except Exception:
    def center_window_on_screen(win, w, h):
        win.update_idletasks()
        x = (win.winfo_screenwidth()  - w) // 2
        y = (win.winfo_screenheight() - h) // 2
        win.geometry(f"{w}x{h}+{x}+{y}")

try:
    from common.titlebar import apply_green_titlebar
except Exception:
    def apply_green_titlebar(win):
        pass

from hq.orders_hq import HqOrdersMixin


class FakeApp(tk.Tk, HqOrdersMixin):
    SERVER = "http://localhost:5000"
    admin_credentials = ("evans", "")
    icon_purchase = None
    icon_orders = None

    def __init__(self):
        super().__init__()
        self.withdraw()
        self._wins = {}

    def open_content_window(self, key, title, group=None, icon=None):
        if key in self._wins and self._wins[key].winfo_exists():
            self._wins[key].lift()
            return self._wins[key]
        w = tk.Toplevel(self)
        w.title(title)
        w.geometry("1000x640")
        w.configure(bg="#dfe6ee")
        try:
            apply_green_titlebar(w)
        except Exception:
            pass
        self._wins[key] = w
        return w

    def message_info(self,  t, m): print("INFO ", t, m)
    def message_error(self, t, m): print("ERROR", t, m)
    def message_warn(self,  t, m): print("WARN ", t, m)
    def message_yesno(self, t, m):
        print("YESNO", t, m)
        return True

    def _hqo_refresh(self):
        self._hqo_fill([
            {"id": 9,  "lpo_no": None,        "date": "2026-09-19",
             "branch": "MAIN", "supplier": "BROOKSIDE", "reference": "",
             "vehicle": "", "expiry_date": "2026-10-03",
             "status": "Pending", "user": "brian",
             "value": 22500.00, "total_lines": 1, "total_qty": 18,
             "lines": [{"code": "280100",
                        "description": "CAPTAIN MORGAN GOLD 750ML",
                        "qty": 3, "total_pcs": 18, "packaging": "Carton",
                        "cost_price": 1250.00, "line_total": 22500.00}]},
            {"id": 8,  "lpo_no": None,        "date": "2026-09-18",
             "branch": "MAIN", "supplier": "BROOKSIDE", "reference": "",
             "vehicle": "", "expiry_date": "2026-10-02",
             "status": "Pending", "user": "brian",
             "value": 39600.00, "total_lines": 2, "total_qty": 33,
             "lines": []},
            {"id": 7,  "lpo_no": "LPO-00007", "date": "2026-09-17",
             "branch": "WEST", "supplier": "TechSupply Ltd",
             "reference": "", "vehicle": "", "expiry_date": "2026-10-01",
             "status": "Approved", "user": "brian",
             "value": 4400.00, "total_lines": 1, "total_qty": 4,
             "lines": []},
            {"id": 6,  "lpo_no": "LPO-00006", "date": "2026-09-16",
             "branch": "EAST", "supplier": "UDV KENYA LTD",
             "reference": "", "vehicle": "", "expiry_date": "2026-09-30",
             "status": "Approved", "user": "brian",
             "value": 37500.00, "total_lines": 1, "total_qty": 10,
             "lines": []},
        ])


if __name__ == "__main__":
    app = FakeApp()
    app.open_hq_orders_window()
    app.mainloop()