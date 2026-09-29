"""Read-only stock fingerprint for acceptance checks: rows, totals and a hash of every balance row.

Usage: prototype/.venv/bin/python scripts/stock_fingerprint.py <path to prototype sqlite db>
Opens the database read-only; prints one line. Compare the line before and after a flow.
"""
import hashlib
import sqlite3
import sys

db = sys.argv[1]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
rows = con.execute(
    "SELECT owner_id, product_id, lot_id, location_id, condition, on_hand, allocated "
    "FROM inventory_stockbalance ORDER BY id").fetchall()
extra = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in ("inventory_stockmovement", "inventory_order", "inventory_receiptnotice")}
digest = hashlib.sha256(repr(rows).encode()).hexdigest()[:16]
print(f"balances={len(rows)} on_hand={sum(r[5] for r in rows)} allocated={sum(r[6] for r in rows)} "
      f"movements={extra['inventory_stockmovement']} orders={extra['inventory_order']} "
      f"notices={extra['inventory_receiptnotice']} hash={digest}")
