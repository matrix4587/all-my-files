import sqlite3
from datetime import datetime

DB = "pos.db"

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT,
        role TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        price REAL,
        stock INTEGER,
        category TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        total REAL,
        payment REAL,
        change_due REAL,
        cashier TEXT,
        created_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER,
        product_id INTEGER,
        name TEXT,
        price REAL,
        qty INTEGER
    )""")

    c.execute("INSERT OR IGNORE INTO users (username,password,role) VALUES ('admin','admin','admin')")
    c.execute("INSERT OR IGNORE INTO users (username,password,role) VALUES ('cashier','1234','cashier')")

    c.execute("SELECT COUNT(*) FROM products")
    if c.fetchone()[0] == 0:
        sample = [
            ("Coffee", 2.50, 100, "Drinks"),
            ("Tea", 2.00, 100, "Drinks"),
            ("Sandwich", 5.00, 50, "Food"),
            ("Cake Slice", 3.50, 30, "Food"),
            ("Water Bottle", 1.50, 200, "Drinks"),
        ]
        c.executemany("INSERT INTO products (name,price,stock,category) VALUES (?,?,?,?)", sample)

    conn.commit()
    conn.close()

# ---------- Auth ----------
def authenticate(username, password):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM users WHERE username=? AND password=?",
        (username, password)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

# ---------- Products ----------
def get_products(search=""):
    conn = get_conn()
    if search:
        rows = conn.execute(
            "SELECT * FROM products WHERE name LIKE ?", (f"%{search}%",)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM products").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_product(name, price, stock, category):
    conn = get_conn()
    conn.execute("INSERT INTO products (name,price,stock,category) VALUES (?,?,?,?)",
                 (name, price, stock, category))
    conn.commit()
    conn.close()

def update_product(pid, name, price, stock, category):
    conn = get_conn()
    conn.execute("UPDATE products SET name=?,price=?,stock=?,category=? WHERE id=?",
                 (name, price, stock, category, pid))
    conn.commit()
    conn.close()

def delete_product(pid):
    conn = get_conn()
    conn.execute("DELETE FROM products WHERE id=?", (pid,))
    conn.commit()
    conn.close()

# ---------- Sales ----------
def checkout(items, payment, cashier):
    """items = list of {id, name, price, qty}"""
    total = sum(i["price"] * i["qty"] for i in items)
    if payment < total:
        raise ValueError("Insufficient payment")

    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT INTO sales (total,payment,change_due,cashier,created_at) VALUES (?,?,?,?,?)",
              (total, payment, payment - total, cashier, datetime.now().isoformat()))
    sale_id = c.lastrowid
    for i in items:
        c.execute("INSERT INTO sale_items (sale_id,product_id,name,price,qty) VALUES (?,?,?,?,?)",
                  (sale_id, i["id"], i["name"], i["price"], i["qty"]))
        c.execute("UPDATE products SET stock = stock - ? WHERE id=?", (i["qty"], i["id"]))
    conn.commit()
    conn.close()
    return sale_id, total, payment - total

def get_sales(limit=100):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM sales ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_dashboard():
    conn = get_conn()
    c = conn.cursor()
    total = c.execute("SELECT COALESCE(SUM(total),0) FROM sales").fetchone()[0]
    count = c.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    low = c.execute("SELECT COUNT(*) FROM products WHERE stock < 10").fetchone()[0]
    top = c.execute("""SELECT name, SUM(qty) q FROM sale_items
                       GROUP BY name ORDER BY q DESC LIMIT 5""").fetchall()
    conn.close()
    return {
        "total": total,
        "count": count,
        "low_stock": low,
        "top_products": [dict(r) for r in top]
    }