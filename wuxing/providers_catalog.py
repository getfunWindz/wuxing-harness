"""供应商目录（R5-1）——官方约定单一事实来源（名称/base_url/协议/环境变量/文档）。

用途：
- 壳（设置页）：按 base_url 自动匹配供应商名称与协议；条目也可直接作为预填卡。
- 配置模板：`scripts/gen_config_example.py` 据此生成 config.example.jsonc 的 providers 段。

核实口径（2026-09-16）：pi 内置供应商目录（生产级）交叉 + DSH 适配器 + 官方端点
存活校验（无 key 请求 `{base_url}/models` → 401/403 鉴权正常，或 200 公开列表）。
协议口径：openai（OpenAI 兼容，含各家 compatible-mode）/ anthropic / responses。
"""
import re
from urllib.parse import urlparse

# type 取值对齐 wuxing.config_schema.VALID_PROVIDER_TYPES（mock 除外）
CATALOG = [
    # ---- 国内主流 ----
    {"id": "deepseek", "name": "DeepSeek 官方", "base_url": "https://api.deepseek.com",
     "type": "deepseek", "env": "DEEPSEEK_API_KEY", "docs": "https://api-docs.deepseek.com/",
     "hosts": ["api.deepseek.com"]},
    {"id": "moonshot", "name": "月之暗面 Kimi", "base_url": "https://api.moonshot.cn/v1",
     "type": "openai", "env": "MOONSHOT_API_KEY", "docs": "https://platform.moonshot.cn/docs/",
     "hosts": ["api.moonshot.cn", "api.moonshot.ai"]},
    {"id": "zhipu", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "type": "openai", "env": "GLM_API_KEY", "docs": "https://docs.bigmodel.cn/",
     "hosts": ["open.bigmodel.cn", "api.z.ai"]},
    {"id": "dashscope", "name": "阿里云百炼（通义）",
     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "type": "openai", "env": "DASHSCOPE_API_KEY",
     "docs": "https://help.aliyun.com/zh/model-studio/",
     "hosts": ["dashscope.aliyuncs.com"]},
    {"id": "siliconflow", "name": "硅基流动", "base_url": "https://api.siliconflow.cn/v1",
     "type": "openai", "env": "SILICONFLOW_API_KEY", "docs": "https://docs.siliconflow.cn/",
     "hosts": ["api.siliconflow.cn"]},
    {"id": "stepfun", "name": "阶跃星辰", "base_url": "https://api.stepfun.com/v1",
     "type": "openai", "env": "STEPFUN_API_KEY", "docs": "https://platform.stepfun.com/docs/",
     "hosts": ["api.stepfun.com"]},
    {"id": "ark", "name": "火山方舟（豆包）", "base_url": "https://ark.cn-beijing.volces.com/api/v3",
     "type": "openai", "env": "ARK_API_KEY",
     "docs": "https://www.volcengine.com/docs/82379", "hosts": ["ark.cn-beijing.volces.com"]},
    {"id": "qianfan", "name": "百度千帆", "base_url": "https://qianfan.baidubce.com/v2",
     "type": "openai", "env": "QIANFAN_API_KEY",
     "docs": "https://cloud.baidu.com/doc/WENXINWORKSHOP/index.html",
     "hosts": ["qianfan.baidubce.com"]},
    {"id": "hunyuan", "name": "腾讯混元", "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
     "type": "openai", "env": "HUNYUAN_API_KEY",
     "docs": "https://cloud.tencent.com/document/product/1729",
     "hosts": ["api.hunyuan.cloud.tencent.com"]},
    {"id": "minimax", "name": "MiniMax", "base_url": "https://api.minimaxi.com/v1",
     "type": "openai", "env": "MINIMAX_API_KEY", "docs": "https://platform.minimaxi.com/document/",
     "hosts": ["api.minimaxi.com", "api.minimax.io", "api.minimax.chat"]},
    {"id": "spark", "name": "讯飞星火", "base_url": "https://spark-api-open.xf-yun.com/v1",
     "type": "openai", "env": "SPARK_API_KEY", "docs": "https://www.xfyun.cn/doc/spark/",
     "hosts": ["spark-api-open.xf-yun.com"]},
    {"id": "modelscope", "name": "魔搭 ModelScope", "base_url": "https://api-inference.modelscope.cn/v1",
     "type": "openai", "env": "MODELSCOPE_API_KEY", "docs": "https://modelscope.cn/docs",
     "hosts": ["api-inference.modelscope.cn"]},
    {"id": "xiaomi", "name": "小米 MiMo", "base_url": "https://api.xiaomimimo.com/v1",
     "type": "openai", "env": "MIMO_API_KEY", "docs": "https://platform.xiaomimimo.com/",
     "hosts": ["api.xiaomimimo.com"]},
    # ---- 国际主流 ----
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1",
     "type": "openai", "env": "OPENAI_API_KEY", "docs": "https://platform.openai.com/docs/",
     "hosts": ["api.openai.com"]},
    {"id": "anthropic", "name": "Anthropic", "base_url": "https://api.anthropic.com",
     "type": "anthropic", "env": "ANTHROPIC_API_KEY", "docs": "https://docs.anthropic.com/",
     "hosts": ["api.anthropic.com"]},
    {"id": "google", "name": "Google Gemini",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "type": "openai", "env": "GEMINI_API_KEY", "docs": "https://ai.google.dev/gemini-api/docs",
     "hosts": ["generativelanguage.googleapis.com"]},
    {"id": "xai", "name": "xAI Grok", "base_url": "https://api.x.ai/v1",
     "type": "openai", "env": "XAI_API_KEY", "docs": "https://docs.x.ai/",
     "hosts": ["api.x.ai"]},
    {"id": "mistral", "name": "Mistral", "base_url": "https://api.mistral.ai/v1",
     "type": "openai", "env": "MISTRAL_API_KEY", "docs": "https://docs.mistral.ai/",
     "hosts": ["api.mistral.ai"]},
    {"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1",
     "type": "openai", "env": "GROQ_API_KEY", "docs": "https://console.groq.com/docs",
     "hosts": ["api.groq.com"]},
    {"id": "cerebras", "name": "Cerebras", "base_url": "https://api.cerebras.ai/v1",
     "type": "openai", "env": "CEREBRAS_API_KEY", "docs": "https://inference-docs.cerebras.ai/",
     "hosts": ["api.cerebras.ai"]},
    {"id": "together", "name": "Together AI", "base_url": "https://api.together.xyz/v1",
     "type": "openai", "env": "TOGETHER_API_KEY", "docs": "https://docs.together.ai/",
     "hosts": ["api.together.xyz", "api.together.ai"]},
    {"id": "fireworks", "name": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1",
     "type": "openai", "env": "FIREWORKS_API_KEY", "docs": "https://docs.fireworks.ai/",
     "hosts": ["api.fireworks.ai"]},
    {"id": "nvidia", "name": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1",
     "type": "openai", "env": "NVIDIA_API_KEY", "docs": "https://docs.nvidia.com/nim/",
     "hosts": ["integrate.api.nvidia.com"]},
    {"id": "baseten", "name": "Baseten", "base_url": "https://inference.baseten.co/v1",
     "type": "openai", "env": "BASETEN_API_KEY", "docs": "https://docs.baseten.co/",
     "hosts": ["inference.baseten.co"]},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
     "type": "openai", "env": "OPENROUTER_API_KEY", "docs": "https://openrouter.ai/docs",
     "hosts": ["openrouter.ai"]},
    # ---- 本地 / 自建 ----
    {"id": "ollama", "name": "Ollama（本地）", "base_url": "http://localhost:11434/v1",
     "type": "openai", "env": "OLLAMA_API_KEY", "docs": "https://docs.ollama.com/",
     "hosts": ["localhost:11434", "127.0.0.1:11434"]},
    {"id": "lmstudio", "name": "LM Studio（本地）", "base_url": "http://localhost:1234/v1",
     "type": "openai", "env": "LMSTUDIO_API_KEY", "docs": "https://lmstudio.ai/docs",
     "hosts": ["localhost:1234", "127.0.0.1:1234"]},
    {"id": "vllm", "name": "vLLM（自建）", "base_url": "http://localhost:8000/v1",
     "type": "openai", "env": "VLLM_API_KEY", "docs": "https://docs.vllm.ai/",
     "hosts": ["localhost:8000", "127.0.0.1:8000"]},
]

_BY_ID = {e["id"]: e for e in CATALOG}


def catalog_entries() -> list[dict]:
    """目录快照（深拷贝的列表——调用方可安全遍历）。"""
    return [dict(e, hosts=list(e["hosts"])) for e in CATALOG]


def match_provider_by_url(url: str) -> dict | None:
    """按 base_url 主机名（含端口语义）匹配目录条目；未命中 → None。

    端口规则：目录 host 带端口（本地服务）时要求端口一致；不带端口则任意端口可。
    """
    if not isinstance(url, str) or not url.strip():
        return None
    raw = url.strip() if "://" in url else "https://" + url.strip()
    try:
        parsed = urlparse(raw)
    except ValueError:
        # URL 解析失败 → None（调用方按无效地址处理）
        return None
    host = (parsed.hostname or "").lower()
    if not host:
        return None
    port = parsed.port
    for entry in CATALOG:
        for item in entry["hosts"]:
            h, _, p = item.partition(":")
            if host == h.lower() and (not p or port == int(p)):
                return dict(entry, hosts=list(entry["hosts"]))
    return None


def slug_provider_id(text: str) -> str:
    """供应商名称/主机名 → 配置键（slug，≤32 位）。空输入 → 'provider'。"""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    return slug[:32] or "provider"


def find_entry(provider_id: str) -> dict | None:
    entry = _BY_ID.get(str(provider_id))
    return dict(entry, hosts=list(entry["hosts"])) if entry else None
