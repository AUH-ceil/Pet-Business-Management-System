# ============================================================
# backend/llm_client.py - LLM 调用封装（复用 agent11 架构）
# 支持 DeepSeek，指数退避重试，JSON 自动修复
# ============================================================
import os, json, time, re
from typing import Optional, Dict, Any

LLM_CONFIG = {
    "api_key": os.environ.get("DEEPSEEK_API_KEY", "sk-your-key"),
    "base_url": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
    "default_model": os.environ.get("LLM_MODEL", "deepseek-chat"),
    "max_retries": 3,
    "timeout": 60,
}

_client = None
_available = None

def _get_client():
    global _client, _available
    if _available is None:
        try:
            from openai import OpenAI
            _client = OpenAI(api_key=LLM_CONFIG["api_key"], base_url=LLM_CONFIG["base_url"], timeout=LLM_CONFIG["timeout"])
            _client.models.list()
            _available = True
            print(f"[LLM] 已连接 {LLM_CONFIG['base_url']}")
        except Exception as e:
            _available = False
            print(f"[LLM] 不可用: {str(e)[:80]}")
    return _client if _available else None

def is_llm_available() -> bool:
    return _get_client() is not None

def call_llm(system_prompt: str, user_prompt: str, model: str = None, temperature: float = 0.3, max_tokens: int = 2048) -> str:
    client = _get_client()
    if client is None:
        raise RuntimeError("LLM 不可用")
    model = model or LLM_CONFIG["default_model"]
    for attempt in range(LLM_CONFIG["max_retries"]):
        try:
            resp = client.chat.completions.create(model=model, temperature=temperature, max_tokens=max_tokens,
                messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}])
            return resp.choices[0].message.content or ""
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err:
                time.sleep(min((attempt+1)*10, 60))
            elif attempt < LLM_CONFIG["max_retries"] - 1:
                time.sleep(min(2**attempt, 8))
            else:
                raise RuntimeError(f"LLM 调用失败: {err}")
    raise RuntimeError("LLM 调用失败")

def call_llm_json(system_prompt: str, user_prompt: str, model: str = None, temperature: float = 0.1) -> Dict[str, Any]:
    try:
        raw = call_llm(system_prompt, user_prompt, model, temperature, max_tokens=2048)
        return _parse_json(raw)
    except Exception as e:
        print(f"[LLM JSON] 失败: {e}")
        return {"error": str(e)}

def _parse_json(raw: str) -> Dict[str, Any]:
    if not raw: return {"error": "空响应"}
    try: return json.loads(raw)
    except: pass
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if m:
        try: return json.loads(m.group(1))
        except: pass
    s = raw.find('{'); e = raw.rfind('}')
    if s >= 0 and e > s:
        try: return json.loads(raw[s:e+1])
        except: pass
    return {"error": "JSON解析失败", "raw": raw[:300]}
