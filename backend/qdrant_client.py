# ============================================================
# backend/qdrant_client.py - 向量库（客户画像 + 内容模板）
# 三级降级：本地嵌入式 Qdrant → 远程 Qdrant 服务端 → 本地文件（余弦暴力检索）
# ============================================================
import os, json, zlib, uuid, time, numpy as np
from typing import List, Dict, Any, Optional

QDRANT_HOST = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.environ.get("QDRANT_PORT", "6333"))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QDRANT_PATH = os.environ.get("QDRANT_PATH", os.path.join(_ROOT, "qdrant_data"))
_FALLBACK_FILE = os.path.join(_ROOT, "data", "vector_fallback.json")

_qdrant = None
_available = None
_backend = None                    # embedded | remote | memory
_opened_by = None                  # 谁打开的，供日志/状态接口显示
_local_store: Dict[str, dict] = {}

# 嵌入式模式只接受 UUID 格式的 point id，业务 id（CUST001）要先做确定性映射。
# 用 uuid5 而不是 uuid4：同一个 customer_id 每次都映射到同一个 UUID，才谈得上"更新画像"。
_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _point_id(key: str) -> str:
    return str(uuid.uuid5(_NS, key))


# ==================== 本地文件兜底层 ====================
def _load_local_store():
    """第 3 层降级不再放内存——落盘，否则进程一重启相似客户检索就是空的"""
    global _local_store
    try:
        with open(_FALLBACK_FILE, encoding="utf-8") as f:
            _local_store = json.load(f)
    except Exception:
        _local_store = {}


def _save_local_store():
    try:
        os.makedirs(os.path.dirname(_FALLBACK_FILE), exist_ok=True)
        with open(_FALLBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(_local_store, f, ensure_ascii=False)
    except Exception as e:
        print(f"[向量库] 兜底数据落盘失败: {e}")


# ==================== 连接（三级降级） ====================
def _get_qdrant():
    global _qdrant, _available, _backend, _opened_by
    if _available is None:
        try:
            from qdrant_client import QdrantClient as QC
        except Exception as e:
            _qdrant, _available, _backend = None, False, "memory"
            _opened_by = f"客户端库不可用: {str(e)[:60]}"
            _load_local_store()
            return None

        # ---- 第 1 层：本地嵌入式（无需服务端，向量持久化到磁盘）----
        # makedirs 必须包在 try 里：磁盘不存在/无权限时也要能降级，不能让异常冒出去
        # uvicorn reload 时新旧进程可能瞬间撞文件锁，重试几次再判定失败
        _embedded_error = "未尝试"
        for attempt in range(3):
            try:
                os.makedirs(QDRANT_PATH, exist_ok=True)
                _qdrant = QC(path=QDRANT_PATH)
                _qdrant.get_collections()
                _available, _backend = True, "embedded"
                _opened_by = f"本地嵌入式 {QDRANT_PATH}"
                print(f"[向量库] 本地嵌入式模式：{QDRANT_PATH}")
                return _qdrant
            except Exception as e:
                if attempt < 2:
                    time.sleep(0.5)
                    continue
                _embedded_error = str(e)[:80]
                print(f"[向量库] 嵌入式不可用：{str(e)[:100]}")

        # ---- 第 2 层：远程 Qdrant 服务端 ----
        try:
            _qdrant = QC(host=QDRANT_HOST, port=QDRANT_PORT, timeout=3)
            _qdrant.get_collections()
            _available, _backend = True, "remote"
            _opened_by = f"远程服务端 {QDRANT_HOST}:{QDRANT_PORT}"
            print(f"[向量库] 远程服务端模式：{QDRANT_HOST}:{QDRANT_PORT}")
            return _qdrant
        except Exception as e:
            _opened_by = f"嵌入式: {_embedded_error}；远程: {str(e)[:60]}"
            print(f"[向量库] 远程服务端不可用：{str(e)[:100]}")

        # ---- 第 3 层：本地文件兜底 ----
        _qdrant, _available, _backend = None, False, "memory"
        _load_local_store()
        print(f"[向量库] 降级为本地文件模式（已有 {len(_local_store)} 条），存储于 {_FALLBACK_FILE}")

    return _qdrant if _available else None


def vector_status() -> Dict:
    """给状态接口用：当前实际生效的是哪一层、有多少条画像"""
    client = _get_qdrant()
    label = {"embedded": "本地嵌入式 Qdrant", "remote": "Qdrant 服务端", "memory": "本地文件降级"}
    count = len(_local_store)
    if client:
        try:
            count = client.count("customer_profiles").count
        except Exception:
            pass
    return {
        "backend": _backend,
        "label": label.get(_backend, "未初始化"),
        "available": bool(_available),
        "reason": _opened_by,
        "count": count,
        "fallback_count": len(_local_store),
    }


# ==================== 简易向量化（字符级 bigram 哈希） ====================
def _hash_vector(text: str, dim: int = 128) -> List[float]:
    """轻量向量化：字符bigram哈希 → 128维（不依赖sklearn，方便部署）

    注意：必须用 crc32 这类稳定哈希，不能用内建 hash()——后者带 PYTHONHASHSEED
    随机盐，进程重启后同一段文本会落到不同维度，已写入 Qdrant 的向量将全部失效。
    """
    vec = np.zeros(dim)
    for i in range(len(text) - 1):
        h = zlib.crc32(text[i:i+2].encode("utf-8")) % dim
        vec[h] += 1
    norm = np.linalg.norm(vec)
    return (vec / norm).tolist() if norm > 0 else vec.tolist()


def _strip_internal(payload: Dict) -> Dict:
    return {k: v for k, v in payload.items() if k != "profile_text"}


# ==================== 客户画像存储 ====================
def upsert_customer_profile(customer_id: str, profile_text: str, metadata: Dict):
    vec = _hash_vector(profile_text)
    payload = {**metadata, "customer_id": customer_id, "profile_text": profile_text}

    client = _get_qdrant()
    if client:
        try:
            from qdrant_client.models import PointStruct
            client.upsert(collection_name="customer_profiles",
                          points=[PointStruct(id=_point_id(customer_id), vector=vec,
                                              payload=payload)])
            return
        except Exception as e:
            print(f"[向量库] 写入失败，回落本地文件：{str(e)[:80]}")

    _local_store[customer_id] = {"vector": vec, "payload": payload}
    _save_local_store()


def search_similar_customers(query: str, limit: int = 5) -> List[Dict]:
    vec = _hash_vector(query)

    client = _get_qdrant()
    if client:
        try:
            results = client.query_points(collection_name="customer_profiles",
                                          query=vec, limit=limit).points
            return [{"id": r.payload.get("customer_id", str(r.id)),
                     "score": round(r.score, 4), **_strip_internal(r.payload)}
                    for r in results]
        except Exception as e:
            print(f"[向量库] 检索失败，回落本地文件：{str(e)[:80]}")

    # 本地文件检索：数据量小，暴力算余弦就够
    results = []
    for cid, entry in _local_store.items():
        dot = float(np.dot(vec, entry["vector"]))
        n1, n2 = float(np.linalg.norm(vec)), float(np.linalg.norm(entry["vector"]))
        score = float(dot / (n1 * n2)) if n1 * n2 > 0 else 0.0
        results.append({"id": cid, "score": round(score, 4),
                        **_strip_internal(entry["payload"])})
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


# ==================== 内容模板存储 ====================
def search_content_templates(topic: str, limit: int = 3) -> List[Dict]:
    """根据话题检索营销文案模板（content_library 集合尚无数据，先复用同一套检索）"""
    return search_similar_customers(topic, limit)


def init_qdrant():
    client = _get_qdrant()
    if client is None:
        print("[向量库] 当前使用本地文件降级模式，检索功能正常")
        return

    from qdrant_client.models import Distance, VectorParams
    for name in ["customer_profiles", "content_library"]:
        try:
            names = [c.name for c in client.get_collections().collections]
            if name not in names:
                client.create_collection(collection_name=name,
                                         vectors_config=VectorParams(size=128, distance=Distance.COSINE))
                print(f"[向量库] 集合 '{name}' 已创建")
        except Exception as e:
            print(f"[向量库] 创建集合失败: {e}")
    print(f"[向量库] 初始化完成（{_backend}）")
