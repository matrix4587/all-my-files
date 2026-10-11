"""
One-off script: check the products table and list every product's
barcode + current short code, so we can see which ones still show
the barcode instead of a proper short code.

Run with the server STOPPED:
    py fix_short_codes.py
"""

import sqlite3
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "back_office.db")

if not os.path.exists(DB_PATH):
    print(f"No DB at {DB_PATH}")
    raise SystemExit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print("\n--- Current products ---\n")
rows = conn.execute("""
    SELECT id, name, barcode, code FROM products ORDER BY id
""").fetchall()

for r in rows:
    barcode = r["barcode"] or ""
    code = r["code"] or ""
    same = "(code == barcode)" if code == barcode else ""
    print(f"id={r['id']:>3}  name={r['name'][:30]:<32}  barcode={barcode:<16}  code={code:<16} {same}")

print("\n--- Prompts ---")
print()
print("Type the NEW short code for each product below.")
print("Leave blank to keep the current value. Type 'skip' to stop.")
print()

for r in rows:
    current = r["code"] or ""
    prompt = f"id={r['id']} '{r['name'][:30]}' (barcode={r['barcode']}) current code='{current}' -> new code: "
    answer = input(prompt).strip()
    if answer.lower() == "skip":
        break
    if answer == "":
        continue
    conn.execute("UPDATE products SET code = ? WHERE id = ?", (answer, r["id"]))
    print(f"    set code='{answer}' for id={r['id']}")

conn.commit()
conn.close()
print("\nDone. Restart the server.")
"""
One-off script: check the products table and list every product's
barcode + current short code, so we can see which ones still show
the barcode instead of a proper short code.

Run with the server STOPPED:
    py fix_short_codes.py
"""

import sqlite3
import os

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "back_office.db")

if not os.path.exists(DB_PATH):
    print(f"No DB at {DB_PATH}")
    raise SystemExit(1)

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

print("\n--- Current products ---\n")
rows = conn.execute("""
    SELECT id, name, barcode, code FROM products ORDER BY id
""").fetchall()

for r in rows:
    barcode = r["barcode"] or ""
    code = r["code"] or ""
    same = "(code == barcode)" if code == barcode else ""
    print(f"id={r['id']:>3}  name={r['name'][:30]:<32}  barcode={barcode:<16}  code={code:<16} {same}")

print("\n--- Prompts ---")
print()
print("Type the NEW short code for each product below.")
print("Leave blank to keep the current value. Type 'skip' to stop.")
print()

for r in rows:
    current = r["code"] or ""
    prompt = f"id={r['id']} '{r['name'][:30]}' (barcode={r['barcode']}) current code='{current}' -> new code: "
    answer = input(prompt).strip()
    if answer.lower() == "skip":
        break
    if answer == "":
        continue
    conn.execute("UPDATE products SET code = ? WHERE id = ?", (answer, r["id"]))
    print(f"    set code='{answer}' for id={r['id']}")

conn.commit()
conn.close()
print("\nDone. Restart the server.")