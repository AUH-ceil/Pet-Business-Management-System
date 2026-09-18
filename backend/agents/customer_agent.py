# ============================================================
# Agent 2: 熟客维系官 — 客户记忆 + 宠物档案 + 流失预警
# 触发：扫会员码（实时） / 每日定时（9:00）
# ============================================================
import json
from typing import Dict, Any, List, Optional
from backend.database import get_customer, get_all_customers, get_retention_suggestions
from backend.qdrant_client import upsert_customer_profile, search_similar_customers
from backend.llm_client import call_llm_json, is_llm_available


def customer_agent(action: str, **kwargs) -> Dict[str, Any]:
    handlers = {
        "lookup": _lookup_customer,
        "retention_list": _retention_list,
        "recommend": _recommend_products,
        "daily_contacts": _daily_contacts,
    }
    handler = handlers.get(action)
    if not handler: return {"success": False, "message": f"未知操作: {action}"}
    try: return handler(**kwargs)
    except Exception as e: return {"success": False, "message": str(e)}


# ==================== 会员信息查询（扫会员码触发） ====================
def _lookup_customer(customer_id: str, **kw) -> Dict:
    customer = get_customer(customer_id)
    if not customer:
        return {"success": False, "message": "未找到该会员"}

    # 构建提醒
    alerts = _build_alerts(customer)

    # 更新 Qdrant 客户画像
    profile_text = _build_profile_text(customer)
    upsert_customer_profile(customer_id, profile_text, {
        "name": customer["name"], "tags": customer.get("tags", []),
        "member_level": customer.get("member_level", ""),
    })

    return {
        "success": True,
        "data": {
            "customer_id": customer["customer_id"],
            "name": customer["name"],
            "phone": customer.get("phone", ""),
            "member_level": customer.get("member_level", "普通"),
            "pets": customer.get("pets", []),
            "last_visit": str(customer.get("last_visit", "")),
            "total_spent": float(customer.get("total_spent", 0)),
            "visit_count": customer.get("visit_count", 0),
            "alerts": alerts,
        },
    }


def _build_alerts(customer: Dict) -> List[Dict]:
    """根据宠物档案生成AI提醒"""
    alerts = []
    pets = customer.get("pets", []) or []
    from datetime import date, datetime

    for pet in pets:
        # 疫苗到期提醒
        vaccines = pet.get("vaccine_dates", [])
        if vaccines:
            last_v = max(vaccines)
            try:
                last_date = date.fromisoformat(last_v)
                next_due = last_date.replace(year=last_date.year + 1)
                days_left = (next_due - date.today()).days
                if days_left <= 30:
                    alerts.append({"type": "vaccine", "pet_name": pet["name"],
                                   "message": f"{pet['name']} 疫苗将在 {days_left} 天后到期，建议预约",
                                   "severity": "warning" if days_left <= 7 else "info"})
            except: pass

        # 洗护周期提醒
        last_groom = pet.get("last_grooming", "")
        if last_groom:
            try:
                g_date = date.fromisoformat(last_groom)
                if (date.today() - g_date).days > 28:
                    alerts.append({"type": "grooming", "pet_name": pet["name"],
                                   "message": f"{pet['name']} 距上次洗护已超过4周",
                                   "severity": "info"})
            except: pass

    return alerts


def _build_profile_text(customer: Dict) -> str:
    """构造客户画像文本，用于Qdrant语义检索"""
    pets = customer.get("pets", []) or []
    pet_desc = " ".join([f"{p.get('name','')} {p.get('species','')} {p.get('breed','')}" for p in pets])
    tags = " ".join(customer.get("tags", []))
    return f"{customer['name']} {pet_desc} {tags} {customer.get('member_level','')}"


# ==================== 流失预警名单 ====================
def _retention_list(**kw) -> Dict:
    rows = get_retention_suggestions()
    return {"success": True, "count": len(rows), "items": rows}


# ==================== 推荐商品（基于相似客户） ====================
def _recommend_products(customer_id: str, **kw) -> Dict:
    customer = get_customer(customer_id)
    if not customer:
        return {"success": False, "message": "客户不存在"}

    profile_text = _build_profile_text(customer)
    similar = search_similar_customers(profile_text, limit=3)

    return {
        "success": True,
        "customer_name": customer["name"],
        "similar_customers": [{"name": s.get("name",""), "score": s["score"]} for s in similar],
        "recommendation": "基于相似客户画像，推荐推送同品类新品或关联服务",
    }


# ==================== 每日联系清单 ====================
def _daily_contacts(**kw) -> Dict:
    """每天早上9点生成今日该联系的客户"""
    retention = _retention_list()

    # LLM 润色话术
    contacts = []
    for item in retention.get("items", [])[:5]:
        msg = f"{item['name']}，{item['pet_name']}（{item['pet_breed']}）{item['reason']}"
        if is_llm_available():
            try:
                result = call_llm_json(
                    "你是宠物店客服。给客户写一条温馨的微信消息，20-40字，自然不推销。",
                    f"客户{msg}，建议：{item['suggestion']}",
                    temperature=0.7)
                if "error" not in result:
                    msg = result.get("message", msg)
            except: pass
        contacts.append({"customer_name": item["name"], "pet_name": item["pet_name"],
                         "reason": item["reason"], "message": msg})

    return {"success": True, "contacts": contacts}
