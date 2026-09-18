# ============================================================
# backend/workflow/nodes.py — LangGraph 节点函数
# 每个节点 = 调用对应 Agent
# ============================================================
from backend.agents.inventory_agent import inventory_agent
from backend.agents.customer_agent import customer_agent
from backend.agents.grooming_agent import grooming_agent
from backend.agents.content_agent import content_agent


# ===== DAG 1: 每日开店 =====
def node_stock_check(state: dict) -> dict:
    r = inventory_agent("stock_check", low_stock_only=True)
    return {"stock_alerts": r.get("items", [])}

def node_expiry_scan(state: dict) -> dict:
    r = inventory_agent("expiry_alert")
    return {"expiry_items": r.get("items", [])}

def node_grooming_schedule(state: dict) -> dict:
    r = grooming_agent("today_schedule")
    return {"grooming_schedule": r}

def node_customer_retention(state: dict) -> dict:
    r = customer_agent("daily_contacts")
    return {"retention_contacts": r.get("contacts", [])}

def node_content_generate(state: dict) -> dict:
    r = content_agent("generate")
    return {"content_result": r.get("data", {})}


# ===== DAG 2: 顾客到店 =====
def node_customer_lookup(state: dict) -> dict:
    cid = state.get("customer_id", "")
    if cid:
        r = customer_agent("lookup", customer_id=cid)
        return {"customer_info": r.get("data", {})}
    return {"customer_info": {}}

def node_process_sale(state: dict) -> dict:
    return {"sale_result": {"status": "done"}}

def node_update_profile(state: dict) -> dict:
    return {"customer_info": state.get("customer_info", {})}

def node_service_report(state: dict) -> dict:
    return {"service_report": {"summary": "服务完成"}}
