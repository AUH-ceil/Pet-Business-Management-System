# ============================================================
# Agent 4: 活体健康哨兵 — 店内宠物健康监测 + 隔离 + 随访
# ============================================================
from datetime import date, datetime, timedelta
from typing import Dict, Any
from backend.database import get_connection
from backend.llm_client import call_llm_json, is_llm_available

def pet_health_agent(action: str, **kw) -> Dict[str, Any]:
    handlers = {
        "daily_check": _daily_check,
        "isolation_plan": _isolation_plan,
        "follow_up_list": _follow_up_list,
        "health_alerts": _health_alerts,
    }
    h = handlers.get(action)
    if not h: return {"success": False, "message": f"未知操作: {action}"}
    try: return h(**kw)
    except Exception as e: return {"success": False, "message": str(e)}

def _daily_check(**kw) -> Dict:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT * FROM daycare_records WHERE checkout_time IS NULL ORDER BY checkin_time")
    rows = cur.fetchall(); cur.close(); conn.close()
    pets = []
    for r in rows:
        pets.append({
            "id": r["id"], "pet_name": r["pet_name"], "breed": r.get("breed", ""),
            "owner_name": r.get("owner_name", ""), "owner_phone": r.get("owner_phone", ""),
            "staff": r.get("staff", ""), "daycare_type": r["daycare_type"],
            "duration": r.get("duration", ""), "status": r["status"],
            "checkin_time": str(r["checkin_time"]) if r.get("checkin_time") else "",
            "notes": r.get("notes", ""),
        })
    return {"success": True, "total": len(pets), "data": pets}


def _isolation_plan(pet_name: str, species: str, breed: str = "", **kw) -> Dict:
    plan = {"day_1": "单独隔离，观察精神和食欲",
            "day_2_3": "记录进食量和排便，观察异常症状",
            "day_4_5": "如正常则基础体检（体温/体重/皮肤）",
            "day_6": "体内外驱虫",
            "day_7": "隔离期满，无异常可移入开放区"}
    if is_llm_available():
        try:
            r = call_llm_json("你是宠物医生，生成7天隔离计划。返回{'plan':{}}",
                              f"{species}，品种{breed}", temperature=0.3)
            if "error" not in r and r.get("plan"): plan = r["plan"]
        except: pass
    return {"success": True, "pet_name": pet_name, "isolation_plan": plan}


def _follow_up_list(**kw) -> Dict:
    """从数据库查询售出活体的回访记录（售出第3天和第7天触发）"""
    conn = get_connection(); cur = conn.cursor()
    # 查询近期 outbound_records 中类型为"活体销售"的记录
    cur.execute("""SELECT o.outbound_id, o.sku_id, o.customer_id, o.total_amount,
        o.outbound_time, p.name as pet_name, c.name as customer_name, c.phone
        FROM outbound_records o
        JOIN products p ON o.sku_id = p.sku_id
        LEFT JOIN customers c ON o.customer_id = c.customer_id
        WHERE o.outbound_type = '活体销售'
        ORDER BY o.outbound_time DESC LIMIT 10""")
    rows = cur.fetchall()

    follow_ups = []
    for r in rows:
        days_ago = (date.today() - r["outbound_time"].date()).days if r.get("outbound_time") else 0
        # 第3天和第7天触发回访
        if days_ago in [3, 7]:
            follow_ups.append({
                "pet_name": r.get("pet_name", "未知"),
                "customer_name": r.get("customer_name", ""),
                "phone": r.get("phone", ""),
                "days_after_sale": days_ago,
                "action": "电话回访确认适应情况" if days_ago == 3 else "消息确认健康状况和疫苗提醒",
            })

    # 如果数据库没有活体销售记录，从托管记录生成回访提醒
    if not follow_ups:
        cur.execute("""SELECT pet_name, owner_name, owner_phone, checkin_time
            FROM daycare_records WHERE checkout_time IS NOT NULL
            ORDER BY checkout_time DESC LIMIT 10""")
        daycare_rows = cur.fetchall()
        for r in daycare_rows:
            if r.get("checkin_time"):
                days_ago = (date.today() - r["checkin_time"].date()).days
                if days_ago in [3, 7]:
                    follow_ups.append({
                        "pet_name": r["pet_name"],
                        "customer_name": r.get("owner_name", ""),
                        "phone": r.get("owner_phone", ""),
                        "days_after_sale": days_ago,
                        "action": "托管后回访了解回家适应情况",
                    })

    cur.close(); conn.close()
    return {"success": True, "follow_ups": follow_ups}


def _health_alerts(**kw) -> Dict:
    """综合健康告警：隔离检查 + 流失风险 + 托管超时提醒"""
    conn = get_connection(); cur = conn.cursor()

    # 1. 隔离提醒：查询 daycare 中超过 4 小时无更新的
    cur.execute("""SELECT pet_name, breed, staff, checkin_time, status,
        TIMESTAMPDIFF(HOUR, checkin_time, NOW()) as hours_elapsed
        FROM daycare_records WHERE checkout_time IS NULL
        AND TIMESTAMPDIFF(HOUR, checkin_time, NOW()) > 4""")
    iso_rows = cur.fetchall()
    isolation_alerts = []
    for r in iso_rows:
        isolation_alerts.append({
            "pet_name": r["pet_name"],
            "breed": r.get("breed", ""),
            "staff": r.get("staff", ""),
            "hours_elapsed": r["hours_elapsed"],
            "message": f"已托管{r['hours_elapsed']}小时，请检查状态" if r["status"] != "resting" else "正在休息中，注意按时喂食",
        })

    # 2. 流失风险：30天以上未到店客户
    cur.execute("""SELECT name, phone, pets, DATEDIFF(CURDATE(), last_visit) as days_absent
        FROM customers WHERE last_visit IS NOT NULL
        AND DATEDIFF(CURDATE(), last_visit) > 30 ORDER BY days_absent DESC LIMIT 5""")
    risk_rows = cur.fetchall()
    retention_risks = []
    for r in risk_rows:
        import json
        pets = json.loads(r["pets"]) if isinstance(r.get("pets"), str) else (r.get("pets") or [])
        pet_name = pets[0]["name"] if pets else "未知"
        pet_breed = pets[0]["breed"] if pets else ""
        retention_risks.append({
            "customer_name": r["name"],
            "phone": r.get("phone", ""),
            "pet_name": pet_name,
            "pet_breed": pet_breed,
            "days_absent": r["days_absent"],
            "reason": f"{r['days_absent']}天未到店",
            "suggestion": "推送洗护优惠券" if r["days_absent"] > 60 else "发送关心问候",
        })

    cur.close(); conn.close()

    return {
        "success": True,
        "isolation_alerts": isolation_alerts,
        "retention_risks": retention_risks,
        "follow_ups": _follow_up_list().get("follow_ups", []),
    }
