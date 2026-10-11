"""
Back Office API server.

Role-based access:
    Role order: staff < supervisor < manager < admin

    Each protected endpoint declares a minimum role. The server reads
    X-User and X-Pass headers, verifies them against admins or users,
    and returns 401/403 if the credentials are wrong or the role is
    too low.

Endpoints:
    GET   /products
    POST  /products                       (manager+)
    GET   /stock_ledger
    GET   /stock_movement_summary
    POST  /stock_adjust                   (manager+)
    GET   /sales
    POST  /sales
    GET   /sales/<id>
    GET   /suppliers
    POST  /suppliers
    GET   /departments
    POST  /departments
    GET   /purchase_orders
    POST  /purchase_orders
    GET   /purchase_orders/<id>
    PATCH /purchase_orders/<id>/approve   (admin only)
    PATCH /purchase_orders/<id>/receive
    POST  /grn
    GET   /grns
    GET   /grns/<id>
    POST  /crn                            (admin only)
    GET   /crns
    GET   /crns/<id>
    PATCH /crns/<id>/receive              (staff+)
    POST  /login
    GET   /usernames
    GET   /users                          (admin only)
    POST  /users                          (admin only)
    GET   /users/<id>                     (admin only)
    PATCH /users/<id>                     (admin only)
    DELETE /users/<id>                    (admin only)
"""

import sqlite3
import datetime
import os
import hashlib

from flask import Flask, request, jsonify

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "back_office.db")

app = Flask(__name__)

ORDER_EXPIRY_DAYS = 14

# Role ordering used by _require_role.
ROLE_RANK = {
    "staff": 1,
    "supervisor": 2,
    "manager": 3,
    "admin": 4,
}


# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _table_columns(cur, table):
    try:
        return {row["name"] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _ensure_column(cur, table, column, ddl):
    cols = _table_columns(cur, table)
    if column not in cols:
        cur.execute(ddl)
        return True
    return False


def init_db():
    conn = get_db()
    cur = conn.cursor()

    # ---- products ----
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
            pack_size REAL DEFAULT 1,
            cost_price REAL,
            markup REAL,
            markup_type TEXT DEFAULT '%',
            selling_price REAL,
            supplier TEXT,
            shelf TEXT
        )
    """)
    _ensure_column(cur, "products", "code",
                   "ALTER TABLE products ADD COLUMN code TEXT")
    _ensure_column(cur, "products", "pack_size",
                   "ALTER TABLE products ADD COLUMN pack_size REAL DEFAULT 1")
    cur.execute("UPDATE products SET code = barcode WHERE code IS NULL OR code = ''")
    cur.execute("UPDATE products SET pack_size = 1 WHERE pack_size IS NULL OR pack_size = 0")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_products_code ON products(code)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_products_barcode ON products(barcode)")

    # ---- stock_ledger ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stock_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            barcode TEXT NOT NULL,
            date TEXT NOT NULL,
            transaction_type TEXT NOT NULL,
            stock_in REAL DEFAULT 0,
            stock_out REAL DEFAULT 0,
            balance REAL NOT NULL,
            reference TEXT
        )
    """)
    _ensure_column(cur, "stock_ledger", "reference",
                   "ALTER TABLE stock_ledger ADD COLUMN reference TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_ledger_barcode ON stock_ledger(barcode)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_ledger_barcode_date ON stock_ledger(barcode, date)")

    # ---- sales ----
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
    for col, ddl in (
        ("cashier", "ALTER TABLE sales ADD COLUMN cashier TEXT"),
        ("payment_method", "ALTER TABLE sales ADD COLUMN payment_method TEXT"),
        ("phone", "ALTER TABLE sales ADD COLUMN phone TEXT"),
        ("amount_received", "ALTER TABLE sales ADD COLUMN amount_received REAL"),
    ):
        _ensure_column(cur, "sales", col, ddl)

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

    # ---- suppliers / departments / admins ----
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

    # ---- users (branch staff) ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            full_name TEXT,
            password_hash TEXT NOT NULL,
            branch TEXT,
            phone TEXT,
            email TEXT,
            role TEXT DEFAULT 'staff',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT,
            created_by TEXT
        )
    """)
    _ensure_column(cur, "users", "full_name",
                   "ALTER TABLE users ADD COLUMN full_name TEXT")
    _ensure_column(cur, "users", "branch",
                   "ALTER TABLE users ADD COLUMN branch TEXT")
    _ensure_column(cur, "users", "phone",
                   "ALTER TABLE users ADD COLUMN phone TEXT")
    _ensure_column(cur, "users", "email",
                   "ALTER TABLE users ADD COLUMN email TEXT")
    _ensure_column(cur, "users", "role",
                   "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'staff'")
    _ensure_column(cur, "users", "active",
                   "ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
    _ensure_column(cur, "users", "created_at",
                   "ALTER TABLE users ADD COLUMN created_at TEXT")
    _ensure_column(cur, "users", "created_by",
                   "ALTER TABLE users ADD COLUMN created_by TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_users_username ON users(LOWER(username))")

    # ---- grns ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS grns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier TEXT NOT NULL,
            date TEXT NOT NULL,
            total REAL NOT NULL,
            purchase_order_id INTEGER,
            user TEXT
        )
    """)
    _ensure_column(cur, "grns", "purchase_order_id",
                   "ALTER TABLE grns ADD COLUMN purchase_order_id INTEGER")
    _ensure_column(cur, "grns", "user",
                   "ALTER TABLE grns ADD COLUMN user TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS grn_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grn_id INTEGER NOT NULL REFERENCES grns(id),
            barcode TEXT NOT NULL,
            qty REAL NOT NULL,
            total_qty REAL DEFAULT 0,
            packaging TEXT,
            pack_size REAL DEFAULT 1,
            unit_cost REAL NOT NULL,
            markup REAL,
            markup_type TEXT,
            selling_price REAL
        )
    """)
    _ensure_column(cur, "grn_lines", "total_qty",
                   "ALTER TABLE grn_lines ADD COLUMN total_qty REAL DEFAULT 0")
    _ensure_column(cur, "grn_lines", "pack_size",
                   "ALTER TABLE grn_lines ADD COLUMN pack_size REAL DEFAULT 1")

    # ---- credit notes (CRNs) ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS crns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            reference TEXT,
            reason TEXT,
            user TEXT,
            total_lines INTEGER NOT NULL DEFAULT 0,
            total_qty REAL NOT NULL DEFAULT 0,
            value REAL NOT NULL DEFAULT 0,
            received INTEGER NOT NULL DEFAULT 0,
            received_date TEXT
        )
    """)
    _ensure_column(cur, "crns", "reference",
                   "ALTER TABLE crns ADD COLUMN reference TEXT")
    _ensure_column(cur, "crns", "reason",
                   "ALTER TABLE crns ADD COLUMN reason TEXT")
    _ensure_column(cur, "crns", "user",
                   "ALTER TABLE crns ADD COLUMN user TEXT")
    _ensure_column(cur, "crns", "total_lines",
                   "ALTER TABLE crns ADD COLUMN total_lines INTEGER NOT NULL DEFAULT 0")
    _ensure_column(cur, "crns", "total_qty",
                   "ALTER TABLE crns ADD COLUMN total_qty REAL NOT NULL DEFAULT 0")
    _ensure_column(cur, "crns", "value",
                   "ALTER TABLE crns ADD COLUMN value REAL NOT NULL DEFAULT 0")
    _ensure_column(cur, "crns", "received",
                   "ALTER TABLE crns ADD COLUMN received INTEGER NOT NULL DEFAULT 0")
    _ensure_column(cur, "crns", "received_date",
                   "ALTER TABLE crns ADD COLUMN received_date TEXT")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS crn_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            crn_id INTEGER NOT NULL REFERENCES crns(id),
            barcode TEXT NOT NULL,
            code TEXT,
            name TEXT,
            qty REAL NOT NULL,
            unit_cost REAL NOT NULL DEFAULT 0,
            subtotal REAL NOT NULL DEFAULT 0
        )
    """)
    _ensure_column(cur, "crn_lines", "code",
                   "ALTER TABLE crn_lines ADD COLUMN code TEXT")
    _ensure_column(cur, "crn_lines", "name",
                   "ALTER TABLE crn_lines ADD COLUMN name TEXT")
    _ensure_column(cur, "crn_lines", "unit_cost",
                   "ALTER TABLE crn_lines ADD COLUMN unit_cost REAL NOT NULL DEFAULT 0")
    _ensure_column(cur, "crn_lines", "subtotal",
                   "ALTER TABLE crn_lines ADD COLUMN subtotal REAL NOT NULL DEFAULT 0")

    # ---- purchase orders ----
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            lpo_no TEXT UNIQUE NOT NULL,
            supplier TEXT NOT NULL,
            value REAL NOT NULL DEFAULT 0,
            expiry_date TEXT,
            approved INTEGER NOT NULL DEFAULT 0,
            received INTEGER NOT NULL DEFAULT 0
        )
    """)
    _ensure_column(cur, "purchase_orders", "received",
                   "ALTER TABLE purchase_orders ADD COLUMN received INTEGER NOT NULL DEFAULT 0")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchase_order_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            po_id INTEGER NOT NULL REFERENCES purchase_orders(id),
            barcode TEXT NOT NULL,
            code TEXT,
            name TEXT NOT NULL,
            qty REAL NOT NULL,
            pack_size REAL NOT NULL DEFAULT 1,
            total_qty REAL NOT NULL DEFAULT 0,
            packaging TEXT,
            notes TEXT,
            unit_cost REAL NOT NULL DEFAULT 0,
            subtotal REAL NOT NULL DEFAULT 0
        )
    """)
    _ensure_column(cur, "purchase_order_lines", "code",
                   "ALTER TABLE purchase_order_lines ADD COLUMN code TEXT")
    _ensure_column(cur, "purchase_order_lines", "pack_size",
                   "ALTER TABLE purchase_order_lines ADD COLUMN pack_size REAL DEFAULT 1")
    _ensure_column(cur, "purchase_order_lines", "total_qty",
                   "ALTER TABLE purchase_order_lines ADD COLUMN total_qty REAL DEFAULT 0")

    # ---- Seed data (first run only) ----
    cur.execute("SELECT COUNT(*) FROM products")
    if cur.fetchone()[0] == 0:
        seed_products = [
            ("USB-C Cable 1m", "Cables", 250.0, 40, "1001", "1001", "1ctn x 12pcs", 12, 120.0, 20, "%", 144.0, "Acme Electronics", "A1"),
            ("Wireless Mouse", "Peripherals", 900.0, 25, "1002", "1002", "1ctn x 10pcs", 10, 550.0, 25, "%", 687.5, "TechSupply Ltd", "B2"),
            ("HDMI Cable 2m", "Cables", 400.0, 60, "1003", "1003", "1ctn x 20pcs", 20, 220.0, 15, "%", 253.0, "Acme Electronics", "A2"),
            ("Phone Charger 20W", "Chargers", 700.0, 15, "1004", "1004", "1ctn x 24pcs", 24, 380.0, 30, "%", 494.0, "TechSupply Ltd", "C1"),
        ]
        cur.executemany("""
            INSERT INTO products
                (name, category, price, stock, barcode, code, packaging, pack_size,
                 cost_price, markup, markup_type, selling_price, supplier, shelf)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, seed_products)
        today = datetime.date.today().isoformat()
        for row in seed_products:
            stock = row[3]
            barcode = row[4]
            cur.execute("""
                INSERT INTO stock_ledger (barcode, date, transaction_type, stock_in, stock_out, balance, reference)
                VALUES (?, ?, 'Opening Stock', ?, 0, ?, NULL)
            """, (barcode, today, stock, stock))

    cur.execute("SELECT COUNT(*) FROM suppliers")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO suppliers (name) VALUES (?)",
                        [("Acme Electronics",), ("TechSupply Ltd",), ("Global Gadgets Co",)])

    cur.execute("SELECT COUNT(*) FROM departments")
    if cur.fetchone()[0] == 0:
        cats = {r["category"] for r in cur.execute(
            "SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category != ''"
        ).fetchall()}
        for name in sorted(cats):
            cur.execute("INSERT OR IGNORE INTO departments (name) VALUES (?)", (name,))

    cur.execute("SELECT COUNT(*) FROM admins")
    if cur.fetchone()[0] == 0:
        default_pw = hashlib.sha256("admin".encode("utf-8")).hexdigest()
        cur.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                    ("admin", default_pw))
        print("Seeded default admin account:  username='admin'  password='admin'  (CHANGE THIS)")

    conn.commit()
    conn.close()


def _lookup_product(conn, ident):
    if not ident:
        return None
    row = conn.execute("SELECT * FROM products WHERE barcode = ?", (ident,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM products WHERE code = ?", (ident,)).fetchone()
    return row


def _lookup_user_by_username(conn, username):
    if not username:
        return None
    u = username.strip().lower()
    return conn.execute(
        "SELECT * FROM users WHERE LOWER(username) = ?", (u,)).fetchone()


def _lookup_admin_by_username(conn, username):
    if not username:
        return None
    u = username.strip().lower()
    return conn.execute(
        "SELECT * FROM admins WHERE LOWER(username) = ?", (u,)).fetchone()


def product_row_to_dict(row):
    return {
        "id": row["id"], "name": row["name"], "category": row["category"],
        "price": row["price"], "stock": row["stock"], "barcode": row["barcode"],
        "code": row["code"], "packaging": row["packaging"],
        "pack_size": row["pack_size"] if "pack_size" in row.keys() else 1,
        "cost_price": row["cost_price"], "markup": row["markup"],
        "markup_type": row["markup_type"], "selling_price": row["selling_price"],
        "supplier": row["supplier"], "shelf": row["shelf"],
    }


def user_row_to_dict(row, include_hash=False):
    d = {
        "id": row["id"],
        "username": row["username"],
        "full_name": row["full_name"] if "full_name" in row.keys() else None,
        "branch": row["branch"] if "branch" in row.keys() else None,
        "phone": row["phone"] if "phone" in row.keys() else None,
        "email": row["email"] if "email" in row.keys() else None,
        "role": (row["role"] if "role" in row.keys() else "staff") or "staff",
        "active": bool(row["active"]) if "active" in row.keys() else True,
        "created_at": (row["created_at"] if "created_at" in row.keys() else None),
        "created_by": (row["created_by"] if "created_by" in row.keys() else None),
    }
    if include_hash:
        d["password_hash"] = row["password_hash"]
    return d


# ---------------------------------------------------------------------------
# Auth + roles
# ---------------------------------------------------------------------------

def _hash_pw(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _check_admin_auth():
    """Legacy: verify X-Admin-User / X-Admin-Pass headers against admins."""
    username = request.headers.get("X-Admin-User", "").strip()
    password = request.headers.get("X-Admin-Pass", "").strip()
    if not username or not password:
        return False, "Admin authorization required"
    conn = get_db()
    row = _lookup_admin_by_username(conn, username)
    conn.close()
    if row is None or _hash_pw(password) != row["password_hash"]:
        return False, "Invalid admin credentials"
    return True, None


def _identify_request_user():
    """Return (user_info or None, error string or None).

    Reads X-User / X-Pass (falling back to X-Admin-User / X-Admin-Pass for
    the admin panel).  Verifies credentials against admins first, then
    users.  Returns dict with id, username, role, kind, full_name.
    """
    username = (request.headers.get("X-User")
                or request.headers.get("X-Admin-User") or "").strip()
    password = (request.headers.get("X-Pass")
                or request.headers.get("X-Admin-Pass") or "").strip()
    if not username or not password:
        return None, "Credentials required"

    conn = get_db()
    # Admin?
    admin = _lookup_admin_by_username(conn, username)
    if admin is not None and _hash_pw(password) == admin["password_hash"]:
        conn.close()
        return {
            "id": admin["id"],
            "username": admin["username"],
            "full_name": admin["username"],
            "role": "admin",
            "kind": "admin",
        }, None

    # Branch user?
    user = _lookup_user_by_username(conn, username)
    if user is not None:
        if not (user["active"] if "active" in user.keys() else 1):
            conn.close()
            return None, "Account is disabled"
        if _hash_pw(password) == user["password_hash"]:
            payload = user_row_to_dict(user)
            conn.close()
            return {
                "id": payload["id"],
                "username": payload["username"],
                "full_name": payload.get("full_name") or payload["username"],
                "role": payload.get("role") or "staff",
                "kind": "user",
            }, None

    conn.close()
    return None, "Invalid credentials"


def _require_role(min_role):
    """Enforce a minimum role on the current request.

    Returns (ok, err, user_info).  `ok` is True if the credentials are
    valid AND the role rank >= the required rank.
    """
    user_info, err = _identify_request_user()
    if user_info is None:
        return False, err or "Authentication failed", None

    role = (user_info.get("role") or "staff").lower()
    if role not in ROLE_RANK:
        role = "staff"

    if ROLE_RANK[role] < ROLE_RANK.get(min_role, 0):
        return False, f"Requires {min_role} role or higher", user_info

    return True, None, user_info


@app.route("/usernames", methods=["GET"])
def list_usernames():
    q = (request.args.get("q") or "").strip().lower()
    conn = get_db()
    names = []
    for r in conn.execute("SELECT username FROM admins ORDER BY username"):
        names.append(r["username"])
    for r in conn.execute("SELECT username, active FROM users ORDER BY username"):
        if "active" in r.keys() and not r["active"]:
            continue
        names.append(r["username"])
    conn.close()
    if q:
        names = [n for n in names if q in n.lower()]
    return jsonify(sorted(set(names)))


@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    username_raw = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username_raw or not password:
        return jsonify({"status": "error",
                        "message": "Username and password are required"}), 400

    conn = get_db()
    row = _lookup_admin_by_username(conn, username_raw)
    if row is not None and _hash_pw(password) == row["password_hash"]:
        conn.close()
        return jsonify({
            "status": "ok",
            "kind": "admin",
            "username": row["username"],
            "full_name": row["username"],
            "branch": None,
            "role": "admin",
        }), 200

    row = _lookup_user_by_username(conn, username_raw)
    if row is not None:
        if not (row["active"] if "active" in row.keys() else 1):
            conn.close()
            return jsonify({"status": "error",
                            "message": "Account is disabled. Contact HQ."}), 403
        if _hash_pw(password) == row["password_hash"]:
            payload = user_row_to_dict(row)
            conn.close()
            return jsonify({
                "status": "ok",
                "kind": "user",
                "username": payload["username"],
                "full_name": payload["full_name"] or payload["username"],
                "branch": payload["branch"],
                "role": payload["role"] or "staff",
            }), 200

    conn.close()
    return jsonify({"status": "error",
                    "message": "Invalid username or password"}), 401


@app.route("/me", methods=["GET"])
def me():
    """Return the current authenticated user's identity + role."""
    user_info, err = _identify_request_user()
    if user_info is None:
        return jsonify({"status": "error", "message": err or "Unauthorized"}), 401
    return jsonify({"status": "ok", **user_info})


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
    ok, err, _ = _require_role("manager")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401

    data = request.get_json(force=True)
    required = ("name", "category", "price", "stock", "barcode")
    if not all(k in data for k in required):
        return f"Missing one of required fields: {required}", 400

    barcode = data["barcode"]
    code = (data.get("code") or barcode)

    try:
        pack_size = float(data.get("pack_size", 1) or 1)
        if pack_size <= 0:
            pack_size = 1
    except (TypeError, ValueError):
        pack_size = 1

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO products
                (name, category, price, stock, barcode, code, packaging, pack_size,
                 cost_price, markup, markup_type, selling_price, supplier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data["name"], data["category"], data["price"], data["stock"],
            barcode, code, data.get("packaging"), pack_size,
            data.get("cost_price"), data.get("markup"),
            data.get("markup_type", "%"),
            data.get("selling_price", data["price"]), data.get("supplier"),
        ))
        if data.get("category"):
            conn.execute("INSERT OR IGNORE INTO departments (name) VALUES (?)", (data["category"],))

        initial_stock = float(data["stock"]) if data["stock"] else 0
        if initial_stock:
            today = datetime.date.today().isoformat()
            conn.execute("""
                INSERT INTO stock_ledger (barcode, date, transaction_type, stock_in, stock_out, balance, reference)
                VALUES (?, ?, 'Opening Stock', ?, 0, ?, NULL)
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
# Stock ledger + adjustment
# ---------------------------------------------------------------------------

@app.route("/stock_ledger", methods=["GET"])
def stock_ledger():
    barcode = request.args.get("barcode")
    from_date = request.args.get("from_date")
    to_date = request.args.get("to_date")

    conn = get_db()
    try:
        if barcode:
            prod = _lookup_product(conn, barcode)
            if prod is not None:
                barcode = prod["barcode"]

        query = "SELECT * FROM stock_ledger WHERE 1=1"
        params = []
        if barcode:
            query += " AND barcode = ?"
            params.append(barcode)
        if from_date:
            query += " AND date >= ?"
            params.append(from_date)
        if to_date:
            query += " AND date <= ?"
            params.append(to_date)
        query += " ORDER BY date, id"

        rows = conn.execute(query, params).fetchall()

        codes = {}
        if rows:
            all_barcodes = list({r["barcode"] for r in rows})
            placeholders = ",".join("?" for _ in all_barcodes)
            for p in conn.execute(
                f"SELECT barcode, code FROM products WHERE barcode IN ({placeholders})",
                all_barcodes):
                codes[p["barcode"]] = p["code"] or p["barcode"]
    finally:
        conn.close()

    return jsonify([{
        "date": r["date"],
        "transaction_type": r["transaction_type"],
        "barcode": r["barcode"],
        "code": codes.get(r["barcode"], r["barcode"]),
        "reference": (r["reference"] if "reference" in r.keys() else None),
        "stock_in": r["stock_in"], "stock_out": r["stock_out"],
        "balance": r["balance"],
    } for r in rows])


@app.route("/stock_movement_summary", methods=["GET"])
def stock_movement_summary():
    ident = request.args.get("barcode")
    if not ident:
        return jsonify({"status": "error", "message": "barcode is required"}), 400

    conn = get_db()
    try:
        prod = _lookup_product(conn, ident)
        if prod is None:
            return jsonify({"status": "error",
                            "message": f"No product found for code '{ident}'"}), 404
        barcode = prod["barcode"]
        today = datetime.date.today()

        def sum_since(days):
            start = (today - datetime.timedelta(days=days - 1)).isoformat()
            row = conn.execute(
                "SELECT COALESCE(SUM(ABS(stock_in) + stock_out), 0) AS moved "
                "FROM stock_ledger WHERE barcode = ? AND date >= ?",
                (barcode, start)).fetchone()
            return float(row["moved"] or 0)

        return jsonify({
            "barcode": barcode,
            "code": prod["code"] or prod["barcode"],
            "name": prod["name"],
            "days7":  sum_since(7),
            "days14": sum_since(14),
            "days21": sum_since(21),
            "days30": sum_since(30),
        })
    finally:
        conn.close()


@app.route("/stock_adjust", methods=["POST"])
def stock_adjust():
    ok, err, _ = _require_role("manager")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401

    data = request.get_json(force=True) or {}
    ident = str(data.get("barcode", "")).strip()
    reason = str(data.get("reason", "")).strip() or "Adjustment"
    notes = str(data.get("notes", "")).strip()
    try:
        qty_delta = float(data.get("qty_delta"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "qty_delta must be a number"}), 400
    if qty_delta == 0:
        return jsonify({"status": "error", "message": "qty_delta cannot be zero"}), 400
    if not ident:
        return jsonify({"status": "error", "message": "barcode is required"}), 400

    conn = get_db()
    cur = conn.cursor()
    product = _lookup_product(conn, ident)
    if product is None:
        conn.close()
        return jsonify({"status": "error", "message": f"No product found for code '{ident}'"}), 404

    current_stock = product["stock"]
    new_stock = current_stock + qty_delta
    if new_stock < 0:
        conn.close()
        return jsonify({"status": "error",
                        "message": f"Adjustment would make stock negative. "
                                   f"Current {current_stock}, delta {qty_delta}."}), 409

    today = datetime.date.today().isoformat()
    cur.execute("UPDATE products SET stock = ? WHERE id = ?", (new_stock, product["id"]))
    cur.execute("""
        INSERT INTO stock_ledger (barcode, date, transaction_type,
                                   stock_in, stock_out, balance, reference)
        VALUES (?, ?, ?, ?, 0, ?, NULL)
    """, (product["barcode"], today, reason, qty_delta, new_stock))
    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok", "barcode": product["barcode"],
        "short_code": product["code"] or product["barcode"],
        "name": product["name"],
        "previous_stock": current_stock, "new_stock": new_stock,
        "qty_delta": qty_delta, "reason": reason, "notes": notes, "date": today,
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
        "id": r["id"], "total": r["total"], "date": r["date"],
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
        try:
            qty = float(line.get("quantity"))
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
            return jsonify({"status": "error",
                            "message": f"Not enough stock for '{row['name']}' "
                                       f"(barcode {row['barcode']}). "
                                       f"In stock: {row['stock']}, requested: {qty}"}), 409
        price_each = line.get("price_each")
        try:
            price_each = float(price_each) if price_each is not None else float(row["price"])
        except (TypeError, ValueError):
            price_each = float(row["price"])
        resolved.append({
            "product_id": row["id"], "barcode": row["barcode"], "name": row["name"],
            "qty": qty, "price_each": price_each,
            "subtotal": round(qty * price_each, 2),
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
        cur.execute("""
            INSERT INTO stock_ledger (barcode, date, transaction_type, stock_in, stock_out, balance, reference)
            VALUES (?, ?, 'Sale', 0, ?, ?, NULL)
        """, (r["barcode"], today, r["qty"], r["new_stock"]))

    conn.commit()
    conn.close()
    return jsonify({
        "sale_id": sale_id, "total": total, "date": today,
        "lines": [{
            "product_id": r["product_id"], "barcode": r["barcode"], "name": r["name"],
            "qty": r["qty"], "price_each": r["price_each"], "subtotal": r["subtotal"],
        } for r in resolved],
    }), 201


@app.route("/sales/<int:sale_id>", methods=["GET"])
def get_sale(sale_id):
    conn = get_db()
    header = conn.execute("SELECT * FROM sales WHERE id = ?", (sale_id,)).fetchone()
    if header is None:
        conn.close()
        return jsonify({"status": "error", "message": "Sale not found"}), 404
    lines = conn.execute("SELECT * FROM sale_lines WHERE sale_id = ? ORDER BY id",
                         (sale_id,)).fetchall()
    conn.close()
    return jsonify({
        "id": header["id"], "total": header["total"], "date": header["date"],
        "cashier": header["cashier"] if "cashier" in header.keys() else None,
        "payment_method": header["payment_method"] if "payment_method" in header.keys() else None,
        "phone": header["phone"] if "phone" in header.keys() else None,
        "amount_received": header["amount_received"] if "amount_received" in header.keys() else None,
        "lines": [{
            "product_id": r["product_id"], "barcode": r["barcode"], "name": r["name"],
            "qty": r["qty"], "price_each": r["price_each"], "subtotal": r["subtotal"],
        } for r in lines],
    })


# ---------------------------------------------------------------------------
# Suppliers + Departments
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
# Purchase orders
# ---------------------------------------------------------------------------

def _po_row_to_dict(row, include_lines=False, conn=None):
    d = {
        "id": row["id"], "date": row["date"], "lpo_no": row["lpo_no"],
        "supplier": row["supplier"], "value": row["value"],
        "expiry_date": row["expiry_date"],
        "approved": bool(row["approved"]),
        "received": bool(row["received"]) if "received" in row.keys() else False,
    }
    if include_lines and conn is not None:
        lines = conn.execute(
            "SELECT * FROM purchase_order_lines WHERE po_id = ? ORDER BY id",
            (row["id"],)).fetchall()
        codes = {}
        if lines:
            barcodes = list({l["barcode"] for l in lines})
            placeholders = ",".join("?" for _ in barcodes)
            for p in conn.execute(
                f"SELECT barcode, code FROM products WHERE barcode IN ({placeholders})",
                barcodes):
                codes[p["barcode"]] = p["code"] or p["barcode"]

        d["lines"] = []
        for l in lines:
            code_val = l["code"] if "code" in l.keys() and l["code"] else None
            if not code_val:
                code_val = codes.get(l["barcode"], l["barcode"])
            d["lines"].append({
                "barcode": l["barcode"], "code": code_val, "name": l["name"],
                "qty": l["qty"], "pack_size": l["pack_size"],
                "total_qty": l["total_qty"], "packaging": l["packaging"],
                "notes": l["notes"], "unit_cost": l["unit_cost"],
                "subtotal": l["subtotal"],
            })
    return d


def _next_lpo_no(cur):
    row = cur.execute("SELECT MAX(id) FROM purchase_orders").fetchone()
    next_id = (row[0] or 0) + 1
    return f"LPO-{next_id:05d}"


@app.route("/purchase_orders", methods=["GET"])
def list_purchase_orders():
    only_receivable = request.args.get("receivable") == "1"
    conn = get_db()
    if only_receivable:
        rows = conn.execute(
            "SELECT * FROM purchase_orders "
            "WHERE approved = 1 AND received = 0 "
            "ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM purchase_orders ORDER BY id DESC").fetchall()
    result = [_po_row_to_dict(r, include_lines=True, conn=conn) for r in rows]
    conn.close()
    return jsonify(result)


@app.route("/purchase_orders/<int:po_id>", methods=["GET"])
def get_purchase_order(po_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"status": "error", "message": "Order not found"}), 404
    result = _po_row_to_dict(row, include_lines=True, conn=conn)
    conn.close()
    return jsonify(result)


@app.route("/purchase_orders", methods=["POST"])
def create_purchase_order():
    data = request.get_json(force=True) or {}
    supplier = (data.get("supplier") or "").strip()
    date = (data.get("date") or datetime.date.today().isoformat())
    lines_in = data.get("lines") or []

    if not supplier:
        return jsonify({"status": "error", "message": "Supplier is required"}), 400
    if not lines_in:
        return jsonify({"status": "error", "message": "At least one line is required"}), 400

    conn = get_db()
    cur = conn.cursor()

    resolved = []
    for line in lines_in:
        ident = str(line.get("barcode", "")).strip()
        product = _lookup_product(cur, ident)
        if product is None:
            conn.close()
            return jsonify({"status": "error",
                            "message": f"No product found for code '{ident}'"}), 400
        try:
            qty = float(line.get("qty"))
        except (TypeError, ValueError):
            conn.close()
            return jsonify({"status": "error",
                            "message": f"Invalid qty for '{ident}'"}), 400
        if qty <= 0:
            conn.close()
            return jsonify({"status": "error",
                            "message": f"qty must be > 0 for '{ident}'"}), 400

        pack_size = float(product["pack_size"] or 1)
        if pack_size <= 0:
            pack_size = 1
        total_qty = qty * pack_size

        unit_cost = float(product["cost_price"] or 0)
        subtotal = total_qty * unit_cost

        resolved.append({
            "barcode": product["barcode"],
            "code": product["code"] or product["barcode"],
            "name": product["name"],
            "qty": qty,
            "pack_size": pack_size,
            "total_qty": total_qty,
            "packaging": line.get("packaging"),
            "notes": line.get("notes") or "",
            "unit_cost": unit_cost,
            "subtotal": subtotal,
        })

    total_value = round(sum(r["subtotal"] for r in resolved), 2)
    expiry = (datetime.date.fromisoformat(date) +
              datetime.timedelta(days=ORDER_EXPIRY_DAYS)).isoformat()
    lpo_no = _next_lpo_no(cur)

    cur.execute("""
        INSERT INTO purchase_orders (date, lpo_no, supplier, value, expiry_date, approved, received)
        VALUES (?, ?, ?, ?, ?, 0, 0)
    """, (date, lpo_no, supplier, total_value, expiry))
    po_id = cur.lastrowid

    for r in resolved:
        cur.execute("""
            INSERT INTO purchase_order_lines
                (po_id, barcode, code, name, qty, pack_size, total_qty,
                 packaging, notes, unit_cost, subtotal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (po_id, r["barcode"], r["code"], r["name"], r["qty"], r["pack_size"],
              r["total_qty"], r["packaging"], r["notes"], r["unit_cost"], r["subtotal"]))

    conn.commit()
    conn.close()
    return jsonify({
        "status": "ok", "id": po_id, "lpo_no": lpo_no, "date": date,
        "supplier": supplier, "value": total_value, "expiry_date": expiry,
    }), 201


@app.route("/purchase_orders/<int:po_id>/approve", methods=["PATCH"])
def approve_purchase_order(po_id):
    # Admin only — manager cannot approve.
    ok, err, _ = _require_role("admin")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401

    data = request.get_json(force=True) or {}
    approved = bool(data.get("approved", True))

    conn = get_db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"status": "error", "message": "Order not found"}), 404

    cur.execute("UPDATE purchase_orders SET approved = ? WHERE id = ?",
                (1 if approved else 0, po_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "id": po_id, "approved": approved}), 200


@app.route("/purchase_orders/<int:po_id>/receive", methods=["PATCH"])
def mark_po_received(po_id):
    conn = get_db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"status": "error", "message": "Order not found"}), 404
    if not row["approved"]:
        conn.close()
        return jsonify({"status": "error",
                        "message": "Order must be approved before receiving"}), 409
    cur.execute("UPDATE purchase_orders SET received = 1 WHERE id = ?", (po_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "id": po_id, "received": True}), 200


# ---------------------------------------------------------------------------
# GRNs
# ---------------------------------------------------------------------------

@app.route("/grn", methods=["POST"])
def receive_grn():
    data = request.get_json(force=True) or {}
    supplier = (data.get("supplier") or "").strip()
    date = (data.get("date") or datetime.date.today().isoformat())
    lines = (data.get("lines") or [])
    po_id = data.get("purchase_order_id")
    user = (data.get("user") or "").strip() or None

    if not supplier:
        return "Supplier is required", 400
    if not lines:
        return "At least one line is required", 400

    conn = get_db()
    cur = conn.cursor()

    resolved_lines = []
    for line in lines:
        ident = str(line.get("barcode") or line.get("code") or "").strip()
        row = _lookup_product(cur, ident)
        if row is None:
            conn.close()
            return f"No product found for code '{ident}'", 400
        try:
            qty = float(line.get("qty"))
        except (TypeError, ValueError):
            conn.close()
            return f"Invalid qty for '{ident}'", 400
        if qty <= 0:
            conn.close()
            return f"qty must be > 0 for '{ident}'", 400

        pack_size = float(row["pack_size"] or 1)
        if pack_size <= 0:
            pack_size = 1
        total_qty = qty * pack_size

        unit_cost = float(line.get("unit_cost") or 0)
        line_value = total_qty * unit_cost

        line = dict(line)
        line["barcode"] = row["barcode"]
        line["code"] = row["code"] or row["barcode"]
        line["qty"] = qty
        line["pack_size"] = pack_size
        line["total_qty"] = total_qty
        line["line_value"] = line_value
        resolved_lines.append(line)
    lines = resolved_lines

    total_value = sum(line["line_value"] for line in lines)
    cur.execute("""INSERT INTO grns
                     (supplier, date, total, purchase_order_id, user)
                   VALUES (?, ?, ?, ?, ?)""",
                (supplier, date, total_value, po_id, user))
    grn_id = cur.lastrowid

    for line in lines:
        barcode = line["barcode"]
        qty = line["qty"]
        total_qty = line["total_qty"]
        pack_size = line["pack_size"]
        unit_cost = line["unit_cost"]
        packaging = line.get("packaging")
        markup = line.get("markup")
        markup_type = line.get("markup_type")
        selling_price = line.get("selling_price")

        cur.execute("""
            INSERT INTO grn_lines (grn_id, barcode, qty, total_qty, packaging,
                                    pack_size, unit_cost, markup, markup_type, selling_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (grn_id, barcode, qty, total_qty, packaging, pack_size,
              unit_cost, markup, markup_type, selling_price))

        product = cur.execute("SELECT stock FROM products WHERE barcode = ?",
                              (barcode,)).fetchone()
        new_stock = product["stock"] + total_qty

        update_fields = ["stock = ?", "cost_price = ?"]
        update_values = [new_stock, unit_cost]
        if packaging:
            update_fields.append("packaging = ?"); update_values.append(packaging)
        if pack_size:
            update_fields.append("pack_size = ?"); update_values.append(pack_size)
        if markup is not None:
            update_fields.append("markup = ?"); update_values.append(markup)
        if markup_type is not None:
            update_fields.append("markup_type = ?"); update_values.append(markup_type)
        if selling_price is not None:
            update_fields.append("selling_price = ?"); update_values.append(selling_price)
            update_fields.append("price = ?"); update_values.append(selling_price)
        update_fields.append("supplier = ?"); update_values.append(supplier)
        update_values.append(barcode)
        cur.execute(f"UPDATE products SET {', '.join(update_fields)} WHERE barcode = ?",
                    update_values)

        cur.execute("""
            INSERT INTO stock_ledger (barcode, date, transaction_type, stock_in, stock_out, balance, reference)
            VALUES (?, ?, 'GRN Receive', ?, 0, ?, NULL)
        """, (barcode, date, total_qty, new_stock))

    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "grn_id": grn_id}), 201


@app.route("/grns", methods=["GET"])
def list_grns():
    conn = get_db()
    rows = conn.execute("SELECT * FROM grns ORDER BY id DESC").fetchall()

    counts = {}
    if rows:
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        for row in conn.execute(
            f"SELECT grn_id, COUNT(*) AS n FROM grn_lines "
            f"WHERE grn_id IN ({placeholders}) GROUP BY grn_id", ids):
            counts[row["grn_id"]] = row["n"]
    conn.close()

    return jsonify([{
        "id": r["id"], "supplier": r["supplier"], "date": r["date"],
        "total": r["total"],
        "purchase_order_id": (r["purchase_order_id"]
                              if "purchase_order_id" in r.keys() else None),
        "user": (r["user"] if "user" in r.keys() else None),
        "lines_count": counts.get(r["id"], 0),
    } for r in rows])


@app.route("/grns/<int:grn_id>", methods=["GET"])
def get_grn(grn_id):
    conn = get_db()
    header = conn.execute("SELECT * FROM grns WHERE id = ?", (grn_id,)).fetchone()
    if header is None:
        conn.close()
        return jsonify({"status": "error", "message": "GRN not found"}), 404

    lines = conn.execute(
        "SELECT * FROM grn_lines WHERE grn_id = ? ORDER BY id",
        (grn_id,)).fetchall()

    codes = {}
    names = {}
    if lines:
        barcodes = list({l["barcode"] for l in lines})
        placeholders = ",".join("?" for _ in barcodes)
        for p in conn.execute(
            f"SELECT barcode, code, name FROM products WHERE barcode IN ({placeholders})",
            barcodes):
            codes[p["barcode"]] = p["code"] or p["barcode"]
            names[p["barcode"]] = p["name"]

    conn.close()

    return jsonify({
        "id": header["id"], "supplier": header["supplier"],
        "date": header["date"], "total": header["total"],
        "purchase_order_id": (header["purchase_order_id"]
                              if "purchase_order_id" in header.keys() else None),
        "user": (header["user"] if "user" in header.keys() else None),
        "lines": [{
            "barcode": l["barcode"],
            "code": codes.get(l["barcode"], l["barcode"]),
            "name": names.get(l["barcode"], "-"),
            "qty": l["qty"], "total_qty": l["total_qty"],
            "packaging": l["packaging"], "pack_size": l["pack_size"],
            "unit_cost": l["unit_cost"],
            "subtotal": round(float(l["total_qty"] or 0) * float(l["unit_cost"] or 0), 2),
        } for l in lines],
    })


# ---------------------------------------------------------------------------
# Credit Notes (CRNs)
# ---------------------------------------------------------------------------

def _crn_row_to_dict(row, include_lines=False, conn=None):
    d = {
        "id": row["id"], "date": row["date"],
        "reference": row["reference"] if "reference" in row.keys() else None,
        "reason": row["reason"] if "reason" in row.keys() else None,
        "user": row["user"] if "user" in row.keys() else None,
        "total_lines": row["total_lines"] if "total_lines" in row.keys() else 0,
        "total_qty": row["total_qty"] if "total_qty" in row.keys() else 0,
        "value": row["value"] if "value" in row.keys() else 0,
        "received": bool(row["received"]) if "received" in row.keys() else False,
        "received_date": (row["received_date"]
                          if "received_date" in row.keys() else None),
    }
    if include_lines and conn is not None:
        lines = conn.execute(
            "SELECT * FROM crn_lines WHERE crn_id = ? ORDER BY id",
            (row["id"],)).fetchall()
        d["lines"] = [{
            "barcode": l["barcode"],
            "code": l["code"] if "code" in l.keys() and l["code"] else l["barcode"],
            "name": l["name"] if "name" in l.keys() else "-",
            "qty": l["qty"],
            "unit_cost": l["unit_cost"] if "unit_cost" in l.keys() else 0,
            "subtotal": l["subtotal"] if "subtotal" in l.keys() else 0,
        } for l in lines]
    return d


@app.route("/crn", methods=["POST"])
def create_crn():
    # Admin only — CRNs are generated at HQ.
    ok, err, _ = _require_role("admin")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401

    data = request.get_json(force=True) or {}
    date = (data.get("date") or datetime.date.today().isoformat())
    reference = (data.get("reference") or "").strip() or None
    reason = (data.get("reason") or "").strip() or None
    user = (data.get("user") or "").strip() or None
    lines_in = data.get("lines") or []

    if not lines_in:
        return jsonify({"status": "error", "message": "At least one line is required"}), 400

    conn = get_db()
    cur = conn.cursor()

    resolved = []
    for line in lines_in:
        ident = str(line.get("barcode") or line.get("code") or "").strip()
        product = _lookup_product(cur, ident)
        if product is None:
            conn.close()
            return jsonify({"status": "error",
                            "message": f"No product found for code '{ident}'"}), 400
        try:
            qty = float(line.get("qty"))
        except (TypeError, ValueError):
            conn.close()
            return jsonify({"status": "error",
                            "message": f"Invalid qty for '{ident}'"}), 400
        if qty <= 0:
            conn.close()
            return jsonify({"status": "error",
                            "message": f"qty must be > 0 for '{ident}'"}), 400

        unit_cost = float(product["cost_price"] or 0)
        subtotal = round(qty * unit_cost, 2)

        resolved.append({
            "barcode": product["barcode"],
            "code": product["code"] or product["barcode"],
            "name": product["name"],
            "qty": qty, "unit_cost": unit_cost, "subtotal": subtotal,
        })

    total_qty = round(sum(r["qty"] for r in resolved), 4)
    total_value = round(sum(r["subtotal"] for r in resolved), 2)

    cur.execute("""
        INSERT INTO crns (date, reference, reason, user,
                          total_lines, total_qty, value, received)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
    """, (date, reference, reason, user, len(resolved), total_qty, total_value))
    crn_id = cur.lastrowid

    for r in resolved:
        cur.execute("""
            INSERT INTO crn_lines (crn_id, barcode, code, name, qty, unit_cost, subtotal)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (crn_id, r["barcode"], r["code"], r["name"],
              r["qty"], r["unit_cost"], r["subtotal"]))

    conn.commit()
    conn.close()
    return jsonify({
        "status": "ok", "id": crn_id, "date": date,
        "reference": reference, "lines": len(resolved),
        "total_qty": total_qty, "value": total_value,
    }), 201


@app.route("/crns", methods=["GET"])
def list_crns():
    show_all = request.args.get("all") == "1"
    conn = get_db()
    if show_all:
        rows = conn.execute("SELECT * FROM crns ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM crns WHERE received = 0 ORDER BY id DESC").fetchall()
    result = [_crn_row_to_dict(r) for r in rows]
    conn.close()
    return jsonify(result)


@app.route("/crns/<int:crn_id>", methods=["GET"])
def get_crn(crn_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM crns WHERE id = ?", (crn_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"status": "error", "message": "CRN not found"}), 404
    result = _crn_row_to_dict(row, include_lines=True, conn=conn)
    conn.close()
    return jsonify(result)


@app.route("/crns/<int:crn_id>/receive", methods=["PATCH"])
def receive_crn(crn_id):
    # staff and above — any logged-in user.
    ok, err, _ = _require_role("staff")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401

    conn = get_db()
    cur = conn.cursor()

    crn = cur.execute("SELECT * FROM crns WHERE id = ?", (crn_id,)).fetchone()
    if crn is None:
        conn.close()
        return jsonify({"status": "error", "message": "CRN not found"}), 404
    if crn["received"]:
        conn.close()
        return jsonify({"status": "error",
                        "message": "CRN has already been received"}), 409

    lines = cur.execute(
        "SELECT * FROM crn_lines WHERE crn_id = ? ORDER BY id",
        (crn_id,)).fetchall()
    if not lines:
        conn.close()
        return jsonify({"status": "error",
                        "message": "CRN has no lines"}), 400

    pending = []
    for l in lines:
        product = cur.execute("SELECT * FROM products WHERE barcode = ?",
                              (l["barcode"],)).fetchone()
        if product is None:
            conn.close()
            return jsonify({"status": "error",
                            "message": f"Product with barcode {l['barcode']} "
                                       f"no longer exists"}), 409
        qty = float(l["qty"] or 0)
        current = float(product["stock"] or 0)
        if qty > current:
            conn.close()
            return jsonify({
                "status": "error",
                "message": (f"Not enough stock for {l['code'] or l['barcode']} "
                            f"({l['name'] or ''}). "
                            f"Available: {current:g}, required: {qty:g}.")
            }), 409
        pending.append((product, qty))

    today = datetime.date.today().isoformat()
    reference = f"CRN-{crn_id:05d}"

    for product, qty in pending:
        new_stock = float(product["stock"] or 0) - qty
        cur.execute("UPDATE products SET stock = ? WHERE id = ?",
                    (new_stock, product["id"]))
        cur.execute("""
            INSERT INTO stock_ledger
                (barcode, date, transaction_type, stock_in, stock_out, balance, reference)
            VALUES (?, ?, 'CREDIT NOT B', ?, 0, ?, ?)
        """, (product["barcode"], today, -qty, new_stock, reference))

    cur.execute("UPDATE crns SET received = 1, received_date = ? WHERE id = ?",
                (today, crn_id))
    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok", "id": crn_id,
        "received_date": today, "lines": len(pending),
    }), 200


# ---------------------------------------------------------------------------
# Users (branch staff) — admin only
# ---------------------------------------------------------------------------

@app.route("/users", methods=["GET"])
def list_users():
    ok, err, _ = _require_role("admin")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401
    conn = get_db()
    rows = conn.execute("SELECT * FROM users ORDER BY LOWER(username)").fetchall()
    conn.close()
    return jsonify([user_row_to_dict(r) for r in rows])


@app.route("/users", methods=["POST"])
def create_user():
    ok, err, admin_info = _require_role("admin")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401

    data = request.get_json(force=True) or {}
    username_raw = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username_raw or not password:
        return jsonify({"status": "error",
                        "message": "username and password are required"}), 400

    username = username_raw.lower()

    conn = get_db()
    try:
        existing = _lookup_user_by_username(conn, username)
        if existing is not None:
            conn.close()
            return jsonify({"status": "error",
                            "message": f"Username '{username_raw}' already exists"}), 409

        conn.execute("""
            INSERT INTO users
                (username, full_name, password_hash, branch, phone, email,
                 role, active, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            username,
            (data.get("full_name") or "").strip() or None,
            _hash_pw(password),
            (data.get("branch") or "").strip() or None,
            (data.get("phone") or "").strip() or None,
            (data.get("email") or "").strip() or None,
            (data.get("role") or "staff").strip() or "staff",
            1 if data.get("active", True) else 0,
            datetime.date.today().isoformat(),
            admin_info.get("username") if admin_info else None,
        ))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"status": "error",
                        "message": f"Username '{username_raw}' already exists"}), 409
    conn.close()
    return jsonify({"status": "ok"}), 201


@app.route("/users/<int:user_id>", methods=["GET"])
def get_user(user_id):
    ok, err, _ = _require_role("admin")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row is None:
        return jsonify({"status": "error", "message": "User not found"}), 404
    return jsonify(user_row_to_dict(row))


@app.route("/users/<int:user_id>", methods=["PATCH"])
def update_user(user_id):
    ok, err, _ = _require_role("admin")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401

    data = request.get_json(force=True) or {}
    conn = get_db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"status": "error", "message": "User not found"}), 404

    fields = []
    values = []

    if "username" in data:
        new_name_raw = (data.get("username") or "").strip()
        if new_name_raw:
            new_name = new_name_raw.lower()
            existing = _lookup_user_by_username(conn, new_name)
            if existing is not None and existing["id"] != user_id:
                conn.close()
                return jsonify({"status": "error",
                                "message": f"Username '{new_name_raw}' already exists"}), 409
            fields.append("username = ?")
            values.append(new_name)

    for key in ("full_name", "branch", "phone", "email", "role"):
        if key in data:
            fields.append(f"{key} = ?")
            values.append((data.get(key) or "").strip() or None)

    if "active" in data:
        fields.append("active = ?")
        values.append(1 if data.get("active") else 0)

    if data.get("password"):
        fields.append("password_hash = ?")
        values.append(_hash_pw((data.get("password") or "").strip()))

    if not fields:
        conn.close()
        return jsonify({"status": "error", "message": "Nothing to update"}), 400

    values.append(user_id)
    try:
        cur.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        return jsonify({"status": "error", "message": str(e)}), 409
    conn.close()
    return jsonify({"status": "ok", "id": user_id}), 200


@app.route("/users/<int:user_id>", methods=["DELETE"])
def deactivate_user(user_id):
    ok, err, _ = _require_role("admin")
    if not ok:
        return jsonify({"status": "error", "message": err}), 401
    conn = get_db()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"status": "error", "message": "User not found"}), 404
    cur.execute("UPDATE users SET active = 0 WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "id": user_id, "active": False}), 200


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000, threaded=True)