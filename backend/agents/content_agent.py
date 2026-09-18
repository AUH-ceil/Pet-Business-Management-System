# ============================================================
# Agent 5: 内容运营官 — 朋友圈/社群/小红书文案 + 素材推荐
# ============================================================
from typing import Dict, Any
from backend.llm_client import call_llm_json, is_llm_available

def content_agent(action: str, **kw) -> Dict[str, Any]:
    handlers = {"generate": _generate_content, "materials": _today_materials}
    h = handlers.get(action)
    if not h: return {"success": False, "message": f"未知操作: {action}"}
    try: return h(**kw)
    except Exception as e: return {"success": False, "message": str(e)}

def _generate_content(channel: str = "all", **kw) -> Dict:
    """生成各渠道营销文案"""
    result = {"wechat": "", "community": "", "materials": []}

    if is_llm_available():
        try:
            system = "你是宠物店运营专家，为社区宠物店写今日营销文案。只返回JSON。"
            user = """请为社区宠物店写今日营销文案，风格口语化、不推销腔。
返回JSON: {"wechat":"朋友圈文案30-60字","community":"社区群推广文案20-40字","materials":["今日推荐素材1","素材2","素材3"]}"""
            r = call_llm_json(system, user, temperature=0.8)
            if "error" not in r:
                result["wechat"] = r.get("wechat", "")
                result["community"] = r.get("community", "")
                result["materials"] = r.get("materials", [])
                return {"success": True, "data": result, "source": "LLM"}
        except: pass

    # 规则兜底
    result["wechat"] = "夏天到啦☀️ 毛孩子做好驱虫了吗？即日起进店选购驱虫药享会员9折，满199送宠物凉垫一个！🏖️"
    result["community"] = "邻居们好～最近天热，遛狗请选早晚凉快时段，备足饮水💧 有问题随时群里找我！"
    result["materials"] = ["洗护前后对比照3组", "新到爱肯拿猫粮实拍", "豆豆2岁生日派对照片"]
    return {"success": True, "data": result, "source": "模板"}

def _today_materials(**kw) -> Dict:
    return {"success": True, "materials": [
        {"type": "photo", "desc": "洗护前后对比——柯基豆豆", "score": 85},
        {"type": "photo", "desc": "新到货：爱肯拿猫粮全系列", "score": 72},
        {"type": "event", "desc": "今天豆豆2岁生日，在店里办了派对", "score": 90},
    ]}
