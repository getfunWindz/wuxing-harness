"""供应商模型发现（R3-1 · DSH `llm/discoverModels` 同构）——一次性凭据探询，不落盘。

- OpenAI 兼容（openai/deepseek/responses）：GET {base}/models + Authorization: Bearer
- Anthropic Messages：GET {base}/models + x-api-key + anthropic-version
- 解析宽容（DSH）：`data[]` 列表 / `models[]` 列表 / `models{}` 富信息对象；id 去重且保序
- 安全：错误信息不回显 key；请求体不入日志（调用方纪律——api.py 只透传不回显）

壳侧模块（native_dialog 同款）：纯探询、不触碰引擎内部——壳边界纪律不变。
"""
import json
import urllib.error
import urllib.request

ANTHROPIC_VERSION = "2023-06-01"
_PROBE_TYPES = ("openai", "deepseek", "responses", "anthropic")


class ProbeError(RuntimeError):
    """发现失败（参数/连接/上游/解析）——消息不含凭据材料。"""


def _items_of(data) -> list:
    if not isinstance(data, dict):
        return []
    items = data.get("data")
    if isinstance(items, list):
        return items
    models = data.get("models")
    if isinstance(models, list):
        return models
    if isinstance(models, dict):
        return [dict(v, id=k) if isinstance(v, dict) else {"id": k}
                for k, v in models.items()]
    return []


def _normalize(items: list) -> list[dict]:
    out, seen = [], set()
    for it in items:
        extra = it if isinstance(it, dict) else {}
        mid = it if isinstance(it, str) else (extra.get("id") or extra.get("name"))
        if not isinstance(mid, str) or not mid or mid in seen:
            continue
        seen.add(mid)
        entry = {"id": mid}
        dn = extra.get("display_name")
        if isinstance(dn, str) and dn and dn != mid:
            entry["display_name"] = dn
        for cap in ("context_window", "max_tokens"):
            v = extra.get(cap)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                entry[cap] = v
        out.append(entry)
    return out


def discover_models(base_url: str, ptype: str, api_key: str | None = None,
                    timeout: float = 30.0) -> list[dict]:
    """向端点询问可用模型（一次性凭据 api_key 可空——供应商原生认证链）。"""
    if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
        raise ProbeError("base_url 需为 http(s) URL")
    if ptype not in _PROBE_TYPES:
        raise ProbeError(f"类型 {ptype!r} 不支持模型发现（请手工填写模型）")
    headers = {}
    if ptype == "anthropic":
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if api_key:
            headers["x-api-key"] = api_key
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(base_url.rstrip("/") + "/models", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        data = json.loads(raw.decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise ProbeError(f"端点返回 HTTP {exc.code}（检查端点与凭据）") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProbeError(f"无法连接端点：{type(exc).__name__}") from exc
    except ValueError as exc:
        raise ProbeError("端点响应不是 JSON——该类型可能不支持 /models 询问") from exc
    return _normalize(_items_of(data))
