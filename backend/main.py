# ============================================================
# backend/main.py — FastAPI 主入口
# ============================================================
import os, sys
from contextlib import asynccontextmanager
from dotenv import load_dotenv

_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(_env_path)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.database import init_database, seed_sample_data
from backend.qdrant_client import init_qdrant


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n" + "=" * 50)
    print("  宠物店智慧经营中枢 v1.0.0")
    print("  收银台: http://localhost:8001/app")
    print("  看板:   http://localhost:8001/dashboard")
    print("=" * 50 + "\n")
    # 基础设施逐层降级：任何一层挂了都不阻断启动
    try:
        init_database()
        seed_sample_data()
        print("[启动] MySQL 初始化完成")
    except Exception as e:
        print(f"[警告] MySQL 初始化失败: {e}")
    try:
        init_qdrant()
        print("[启动] Qdrant 初始化完成")
    except Exception as e:
        print(f"[警告] Qdrant 初始化失败: {e}")
    yield


app = FastAPI(title="宠物店智慧经营中枢", version="1.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

# 开发期禁止浏览器缓存前端资源。
# 不加这个，改完 js/html 后浏览器仍按启发式缓存跑旧版，会出现
# "代码明明改了、页面却没变"的假象——前端调试里最浪费时间的一类问题。
# （index.html 里的 js/x.js?v=N 是第二道保险，两层都留着。）
_PAGE_PATHS = {"/", "/app", "/dashboard", "/inventory", "/customers",
               "/grooming", "/health", "/daycare", "/content"}

@app.middleware("http")
async def no_cache_frontend(request, call_next):
    resp = await call_next(request)
    path = request.url.path
    if path in _PAGE_PATHS or path.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp

app.include_router(router)

FRONTEND = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND, "js")), name="js")

# 前端构建号：改了前端就 +1。必须与 index.html 里 js/x.js?v=N 的 N 保持一致。
_FRONTEND_BUILD = "4"

@app.get("/")
async def root():
    """根路径 → 收银台（顺便当"强制拿最新前端"的入口）。

    跳的是 /app?v=<构建号>，不是裸的 /app：浏览器可能缓存过旧的 /app，
    而这个带版本号的 URL 它从没请求过，只能走网络，必定拿到最新前端。
    改了前端只需要 +1 这里的 _FRONTEND_BUILD 和 index.html 里的 ?v=，
    老书签、老侧边栏链接下一跳就自动换新。
    """
    return RedirectResponse(url=f"/app?v={_FRONTEND_BUILD}", status_code=302)

@app.get("/app")
async def page_app(): return FileResponse(os.path.join(FRONTEND, "index.html"))

@app.get("/dashboard")
async def page_dashboard(): return FileResponse(os.path.join(FRONTEND, "dashboard.html"))

@app.get("/inventory")
async def page_inventory(): return FileResponse(os.path.join(FRONTEND, "inventory.html"))

@app.get("/customers")
async def page_customers(): return FileResponse(os.path.join(FRONTEND, "customers.html"))

@app.get("/grooming")
async def page_grooming(): return FileResponse(os.path.join(FRONTEND, "grooming.html"))

@app.get("/health")
async def page_health(): return FileResponse(os.path.join(FRONTEND, "health.html"))

@app.get("/daycare")
async def page_daycare(): return FileResponse(os.path.join(FRONTEND, "daycare.html"))

@app.get("/content")
async def page_content(): return FileResponse(os.path.join(FRONTEND, "content.html"))
