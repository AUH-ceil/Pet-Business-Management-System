# ============================================================
# Agent 3: 洗护排班官 — 美容师时间表 + 宠物护理注意事项
# 触发：每日开店时生成排班 / 顾客预约时更新
# ============================================================
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, List
from backend.database import get_connection
from backend.llm_client import call_llm_json, is_llm_available


def grooming_agent(action: str, **kwargs) -> Dict[str, Any]:
    handlers = {
        "today_schedule": _today_schedule,
        "book": _book_appointment,
        "pet_notes": _pet_notes,
    }
    handler = handlers.get(action)
    if not handler: return {"success": False, "message": f"未知操作: {action}"}
    try: return handler(**kwargs)
    except Exception as e: return {"success": False, "message": str(e)}


# ==================== 今日排班 ====================
def _today_schedule(**kw) -> Dict:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT * FROM grooming_schedule
        WHERE DATE(scheduled_start) = CURDATE() ORDER BY scheduled_start""")
    rows = cur.fetchall(); cur.close(); conn.close()

    # 按美容师分组
    groomers = {}
    for r in rows:
        g = r["groomer"]
        if g not in groomers:
            groomers[g] = {"name": g, "appointments": []}
        groomers[g]["appointments"].append({
            "appointment_id": r["appointment_id"],
            "time": str(r["scheduled_start"])[11:16] if r["scheduled_start"] else "",
            "customer_name": r.get("customer_name", ""),
            "pet_name": r["pet_name"],
            "service_type": r["service_type"],
            "estimated_minutes": r["estimated_minutes"],
            "pet_notes": r.get("pet_notes", ""),
            "status": r["status"],
        })

    # 如果没有预约，生成模拟建议
    if not groomers:
        groomers = {
            "张师傅": {"name": "张师傅", "appointments": []},
            "李师傅": {"name": "李师傅", "appointments": []},
        }

    total = sum(len(g["appointments"]) for g in groomers.values())
    pending = sum(1 for g in groomers.values() for a in g["appointments"] if a["status"] != "已完成")

    return {
        "success": True,
        "total": total,
        "pending": pending,
        "groomers": list(groomers.values()),
    }


# ==================== 预约 ====================
def _book_appointment(customer_id: str, customer_name: str, pet_name: str,
                      pet_species: str, service_type: str, groomer: str,
                      scheduled_start: str, estimated_minutes: int = 60,
                      pet_notes: str = "", **kw) -> Dict:
    aid = "APT-" + uuid.uuid4().hex[:8].upper()
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""INSERT INTO grooming_schedule (appointment_id, customer_id, customer_name,
        pet_name, pet_species, service_type, groomer, scheduled_start,
        estimated_minutes, pet_notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (aid, customer_id, customer_name, pet_name, pet_species, service_type,
         groomer, scheduled_start, estimated_minutes, pet_notes))
    conn.commit(); cur.close(); conn.close()
    return {"success": True, "appointment_id": aid, "message": f"{pet_name} 预约成功，{groomer} {scheduled_start}"}


# ==================== 护理注意事项（LLM） ====================
def _pet_notes(pet_name: str, pet_species: str, breed: str = "",
               history: str = "", **kw) -> Dict:
    """根据宠物信息生成护理注意事项"""
    notes = ""
    # 规则：基础注意事项
    if pet_species == "猫":
        notes = "猫咪洗护：先让猫适应环境10分钟再开始；水温37-38℃；避免水进耳朵；吹风用最低档"
    elif pet_species == "狗":
        notes = "狗狗洗护：检查指甲是否需要剪；耳朵是否需要清洁；双层毛品种需要充分吹干底层绒毛"

    # LLM 补充
    if is_llm_available() and breed:
        try:
            result = call_llm_json(
                "你是宠物美容专家。请给出一句话护理注意事项。返回JSON: {'notes':'...'}",
                f"宠物：{pet_species}，品种：{breed}。历史：{history}",
                temperature=0.3)
            if "error" not in result and result.get("notes"):
                notes = result["notes"]
        except: pass

    return {"success": True, "pet_name": pet_name, "notes": notes}
