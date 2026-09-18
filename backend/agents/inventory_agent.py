# ============================================================
# Agent 1: 库存先知 — 扫码进销存 + 补货决策
# 店员操作：扫条码 → 确认数量 → 入库/出库
# 系统自动：补货预警、效期预警、滞销检测、进价异常提醒
# ============================================================
import json
import uuid
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from backend.database import (
    get_product_by_barcode, get_product, insert_inbound, insert_inbound_batch,
    get_recent_inbounds, process_outbound, get_all_stock, get_low_stock_alerts,
)
from backend.llm_client import call_llm_json, is_llm_available


def inventory_agent(action: str, **kwargs) -> Dict[str, Any]:
    """库存先知统一入口"""
    handlers = {
        "scan_product": _scan_product,
        "inbound": _inbound,
        "inbound_batch": _inbound_batch,
        "inbound_recent": _inbound_recent,
        "outbound": _outbound,
        "stock_check": _stock_check,
        "replenish_plan": _replenish_plan,
        "expiry_alert": _expiry_alert,
        "daily_report": _daily_report,
    }
    handler = handlers.get(action)
    if not handler:
        return {"success": False, "message": f"未知操作: {action}"}
    try:
        return handler(**kwargs)
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== 扫码识别 ====================
def _scan_product(barcode: str = "", sku_id: str = "", **kw) -> Dict:
    """扫条码或输入SKU ID，返回商品信息"""
    product = None
    if barcode:
        product = get_product_by_barcode(barcode)
    if not product and sku_id:
        product = get_product(sku_id)

    if not product:
        return {"success": False, "message": "未识别到商品，请手动输入"}

    # 查库存
    stock = get_all_stock()
    stock_info = next((s for s in stock if s["sku_id"] == product["sku_id"]), None)

    return {
        "success": True,
        "data": {
            "sku_id": product["sku_id"],
            "name": product["name"],
            "category": product["category"],
            "spec": product["spec"],
            "unit": product["unit"],
            "retail_price": float(product["retail_price"]),
            "current_stock": stock_info["current_stock"] if stock_info else 0,
            "safety_stock": product["safety_stock"],
            "type": "grooming" if product["category"] == "服务" else "product",
            "expiry_warning": _check_expiry(product["sku_id"]),
        },
    }


# ==================== 入库 ====================
def _inbound(sku_id: str, quantity: int, unit_cost: float,
             supplier_id: str = "", batch_no: str = "",
             expiry_date: str = None, operator: str = "店员", **kw) -> Dict:
    """到货入库，自动更新库存快照"""
    product = get_product(sku_id)
    if not product:
        return {"success": False, "message": "商品不存在，请先在系统中创建"}

    inbound_id = f"IN-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    total_cost = round(quantity * unit_cost, 2)

    record = {
        "inbound_id": inbound_id, "sku_id": sku_id, "supplier_id": supplier_id,
        "quantity": quantity, "unit_cost": unit_cost, "total_cost": total_cost,
        "batch_no": batch_no or f"BT{datetime.now().strftime('%y%m%d%H%M')}",
        "expiry_date": expiry_date, "remaining_qty": quantity, "operator": operator,
    }
    insert_inbound(record)

    # 进价异常检测
    alert = ""
    if product["last_unit_cost"] and product["last_unit_cost"] > 0:
        change = (unit_cost - float(product["last_unit_cost"])) / float(product["last_unit_cost"])
        if change > 0.15:
            alert = f"⚠️ 进价比上次涨了 {change*100:.0f}%，建议确认供应商报价"

    return {
        "success": True,
        "inbound_id": inbound_id,
        "message": f"{product['name']} 入库 {quantity}{product['unit']}，金额 ¥{total_cost}",
        "price_alert": alert,
    }


# ==================== 多行进货单 ====================
def _inbound_batch(lines: List[Dict], supplier_id: str = "", operator: str = "店员", **kw) -> Dict:
    """整张进货单一次录入：先全量校验，再整单写入（或整单拒绝）。

    校验不过就一条都不写。货要么到了要么没到，写进去一半会让账和事实分叉，
    而且后面谁都说不清到底哪半是真的。
    """
    if not lines:
        return {"success": False, "message": "进货单是空的，请至少加一行"}

    errors, prepared, alerts = [], [], []
    for idx, line in enumerate(lines, start=1):
        sku_id = str(line.get("sku_id") or "").strip()
        name = sku_id or f"第{idx}行"

        product = get_product(sku_id) if sku_id else None
        if not product:
            errors.append(f"第{idx}行：商品 {sku_id or '(空)'} 不存在")
            continue
        name = product["name"]

        # 数量：必须是正整数。负数是能"反向着入库"的——它会把库存和均价一起刷成负数，
        # 而且悄无声息，所以这里必须挡住
        try:
            qty = int(line.get("quantity"))
        except (TypeError, ValueError):
            errors.append(f"第{idx}行 {name}：数量「{line.get('quantity')}」不是整数")
            continue
        if qty <= 0:
            errors.append(f"第{idx}行 {name}：数量必须大于 0（收到 {qty}）")
            continue

        try:
            unit_cost = round(float(line.get("unit_cost", 0)), 2)
        except (TypeError, ValueError):
            errors.append(f"第{idx}行 {name}：进价「{line.get('unit_cost')}」不是数字")
            continue
        if unit_cost < 0:
            errors.append(f"第{idx}行 {name}：进价不能为负（收到 {unit_cost}）")
            continue

        # 效期：可空；非空则必须能解析。填错就整单不入，
        # 因为效期错了会让预警直接漏报，比不入更糟
        expiry = (line.get("expiry_date") or "").strip()
        if expiry:
            try:
                datetime.strptime(expiry, "%Y-%m-%d")
            except ValueError:
                errors.append(f"第{idx}行 {name}：效期「{expiry}」格式不对，应为 2026-10-01")
                continue

        # 进价异常：只提醒不拦。涨价本身是合法事实，拦下来等于让用户录不进真账
        old_cost = float(product["last_unit_cost"] or 0)
        if old_cost > 0 and (unit_cost - old_cost) / old_cost > 0.15:
            alerts.append(f"{name} 进价比上次涨了 {(unit_cost-old_cost)/old_cost*100:.0f}%（¥{old_cost:.2f} → ¥{unit_cost:.2f}）")

        prepared.append({
            "inbound_id": f"IN-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}",
            "sku_id": sku_id, "supplier_id": supplier_id,
            "quantity": qty, "unit_cost": unit_cost, "total_cost": round(qty * unit_cost, 2),
            "batch_no": (line.get("batch_no") or "").strip() or f"BT{datetime.now().strftime('%y%m%d%H%M')}",
            "expiry_date": expiry or None, "remaining_qty": qty, "operator": operator,
            "name": name, "unit": product.get("unit", "件"),
        })

    if errors:
        # 一次把问题全列出来，别让用户改一行交一次、挤牙膏式地被拒
        return {"success": False, "message": "进货单有 " + str(len(errors)) + " 处问题，已全部退回（未写入任何数据）",
                "errors": errors}

    result = insert_inbound_batch(prepared)
    if not result.get("ok"):
        return {"success": False, "message": f"入库失败，整单已回滚：{result.get('message')}"}

    total = round(sum(p["total_cost"] for p in prepared), 2)
    detail = []
    for p, r in zip(prepared, result["lines"]):
        detail.append({"sku_id": p["sku_id"], "name": p["name"],
                       "quantity": p["quantity"], "total_cost": p["total_cost"],
                       "before": r["before"], "after": r["after"]})
    return {
        "success": True,
        "message": f"入库完成，共 {len(prepared)} 个商品，金额 ¥{total}",
        "total_cost": total, "count": len(prepared),
        "items": detail, "price_alerts": alerts,
    }


def _inbound_recent(limit: int = 20, **kw) -> Dict:
    """最近入库记录"""
    return {"success": True, "items": get_recent_inbounds(int(limit))}


# ==================== 出库 ====================
def _outbound(sku_id: str, quantity: int = 1, outbound_type: str = "销售",
              unit_price: float = 0, customer_id: str = None,
              operator: str = "店员", **kw) -> Dict:
    """销售/损耗/试用出库，FIFO自动扣批次"""
    product = get_product(sku_id)
    if not unit_price and product:
        unit_price = float(product.get("retail_price", 0))

    result = process_outbound(sku_id, quantity, outbound_type, unit_price, customer_id, operator)
    if result is None:
        return {"success": False, "message": "库存不足或批次异常"}

    return {
        "success": True,
        "outbound_id": result["outbound_id"],
        "total_amount": result["total_amount"],
        "remaining_stock": result["remaining_stock"],
        "message": f"{product['name'] if product else sku_id} 出库 {quantity}件，金额 ¥{result['total_amount']}",
    }


# ==================== 库存查询 ====================
def _stock_check(category: str = None, low_stock_only: bool = False, **kw) -> Dict:
    """实时库存查询"""
    rows = get_all_stock(category)
    if low_stock_only:
        rows = [r for r in rows if r["current_stock"] <= r.get("replenish_point", 3)]

    items = []
    for r in rows:
        items.append({
            "sku_id": r["sku_id"], "name": r["name"], "category": r["category"],
            # brand/spec 是给收银台用的：它的商品目录已经改成由这里下发，
            # 字段少一个前端就得回退到写死的兜底目录，等于又分叉了
            "brand": r.get("brand",""), "spec": r.get("spec",""),
            "current_stock": r["current_stock"], "unit": r.get("unit","个"),
            "avg_cost": float(r["avg_cost"]), "retail_price": float(r.get("retail_price",0)),
            "safety_stock": r.get("safety_stock",5), "replenish_point": r.get("replenish_point",3),
            "turnover_days": float(r.get("turnover_days",0)),
            "expiry_warning": _check_expiry(r["sku_id"]),
            "slow_moving": float(r.get("turnover_days",0)) > 90,
        })

    low = sum(1 for i in items if i["current_stock"] <= i["replenish_point"])
    return {
        "success": True,
        "summary": {"total_sku": len(items), "low_stock_count": low,
                     "total_value": round(sum(i["current_stock"]*i["avg_cost"] for i in items), 2)},
        "items": items,
    }


# ==================== 补货计划（LLM推理 + 规则兜底） ====================
def _replenish_plan(**kw) -> Dict:
    alerts = get_low_stock_alerts()
    if not alerts:
        return {"success": True, "urgent": [], "suggestion": "库存健康，无需补货"}

    items = [{"name": a["name"], "current": a["current_stock"],
              "safety": a.get("safety_stock", 5), "category": a.get("category","")} for a in alerts]

    # 尝试 LLM
    if is_llm_available():
        try:
            prompt = f"以下宠物店商品库存不足，请给补货建议：\n{json.dumps(items, ensure_ascii=False)}\n返回JSON: {{'analysis':'','urgent':[],'plan':[]}}"
            result = call_llm_json("你是宠物店库存管理专家。", prompt, temperature=0.3)
            if "error" not in result:
                return {"success": True, "source": "LLM", **result}
        except:
            pass

    # 规则兜底
    urgent = [i for i in items if i["current"] <= 2]
    return {
        "success": True, "source": "规则引擎",
        "analysis": f"共{len(items)}个SKU需要补货，其中{len(urgent)}个紧急",
        "urgent": [{"name": i["name"], "current_stock": i["current"],
                     "suggested_qty": max(5, i["safety"]*2 - i["current"]),
                     "urgency": "紧急" if i["current"] <= 2 else "本周"} for i in items],
    }


# ==================== 效期预警 ====================
def _expiry_alert(**kw) -> Dict:
    from backend.database import get_connection
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT i.sku_id, p.name, i.batch_no, i.expiry_date, i.remaining_qty
        FROM inbound_records i JOIN products p ON i.sku_id=p.sku_id
        WHERE i.remaining_qty > 0 AND i.expiry_date IS NOT NULL
        AND i.expiry_date <= DATE_ADD(CURDATE(), INTERVAL 30 DAY)
        ORDER BY i.expiry_date""")
    rows = cur.fetchall(); cur.close(); conn.close()

    urgent = [{"name": r["name"], "batch": r["batch_no"], "expiry": str(r["expiry_date"]),
               "remaining": r["remaining_qty"],
               "suggestion": "本周内促销/捆绑/捐赠"} for r in rows]
    return {"success": True, "urgent_count": len(urgent), "items": urgent}


def _daily_report(**kw) -> Dict:
    stock = _stock_check()
    expiry = _expiry_alert()
    return {"success": True, "date": str(date.today()),
            "stock_summary": stock.get("summary", {}),
            "expiry_alerts": expiry.get("urgent_count", 0)}


def _check_expiry(sku_id: str) -> Optional[str]:
    from backend.database import get_connection
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT MIN(expiry_date) as d FROM inbound_records
        WHERE sku_id=%s AND remaining_qty>0 AND expiry_date IS NOT NULL""", (sku_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    if row and row["d"]:
        days = (row["d"] - date.today()).days
        if days <= 30:
            return f"⚠ {days}天后到期"
    return None
