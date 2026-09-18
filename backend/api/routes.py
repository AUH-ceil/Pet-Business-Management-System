# ============================================================
# backend/api/routes.py — 对接前端所有 API
# ============================================================
import json
from fastapi import APIRouter, HTTPException
from backend.models import *
from backend.agents.inventory_agent import inventory_agent
from backend.agents.customer_agent import customer_agent
from backend.agents.grooming_agent import grooming_agent
from backend.agents.pet_health_agent import pet_health_agent
from backend.agents.content_agent import content_agent
from backend.database import get_all_stock
from backend.workflow.graph import run_daily_dag, run_customer_dag

router = APIRouter()

# ==================== 系统状态 ====================
@router.get("/api/system/status")
async def system_status():
    """当前实际生效的降级层级，供前端如实展示（别让 UI 替底层撒谎）"""
    from backend.llm_client import is_llm_available
    from backend.qdrant_client import vector_status
    return {"success": True, "data": {
        "vector": vector_status(),
        "llm": {"available": is_llm_available()},
    }}

# ==================== 收银台 ====================
@router.get("/api/scan/product")
async def scan_product(barcode: str = "", sku_id: str = ""):
    """扫码识别商品"""
    return inventory_agent("scan_product", barcode=barcode, sku_id=sku_id)

@router.get("/api/customer/{customer_id}")
async def get_customer_info(customer_id: str):
    """查询会员信息 + AI提醒"""
    return customer_agent("lookup", customer_id=customer_id)

@router.post("/api/checkout")
async def checkout(req: CheckoutRequest):
    """结算：逐件出库 + 更新客户消费"""
    # 折扣：1.0 = 原价，0<discount<1 打折。非法值一律按原价处理
    discount = req.discount if 0 < req.discount <= 1 else 1.0

    results, failed = [], []
    for item in req.items:
        r = inventory_agent("outbound", sku_id=item.sku_id, quantity=item.quantity,
                            unit_price=round(item.unit_price * discount, 2),
                            customer_id=req.customer_id)
        results.append(r)
        if not r.get("success"):
            failed.append(item.sku_id)

    msg = f"结算完成，共{len(req.items)}件"
    if failed:
        msg += f"；{len(failed)} 件出库失败（{', '.join(failed)}）"
    return {"success": not failed, "data": results, "failed": failed, "message": msg}

# ==================== 库存 ====================
@router.get("/api/stock/all")
async def stock_all():
    """全量库存查询"""
    r = inventory_agent("stock_check")
    items = r.get("items", [])
    return {"success": True, "data": items, "summary": r.get("summary", {})}

@router.post("/api/inbound")
async def inbound(req: InboundBatchRequest):
    """到货入库（多行进货单）。整单一个事务：要么全入，要么一条都不入。"""
    return inventory_agent("inbound_batch",
                           lines=[l.model_dump() for l in req.lines],
                           supplier_id=req.supplier_id, operator=req.operator)

@router.get("/api/inbound/recent")
async def inbound_recent(limit: int = 20):
    """最近入库记录，录完能立刻对账"""
    return inventory_agent("inbound_recent", limit=limit)

@router.get("/api/stock/alerts")
async def stock_alerts():
    """低库存 + 效期预警"""
    r = inventory_agent("stock_check", low_stock_only=True)
    items = r.get("items", [])
    alerts = [{"name": i["name"], "stock": i["current_stock"],
               "severity": "urgent" if i["current_stock"] <= 2 else "warning",
               "expiry_warning": i.get("expiry_warning","")} for i in items]
    return {"success": True, "data": alerts}

@router.get("/api/stock/warnings")
async def stock_warnings():
    """库存预警（看板用）"""
    return await stock_alerts()

# ==================== 托管 ====================
@router.post("/api/daycare/checkin")
async def daycare_checkin(req: DaycareCheckin):
    """宠物托管签到"""
    import uuid
    from backend.database import get_connection
    record = {"id": "DC-" + uuid.uuid4().hex[:8].upper(), "pet_name": req.pet_name,
              "breed": req.breed, "owner_name": req.owner_name, "owner_phone": req.owner_phone,
              "staff": req.staff, "daycare_type": req.daycare_type.value,
              "duration": req.duration, "status": "playing", "notes": req.notes}
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""INSERT INTO daycare_records (id,pet_name,breed,owner_name,owner_phone,staff,daycare_type,duration,status,notes)
        VALUES (%(id)s,%(pet_name)s,%(breed)s,%(owner_name)s,%(owner_phone)s,%(staff)s,%(daycare_type)s,%(duration)s,%(status)s,%(notes)s)""", record)
    conn.commit(); cur.close(); conn.close()
    return {"success": True, "data": record, "message": f"{req.pet_name} 托管签到成功"}

@router.get("/api/daycare/today")
async def daycare_today():
    """今日托管列表"""
    return pet_health_agent("daily_check")

# ==================== 看板 ====================
# period 口径：today / week / month / year。
# 昨天及以前读 daily_metrics（日报表），今天实时算出库记录——见 database._today_live。
@router.get("/api/dashboard/summary")
async def dashboard_summary(period: str = "today"):
    """经营数据汇总"""
    from backend.database import get_period_stats, get_customer_stats, get_today_stats
    stats = get_period_stats(period)
    base = get_today_stats()          # 库存那两个数跟时间窗口无关，照旧
    cust = get_customer_stats()
    return {"success": True, "data": {**stats,
            "total_stock": base["total_stock"], "low_stock_count": base["low_stock_count"], **cust}}

@router.get("/api/dashboard/trend")
async def dashboard_trend(period: str = "today"):
    """销售趋势。桶按**自然区间**铺满，不是往前滚 N 天：

        today → 近 7 天（单看一个点没有意义，所以今日也画一周）
        week  → 本周一到周日
        month → 本月 1 号到月末（今天之后的日子补 0）
        year  → 近 12 个自然月

    返回的 labels 是**固定长度**的，没数据的桶补 0——直接 GROUP BY 会让空桶消失，
    折线图点数会飘。具体桶由 database._trend_buckets() 决定。
    """
    from backend.database import get_trend_data
    return {"success": True, "data": get_trend_data(period)}

@router.get("/api/dashboard/top-products")
async def top_products(period: str = "today"):
    """热销TOP5（真实销量：daily_product_sales + 今日实时出库）"""
    from backend.database import get_top_products
    return {"success": True, "data": get_top_products(period)}

@router.get("/api/dashboard/monthly")
async def dashboard_monthly(months: int = 12):
    """月度明细（看板"近一年"下方的表格用），含环比"""
    from backend.database import get_monthly_metrics
    return {"success": True, "data": get_monthly_metrics(months)}

@router.get("/api/customers/stats")
async def customer_stats():
    from backend.database import get_customer_stats
    return {"success": True, "data": get_customer_stats()}

@router.get("/api/customers/retention-suggestions")
async def retention_suggestions():
    return customer_agent("retention_list")

@router.get("/api/grooming/today")
async def grooming_today():
    return grooming_agent("today_schedule")

@router.post("/api/grooming/book")
async def grooming_book(req: GroomingAppointment):
    """预约洗护服务"""
    return grooming_agent("book",
        customer_id=req.customer_id, customer_name=req.customer_name,
        pet_name=req.pet_name, pet_species=req.pet_species,
        service_type=req.service_type, groomer=req.groomer,
        scheduled_start=req.scheduled_start, estimated_minutes=req.estimated_minutes,
        pet_notes=req.pet_notes)

@router.get("/api/grooming/pet-notes")
async def grooming_pet_notes(pet_name: str, pet_species: str, breed: str = "", history: str = ""):
    """获取宠物护理注意事项"""
    return grooming_agent("pet_notes", pet_name=pet_name, pet_species=pet_species,
                          breed=breed, history=history)

@router.get("/api/health/alerts")
async def health_alerts():
    return pet_health_agent("health_alerts")

# ==================== AI内容生成 ====================
@router.post("/api/content/generate")
async def generate_content(req: ContentGenRequest):
    return content_agent("generate", channel=req.channel)

# ==================== 补货分析（RAG + LLM） ====================
class ReplenishRequest(BaseModel):
    low_stock: list = []
    hot_items: list = []
    category_preference: dict = {}
    total_sales_count: int = 0

@router.post("/api/replenish/analyze")
async def replenish_analysis(req: ReplenishRequest):
    """RAG检索（库存+销售+顾客偏好）→ DeepSeek生成补货建议"""
    from backend.llm_client import call_llm, is_llm_available

    if not is_llm_available():
        return {"success": False, "message": "LLM不可用"}

    prompt = f"""
## 当前库存状况
低库存商品：{json.dumps(req.low_stock, ensure_ascii=False)}

## 近期销售数据
热销商品：{json.dumps(req.hot_items[:8], ensure_ascii=False)}

## RAG检索：顾客品类偏好
{json.dumps(req.category_preference, ensure_ascii=False)}
历史总销售单数：{req.total_sales_count}

## 任务
你是宠物店AI库存顾问。基于以上真实数据 + RAG顾客偏好分析，给出补货建议。

要求：
1. 必须引用具体数据（"XX已售YY件，仅剩ZZ件"）
2. 区分紧急程度：库存≤3且热销的为"紧急"，其余为"本周计划"
3. 建议进货量参考：日均销量 × 补货周期 × 1.3
4. 考虑顾客品类偏好（RAG数据）：猫用品需求大的店，猫粮猫砂优先
5. 不要套模板，每一条建议基于实际数据

返回JSON：
{{
  "analysis": "一段话总结当前库存健康和补货优先级（100字以内）",
  "urgent_items": [{{"name":"","current_stock":0,"suggested_qty":0,"reason":"基于XX数据"}}],
  "plan_items": [{{"name":"","current_stock":0,"suggested_qty":0,"reason":"基于XX数据"}}]
}}"""

    try:
        import re
        result = call_llm(
            "你是宠物店AI库存顾问，给出数据驱动的补货建议。只返回JSON。",
            prompt, temperature=0.5, max_tokens=1500
        )
        json_str = result
        m = re.search(r'\{.*\}', result, re.DOTALL)
        if m: json_str = m.group()
        data = json.loads(json_str)
        return {"success": True, "data": data, "source": "DeepSeek"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ==================== LangGraph DAG 触发 ====================
@router.post("/api/dag/daily")
async def trigger_daily_dag():
    """手动触发每日开店DAG"""
    r = run_daily_dag()
    return {"success": True, "data": r}

@router.post("/api/dag/customer")
async def trigger_customer_dag(customer_id: str):
    """手动触发顾客服务DAG"""
    r = run_customer_dag(customer_id)
    return {"success": True, "data": r}


# ==================== RAG + LLM 联合分析 ====================
class RAGAnalysisRequest(BaseModel):
    phone: str
    purchase_history: list  # [{time, items:[{name,qty}], total}]
    habit_summary: dict     # {top_items, top_brands, insights}
    similar_customers: list # [{phone, score, purchases}]

@router.post("/api/rag/analyze")
async def rag_llm_analysis(req: RAGAnalysisRequest):
    """RAG检索结果 + DeepSeek大模型联合分析"""
    from backend.llm_client import call_llm, is_llm_available

    if not is_llm_available():
        return {"success": False, "message": "LLM不可用"}

    # 构建 prompt：RAG检索上下文 → LLM 生成建议
    context = f"""
## 当前顾客消费数据
购买历史：{json.dumps(req.purchase_history[-5:], ensure_ascii=False)}
常购商品：{json.dumps(req.habit_summary.get('top_items',[]), ensure_ascii=False)}

## RAG检索结果（余弦相似度匹配的相似顾客）
{json.dumps(req.similar_customers[:3], ensure_ascii=False)}

## 任务
你是宠物店资深 AI 顾问。基于真实数据和RAG检索结果，给出3条个性化建议。

**禁止套用固定模板**，必须根据实际数据动态分析：
- 如果顾客多次回购同一款粮 → 分析品牌忠诚度，建议推出订阅制
- 如果顾客只买粮不买零食 → 结合相似顾客数据，推荐他们买了且适合的
- 如果顾客消费间隔越来越大 → 给出激活话术
- 不要千篇一律说"推荐搭配零食""建议补货"
- 每条建议必须引用具体数据（RAG检索到的相似顾客买了什么、你自己的购买频率）

返回JSON：
{{
  "profile": "消费画像：基于真实数据的1句话总结",
  "recommendation": "具体到商品名的推荐，必须引用RAG相似顾客数据",
  "message_template": "可直接复制发送的微信话术，口语化、不推销腔"
}}"""

    try:
        result = call_llm(
            "你是宠物店资深 AI 经营顾问，擅长基于数据分析给出可执行建议。请只返回JSON。",
            context,
            temperature=0.7, max_tokens=800
        )
        import re
        # 解析 JSON
        json_str = result
        m = re.search(r'\{.*\}', result, re.DOTALL)
        if m: json_str = m.group()
        data = json.loads(json_str)
        return {"success": True, "data": data, "source": "DeepSeek + RAG"}
    except Exception as e:
        return {"success": False, "message": str(e)}
