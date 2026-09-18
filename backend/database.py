# ============================================================
# backend/database.py - MySQL 操作（pymysql 直连）
# 表：products / inbound / outbound / stock / customers / grooming / daycare
# ============================================================
import pymysql, os, json, random
from typing import List, Dict, Any, Optional
from datetime import date, datetime, timedelta

DB_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "localhost"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", "123456"),
    "database": os.environ.get("MYSQL_DATABASE", "petstore_db"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

def get_connection():
    return pymysql.connect(**DB_CONFIG)

# ==================== 初始化 ====================
def init_database():
    config_no_db = {k: v for k, v in DB_CONFIG.items() if k != "database"}
    config_no_db.pop("cursorclass", None)
    conn = pymysql.connect(**config_no_db)
    cur = conn.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS petstore_db DEFAULT CHARSET utf8mb4")
    conn.commit(); cur.close(); conn.close()

    conn = get_connection(); cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS products (
        sku_id VARCHAR(32) PRIMARY KEY, barcode VARCHAR(64), name VARCHAR(128) NOT NULL,
        category VARCHAR(32), brand VARCHAR(64), spec VARCHAR(64), unit VARCHAR(16),
        retail_price DECIMAL(8,2), last_unit_cost DECIMAL(8,2),
        safety_stock INT DEFAULT 5, replenish_point INT DEFAULT 3, created_at DATETIME DEFAULT NOW()
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS inbound_records (
        inbound_id VARCHAR(32) PRIMARY KEY, sku_id VARCHAR(32), supplier_id VARCHAR(16),
        quantity INT, unit_cost DECIMAL(8,2), total_cost DECIMAL(10,2),
        batch_no VARCHAR(32), expiry_date DATE, remaining_qty INT,
        operator VARCHAR(32), inbound_time DATETIME DEFAULT NOW()
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS outbound_records (
        outbound_id VARCHAR(32) PRIMARY KEY, sku_id VARCHAR(32), inbound_id VARCHAR(32),
        quantity INT, outbound_type VARCHAR(16), unit_price DECIMAL(8,2),
        total_amount DECIMAL(10,2), customer_id VARCHAR(32),
        operator VARCHAR(32), outbound_time DATETIME DEFAULT NOW()
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS stock_snapshots (
        sku_id VARCHAR(32) PRIMARY KEY, current_stock INT DEFAULT 0,
        avg_cost DECIMAL(8,2), total_value DECIMAL(10,2),
        min_expiry_date DATE, turnover_days DECIMAL(6,1) DEFAULT 0,
        updated_at DATETIME DEFAULT NOW()
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS customers (
        customer_id VARCHAR(32) PRIMARY KEY, name VARCHAR(32), phone VARCHAR(16),
        wechat_id VARCHAR(64), pets JSON, tags JSON,
        total_spent DECIMAL(10,2) DEFAULT 0, visit_count INT DEFAULT 0,
        last_visit DATE, preferred_categories JSON, member_level VARCHAR(16) DEFAULT '普通',
        created_at DATETIME DEFAULT NOW()
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS grooming_schedule (
        appointment_id VARCHAR(32) PRIMARY KEY, customer_id VARCHAR(32),
        customer_name VARCHAR(32), pet_name VARCHAR(32), pet_species VARCHAR(16),
        service_type VARCHAR(32), groomer VARCHAR(32),
        scheduled_start DATETIME, estimated_minutes INT DEFAULT 60,
        status VARCHAR(16) DEFAULT '已预约', pet_notes VARCHAR(256),
        created_at DATETIME DEFAULT NOW()
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS daycare_records (
        id VARCHAR(32) PRIMARY KEY, pet_name VARCHAR(32), breed VARCHAR(64),
        owner_name VARCHAR(32), owner_phone VARCHAR(16), staff VARCHAR(32),
        daycare_type VARCHAR(16), duration VARCHAR(16), status VARCHAR(16) DEFAULT 'playing',
        checkin_time DATETIME DEFAULT NOW(), checkout_time DATETIME, notes VARCHAR(256)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    # ---- 经营报表层（与库存层解耦，见文件末尾 seed_history_metrics 的说明）----
    cur.execute("""CREATE TABLE IF NOT EXISTS daily_metrics (
        stat_date DATE PRIMARY KEY,
        revenue DECIMAL(10,2) DEFAULT 0, order_count INT DEFAULT 0,
        gross_profit DECIMAL(10,2) DEFAULT 0,
        new_customers INT DEFAULT 0, returning_customers INT DEFAULT 0,
        grooming_orders INT DEFAULT 0, daycare_count INT DEFAULT 0,
        is_synthetic TINYINT DEFAULT 1, created_at DATETIME DEFAULT NOW()
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    cur.execute("""CREATE TABLE IF NOT EXISTS daily_product_sales (
        stat_date DATE, sku_id VARCHAR(32), sku_name VARCHAR(128), category VARCHAR(32),
        qty INT DEFAULT 0, revenue DECIMAL(10,2) DEFAULT 0,
        PRIMARY KEY (stat_date, sku_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

    conn.commit(); cur.close(); conn.close()
    print("[数据库] petstore_db 初始化完成（9张表）")

# ==================== 产品查询 ====================
def get_product_by_barcode(barcode: str) -> Optional[Dict]:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE barcode = %s", (barcode,))
    row = cur.fetchone(); cur.close(); conn.close()
    return row

def get_product(sku_id: str) -> Optional[Dict]:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE sku_id = %s", (sku_id,))
    row = cur.fetchone(); cur.close(); conn.close()
    return row

# ==================== 入库 ====================
def _apply_inbound(cur, record: Dict) -> Dict:
    """写入**一行**入库：开批次 + 重算库存快照 + 回写商品最近进价。

    接收外部的 cur，自己不开连接——这样多行进货单才能被包进同一个事务。
    单独开连接的写法没法回滚，一张单子写到一半失败就会留下半截账。

    返回该行 SKU 的 before/after，供调用方如实报出"库存 2 → 22，均价 180 → 180"。
    """
    # 先取改动前的状态：报告和校验都要用，必须在 UPDATE 之前读
    cur.execute("SELECT current_stock, avg_cost, total_value FROM stock_snapshots WHERE sku_id = %s",
                (record["sku_id"],))
    stock = cur.fetchone()
    before = {"stock": int(stock["current_stock"]) if stock else 0,
              "avg_cost": float(stock["avg_cost"]) if stock and stock["avg_cost"] is not None else 0.0}

    cur.execute("""INSERT INTO inbound_records (inbound_id, sku_id, supplier_id, quantity,
        unit_cost, total_cost, batch_no, expiry_date, remaining_qty, operator)
        VALUES (%(inbound_id)s,%(sku_id)s,%(supplier_id)s,%(quantity)s,
        %(unit_cost)s,%(total_cost)s,%(batch_no)s,%(expiry_date)s,%(remaining_qty)s,%(operator)s)""", record)

    new_qty = before["stock"] + record["quantity"]
    new_val = (float(stock["total_value"]) if stock and stock["total_value"] is not None else 0.0) + record["total_cost"]
    new_cost = round(new_val / new_qty, 2) if new_qty > 0 else 0
    if stock:
        cur.execute("UPDATE stock_snapshots SET current_stock=%s, avg_cost=%s, total_value=%s, updated_at=NOW() WHERE sku_id=%s",
                    (new_qty, new_cost, round(new_val, 2), record["sku_id"]))
    else:
        cur.execute("INSERT INTO stock_snapshots (sku_id, current_stock, avg_cost, total_value) VALUES (%s,%s,%s,%s)",
                    (record["sku_id"], new_qty, new_cost, round(new_val, 2)))

    # 商品最近进价也在这个事务里更新。原来它在 _inbound 里单开一个连接，
    # 那个事务失败的话入库已经提交了——静默的部分成功。
    cur.execute("UPDATE products SET last_unit_cost=%s WHERE sku_id=%s",
                (record["unit_cost"], record["sku_id"]))

    return {"sku_id": record["sku_id"], "quantity": record["quantity"],
            "inbound_id": record["inbound_id"], "batch_no": record["batch_no"],
            "total_cost": record["total_cost"],
            "before": before,
            "after": {"stock": new_qty, "avg_cost": new_cost}}


def insert_inbound_batch(records: List[Dict]) -> Dict:
    """整张进货单**一个事务**：要么全部入账，要么一条都不入。

    现实里货要么到了要么没到，部分提交会让账和事实分叉。任何一行出错就整体
    回滚，并把是第几行、什么原因报出去。
    """
    if not records:
        return {"ok": False, "message": "进货单是空的"}
    conn = get_connection()
    cur = conn.cursor()
    try:
        results = [_apply_inbound(cur, r) for r in records]
        conn.commit()
        return {"ok": True, "lines": results}
    except Exception as e:
        # pymysql 默认 autocommit=False，这里显式回滚，不指望连接被回收时顺带回滚
        conn.rollback()
        return {"ok": False, "message": f"{type(e).__name__}: {e}"}
    finally:
        # 原来没有 finally：expiry_date 填垃圾让 MySQL 抛异常时，连接是泄漏的
        cur.close(); conn.close()


def insert_inbound(record: Dict):
    """单行入库（保留原签名，调用方 inventory_agent 不用改）。"""
    return insert_inbound_batch([record])


def get_recent_inbounds(limit: int = 20) -> List[Dict]:
    """最近的入库记录，给「最近入库记录」列表用——录完能立刻对账。"""
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT i.inbound_id, i.sku_id, p.name, p.unit, i.quantity, i.unit_cost,
                          i.total_cost, i.batch_no, i.expiry_date, i.supplier_id,
                          i.operator, i.remaining_qty, i.inbound_time
                   FROM inbound_records i LEFT JOIN products p ON i.sku_id = p.sku_id
                   ORDER BY i.inbound_time DESC, i.inbound_id DESC LIMIT %s""", (limit,))
    rows = cur.fetchall(); cur.close(); conn.close()
    out = []
    for r in rows:
        out.append({
            "inbound_id": r["inbound_id"], "sku_id": r["sku_id"],
            "name": r["name"] or r["sku_id"], "unit": r["unit"] or "件",
            "quantity": int(r["quantity"]), "unit_cost": float(r["unit_cost"]),
            "total_cost": float(r["total_cost"]), "batch_no": r["batch_no"] or "",
            "expiry_date": str(r["expiry_date"]) if r["expiry_date"] else "",
            "supplier_id": r["supplier_id"] or "", "operator": r["operator"] or "",
            "remaining_qty": int(r["remaining_qty"]),
            "inbound_time": r["inbound_time"].strftime("%Y-%m-%d %H:%M") if r["inbound_time"] else "",
        })
    return out

# ==================== 出库（含 FIFO） ====================
def process_outbound(sku_id: str, quantity: int, outbound_type: str, unit_price: float, customer_id: str = None, operator: str = "店员") -> Optional[Dict]:
    conn = get_connection(); cur = conn.cursor()
    # 检查库存
    cur.execute("SELECT * FROM stock_snapshots WHERE sku_id = %s", (sku_id,))
    stock = cur.fetchone()
    if not stock or stock["current_stock"] < quantity:
        cur.close(); conn.close()
        return None
    # FIFO 扣批次
    cur.execute("SELECT * FROM inbound_records WHERE sku_id=%s AND remaining_qty>0 ORDER BY inbound_time", (sku_id,))
    batches = cur.fetchall()
    remaining = quantity; deductions = []
    for b in batches:
        if remaining <= 0: break
        take = min(b["remaining_qty"], remaining)
        cur.execute("UPDATE inbound_records SET remaining_qty=remaining_qty-%s WHERE inbound_id=%s", (take, b["inbound_id"]))
        deductions.append({"inbound_id": b["inbound_id"], "batch_no": b["batch_no"], "took": take})
        remaining -= take
    if remaining > 0:
        conn.rollback(); cur.close(); conn.close()
        return None
    # 写出库记录
    import uuid
    oid = "OUT-" + uuid.uuid4().hex[:10].upper()
    total = round(quantity * unit_price, 2)
    cur.execute("""INSERT INTO outbound_records (outbound_id, sku_id, inbound_id, quantity, outbound_type,
        unit_price, total_amount, customer_id, operator)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (oid, sku_id, deductions[0]["inbound_id"], quantity, outbound_type, unit_price, total, customer_id, operator))
    # 更新库存
    new_qty = stock["current_stock"] - quantity
    new_val = round(new_qty * stock["avg_cost"], 2)
    cur.execute("UPDATE stock_snapshots SET current_stock=%s, total_value=%s, updated_at=NOW() WHERE sku_id=%s",
                (new_qty, new_val, sku_id))
    # 更新客户消费
    if customer_id and outbound_type == "销售":
        cur.execute("UPDATE customers SET total_spent=total_spent+%s, visit_count=visit_count+1, last_visit=CURDATE() WHERE customer_id=%s",
                    (total, customer_id))
    conn.commit(); cur.close(); conn.close()
    return {"outbound_id": oid, "total_amount": total, "remaining_stock": new_qty}

# ==================== 库存查询 ====================
def get_all_stock(category: str = None) -> List[Dict]:
    conn = get_connection(); cur = conn.cursor()
    sql = """SELECT s.*, p.name, p.category, p.brand, p.spec, p.unit, p.retail_price, p.safety_stock, p.replenish_point
             FROM stock_snapshots s JOIN products p ON s.sku_id = p.sku_id"""
    if category: sql += " WHERE p.category = %s"; cur.execute(sql, (category,))
    else: cur.execute(sql)
    rows = cur.fetchall(); cur.close(); conn.close()
    return rows

def get_low_stock_alerts() -> List[Dict]:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT s.*, p.name, p.category FROM stock_snapshots s
        JOIN products p ON s.sku_id=p.sku_id WHERE s.current_stock <= p.replenish_point""")
    rows = cur.fetchall(); cur.close(); conn.close()
    return rows

# ==================== 客户查询 ====================
def get_customer(customer_id: str) -> Optional[Dict]:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT * FROM customers WHERE customer_id = %s", (customer_id,))
    row = cur.fetchone()
    if row and row.get("pets") and isinstance(row["pets"], str):
        row["pets"] = json.loads(row["pets"])
    if row and row.get("tags") and isinstance(row["tags"], str):
        row["tags"] = json.loads(row["tags"])
    cur.close(); conn.close()
    return row

def get_all_customers() -> List[Dict]:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT * FROM customers ORDER BY last_visit DESC")
    rows = cur.fetchall(); cur.close(); conn.close()
    return rows

# ==================== 托管 ====================
def insert_daycare(record: Dict):
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""INSERT INTO daycare_records (id, pet_name, breed, owner_name, owner_phone,
        staff, daycare_type, duration, status, notes) VALUES
        (%(id)s,%(pet_name)s,%(breed)s,%(owner_name)s,%(owner_phone)s,%(staff)s,%(daycare_type)s,%(duration)s,%(status)s,%(notes)s)""", record)
    conn.commit(); cur.close(); conn.close()

def get_today_daycare() -> List[Dict]:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT * FROM daycare_records WHERE DATE(checkin_time) = CURDATE() AND checkout_time IS NULL")
    rows = cur.fetchall(); cur.close(); conn.close()
    return rows

# ==================== 看板统计 ====================
def get_today_stats() -> Dict:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(total_amount),0) as revenue, COUNT(*) as orders FROM outbound_records WHERE DATE(outbound_time)=CURDATE() AND outbound_type='销售'")
    sales = cur.fetchone()
    cur.execute("SELECT COUNT(*) as total, COALESCE(SUM(current_stock),0) as stock_total FROM stock_snapshots")
    stock = cur.fetchone()
    cur.execute("SELECT COUNT(*) as low FROM stock_snapshots s JOIN products p ON s.sku_id=p.sku_id WHERE s.current_stock <= p.replenish_point")
    low = cur.fetchone()
    cur.close(); conn.close()
    return {"revenue": float(sales["revenue"]), "orders": sales["orders"],
            "total_stock": stock["stock_total"] or 0, "low_stock_count": low["low"] or 0}

def _recent_month_buckets(months: int) -> List[str]:
    """最近 N 个自然月的 'YYYY-MM'，从最早到最近。

    先造桶、再去填数——直接 GROUP BY 的话，没有数据的月份会整个消失，
    折线图就会从 12 个点变成只有几个点。这是本模块最容易踩的坑。
    """
    today = date.today()
    y, m, out = today.year, today.month, []
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))

def _month_bounds(d: date = None):
    """d 所在自然月的 (1号, 月末)。"""
    d = d or date.today()
    first = d.replace(day=1)
    nxt = date(first.year + 1, 1, 1) if first.month == 12 else date(first.year, first.month + 1, 1)
    return first, nxt - timedelta(days=1)

def _week_bounds(d: date = None):
    """d 所在自然周的 (周一, 周日)。date.weekday() 周一=0，符合国内习惯。"""
    d = d or date.today()
    mon = d - timedelta(days=d.weekday())
    return mon, mon + timedelta(days=6)

def _kpi_start(period: str) -> date:
    """KPI 汇总窗口的起始日。一律取**自然区间**的起点，不是往前滚 N 天。

    注意这和下面的趋势窗口**不是一回事**：period='today' 时 KPI 只有今天一天，
    但趋势图仍然画近 7 天（单看一个点没有意义）。两者混用会让"今日营收"
    变成"近7天营收"——这个坑我已经踩过一次了。
    """
    t = date.today()
    if period == "year":
        k = _recent_month_buckets(12)[0]
        return date(int(k[:4]), int(k[5:]), 1)
    if period == "month":
        return _month_bounds(t)[0]
    if period == "week":
        return _week_bounds(t)[0]
    return t

def _trend_buckets(period: str):
    """趋势图 → (日期/月份桶列表, 粒度)。桶一定铺满整个自然区间。

    本月 = 1号到月末（哪怕今天才 18 号，19~30 号也要在，值补 0）；
    本周 = 周一到周日。之前这里是"往前滚 30/7 天"，x 轴会随日期滑动——
    用户看到的「本月」是从 8/20 开始的，不是自然月。
    """
    t = date.today()
    if period == "year":
        return _recent_month_buckets(12), "month"
    # 今天的"所在自然区间"就是今天一天，画一个点没有意义，
    # 所以给它近 7 天当背景，并通过 range 标签说明这是"近 7 天"而不是"本周"
    first, last = (_week_bounds(t) if period == "week"
                   else _month_bounds(t) if period == "month"
                   else (t - timedelta(days=6), t))
    n = (last - first).days + 1
    return [first + timedelta(days=i) for i in range(n)], "day"

def _sum_daily_metrics(start: date, end: date) -> Dict:
    """汇总 daily_metrics 区间（日报表只存到昨天，不含今天）。"""
    if end < start:
        return {"revenue": 0.0, "orders": 0, "profit": 0.0}
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT COALESCE(SUM(revenue),0) rev, COALESCE(SUM(order_count),0) cnt,
                          COALESCE(SUM(gross_profit),0) profit
                   FROM daily_metrics WHERE stat_date BETWEEN %s AND %s""", (start, end))
    r = cur.fetchone(); cur.close(); conn.close()
    return {"revenue": float(r["rev"]), "orders": int(r["cnt"]), "profit": float(r["profit"])}

def _today_live() -> Dict:
    """今天的真实经营数据——直接算，不经过日报表（日报表里永远没有今天）。"""
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT COALESCE(SUM(total_amount),0) rev, COUNT(*) cnt
                   FROM outbound_records WHERE DATE(outbound_time)=CURDATE() AND outbound_type='销售'""")
    r = cur.fetchone()
    # 毛利 = 售价 - 成本，成本取该 SKU 的移动平均成本
    cur.execute("""SELECT COALESCE(SUM(o.total_amount - o.quantity * s.avg_cost),0) profit
                   FROM outbound_records o JOIN stock_snapshots s ON o.sku_id = s.sku_id
                   WHERE DATE(o.outbound_time)=CURDATE() AND o.outbound_type='销售'""")
    p = cur.fetchone(); cur.close(); conn.close()
    return {"revenue": float(r["rev"]), "orders": int(r["cnt"]), "profit": float(p["profit"])}

def get_period_stats(period: str = "today") -> Dict:
    """按时间窗口汇总 KPI：昨天及以前读日报表，今天实时算。"""
    t = date.today()
    start = _kpi_start(period)
    hist = _sum_daily_metrics(start, t - timedelta(days=1))
    live = _today_live()
    return {"revenue": round(hist["revenue"] + live["revenue"], 2),
            "orders": hist["orders"] + live["orders"],
            "gross_profit": round(hist["profit"] + live["profit"], 2)}

def get_trend_data(period: str = "today") -> Dict:
    """销售趋势。桶一定铺满整个自然区间，**没数据的（含还没到的日期）补 0**。

    today → 近 7 天按天（7 个点，纯背景参考）
    week  → 本周一到周日按天（固定 7 个点，未来的日子是 0）
    month → 本月 1 号到月末按天（28~31 个点，未来的日子是 0）
    year  → 近 12 个自然月按月（12 个点，每个月都在）

    返回里带 `range`，前端直接显示在图表标题上——这样"图在画哪一段"不用猜。
    """
    t = date.today()
    buckets, grain = _trend_buckets(period)

    if grain == "month":
        keys = buckets
        rev = {k: 0.0 for k in keys}
        cnt = {k: 0 for k in keys}
        conn = get_connection(); cur = conn.cursor()
        cur.execute("""SELECT DATE_FORMAT(stat_date,'%%Y-%%m') k, COALESCE(SUM(revenue),0) rev,
                              COALESCE(SUM(order_count),0) cnt
                       FROM daily_metrics WHERE stat_date BETWEEN %s AND %s GROUP BY k""",
                    (date(int(keys[0][:4]), int(keys[0][5:]), 1), t - timedelta(days=1)))
        for r in cur.fetchall():
            if r["k"] in rev:
                rev[r["k"]] = float(r["rev"]); cnt[r["k"]] = int(r["cnt"])
        cur.close(); conn.close()
        live = _today_live()                       # 今天实时，落到当月那个点上
        cur_key = f"{t.year:04d}-{t.month:02d}"
        if cur_key in rev:
            rev[cur_key] += live["revenue"]; cnt[cur_key] += live["orders"]
        return {"labels": [f"{k[5:7]}月" for k in keys],
                "revenue": [round(rev[k], 2) for k in keys],
                "orders": [cnt[k] for k in keys], "granularity": "month",
                "range": f"{keys[0]} ~ {keys[-1]}"}

    # 按天：先铺满整段日期（含还没到的），再往里填
    days = buckets
    rev = {d: 0.0 for d in days}
    cnt = {d: 0 for d in days}
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT stat_date d, COALESCE(SUM(revenue),0) rev, COALESCE(SUM(order_count),0) cnt
                   FROM daily_metrics WHERE stat_date BETWEEN %s AND %s GROUP BY stat_date""",
                (days[0], t - timedelta(days=1)))
    for r in cur.fetchall():
        if r["d"] in rev:
            rev[r["d"]] = float(r["rev"]); cnt[r["d"]] = int(r["cnt"])
    cur.close(); conn.close()
    live = _today_live()
    if t in rev:
        rev[t] += live["revenue"]; cnt[t] += live["orders"]
    # 未来的日期天然是 0——日报表里没有它们，今天也没到
    label = (f"{days[0].month}/{days[0].day} ~ {days[-1].month}/{days[-1].day}"
             if period != "today" else "近 7 天")
    return {"labels": [f"{d.month}/{d.day}" for d in days],
            "revenue": [round(rev[d], 2) for d in days],
            "orders": [cnt[d] for d in days], "granularity": "day",
            "range": label}

def get_monthly_metrics(months: int = 12) -> List[Dict]:
    """月度明细（含环比），最近 N 个自然月。空月补 0，一个月都不会少。"""
    t = date.today()
    keys = _recent_month_buckets(months)
    start = date(int(keys[0][:4]), int(keys[0][5:]), 1)
    agg = {k: {"revenue": 0.0, "orders": 0, "profit": 0.0} for k in keys}
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT DATE_FORMAT(stat_date,'%%Y-%%m') k, COALESCE(SUM(revenue),0) rev,
                          COALESCE(SUM(order_count),0) cnt, COALESCE(SUM(gross_profit),0) profit
                   FROM daily_metrics WHERE stat_date BETWEEN %s AND %s GROUP BY k""",
                (start, t - timedelta(days=1)))
    for r in cur.fetchall():
        if r["k"] in agg:
            agg[r["k"]] = {"revenue": float(r["rev"]), "orders": int(r["cnt"]),
                           "profit": float(r["profit"])}
    cur.close(); conn.close()
    live = _today_live()
    cur_key = f"{t.year:04d}-{t.month:02d}"
    agg[cur_key]["revenue"] += live["revenue"]
    agg[cur_key]["orders"] += live["orders"]
    agg[cur_key]["profit"] += live["profit"]

    out, prev = [], None
    for k in keys:
        a = agg[k]
        rev = round(a["revenue"], 2)
        partial = (k == cur_key)
        out.append({"month": k, "label": f"{k[:4]}年{int(k[5:])}月", "revenue": rev,
                    "orders": a["orders"], "profit": round(a["profit"], 2),
                    "avg_order": round(rev / a["orders"], 2) if a["orders"] else 0,
                    # 当月还没走完（今天才 18 号），拿半个月去比上个月整月是假比较，
                    # 会稳定显示成 -50% 左右，看着像生意崩了。宁可标出来不给数。
                    "partial": partial,
                    # 环比：上个月为 0 时不给百分比，避免除零后显示成 +∞ 这种假数
                    "mom": None if partial else (
                           round((rev - prev["revenue"]) / prev["revenue"] * 100, 1)
                           if prev and prev["revenue"] > 0 else None)})
        prev = a
    return out

def get_top_products(period: str = "today", limit: int = 5) -> List[Dict]:
    """真实销量排行：历史走 daily_product_sales，今天走实时出库记录。

    旧实现是把"当前库存"当销量返回的（routes.py 里注释自认"简化"），是假数据。
    """
    t = date.today()
    start = _kpi_start(period)
    agg = {}
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT sku_id, sku_name, COALESCE(SUM(qty),0) qty, COALESCE(SUM(revenue),0) rev
                   FROM daily_product_sales WHERE stat_date BETWEEN %s AND %s
                   GROUP BY sku_id, sku_name""", (start, t - timedelta(days=1)))
    for r in cur.fetchall():
        agg[r["sku_id"]] = {"name": r["sku_name"], "sold_qty": int(r["qty"]),
                            "revenue": float(r["rev"])}
    # 今天实时
    cur.execute("""SELECT o.sku_id, p.name, COALESCE(SUM(o.quantity),0) qty,
                          COALESCE(SUM(o.total_amount),0) rev
                   FROM outbound_records o JOIN products p ON o.sku_id = p.sku_id
                   WHERE DATE(o.outbound_time)=CURDATE() AND o.outbound_type='销售'
                   GROUP BY o.sku_id, p.name""")
    for r in cur.fetchall():
        a = agg.setdefault(r["sku_id"], {"name": r["name"], "sold_qty": 0, "revenue": 0.0})
        a["sold_qty"] += int(r["qty"]); a["revenue"] += float(r["rev"])
    cur.close(); conn.close()
    top = sorted(agg.values(), key=lambda x: x["revenue"], reverse=True)[:limit]
    return [{"name": x["name"], "sold_qty": x["sold_qty"], "revenue": round(x["revenue"], 2)} for x in top]

def get_customer_stats() -> Dict:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) as total FROM customers")
    total = cur.fetchone()["total"]
    cur.execute("SELECT COUNT(*) as cnt FROM customers WHERE visit_count >= 2")
    repeat = cur.fetchone()["cnt"]
    cur.execute("SELECT COUNT(*) as cnt FROM customers WHERE MONTH(created_at)=MONTH(CURDATE())")
    new = cur.fetchone()["cnt"]
    cur.close(); conn.close()
    return {"total": total, "repeat_rate": round(repeat/total*100, 1) if total > 0 else 0, "new_this_month": new}

def get_retention_suggestions() -> List[Dict]:
    conn = get_connection(); cur = conn.cursor()
    cur.execute("""SELECT customer_id, name, pets, DATEDIFF(CURDATE(), last_visit) as days_absent
        FROM customers WHERE last_visit IS NOT NULL AND DATEDIFF(CURDATE(), last_visit) > 30 ORDER BY days_absent DESC LIMIT 5""")
    rows = cur.fetchall(); cur.close(); conn.close()
    result = []
    for r in rows:
        pets = json.loads(r["pets"]) if isinstance(r["pets"], str) else (r["pets"] or [])
        pet = pets[0] if pets else {}
        result.append({"customer_id": r["customer_id"], "name": r["name"],
            "pet_name": pet.get("name",""), "pet_breed": pet.get("breed",""),
            "days_since_last_visit": r["days_absent"],
            "reason": f"{r['days_absent']}天未到店",
            "suggestion": "推送洗护优惠券" if r["days_absent"] > 60 else "发送关心问候"})
    return result

# ==================== 商品目录 ====================
# 必须与 frontend/js/cashier.js 的 PRODUCT_CATALOG 保持一致：
# 同一个 sku_id 在两边的名称/售价必须相同，否则结算时后端会扣错商品的库存。
# 编号约定：SKU001~ 狗粮 / SKU101~ 猫粮 / SKU201~ 零食 / SKU301~ 用品 / SV 服务
# 末位 expiry_days = 保质期天数，None 表示不追踪效期
# (sku_id, barcode, name, category, brand, spec, unit, retail, cost, safety, replenish, init_stock, expiry_days)
CATALOG = [
    ("SKU001","6901234567890","皇家小型犬成犬粮","狗粮","皇家","1.5kg/袋","袋",158,120,8,5,85,365),
    ("SKU002","6901234567891","爱肯拿鸡肉全犬粮","狗粮","爱肯拿","2kg/袋","袋",239,180,5,3,42,365),
    ("SKU007","6901234567900","冠能幼犬粮","狗粮","冠能","2.5kg/袋","袋",189,140,8,5,63,365),
    ("SKU008","6901234567901","渴望六种鱼全犬粮","狗粮","渴望","2kg/袋","袋",298,225,5,3,18,365),
    ("SKU009","6901234567902","伯纳天纯大型犬粮","狗粮","伯纳天纯","15kg/袋","袋",468,350,3,2,8,540),
    ("SKU010","6901234567903","比瑞吉天然粮","狗粮","比瑞吉","2kg/袋","袋",168,125,8,5,55,300),
    ("SKU011","6901234567904","麦富迪双拼粮","狗粮","麦富迪","1.5kg/袋","袋",98,72,15,8,120,365),
    ("SKU012","6901234567905","海洋之星三文鱼粮","狗粮","海洋之星","1.5kg/袋","袋",228,170,8,5,31,240),
    ("SKU101","6901234567910","皇家室内成猫粮","猫粮","皇家","2kg/袋","袋",178,135,8,5,72,365),
    ("SKU102","6901234567911","爱肯拿牧场盛宴猫粮","猫粮","爱肯拿","1.8kg/袋","袋",258,195,5,3,38,365),
    ("SKU103","6901234567912","冠能泌尿健康猫粮","猫粮","冠能","2kg/袋","袋",198,150,8,5,50,365),
    ("SKU104","6901234567913","渴望六种鱼猫粮","猫粮","渴望","1.8kg/袋","袋",318,240,5,3,12,300),
    ("SKU105","6901234567914","GO! 九种肉猫粮","猫粮","GO!","1.8kg/袋","袋",288,218,5,3,25,365),
    ("SKU106","6901234567915","纽顿T24鲑鱼猫粮","猫粮","纽顿","1.5kg/袋","袋",238,180,5,3,3,270),
    ("SKU107","6901234567916","网易严选全价猫粮","猫粮","网易严选","1.8kg/袋","袋",89,65,15,8,95,400),
    ("SKU108","6901234567917","比瑞吉天然猫粮","猫粮","比瑞吉","2kg/袋","袋",158,118,8,5,60,300),
    # 鸡肉绕钙棒故意给短效期，用来演示效期预警
    ("SKU005","6901234567894","鸡肉绕钙棒","零食","顽皮","100g/袋","袋",25,15,30,15,200,25),
    ("SKU006","6901234567895","巅峰牛肉罐头","零食","巅峰","185g/罐","罐",42,30,10,5,48,200),
    ("SKU201","6901234567920","冻干鸡肉粒","零食","朗诺","50g/袋","袋",35,25,20,10,80,150),
    ("SKU202","6901234567921","猫条混合口味","零食","伊纳宝","12支/盒","盒",28,20,30,15,150,120),
    ("SKU003","6901234567892","豆腐猫砂","猫砂","N1","6L/包","包",29.9,18,20,10,300,730),
    ("SKU004","6901234567893","犬用体内驱虫药","药品","拜耳","1粒/盒","盒",68,45,15,8,35,400),
    ("SKU303","6901234567930","宠物尿垫","用品","爱丽丝","60x45cm 50片","包",39,28,15,8,65,None),
    ("SKU304","6901234567931","不锈钢双碗","用品","多格漫","中号","个",55,40,8,5,28,None),
    # 服务类不占库存，前端走 /api/grooming/book
    ("SV001","","小型犬基础洗护","服务","","约40分钟","次",88,0,99,99,None,None),
    ("SV002","","猫咪精洗护理","服务","","约60分钟","次",128,0,99,99,None,None),
    ("SV003","","中大型犬精洗","服务","","约90分钟","次",158,0,99,99,None,None),
    ("SV004","","剃毛造型","服务","","约60-120分钟","次",188,0,99,99,None,None),
    ("SV101","","小型犬日托","托管","","半天","次",68,0,99,99,None,None),
    ("SV102","","小型犬寄养","托管","","过夜","次",98,0,99,99,None,None),
    ("SV103","","玩耍区计时","托管","","1小时","次",38,0,99,99,None,None),
]

CATALOG_BY_SKU = {row[0]: row for row in CATALOG}


def _make_opening_batch(cur, sku_id: str, qty: int, unit_cost: float, expiry_days):
    """给一个 SKU 补期初入库批次。

    FIFO 出库扣的是 inbound_records.remaining_qty——只有库存快照、没有批次记录的话，
    process_outbound 会一直返回"库存不足或批次异常"，后端结算永远失败。
    """
    expiry = date.today() + timedelta(days=expiry_days) if expiry_days else None
    cur.execute("""INSERT INTO inbound_records (inbound_id, sku_id, supplier_id, quantity,
        unit_cost, total_cost, batch_no, expiry_date, remaining_qty, operator)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (f"IN-OPEN-{sku_id}", sku_id, "OPENING", qty, unit_cost,
         round(qty * unit_cost, 2), "期初", expiry, qty, "系统"))


# ==================== 种子数据 ====================
def seed_sample_data():
    """幂等填充：按 SKU 补齐缺失的商品 / 库存快照 / 期初入库批次，已存在的一律不动。"""
    conn = get_connection(); cur = conn.cursor()

    cur.execute("SELECT sku_id FROM products")
    existing = {r["sku_id"] for r in cur.fetchall()}
    added = 0
    for (sku_id, barcode, name, category, brand, spec, unit,
         retail, cost, safety, replenish, init_stock, expiry_days) in CATALOG:
        if sku_id in existing:
            continue
        cur.execute("""INSERT INTO products (sku_id,barcode,name,category,brand,spec,unit,
            retail_price,last_unit_cost,safety_stock,replenish_point)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (sku_id, barcode, name, category, brand, spec, unit, retail, cost, safety, replenish))
        if init_stock is not None:
            cur.execute("""INSERT INTO stock_snapshots (sku_id,current_stock,avg_cost,total_value)
                VALUES (%s,%s,%s,%s)""", (sku_id, init_stock, cost, round(init_stock * cost, 2)))
            _make_opening_batch(cur, sku_id, init_stock, cost, expiry_days)
        added += 1

    # 历史库补批次：有库存快照但一个入库批次都没有的 SKU（老版本种子数据留下的）
    cur.execute("""SELECT s.sku_id, s.current_stock, s.avg_cost FROM stock_snapshots s
        LEFT JOIN inbound_records i ON i.sku_id = s.sku_id
        WHERE s.current_stock > 0 AND i.inbound_id IS NULL""")
    backfilled = cur.fetchall()
    for r in backfilled:
        row = CATALOG_BY_SKU.get(r["sku_id"])
        _make_opening_batch(cur, r["sku_id"], r["current_stock"],
                            float(r["avg_cost"] or 0), row[12] if row else None)

    # 客户
    customers_data = [
        ("CUST001","陈女士","138****5678",
         '[{"name":"豆豆","species":"狗","breed":"柯基","age":3,"vaccine_dates":["2025-08-01"],"last_grooming":"2026-06-20"}]',
         '["VIP","柯基主人"]',6800,32,'2026-07-15','VIP'),
        ("CUST002","李先生","139****1234",
         '[{"name":"乐乐","species":"狗","breed":"金毛","age":2,"vaccine_dates":["2026-01-15"],"last_grooming":"2026-06-30"}]',
         '["金毛主人"]',3200,18,'2026-06-30','金卡'),
        ("CUST003","王女士","136****9988",
         '[{"name":"布丁","species":"猫","breed":"英短","age":1,"vaccine_dates":["2026-03-20"],"last_grooming":"2026-07-03"}]',
         '["猫咪主人"]',1500,8,'2026-07-20','普通'),
        ("CUST004","赵女士","137****5566",
         '[{"name":"大壮","species":"狗","breed":"哈士奇","age":4,"vaccine_dates":["2025-12-10"],"last_grooming":"2026-07-10"}]',
         '["哈士奇主人"]',5200,22,'2026-07-10','金卡'),
        ("CUST005","刘叔","135****7890",
         '[{"name":"小黑","species":"狗","breed":"泰迪","age":5,"vaccine_dates":["2025-08-20"],"last_grooming":"2026-05-15"}]',
         '["泰迪主人"]',12000,56,'2026-07-22','VIP'),
    ]
    cur.execute("SELECT COUNT(*) as cnt FROM customers")
    customers_data = customers_data if cur.fetchone()["cnt"] == 0 else []
    for c in customers_data:
        cur.execute("""INSERT INTO customers (customer_id,name,phone,pets,tags,total_spent,visit_count,last_visit,member_level)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", c)

    # 洗护预约（今天 + 未来几天）
    grooming_data = [
        ("APT-A1B2C3D4","CUST001","陈女士","豆豆","狗","小型犬基础洗护","张师傅",
         f"{date.today()} 10:00:00",60,"已预约","柯基双层毛，注意底层绒毛吹干"),
        ("APT-E5F6G7H8","CUST002","李先生","乐乐","狗","中大型犬精洗","张师傅",
         f"{date.today()} 14:00:00",90,"进行中","金毛掉毛季，深度除浮毛"),
        ("APT-I9J0K1L2","CUST003","王女士","布丁","猫","猫咪精洗护理","李师傅",
         f"{date.today()} 15:30:00",60,"已预约","英短短毛猫，注意水温和吹风档位"),
        ("APT-M3N4O5P6","CUST004","赵女士","大壮","狗","剃毛造型","李师傅",
         f"{date.today()} 11:00:00",120,"已预约","哈士奇夏季剃毛，留3mm底层"),
    ]
    cur.execute("SELECT COUNT(*) as cnt FROM grooming_schedule")
    grooming_data = grooming_data if cur.fetchone()["cnt"] == 0 else []
    for g in grooming_data:
        cur.execute("""INSERT INTO grooming_schedule (appointment_id,customer_id,customer_name,
            pet_name,pet_species,service_type,groomer,scheduled_start,
            estimated_minutes,status,pet_notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", g)

    # 托管
    cur.execute("SELECT COUNT(*) as cnt FROM daycare_records")
    if cur.fetchone()["cnt"] == 0:
        cur.execute("""INSERT INTO daycare_records (id,pet_name,breed,owner_name,owner_phone,staff,daycare_type,duration,status,notes)
            VALUES ('DC001','旺财','柯基','刘先生','139****','小王','daycare','半天','playing','精力旺盛，多玩球'),
                   ('DC002','小花','泰迪','赵女士','136****','小陈','boarding','3天','boarding','早晚各遛一次，每日梳毛'),
                   ('DC003','元宝','法斗','周女士','138****','小王','daycare','全天','resting','短鼻犬注意室温不超过26度')""")

    conn.commit(); cur.close(); conn.close()
    if added:
        print(f"[数据库] 已补齐 {added} 个商品 SKU")
    if backfilled:
        print(f"[数据库] 已为 {len(backfilled)} 个 SKU 补期初入库批次")
    print("[数据库] 种子数据就绪")
    seed_history_metrics()


# ==================== 历史经营数据（演示用） ====================
def seed_history_metrics(days: int = 365):
    """造最近一年的经营日报 + 商品日销，供看板展示年度趋势。

    为什么不直接补一年的 outbound_records 流水：那张表和**库存扣减**是绑死的，
    凭空补一年出库会把库存卖成负数，污染现网数据。报表层只记"卖了多少"，
    不碰库存，天然解耦——真实 POS 系统同样是"流水表 + 日报表"两层。

    两条硬规则：
      1. 只造到【昨天】。今天永远由 _today_live() 实时算，否则今天会被算两遍。
      2. 幂等。daily_metrics 非空就直接返回，重启服务不会重复造。

    关于随机数：本项目其它地方都不用随机（数据全写死），这里是有意偏离——
    一年的经营数据全写死不现实。改用**固定种子**的 Random 实例，既有真实波动，
    又保证每次重建都生成一模一样的数，可复现、可断言。
    """
    conn = get_connection(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) c FROM daily_metrics")
    if cur.fetchone()["c"] > 0:
        cur.close(); conn.close()
        return

    cur.execute("""SELECT sku_id, name, category, retail_price, last_unit_cost FROM products
                   WHERE category NOT IN ('服务','托管') ORDER BY sku_id""")
    prods = cur.fetchall()
    if not prods:
        cur.close(); conn.close()
        print("[数据库] 没有实物商品，跳过历史经营数据")
        return

    today = date.today()
    rng = random.Random(20260918)
    # 每个 SKU 一个"热销度"，决定它每天出现的概率
    weight = {p["sku_id"]: rng.uniform(0.4, 2.6) for p in prods}

    # 宠物店旺季：夏季寄养/洗护多，冬季春节前囤粮
    season = {1: 1.20, 2: 1.10, 3: 0.95, 4: 0.92, 5: 0.95, 6: 1.05,
              7: 1.15, 8: 1.18, 9: 0.98, 10: 0.95, 11: 1.00, 12: 1.15}
    weekend = {4: 1.15, 5: 1.45, 6: 1.35}          # weekday(): 4=周五 5=周六 6=周日

    # 最近 3 个自然月各挑一天"盘点歇业"——整天一行数据都不写。
    # 这不是为了好看，是为了让"空桶必须补 0"这件事**可被验证**：
    # 如果分桶逻辑有 bug 直接 GROUP BY，图上这一天就会凭空消失。
    closed = set()
    for back in range(3):
        y, m = today.year, today.month - back
        while m <= 0:
            m += 12; y -= 1
        d = date(y, m, 5)
        if d < today:
            closed.add(d)

    rows_m, rows_p = [], []
    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        if d in closed:
            continue
        factor = (season.get(d.month, 1.0) * weekend.get(d.weekday(), 1.0)
                  * (0.85 + 0.15 * (days - i) / days)      # 一年内缓慢增长
                  * rng.uniform(0.90, 1.10))
        day_rev = day_cost = 0.0
        for p in prods:
            prob = min(0.95, max(0.04, 0.5 * factor * weight[p["sku_id"]] / 2.0))
            if rng.random() > prob:
                continue
            qty = max(1, int(rng.gauss(2, 1.1)))
            retail = float(p["retail_price"] or 0)
            rev = round(qty * retail, 2)
            day_rev += rev
            day_cost += qty * float(p["last_unit_cost"] or 0)
            rows_p.append((d, p["sku_id"], p["name"], p["category"], qty, rev))
        if day_rev <= 0:
            continue

        # 营业额就是当天商品销售额的合计——不是另掷一次骰子。
        # 两个独立随机数的话，"日报表和商品日销怎么对不上"这种问题迟早会被人问。
        orders = max(1, int(day_rev / rng.uniform(150, 220)))
        new_c = rng.randint(1, 4)
        rows_m.append((d, round(day_rev, 2), orders, round(day_rev - day_cost, 2),
                       new_c, max(0, int(orders * 0.6) - new_c),
                       rng.randint(2, 9), rng.randint(0, 5)))

    cur.executemany("""INSERT INTO daily_metrics (stat_date, revenue, order_count, gross_profit,
        new_customers, returning_customers, grooming_orders, daycare_count, is_synthetic)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1)""", rows_m)
    cur.executemany("""INSERT INTO daily_product_sales (stat_date, sku_id, sku_name, category,
        qty, revenue) VALUES (%s,%s,%s,%s,%s,%s)""", rows_p)
    conn.commit(); cur.close(); conn.close()
    print(f"[数据库] 已生成历史经营数据：{len(rows_m)} 天日报 / {len(rows_p)} 条商品日销"
          f"（歇业日 {len(closed)} 天，用于验证空桶补零）")
