"""
Back Office API server.

Deploy one copy of this file (and its own back_office.db) at EVERY branch.
The HQ admin panel talks to each branch's server over HTTP by hostname.

Ledger convention:
    Sales          -> positive number in stock_out, stock_in = 0
    Everything else -> value in stock_in, signed:
        Opening Stock            +N
        GRN Receive              +N
        Admin adjustment (add)   +N
        Admin adjustment (remove) -N   (negative number in stock_in)

Endpoints:
    GET  /products                -> list all products
    POST /products                -> add a new product   (admin-gated)
    GET  /stock_ledger            -> stock movement history (filterable)
    POST /stock_adjust            -> +/- stock adjustment with reason (admin-gated)
    GET  /sales                   -> list sales
    POST /sales                   -> record a sale (decrements stock)
    GET  /sales/<id>              -> one sale with its lines
    GET  /suppliers               -> list suppliers
    POST /suppliers               -> add a supplier
    GET  /departments             -> list departments
    POST /departments             -> add a department
    POST /grn                     -> receive a GRN: updates stock + prices
    GET  /grns                    -> list past GRNs
    POST /login                   -> verify admin credentials

Default admin credentials (seeded on first run - CHANGE THESE):
    username: admin
    password: admin

Run with:
    pip install flask
    py server.py
"""

import sqlite3
import datetime
import os
import hashlib

from flask import Flask, request, jsonify

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "back_office.db")

app = Flask(__name__)


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            price REAL DEFAULT 0,
            stock REAL DEFAULT 0,
            barcode TEXT UNIQUE NOT NULL,
            code TEXT,
            packaging TEXT,
            cost_price REAL,
            markup REAL,
            markup_type TEXT DEFAULT '%',
            selling_price REAL,
            supplier TEXT,
            shelf TEXT
        )
    """)

    existing_cols = {row["name"] for row in cur.execute("PRAGMA table_info(products)").fetchall()}
    if "code" not in existing_cols:
        cur.execute("ALTER TABLE products ADD COLUMN code TEXT")
        cur.execute("UPDATE products SET code = barcode WHERE code IS NULL OR code = ''")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_code ON products(code)")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT NOT NULL,
            date TEXT NOT NULL,
            transaction_type TEXT NOT NULL,
            stock_in REAL DEFAULT 0,
            stock_out REAL DEFAULT 0,
            balance REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            total REAL NOT NULL,
            date TEXT NOT NULL,
            cashier TEXT,
            payment_method TEXT,
            phone TEXT,
            amount_received REAL
        )
    """)

    sales_cols = {row["name"] for row in cur.execute("PRAGMA table_info(sales)").fetchall()}
    for col, ddl in (
        ("cashier", "ALTER TABLE sales ADD COLUMN cashier TEXT"),
        ("payment_method", "ALTER TABLE sales ADD COLUMN payment_method TEXT"),
        ("phone", "ALTER TABLE sales ADD COLUMN phone TEXT"),
        ("amount_received", "ALTER TABLE sales ADD COLUMN amount_received REAL"),
    ):
        if col not in sales_cols:
            cur.execute(ddl)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sale_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_id INTEGER NOT NULL REFERENCES sales(id),
            product_id INTEGER,
            barcode TEXT NOT NULL,
            name TEXT NOT NULL,
            qty REAL NOT NULL,
            price_each REAL NOT NULL,
            subtotal REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS grns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier TEXT NOT NULL,
            date TEXT NOT NULL,
            total REAL NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS grn_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grn_id INTEGER NOT NULL REFERENCES grns(id),
            barcode TEXT NOT NULL,
            qty REAL NOT NULL,
            packaging TEXT,
            unit_cost REAL NOT NULL,
            markup REAL,
            markup_type TEXT,
            selling_price REAL
        )
    """)

    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        seed_products = [
            ("USB-C Cable 1m", "Cables", 250.0, 40, "1001", "1001", "1ctn x 12pcs", 120.0, 20, "%", 144.0, "Acme Electronics", "A1"),
            ("Wireless Mouse", "Peripherals", 900.0, 25, "1002", "1002", "1ctn x 10pcs", 550.0, 25, "%", 687.5, "TechSupply Ltd", "B2"),
            ("HDMI Cable 2m", "Cables", 400.0, 60, "1003", "1003", "1ctn x 20pcs", 220.0, 15, "%", 253.0, "Acme Electronics", "A2"),
            ("Phone Charger 20W", "Chargers", 700.0, 15, "1004", "1004", "1ctn x 24pcs", 380.0, 30, "%", 494.0, "TechSupply Ltd", "C1"),
        ]
        cur.executemany("""
            INSERT INTO products
                (name, category, price, stock, barcode, code, packaging, cost_price,
                 markup, markup_type, selling_price, supplier, shelf)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, seed_products)

        today = datetime.date.today().isoformat()
        for _, _, _, stock, barcode, *_ in seed_products:
            # Opening Stock -> positive number in stock_in.
            cur.execute("""
                INSERT INTO stock_ledger (barcode, date, transaction_type, stock_in, stock_out, balance)
                VALUES (?, ?, 'Opening Stock', ?, 0, ?)
            """, (barcode, today, stock, stock))

    cur.execute("SELECT COUNT(*) FROM suppliers")
    if cur.fetchone()[0] == 0:
        cur.executemany(
            "INSERT INTO suppliers (name) VALUES (?)",
            [("Acme Electronics",), ("TechSupply Ltd",), ("Global Gadgets Co",)]
        )

    cur.execute("SELECT COUNT(*) FROM departments")
    if cur.fetchone()[0] == 0:
        cats = {row["category"] for row in cur.execute(
            "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != ''"
        ).fetchall()}
        for name in sorted(cats):
            cur.execute("INSERT OR IGNORE INTO departments (name) VALUES (?)", (name,))

    cur.execute("SELECT COUNT(*) FROM admins")
    if cur.fetchone()[0] == 0:
        default_pw = hashlib.sha256("admin".encode("utf-8")).hexdigest()
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            ("admin", default_pw)
        )
        print("Seeded default admin account:  username='admin'  password='admin'  (CHANGE THIS)")

    conn.commit()
    conn.close()


def product_row_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "price": row["price"],
        "stock": row["stock"],
        "barcode": row["barcode"],
        "code": row["code"],
        "packaging": row["packaging"],
        "cost_price": row["cost_price"],
        "markup": row["markup"],
        "markup_type": row["markup_type"],
        "selling_price": row["selling_price"],
        "supplier": row["supplier"],
        "shelf": row["shelf"],
    }


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _hash_pw(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _check_admin_auth():
    username = request.headers.get("X-Admin-User", "").strip()
    password = request.headers.get("X-Admin-Pass", "").strip()
    if not username or not password:
        return False, "Admin authorization required"

    conn = get_db()
    row = conn.execute(
        "SELECT password_hash FROM admins WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    if row is None:
        return False, "Invalid admin credentials"
    if _hash_pw(password) != row["password_hash"]:
        return False, "Invalid admin credentials"
    return True, None


# ---------------------------------------------------------------------------
# Auth endpoint
# ---------------------------------------------------------------------------

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"status": "error", "message": "Username and password are required"}), 400

    conn = get_db()
    row = conn.execute(
        "SELECT password_hash FROM admins WHERE username = ?", (username,)
    ).fetchone()
    conn.close()

    if row is None or _hash_pw(password) != row["password_hash"]:
        return jsonify({"status": "error", "message": "Invalid username or password"}), 401

    return jsonify({"status": "ok", "username": username}), 200


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

@app.route("/products", methods=["GET"])
def list_products():
    conn = get_db()
    rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    conn.close()
    return jsonify([product_row_to_dict(r) for r in rows])


@app.route("/products", methods=["POST"])
def add_product():
    ok, err = _check_admin_auth()
    if not ok:
        return jsonify({"status": "error", "message": err}), 401

    data = request.get_json(force=True)
    required = ("name", "category", "price", "stock", "barcode")
    if not all(k in data for k in required):
        return f"Missing one of required fields: {required}", 400

    barcode = data["barcode"]
    code = (data.get("code") or barcode)

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO products
                (name, category, price, stock, barcode, code, packaging,
                 cost_price, markup, markup_type, selling_price, supplier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["name"],
            data["category"],
            data["price"],
            data["stock"],
            barcode,
            code,
            data.get("packaging"),
            data.get("cost_price"),
            data.get("markup"),
            data.get("markup_type", "%"),
            data.get("selling_price", data["price"]),
            data.get("supplier"),
        ))
        if data.get("category"):
            conn.execute("INSERT OR IGNORE INTO departments (name) VALUES (?)", (data["category"],))

        initial_stock = float(data["stock"]) if data["stock"] else 0
        if initial_stock:
            today = datetime.date.today().isoformat()
            # Opening Stock -> positive number in stock_in.
            conn.execute("""
                INSERT INTO stock_ledger (barcode, date, transaction_type, stock_in, stock_out, balance)
                VALUES (?, ?, 'Opening Stock', ?, 0, ?)
            """, (barcode, today, initial_stock, initial_stock))

        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        msg = str(e)
        if "products.code" in msg or "idx_products_code" in msg:
            return f"A product with short code '{code}' already exists", 409
        return f"A product with barcode '{barcode}' already exists", 409
    conn.close()
    return jsonify({"status": "ok"}), 201


# ---------------------------------------------------------------------------
# Stock ledger
# ---------------------------------------------------------------------------

@app.route("/stock_ledger", methods=["GET"])
def stock_ledger():
    barcode = request.args.get("barcode")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")

    query = "SELECT * FROM stock_ledger WHERE 1=1"
    params = []

    if barcode:
        conn0 = get_db()
        row = conn0.execute(
            "SELECT barcode FROM products WHERE barcode = ? OR code = ?",
            (barcode, barcode)
        ).fetchone()
        conn0.close()
        if row is not None:
            barcode = row["barcode"]
        query += " AND barcode = ?"
        params.append(barcode)
    if from_date:
        query += " AND date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND date <= ?"
        params.append(to_date)
    query += " ORDER BY date, id"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return jsonify([{
        "date": r["date"],
        "transaction_type": r["transaction_type"],
        "stock_in": r["stock_in"],
        "stock_out": r["stock_out"],
        "balance": r["balance"],
    } for r in rows])


# ---------------------------------------------------------------------------
# Stock adjustments (admin-gated) -- always land in stock_in, signed
# ---------------------------------------------------------------------------

@app.route("/stock_adjust", methods=["POST"])
def stock_adjust():
    """Adjust a product's stock up or down with a reason.

    Payload:
        {
            "barcode":   "<long barcode or short code>",
            "qty_delta": <number, positive adds, negative removes>,
            "reason":    "<Damage|Expense|Adjustment|Lost|Correction|...>",
            "notes":     "<optional text>"
        }

    Ledger write:
        stock_in  = qty_delta   (signed: +5.00 to add, -3.00 to remove)
        stock_out = 0
        balance   = new stock after applying qty_delta
    """
    ok, err = _check_admin_auth()
    if not ok:
        return jsonify({"status": "error", "message": err}), 401

    data = request.get_json(force=True) or {}
    ident = str(data.get("barcode", "")).strip()
    reason = str(data.get("reason", "")).strip() or "Adjustment"
    notes = str(data.get("notes", "")).strip()

    try:
        qty_delta = float(data.get("qty_delta"))
    except (TypeError, ValueError):
        return jsonify({"status": "error",
                        "message": "qty_delta must be a number"}), 400
    if qty_delta == 0:
        return jsonify({"status": "error",
                        "message": "qty_delta cannot be zero"}), 400

    if not ident:
        return jsonify({"status": "error", "message": "barcode is required"}), 400

    conn = get_db()
    cur = conn.cursor()

    product = cur.execute(
        "SELECT * FROM products WHERE barcode = ? OR code = ?",
        (ident, ident)
    ).fetchone()
    if product is None:
        conn.close()
        return jsonify({"status": "error",
                        "message": f"No product found for code '{ident}'"}), 404

    current_stock = product["stock"]
    new_stock = current_stock + qty_delta

    if new_stock < 0:
        conn.close()
        return jsonify({
            "status": "error",
            "message": f"Adjustment would make stock negative. "
                       f"Current {current_stock}, delta {qty_delta}, "
                       f"would be {new_stock}."
        }), 409

    today = datetime.date.today().isoformat()

    cur.execute("UPDATE products SET stock = ? WHERE id = ?",
                (new_stock, product["id"]))

    # Admin adjustments always land in stock_in, signed.
    cur.execute("""
        INSERT INTO stock_ledger (barcode, date, transaction_type,
                                   stock_in, stock_out, balance)
        VALUES (?, ?, ?, ?, 0, ?)
    """, (product["barcode"], today, reason, qty_delta, new_stock))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "barcode": product["barcode"],
        "short_code": product["code"] or product["barcode"],
        "name": product["name"],
        "previous_stock": current_stock,
        "new_stock": new_stock,
        "qty_delta": qty_delta,
        "reason": reason,
        "notes": notes,
        "date": today,
    }), 200


# ---------------------------------------------------------------------------
# Sales
# ---------------------------------------------------------------------------

@app.route("/sales", methods=["GET"])
def list_sales():
    conn = get_db()
    rows = conn.execute("SELECT * FROM sales ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([{
        "id": r["id"],
        "total": r["total"],
        "date": r["date"],
        "cashier": r["cashier"] if "cashier" in r.keys() else None,
        "payment_method": r["payment_method"] if "payment_method" in r.keys() else None,
    } for r in rows])


@app.route("/sales", methods=["POST"])
def create_sale():
    data = request.get_json(force=True) or {}
    items = data.get("items") or []
    cashier = (data.get("cashier") or "").strip()
    payment_method = (data.get("payment_method") or "").strip()
    phone = (data.get("phone") or "").strip() or None

    amount_received = data.get("amount_received")
    if amount_received is not None:
        try:
            amount_received = float(amount_received)
        except (TypeError, ValueError):
            amount_received = None

    if not items:
        return jsonify({"status": "error", "message": "Cart is empty"}), 400

    conn = get_db()
    cur = conn.cursor()

    resolved = []
    for line in items:
        product_id = line.get("product_id")
        qty = line.get("quantity")
        try:
            qty = float(qty)
        except (TypeError, ValueError):
            conn.close()
            return jsonify({"status": "error",
                            "message": f"Invalid quantity for product_id {product_id}"}), 400
        if qty <= 0:
            conn.close()
            return jsonify({"status": "error",
                            "message": f"Quantity must be > 0 for product_id {product_id}"}), 400

        row = cur.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            conn.close()
            return jsonify({"status": "error",
                            "message": f"Product id {product_id} not found"}), 404

        if row["stock"] < qty:
            conn.close()
            return jsonify({
                "status": "error",
                "message": f"Not enough stock for '{row['name']}' (barcode {row['barcode']}). "
                           f"In stock: {row['stock']}, requested: {qty}"
            }), 409

        price_each = line.get("price_each")
        try:
            price_each = float(price_each) if price_each is not None else float(row["price"])
        except (TypeError, ValueError):
            price_each = float(row["price"])

        resolved.append({
            "product_id": row["id"],
            "barcode": row["barcode"],
            "name": row["name"],
            "qty": qty,
            "price_each": price_each,
            "subtotal": round(qty * price_each, 2),
            "old_stock": row["stock"],
            "new_stock": row["stock"] - qty,
        })

    total = round(sum(r["subtotal"] for r in resolved), 2)
    today = datetime.date.today().isoformat()

    cur.execute("""
        INSERT INTO sales (total, date, cashier, payment_method, phone, amount_received)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (total, today, cashier or None, payment_method or None, phone, amount_received))
    sale_id = cur.lastrowid

    for r in resolved:
        cur.execute("""
            INSERT INTO sale_lines (sale_id, product_id, barcode, name, qty, price_each, subtotal)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (sale_id, r["product_id"], r["barcode"], r["name"],
              r["qty"], r["price_each"], r["subtotal"]))

        cur.execute("UPDATE products SET stock = ? WHERE id = ?",
                    (r["new_stock"], r["product_id"]))

        # Sales -> positive number in stock_out.
        cur.execute("""
            INSERT INTO stock_ledger (barcode, date, transaction_type, stock_in, stock_out, balance)
            VALUES (?, ?, 'Sale', 0, ?, ?)
        """, (r["barcode"], today, r["qty"], r["new_stock"]))

    conn.commit()
    conn.close()

    return jsonify({
        "sale_id": sale_id,
        "total": total,
        "date": today,
        "lines": [{
            "product_id": r["product_id"],
            "barcode": r["barcode"],
            "name": r["name"],
            "qty": r["qty"],
            "price_each": r["price_each"],
            "subtotal": r["subtotal"],
        } for r in resolved],
    }), 201


@app.route("/sales/<int:sale_id>", methods=["GET"])
def get_sale(sale_id):
    conn = get_db()
    header = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if header is None:
        conn.close()
        return jsonify({"status": "error", "message": "Sale not found"}), 404
    lines = conn.execute(
        "SELECT * FROM sale_lines WHERE sale_id = ? ORDER BY id", (sale_id,)
    ).fetchall()
    conn.close()
    return jsonify({
        "id": header["id"],
        "total": header["total"],
        "date": header["date"],
        "cashier": header["cashier"] if "cashier" in header.keys() else None,
        "payment_method": header["payment_method"] if "payment_method" in header.keys() else None,
        "phone": header["phone"] if "phone" in header.keys() else None,
        "amount_received": header["amount_received"] if "amount_received" in header.keys() else None,
        "lines": [{
            "product_id": r["product_id"],
            "barcode": r["barcode"],
            "name": r["name"],
            "qty": r["qty"],
            "price_each": r["price_each"],
            "subtotal": r["subtotal"],
        } for r in lines],
    })


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@app.route("/suppliers", methods=["GET"])
def list_suppliers():
    conn = get_db()
    rows = conn.execute("SELECT * FROM suppliers ORDER BY name").fetchall()
    conn.close()
    return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])


@app.route("/suppliers", methods=["POST"])
def add_supplier():
    data = request.get_json(force=True)
    name = (data or {}).get("name", "").strip()
    if not name:
        return "Supplier name is required", 400

    conn = get_db()
    try:
        conn.execute("INSERT INTO suppliers (name) VALUES (?)", (name,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return f"Supplier '{name}' already exists", 409
    conn.close()
    return jsonify({"status": "ok"}), 201


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

@app.route("/departments", methods=["GET"])
def list_departments():
    conn = get_db()
    rows = conn.execute("SELECT * FROM departments ORDER BY name").fetchall()
    conn.close()
    return jsonify([{"id": r["id"], "name": r["name"]} for r in rows])


@app.route("/departments", methods=["POST"])
def add_department():
    data = request.get_json(force=True)
    name = (data or {}).get("name", "").strip()
    if not name:
        return "Department name is required", 400

    conn = get_db()
    try:
        conn.execute("INSERT INTO departments (name) VALUES (?)", (name,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return f"Department '{name}' already exists", 409
    conn.close()
    return jsonify({"status": "ok"}), 201


# ---------------------------------------------------------------------------
# GRNs
# ---------------------------------------------------------------------------

@app.route("/grn", methods=["POST"])
def receive_grn():
    data = request.get_json(force=True)
    supplier = (data or {}).get("supplier", "").strip()
    date = (data or {}).get("date") or datetime.date.today().isoformat()
    lines = (data or {}).get("lines") or []

    if not supplier:
        return "Supplier is required", 400
    if not lines:
        return "At least one line is required", 400

    conn = get_db()
    cur = conn.cursor()

    resolved_lines = []
    for line in lines:
        ident = str(line.get("barcode", "")).strip()
        row = cur.execute(
            "SELECT barcode FROM products WHERE barcode = ? OR code = ?",
            (ident, ident)
        ).fetchone()
        if row is None:
            conn.close()
            return f"No product found for code '{ident}'", 400
        line = dict(line)
        line["barcode"] = row["barcode"]
        resolved_lines.append(line)
    lines = resolved_lines

    total_value = sum(line["qty"] * line["unit_cost"] for line in lines)

    cur.execute("INSERT INTO grns (supplier, date, total) VALUES (?, ?, ?)", (supplier, date, total_value))
    grn_id = cur.lastrowid

    for line in lines:
        barcode = line["barcode"]
        qty = line["qty"]
        unit_cost = line["unit_cost"]
        packaging = line.get("packaging")
        markup = line.get("markup")
        markup_type = line.get("markup_type")
        selling_price = line.get("selling_price")

        cur.execute("""
            INSERT INTO grn_lines (grn_id, barcode, qty, packaging, unit_cost,
                                    markup, markup_type, selling_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (grn_id, barcode, qty, packaging, unit_cost, markup, markup_type, selling_price))

        product = cur.execute("SELECT stock FROM products WHERE barcode = ?", (barcode,)).fetchone()
        new_stock = product["stock"] + qty

        update_fields = ["stock = ?", "cost_price = ?"]
        update_values = [new_stock, unit_cost]
        if packaging:
            update_fields.append("packaging = ?")
            update_values.append(packaging)
        if markup is not None:
            update_fields.append("markup = ?")
            update_values.append(markup)
        if markup_type is not None:
            update_fields.append("markup_type = ?")
            update_values.append(markup_type)
        if selling_price is not None:
            update_fields.append("selling_price = ?")
            update_values.append(selling_price)
            update_fields.append("price = ?")
            update_values.append(selling_price)
        update_fields.append("supplier = ?")
        update_values.append(supplier)

        update_values.append(barcode)
        cur.execute(f"UPDATE products SET {', '.join(update_fields)} WHERE barcode = ?", update_values)

        # GRN -> positive number in stock_in.
        cur.execute("""
            INSERT INTO stock_ledger (barcode, date, transaction_type, stock_in, stock_out, balance)
            VALUES (?, ?, 'GRN Receive', ?, 0, ?)
        """, (barcode, date, qty, new_stock))

    conn.commit()
    conn.close()

    return jsonify({"status": "ok", "grn_id": grn_id}), 201


@app.route("/grns", methods=["GET"])
def list_grns():
    conn = get_db()
    rows = conn.execute("SELECT * FROM grns ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify([{"id": r["id"], "supplier": r["supplier"], "date": r["date"], "total": r["total"]} for r in rows])


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, threaded=True)