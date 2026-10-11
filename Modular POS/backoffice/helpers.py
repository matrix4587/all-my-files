"""
Helper mixin for BackOffice.

Contains the small utility methods used everywhere else in the app:
product cache lookups, short-code extraction, and the background
refresh that keeps the product cache up to date.

This is a "mixin" — a class whose methods get added to the main
BackOffice class via inheritance. That way all the code still has
`self.products_cache`, `self.find_product_by_code(...)`, etc., but
the actual method bodies live in their own file.
"""

import threading

import requests


class HelpersMixin:
    """Product cache + product lookup helpers."""

    def refresh_products_cache(self):
        def worker():
            try:
                r = requests.get(f"{self.SERVER}/products", timeout=3)
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
        code = str(code).strip()
        return next(
            (p for p in self.products_cache
             if str(p.get("barcode", "")).strip() == code
             or str(p.get("code", "")).strip() == code),
            None
        )

    def get_short_code(self, product):
        short = product.get("code")
        if short:
            return str(short).strip()
        return str(product.get("barcode", "")).strip()