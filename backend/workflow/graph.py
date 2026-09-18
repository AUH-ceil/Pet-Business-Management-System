# ============================================================
# backend/workflow/graph.py — LangGraph 两条 DAG
# DAG 1: 每日开店（库存检查 → 效期预警 → 排班 → 客户维系 → 内容生成）
# DAG 2: 顾客到店（会员识别 → 消费出库 → 更新画像 → 生成服务报告）
# ============================================================
from typing import TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from backend.workflow.nodes import (
    node_stock_check, node_expiry_scan, node_grooming_schedule,
    node_customer_retention, node_content_generate,
    node_customer_lookup, node_process_sale, node_update_profile,
    node_service_report,
)


# ==================== State 定义 ====================
class DailyState(TypedDict):
    stock_alerts: list
    expiry_items: list
    grooming_schedule: dict
    retention_contacts: list
    content_result: dict

class CustomerState(TypedDict):
    customer_id: str
    customer_info: dict
    cart_items: list
    sale_result: dict
    service_report: dict


# ==================== DAG 1: 每日开店 ====================
def build_daily_dag() -> StateGraph:
    w = StateGraph(DailyState)
    w.add_node("stock_check", node_stock_check)
    w.add_node("expiry_scan", node_expiry_scan)
    w.add_node("grooming", node_grooming_schedule)
    w.add_node("retention", node_customer_retention)
    w.add_node("content", node_content_generate)

    w.set_entry_point("stock_check")
    # 三个并行：效期 + 排班 + 客户维系
    w.add_edge("stock_check", "expiry_scan")
    w.add_edge("stock_check", "grooming")
    w.add_edge("stock_check", "retention")
    # 汇合到内容生成
    w.add_edge("expiry_scan", "content")
    w.add_edge("grooming", "content")
    w.add_edge("retention", "content")
    w.add_edge("content", END)
    return w


# ==================== DAG 2: 顾客到店 ====================
def build_customer_dag() -> StateGraph:
    w = StateGraph(CustomerState)
    w.add_node("customer_lookup", node_customer_lookup)
    w.add_node("process_sale", node_process_sale)
    w.add_node("update_profile", node_update_profile)
    w.add_node("service_report", node_service_report)

    w.set_entry_point("customer_lookup")
    w.add_edge("customer_lookup", "process_sale")
    w.add_edge("process_sale", "update_profile")
    w.add_edge("update_profile", "service_report")
    w.add_edge("service_report", END)
    return w


# ==================== 执行入口 ====================
def run_daily_dag() -> dict:
    """执行每日开店DAG"""
    w = build_daily_dag()
    app = w.compile()
    state: DailyState = {"stock_alerts": [], "expiry_items": [],
                         "grooming_schedule": {}, "retention_contacts": [],
                         "content_result": {}}
    result = app.invoke(state)
    return {"message": "每日开店流程完成", "state": result}

def run_customer_dag(customer_id: str) -> dict:
    """执行顾客到店DAG"""
    w = build_customer_dag()
    app = w.compile()
    state: CustomerState = {"customer_id": customer_id, "customer_info": {},
                            "cart_items": [], "sale_result": {}, "service_report": {}}
    result = app.invoke(state)
    return {"message": f"顾客 {customer_id} 服务流程完成", "state": result}
