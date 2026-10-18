"""Provider 工厂（P4.5：字符串/字典 spec → LlmProvider 实例）。

spec 语法：
  "mock"                            → MockLlmProvider
  "deepseek:deepseek-chat"          → DeepSeek（= OpenAIChatProvider 实例）
  "openai:gpt-4o"                   → OpenAI 兼容（OpenAI 官方/任意 base_url 由字典指定）
  "responses:gpt-4o-mini"           → OpenAI Responses API
  "anthropic:claude-sonnet-4-5"     → Anthropic Messages API
  {"type": "openai", "model": ..., "base_url": ..., "api_key": ...}  → 完整配置
  {"type": "openai", ..., "api_key_env": "GLM_API_KEY"}  → key 从环境读取（多通道不串扰、
    配置面不出现明文 key——P15 多 API 场景；spec() 回构亦不含 key）

R3-1 凭据接入：无显式 key 时按「显式 ref（api_key_env / credential_ref）> 派生
  <TYPE>_API_KEY」解析，每级内部「环境变量（优先）> 凭据存储（write-only）」。
  credential_ref="" 显式声明保留供应商原生认证链（不查存储）。

R5-1 供应商引用：spec 可为 "<provider_id>/<model_id>" 或
  {"provider": "<id>", "model": ...}——解析到 providers 条目（type/base_url/
  credential_ref 等由供应商提供，spec 自字段优先覆盖）；未命中回退旧解析。
"""
from wuxing.llm.mock import MockLlmProvider


def resolve_api_key_for(spec, providers: dict | None,
                        allow_stored_credentials: bool = True):
    """公开：spec（含 provider 引用展开）→ api_key（env > 凭据存储）；无则 None。

    用途：形状化等旁路调用在构造真实客户端前预检凭据（无凭据→降级，不阻断）。
    allow_stored_credentials=False（G4 隔离装配）：仅环境变量——不读凭据存储文件。
    """
    resolved = resolve_spec(spec, providers)
    if isinstance(resolved, dict):
        return _resolve_api_key(resolved,
                                allow_stored=allow_stored_credentials)
    if isinstance(resolved, str):
        text = resolved.strip()
        if text in ("", "mock") or ":" not in text:
            return None
        from wuxing import credentials
        ref = credentials.derive_ref(text.split(":", 1)[0])
        return (credentials.resolve(ref, allow_store=allow_stored_credentials)
                if ref else None)
    return None


def _derive_ref(spec: dict) -> str | None:
    """类型 → 默认凭据 ref（deepseek → DEEPSEEK_API_KEY；单一事实来源在 credentials）。"""
    from wuxing import credentials
    return credentials.derive_ref(str(spec.get("type") or ""))


def _resolve_api_key(spec: dict, allow_stored: bool = True):
    """api_key 解析：显式 api_key > 显式 ref > 派生 ref；每级 env（优先）> 存储。

    allow_stored=False（G4 隔离装配）：env-only——不读凭据存储文件。
    """
    api_key = spec.get("api_key")
    if api_key is not None:
        return api_key
    if "credential_ref" in spec and not spec.get("credential_ref"):
        return None                       # 空 = 原生认证链（不查存储）
    ref = spec.get("api_key_env") or spec.get("credential_ref") or _derive_ref(spec)
    if not ref:
        return None
    from wuxing import credentials  # 惰性导入：仅实际解析时加载
    return credentials.resolve(str(ref), allow_store=allow_stored)


def resolve_spec(spec, providers: dict | None):
    """provider/model 引用展开（R5-1/E1）——未命中回退旧解析（零迁移）。

    - 字典 {"provider": id, ...}：未注册 → ValueError（拼写错早报）
    - 字符串 "<id>/<model>"：前缀命中注册表才展开（model 内可含 "/"）
    - 其余（mock / type:model / 普通字典）原样返回
    展开结果剔除管理字段（display_name/models）——它们是注册表元信息。
    """
    providers = providers or {}
    if isinstance(spec, dict):
        pid = spec.get("provider")
        if pid is None:
            return spec
        entry = providers.get(str(pid))
        if not isinstance(entry, dict):
            # 配置值错误（供应商 id 未注册）而非类型错误——TRY004 不适用
            raise ValueError(  # noqa: TRY004
                f"spec.provider 未在 providers 注册：{pid!r}（可用：{sorted(providers)}）")
        out = {k: v for k, v in entry.items() if k not in ("display_name", "models")}
        out.update({k: v for k, v in spec.items() if k != "provider"})
        return out
    if isinstance(spec, str) and "/" in spec:
        pid, model = spec.split("/", 1)
        entry = providers.get(pid)
        if isinstance(entry, dict) and model:
            out = {k: v for k, v in entry.items() if k not in ("display_name", "models")}
            out["model"] = model
            return out
    return spec


def _heal_credentials_ref_via_registry(spec: dict, providers: dict | None) -> dict:
    """2026-10-01 修复：dict spec 缺凭据信息时按 (type, base_url) 从注册表回填。

    现场：智脑记忆存的 spec（spec() 回构产物）丢失 credential_ref → 回构时
    derive_ref('responses')=RESPONSES_API_KEY 找不到 key → RuntimeError。
    仅当 spec 未声明 api_key/credential_ref/api_key_env 时回填（不覆盖显式值）。
    """
    if not providers:
        return spec
    if any(k in spec for k in ("api_key", "credential_ref", "api_key_env")):
        return spec
    stype = str(spec.get("type") or "")
    base = str(spec.get("base_url") or "").rstrip("/")
    if not stype:
        return spec
    for entry in providers.values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("type") or "") != stype:
            continue
        if str(entry.get("base_url") or "").rstrip("/") != base:
            continue
        ref = entry.get("credential_ref") or entry.get("api_key_env")
        if ref:
            return {**spec, "credential_ref": str(ref)}
    return spec


def create_provider(spec, max_retries: int | None = None, timeout: float | None = None,
                   providers: dict | None = None,
                   allow_stored_credentials: bool = True):
    """spec → LlmProvider。allow_stored_credentials=False：凭据 env-only（G4 隔离装配）。"""
    spec = resolve_spec(spec, providers)
    if isinstance(spec, str):
        if spec == "mock":
            return MockLlmProvider()
        if ":" not in spec:
            raise ValueError(
                f"未知 provider spec: {spec}（格式 type:model，如 deepseek:deepseek-chat）")
        ptype, model = spec.split(":", 1)
        return create_provider({"type": ptype, "model": model},
                               max_retries=max_retries, timeout=timeout,
                               allow_stored_credentials=allow_stored_credentials)
    if isinstance(spec, dict):
        spec = _heal_credentials_ref_via_registry(spec, providers)
        ptype = spec.get("type")
        model = spec.get("model", "")
        api_key = _resolve_api_key(spec, allow_stored=allow_stored_credentials)
        spec_ref = spec.get("credential_ref") or spec.get("api_key_env") or None
        headers = spec.get("headers") or {}
        temperature = spec.get("temperature", 0.0)
        mr = max_retries if max_retries is not None else 4      # P12 定案默认
        spec_to = spec.get("timeout")                           # S1：条目级覆盖
        if spec_to is not None:
            try:
                spec_to = float(spec_to)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"provider timeout 非法：{spec_to!r}") from exc
            if spec_to <= 0:
                raise ValueError(f"provider timeout 必须为正数：{spec_to!r}")
        to = spec_to if spec_to is not None else (
            timeout if timeout is not None else 60.0)
        provider = None
        if ptype == "deepseek":
            from wuxing.llm.deepseek import DeepSeekLlmProvider
            provider = DeepSeekLlmProvider(model=model or "deepseek-chat",
                                           base_url=spec.get("base_url", "https://api.deepseek.com"),
                                           api_key=api_key, max_retries=mr, headers=headers,
                                           temperature=temperature, timeout=to)
        elif ptype == "openai":
            from wuxing.llm.openai import OpenAIChatProvider
            provider = OpenAIChatProvider(model=model or "gpt-4o-mini",
                                          base_url=spec.get("base_url", "https://api.openai.com/v1"),
                                          api_key=api_key, max_retries=mr, headers=headers,
                                          temperature=temperature, timeout=to)
        elif ptype == "responses":
            from wuxing.llm.openai import OpenAIResponsesProvider
            provider = OpenAIResponsesProvider(model=model or "gpt-4o-mini",
                                               base_url=spec.get("base_url", "https://api.openai.com/v1"),
                                               api_key=api_key, max_retries=mr, timeout=to)
        elif ptype == "anthropic":
            from wuxing.llm.anthropic import AnthropicProvider
            provider = AnthropicProvider(model=model or "claude-sonnet-4-5",
                                         base_url=spec.get("base_url", "https://api.anthropic.com/v1"),
                                         api_key=api_key, max_retries=mr, headers=headers,
                                         timeout=to)
        if provider is not None:
            # 2026-10-01：留存凭据引用（spec() 回构不丢 key 解析路径）
            provider._credential_ref = spec_ref
            return provider
        raise ValueError(f"未知 provider type: {ptype}")
    raise ValueError(f"未知 provider spec: {spec}")
