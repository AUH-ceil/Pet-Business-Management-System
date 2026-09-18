# ============================================================
# start.py — 一键启动
# 使用: python start.py
# 收银台: http://localhost:8001/app
# 看板:   http://localhost:8001/dashboard
# API文档: http://localhost:8001/docs
# ============================================================
import uvicorn, sys, os

# 加载 .env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("\n" + "=" * 50)
    print("  宠物店智慧经营中枢 v1.0.0")
    print("  http://localhost:8001/app     收银台")
    print("  http://localhost:8001/dashboard 经营看板")
    print("=" * 50 + "\n")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8001, reload=True, log_level="info")
