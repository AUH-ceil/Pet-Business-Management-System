# ============================================================
# backend/models.py - 数据模型
# ============================================================
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ==================== 枚举 ====================
class OutboundType(str, Enum):
    SALE = "销售"
    DAMAGE = "破损"
    TRIAL = "试用"
    EXPIRED = "过期报损"
    INTERNAL = "店内消耗"


class DaycareType(str, Enum):
    BOARDING = "boarding"   # 寄养
    PLAYING = "playing"     # 玩耍
    DAYCARE = "daycare"     # 日托


class DaycareStatus(str, Enum):
    PLAYING = "playing"
    RESTING = "resting"
    PICKUP = "pickup"


# ==================== 进销存模型 ====================
class ProductInfo(BaseModel):
    sku_id: str
    barcode: Optional[str] = ""
    name: str
    category: str = "用品"
    brand: str = ""
    spec: str = ""
    unit: str = "个"
    retail_price: float = 0
    last_unit_cost: float = 0

class InboundRequest(BaseModel):
    sku_id: str = Field(min_length=1)
    quantity: int = Field(gt=0, le=100000)   # 堵住负数和 0：它们会把库存和均价刷成负数
    unit_cost: float = Field(ge=0)
    supplier_id: str = ""
    batch_no: str = ""
    expiry_date: Optional[str] = None
    operator: str = "店员"

class InboundLine(BaseModel):
    sku_id: str = Field(min_length=1)
    quantity: int = Field(gt=0, le=100000)
    unit_cost: float = Field(ge=0)
    batch_no: str = ""
    expiry_date: Optional[str] = ""

class InboundBatchRequest(BaseModel):
    lines: List[InboundLine] = Field(min_length=1)
    supplier_id: str = ""
    operator: str = "店员"

class OutboundRequest(BaseModel):
    sku_id: str
    quantity: int = 1
    outbound_type: OutboundType = OutboundType.SALE
    unit_price: float = 0
    customer_id: Optional[str] = None
    operator: str = "店员"

class CartItem(BaseModel):
    sku_id: str
    name: str
    quantity: int = 1
    unit_price: float = 0
    type: str = "product"  # product | grooming | daycare

class CheckoutRequest(BaseModel):
    items: List[CartItem]
    customer_id: Optional[str] = None
    discount: float = 1.0
    total_amount: float = 0
    remark: str = ""

class StockSnapshot(BaseModel):
    sku_id: str
    name: str
    category: str
    current_stock: int
    unit: str
    avg_cost: float
    retail_price: float
    safety_stock: int
    replenish_point: int
    min_expiry_date: Optional[str] = None
    turnover_days: float = 0
    expiry_warning: bool = False
    slow_moving: bool = False


# ==================== 客户模型 ====================
class PetInfo(BaseModel):
    name: str
    species: str = "狗"
    breed: str = ""
    gender: str = ""
    birth_date: Optional[str] = None
    vaccine_dates: List[str] = []
    neutered: bool = False
    notes: str = ""

class CustomerInfo(BaseModel):
    customer_id: str
    name: str
    phone: str = ""
    wechat_id: str = ""
    pets: List[PetInfo] = []
    tags: List[str] = []
    total_spent: float = 0
    visit_count: int = 0
    last_visit: Optional[str] = None
    member_level: str = "普通"

class CustomerRetention(BaseModel):
    customer_id: str
    name: str
    pet_name: str
    pet_breed: str
    days_since_last_visit: int
    reason: str
    suggestion: str


# ==================== 洗护模型 ====================
class GroomingAppointment(BaseModel):
    appointment_id: str = ""
    customer_id: str
    customer_name: str = ""
    pet_name: str
    pet_species: str
    service_type: str
    groomer: str
    scheduled_start: str
    estimated_minutes: int = 60
    status: str = "已预约"
    pet_notes: str = ""

class GroomerSchedule(BaseModel):
    name: str
    appointments: List[GroomingAppointment] = []


# ==================== 托管模型 ====================
class DaycareCheckin(BaseModel):
    pet_name: str
    breed: str = ""
    owner_name: str
    owner_phone: str = ""
    staff: str
    daycare_type: DaycareType = DaycareType.PLAYING
    duration: str = "2小时"
    notes: str = ""

class DaycareRecord(BaseModel):
    id: str
    pet_name: str
    breed: str
    owner_name: str
    staff: str
    type_label: str
    duration: str
    status: str
    checkin_time: str
    notes: str = ""


# ==================== 活体健康模型 ====================
class HealthAlert(BaseModel):
    title: str
    desc: str
    severity: str = "info"  # urgent | info
    pet_name: str = ""
    due_date: Optional[str] = None


# ==================== 看板统计模型 ====================
class DashboardSummary(BaseModel):
    revenue: float = 0
    orders: int = 0
    total_stock: int = 0
    low_stock_count: int = 0

class TrendData(BaseModel):
    labels: List[str] = []
    revenue: List[float] = []
    orders: List[int] = []

class TopProduct(BaseModel):
    name: str
    sold_qty: int = 0
    revenue: float = 0

class StockWarning(BaseModel):
    name: str
    stock: int = 0
    severity: str = "warning"
    note: str = ""

class CustStat(BaseModel):
    total: int = 0
    repeat_rate: float = 0
    new_this_month: int = 0


# ==================== API 请求/响应 ====================
class ScanRequest(BaseModel):
    barcode: str

class ContentGenRequest(BaseModel):
    channel: str = "all"  # wechat | community | all

class ApiResponse(BaseModel):
    success: bool = True
    data: Optional[dict] = None
    message: str = ""
