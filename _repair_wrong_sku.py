# -*- coding: utf-8 -*-
"""冲正 2026-09-18 因"前端旧脚本 SKU 编号错位"而扣错商品的 3 条出库记录。

背景：旧版 cashier.js 的狗粮是顺序编号（第4个=SKU004=渴望、第5个=SKU005=伯纳天纯），
数据库里实际是 SKU008/SKU009。于是点"伯纳天纯"发出去的是 SKU005，
把【鸡肉绕钙棒】扣了；点"渴望"发出去的是 SKU004，把【犬用体内驱虫药】扣了。

冲正口径完全对齐 database.process_outbound()：
  扣的时候  inbound_records.remaining_qty -= qty
           stock_snapshots.current_stock  -= qty
           stock_snapshots.total_value     = 新库存 × avg_cost
  冲正就反过来加回去，并删掉那条错误出库记录。

只做冲正，不补记"本想卖的"渴望/伯纳天纯——不能替用户编造销售。
"""
import json
import sys

sys.path.insert(0, r"E:\Python2\agent12")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from backend.database import get_connection

BACKUP = r"E:\Python2\agent12\_repair_wrong_sku_backup.json"

conn = get_connection()
cur = conn.cursor()

# ---------- 1. 定位：记录单价与商品真实售价对不上的出库记录 ----------
cur.execute("""
  SELECT o.outbound_id, o.sku_id, p.name, p.retail_price,
         o.quantity, o.unit_price, o.inbound_id, o.outbound_time
  FROM outbound_records o JOIN products p ON o.sku_id = p.sku_id
  ORDER BY o.outbound_time
""")
all_rows = cur.fetchall()
bad = []
for r in all_rows:
    price, retail = float(r["unit_price"]), float(r["retail_price"])
    # 允许会员折扣 8/85/9/95 折
    if any(abs(price - retail * d) < 0.01 for d in (1, 0.95, 0.9, 0.85, 0.8)):
        continue
    bad.append(r)

print(f"出库记录共 {len(all_rows)} 条，其中价格与商品对不上的 {len(bad)} 条：")
for r in bad:
    print(f"  {r['outbound_id']}  {r['sku_id']} {r['name']} ×{r['quantity']} "
          f"记录单价 ¥{r['unit_price']}  批次 {r['inbound_id']}  {r['outbound_time']}")
if not bad:
    print("没有需要冲正的记录，退出。")
    cur.close(); conn.close(); sys.exit(0)

# ---------- 2. 备份 ----------
affected_skus = sorted({r["sku_id"] for r in bad})
backup = {"说明": "冲正前的原始数据，如需回滚可据此还原", "出库记录": [], "批次": [], "库存快照": []}
for r in bad:
    backup["出库记录"].append({k: str(v) for k, v in r.items()})
for sku in affected_skus:
    cur.execute("SELECT * FROM inbound_records WHERE sku_id=%s", (sku,))
    backup["批次"] += [{k: str(v) for k, v in b.items()} for b in cur.fetchall()]
    cur.execute("SELECT * FROM stock_snapshots WHERE sku_id=%s", (sku,))
    backup["库存快照"] += [{k: str(v) for k, v in s.items()} for s in cur.fetchall()]
with open(BACKUP, "w", encoding="utf-8") as f:
    json.dump(backup, f, ensure_ascii=False, indent=2)
print(f"\n已备份到 {BACKUP}")

# ---------- 3. 一个事务里冲正 ----------
print("\n冲正明细：")
try:
    for r in bad:
        sku, qty, inb = r["sku_id"], int(r["quantity"]), r["inbound_id"]

        cur.execute("SELECT remaining_qty, quantity FROM inbound_records WHERE inbound_id=%s", (inb,))
        b = cur.fetchone()
        assert b, f"批次 {inb} 不存在"
        assert int(b["remaining_qty"]) + qty <= int(b["quantity"]), \
            f"批次 {inb} 冲正后会超过原入库量，拒绝执行"
        cur.execute("UPDATE inbound_records SET remaining_qty = remaining_qty + %s WHERE inbound_id = %s",
                    (qty, inb))

        cur.execute("SELECT current_stock, avg_cost FROM stock_snapshots WHERE sku_id=%s", (sku,))
        s = cur.fetchone()
        new_qty = int(s["current_stock"]) + qty
        cur.execute("UPDATE stock_snapshots SET current_stock=%s, total_value=%s, updated_at=NOW() WHERE sku_id=%s",
                    (new_qty, round(new_qty * float(s["avg_cost"]), 2), sku))
        print(f"  {r['name']:<12} 批次 {inb} +{qty}   账面 {s['current_stock']} → {new_qty}")

        cur.execute("DELETE FROM outbound_records WHERE outbound_id=%s", (r["outbound_id"],))
    conn.commit()
    print("\n✅ 已提交")
except Exception as e:
    conn.rollback()
    print(f"\n❌ 出错已回滚：{e}")
    cur.close(); conn.close(); sys.exit(1)

cur.close(); conn.close()
