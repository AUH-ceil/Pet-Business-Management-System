# -*- coding: utf-8 -*-
"""临时校验：到货入库。断言，不是肉眼看。
跑完把测试数据清干净，不留痕在演示数据里。"""
import sys, io
sys.path.insert(0, '.')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from datetime import date, timedelta
from backend.database import get_connection
from backend.agents.inventory_agent import inventory_agent

FAIL = 0
def ok(cond, msg):
    global FAIL
    print(('  ✅ ' if cond else '  ❌ ') + msg)
    if not cond: FAIL += 1

def q(sql, args=()):
    conn = get_connection(); cur = conn.cursor()
    cur.execute(sql, args); rows = cur.fetchall(); cur.close(); conn.close()
    return rows

def x(sql, args=()):
    conn = get_connection(); cur = conn.cursor()
    cur.execute(sql, args); conn.commit(); cur.close(); conn.close()

def snap(skus):
    """记录受影响 SKU 的全部可变量，用于「有没有动过」的比对和事后还原"""
    out = {}
    for s in skus:
        st = q("SELECT current_stock, avg_cost, total_value FROM stock_snapshots WHERE sku_id=%s", (s,))
        b = q("SELECT COUNT(*) c, COALESCE(SUM(remaining_qty),0) r FROM inbound_records WHERE sku_id=%s", (s,))
        p = q("SELECT last_unit_cost FROM products WHERE sku_id=%s", (s,))
        out[s] = {
            "stock": int(st[0]["current_stock"]) if st else None,
            "avg": float(st[0]["avg_cost"] or 0) if st else None,
            "val": float(st[0]["total_value"] or 0) if st else None,
            "batches": int(b[0]["c"]), "remaining": int(b[0]["r"]),
            "last_cost": float(p[0]["last_unit_cost"] or 0) if p else None,
        }
    return out

def created_ids(before_cnt):
    """本次测试新建的 inbound_id（按数量差取最新的那些）"""
    rows = q("SELECT inbound_id FROM inbound_records ORDER BY inbound_time DESC, inbound_id DESC")
    return [r["inbound_id"] for r in rows[:before_cnt]]

# ---- 选测试对象：有库存、非服务类 ----
stock = q("""SELECT s.sku_id, s.current_stock, s.avg_cost, p.name FROM stock_snapshots s
             JOIN products p ON s.sku_id=p.sku_id
             WHERE p.category<>'服务' AND s.current_stock>0 ORDER BY s.sku_id LIMIT 3""")
A, B, C = [r["sku_id"] for r in stock]
NAMES = {r["sku_id"]: r["name"] for r in stock}
print(f"测试对象：{A} {NAMES[A]} / {B} {NAMES[B]} / {C} {NAMES[C]}\n")

TAG = "IN-TESTCHK"
def line(sku, qty, cost, expiry=""):
    return {"sku_id": sku, "quantity": qty, "unit_cost": cost, "batch_no": TAG, "expiry_date": expiry}

# 记录全部批次剩余，事后原样还原
batch_before = {}
for s in [A, B, C]:
    batch_before[s] = {r["inbound_id"]: int(r["remaining_qty"])
                       for r in q("SELECT inbound_id, remaining_qty FROM inbound_records WHERE sku_id=%s", (s,))}
out_before = {r["outbound_id"] for r in q("SELECT outbound_id FROM outbound_records")}
ids_before = {r["inbound_id"] for r in q("SELECT inbound_id FROM inbound_records")}
STOCK0 = snap([A, B, C])   # 开工前的原始状态，最后照这个还原

try:
    # ==================== A. 正常三行 ====================
    print("=== A. 正常三行进货单 ===")
    s0 = snap([A, B, C])
    r = inventory_agent("inbound_batch", supplier_id="测试供应商", operator="测试员",
                        lines=[line(A, 1, 10), line(B, 2, 20), line(C, 3, 30)])
    ok(r.get("success"), "整单成功：" + str(r.get("message")))
    ok(r.get("count") == 3, "写入 3 行（拿到 %s）" % r.get("count"))
    s1 = snap([A, B, C])
    for s, qty, cost in [(A, 1, 10), (B, 2, 20), (C, 3, 30)]:
        b4, af = s0[s], s1[s]
        ok(af["stock"] == b4["stock"] + qty, f"{s} 库存 {b4['stock']} → {af['stock']}（应 +{qty}）")
        want = round((b4["stock"] * b4["avg"] + qty * cost) / (b4["stock"] + qty), 2)
        ok(abs(af["avg"] - want) < 0.011, f"{s} 均价 {b4['avg']:.2f} → {af['avg']:.2f}（移动平均应为 {want:.2f}）")
        ok(af["batches"] == b4["batches"] + 1, f"{s} 多了一个批次")
        ok(af["remaining"] == b4["remaining"] + qty, f"{s} 批次剩余合计 +{qty}")
        ok(af["last_cost"] == cost, f"{s} products.last_unit_cost 跟着更新为 {cost}")
        ok(af["stock"] == af["remaining"], f"{s} 恒等式：账面 {af['stock']} == Σ批次剩余 {af['remaining']}")
    ok(len(r["items"][0]["before"]) == 2 and r["items"][0]["after"]["stock"] == s1[A]["stock"],
       "返回了逐行 before/after，前端能如实报「2 → 22」")

    # ==================== B. 原子性（最关键） ====================
    print("\n=== B. 原子性：第 2 行非法，第 1/3 行也不许写 ===")
    s0 = snap([A, B, C])
    r = inventory_agent("inbound_batch",
                        lines=[line(A, 5, 10), line("SKU-NOT-EXIST", 5, 10), line(C, 5, 10)])
    ok(not r.get("success"), "整单被拒：" + str(r.get("message")))
    ok(any("第2行" in e for e in r.get("errors", [])), "报出了是第 2 行：%s" % r.get("errors"))
    s1 = snap([A, B, C])
    ok(s0 == s1, "第 1、3 行一个字节都没写（前后快照完全一致）")

    # ==================== C. 非法输入逐个挡 ====================
    print("\n=== C. 非法输入必须被挡，且库无变化 ===")
    bad = [
        ("数量 0",      [line(A, 0, 10)]),
        ("数量 -5",     [line(A, -5, 10)]),
        ("数量不是数字", [{"sku_id": A, "quantity": "abc", "unit_cost": 10}]),
        ("负进价",      [line(A, 3, -1)]),
        ("进价不是数字", [line(A, 3, "x")]),
        ("SKU 不存在",  [line("SKU-NOT-EXIST", 1, 1)]),
        ("效期格式错",  [line(A, 1, 10, "abc")]),
        ("效期写成 2026/10/01", [line(A, 1, 10, "2026/10/01")]),
        ("空单",        []),
    ]
    for label, lines in bad:
        before = snap([A, B, C])
        rr = inventory_agent("inbound_batch", lines=lines)
        after = snap([A, B, C])
        ok(not rr.get("success") and before == after, f"{label} → 拒绝且库无变化（{rr.get('message','')[:40]}）")

    # 一次报出全部问题，不是挤牙膏
    rr = inventory_agent("inbound_batch", lines=[line(A, 0, 10), line(A, 1, -1), line(A, 2, 3, "bad")])
    ok(len(rr.get("errors", [])) == 3, "三处问题一次全列出来（拿到 %d 条）" % len(rr.get("errors", [])))

    # ==================== D. FIFO 衔接：新批次排最后 ====================
    print("\n=== D. 入库新批次后出货，先扣旧批次 ===")
    rr = inventory_agent("inbound_batch", lines=[line(A, 3, 99)])
    new_id = q("SELECT inbound_id FROM inbound_records WHERE sku_id=%s AND batch_no=%s ORDER BY inbound_time DESC LIMIT 1",
               (A, TAG))[0]["inbound_id"]
    batches = q("""SELECT inbound_id, remaining_qty, inbound_time FROM inbound_records
                   WHERE sku_id=%s AND remaining_qty>0 ORDER BY inbound_time""", (A,))
    oldest = batches[0]["inbound_id"]
    oldest_b4 = int(batches[0]["remaining_qty"])
    new_b4 = [int(b["remaining_qty"]) for b in batches if b["inbound_id"] == new_id][0]
    out = inventory_agent("outbound", sku_id=A, quantity=1, outbound_type="销售", unit_price=1)
    ok(out.get("success"), "出库 1 件成功")
    got = {r["inbound_id"]: int(r["remaining_qty"])
           for r in q("SELECT inbound_id, remaining_qty FROM inbound_records WHERE sku_id=%s", (A,))}
    ok(got[oldest] == oldest_b4 - 1, f"扣的是最早的批次 {oldest}（{oldest_b4} → {got[oldest]}）")
    ok(got[new_id] == new_b4, f"新批次 {new_id} 没被动（还是 {got[new_id]}）")

    # ==================== E. 效期进预警 ====================
    print("\n=== E. 录入 10 天后到期的批次，预警要报出来 ===")
    soon = (date.today() + timedelta(days=10)).isoformat()
    inventory_agent("inbound_batch", lines=[{"sku_id": B, "quantity": 2, "unit_cost": 5,
                                             "batch_no": TAG, "expiry_date": soon}])
    al = inventory_agent("expiry_alert")
    hit = [i for i in al.get("items", []) if i["batch"] == TAG]
    ok(hit, f"效期预警报出了测试批次（{soon}）")
    chk = inventory_agent("scan_product", sku_id=B)
    ok("到期" in (chk["data"]["expiry_warning"] or ""), "扫码接口也带出临期提示：%s" % chk["data"]["expiry_warning"])

    # ==================== F. 单行入库老接口没被改坏 ====================
    print("\n=== F. 老的单行 inbound 仍然可用 ===")
    rr = inventory_agent("inbound", sku_id=C, quantity=1, unit_cost=7)
    ok(rr.get("success"), "inventory_agent('inbound') 正常：" + rr.get("message", ""))

finally:
    # ==================== 还原 ====================
    print("\n=== 清理测试数据 ===")
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT inbound_id FROM inbound_records")
    for r in cur.fetchall():
        if r["inbound_id"] not in ids_before:
            cur.execute("DELETE FROM inbound_records WHERE inbound_id=%s", (r["inbound_id"],))
    cur.execute("SELECT outbound_id FROM outbound_records")
    for r in cur.fetchall():
        if r["outbound_id"] not in out_before:
            cur.execute("DELETE FROM outbound_records WHERE outbound_id=%s", (r["outbound_id"],))
    # 批次剩余、快照、最近进价 全部按测试前的值写回
    for sku, m in batch_before.items():
        for bid, rem in m.items():
            cur.execute("UPDATE inbound_records SET remaining_qty=%s WHERE inbound_id=%s", (rem, bid))
        cur.execute("UPDATE stock_snapshots SET current_stock=%s, avg_cost=%s, total_value=%s WHERE sku_id=%s",
                    (STOCK0[sku]["stock"], STOCK0[sku]["avg"], STOCK0[sku]["val"], sku))
        cur.execute("UPDATE products SET last_unit_cost=%s WHERE sku_id=%s", (STOCK0[sku]["last_cost"], sku))
    conn.commit(); cur.close(); conn.close()

    after_clean = snap([A, B, C])
    for s in [A, B, C]:
        ok(after_clean[s]["stock"] == STOCK0[s]["stock"] and after_clean[s]["remaining"] == STOCK0[s]["remaining"],
           f"{s} 已还原（库存 {after_clean[s]['stock']}，批次剩余 {after_clean[s]['remaining']}）")

print("\n" + ("全部通过" if FAIL == 0 else f"{FAIL} 项失败"))
sys.exit(0 if FAIL == 0 else 1)
