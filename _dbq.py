# -*- coding: utf-8 -*-
"""临时小工具：给前端校验脚本读写数据库用。
   python _dbq.py query  "SELECT ..."
   python _dbq.py snap   "SKU001,SKU003"  > snap.json
   python _dbq.py restore snap.json
"""
import sys, io, json
sys.path.insert(0, '.')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from backend.database import get_connection

mode = sys.argv[1]
conn = get_connection(); cur = conn.cursor()

if mode == "query":
    cur.execute(sys.argv[2])
    print(json.dumps(cur.fetchall(), default=str, ensure_ascii=False))

elif mode == "snap":
    out = {}
    for sku in sys.argv[2].split(","):
        cur.execute("SELECT current_stock, avg_cost, total_value FROM stock_snapshots WHERE sku_id=%s", (sku,))
        st = cur.fetchone()
        cur.execute("SELECT inbound_id, remaining_qty FROM inbound_records WHERE sku_id=%s", (sku,))
        batches = {r["inbound_id"]: int(r["remaining_qty"]) for r in cur.fetchall()}
        cur.execute("SELECT last_unit_cost FROM products WHERE sku_id=%s", (sku,))
        out[sku] = {"stock": int(st["current_stock"]), "avg": float(st["avg_cost"] or 0),
                    "val": float(st["total_value"] or 0), "batches": batches,
                    "last_cost": float(cur.fetchone()["last_unit_cost"] or 0)}
    cur.execute("SELECT inbound_id FROM inbound_records")
    out["_ids"] = [r["inbound_id"] for r in cur.fetchall()]
    print(json.dumps(out, default=str, ensure_ascii=False))

elif mode == "restore":
    d = json.load(open(sys.argv[2], encoding="utf-8"))
    ids = set(d.pop("_ids"))
    cur.execute("SELECT inbound_id FROM inbound_records")
    for r in cur.fetchall():
        if r["inbound_id"] not in ids:
            cur.execute("DELETE FROM inbound_records WHERE inbound_id=%s", (r["inbound_id"],))
    for sku, m in d.items():
        for bid, rem in m["batches"].items():
            cur.execute("UPDATE inbound_records SET remaining_qty=%s WHERE inbound_id=%s", (rem, bid))
        cur.execute("UPDATE stock_snapshots SET current_stock=%s, avg_cost=%s, total_value=%s WHERE sku_id=%s",
                    (m["stock"], m["avg"], m["val"], sku))
        cur.execute("UPDATE products SET last_unit_cost=%s WHERE sku_id=%s", (m["last_cost"], sku))
    conn.commit()
    print("restored")

cur.close(); conn.close()
