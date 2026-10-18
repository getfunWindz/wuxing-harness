"""配置 schema（P11：字段声明单源——DSH schemastery 的轻量 Python 版）。

FIELD_SPECS：引擎配置字段声明（名称 → {type, default, enum?, desc}）。
validate_config(data)：load 时校验（早报——构造前失败）。
gen_schema()：生成 JSON Schema（$schema IDE 体验）。
"""
import re
from dataclasses import dataclass
from typing import Any

from wuxing.credentials import REF_RE as _CREDENTIAL_REF_RE
from wuxing.sandbox import validate_container_template

# LLM provider 合法类型（factory 支持）
VALID_PROVIDER_TYPES = ("deepseek", "openai", "anthropic", "responses", "mock")

# providers 注册表（R3-1）：供应商 id 唯一；type 不含 mock（无供应商语义）
PROVIDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
PROVIDER_TYPES = tuple(t for t in VALID_PROVIDER_TYPES if t != "mock")

# MCP 服务器名契约（R3-2/M1：工具命名 mcp__<server>__<tool>）
_MCP_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

@dataclass
class FieldSpec:
    name: str
    type: str                      # "int"|"float"|"bool"|"str"|"tuple"|"dict"
    default: Any = None
    enum: tuple | None = None      # 合法值集（如 provider 类型）
    desc: str = ""
    scope: str = "next"            # 生效范围：now（即时）/ next（下个任务）/ restart（需重启）
    item_type: str = ""            # list 项校验：""（仅类型）/ "mcp"（MCP 条目契约）/ "str"（非空字符串）

FIELD_SPECS = [
    FieldSpec("max_loop_rounds", "int", 6, desc="执行单元轮数基线（到达→机械评分+自评，不失败）"),
    FieldSpec("max_loop_rounds_hard", "int", 12, desc="轮数安全上限（唯一硬停——真测裁决 W2）"),
    FieldSpec("max_unit_budget_hard", "int", 12, desc="调用安全上限（唯一硬停——同上）"),
    FieldSpec("fragment_max_attempts", "int", 2, desc="同碎片最大尝试次数（含首次；达上限后只调度未尝试碎片并留痕）"),
    FieldSpec("max_unit_budget", "int", 5, desc="执行单元 LLM 调用预算（L4 真跑：3 轮不足——探索+产出+声明需≥4）"),
    FieldSpec("provider_retry_max", "int", 1, desc="provider 类失败的自动重试次数（0=关闭；S1-A）"),
    FieldSpec("provider_retry_backoff_s", "float", 15.0, desc="自动重试前固定等待秒数（S1-A）"),
    FieldSpec("default_artifact_dir", "str", "artifacts"),
    FieldSpec("default_domains", "tuple", ("plan", "execute", "verify", "user")),
    FieldSpec("confirm_threshold", "float", 0.0, desc="0=全自动 1=全确认"),
    FieldSpec("confirm_threshold_difficulty", "float", 0.5),
    FieldSpec("max_parallel_units", "int", 8, desc="碎片并行度（目标 8/硬上限 10——用户裁决）"),
    FieldSpec("max_parallel_tools", "int", 8,
              desc="单碎片工具批量并发上限（目标 8/硬上限 10——工具层防失控）"),
    FieldSpec("tool_concurrency_soft", "int", 0,
              desc="分级放行软阈值（0=自动 64=8×8 目标——缓速起点）"),
    FieldSpec("tool_concurrency_hard", "int", 0,
              desc="分级放行硬阈值（0=自动 100=10×10 硬限——阻止起点）"),
    FieldSpec("tool_throttle_delay_ms", "int", 25,
              desc="缓速档每次获取前的节流延迟（毫秒）"),
    FieldSpec("tool_search_enabled", "bool", True,
              desc="ToolSearch 延迟加载（E3-3）：MCP 工具超阈值时不进提示词工具表——模型经 tool_search 检索调用"),
    FieldSpec("tool_search_threshold", "int", 20,
              desc="延迟阈值：MCP 工具数超过该值才启用延迟（默认 20）"),
    FieldSpec("mcp_always_load", "tuple", (),
              desc="永不延迟的 MCP server 名清单（豁免——始终直接披露）"),
    FieldSpec("cleanup_enabled", "bool", True,
              desc="运行时产物清理（E3-5/CU10）：sessions/reports 双上限、最旧先删；只清 .wuxing 内部，绝不触碰用户交付物"),
    FieldSpec("cleanup_interval_s", "int", 3600,
              desc="清理节流间隔（秒）：任务收口后至多每该间隔执行一次"),
    FieldSpec("cleanup_sessions_max", "int", 300,
              desc="会话档案（.wuxing/sessions）文件数上限（超限最旧先删）"),
    FieldSpec("cleanup_reports_max", "int", 300,
              desc="报告归档（.wuxing/reports）文件数上限（超限最旧先删）"),
    FieldSpec("web_fetch_enabled", "bool", False,
              desc="WebFetch 工具（E2-5）：默认关；启用即引擎级网络授权（与容器 network 相互独立——网络默断场景建议保持关闭）"),
    FieldSpec("web_fetch_domains_allow", "list", [], item_type="str",
              desc="web_fetch 域名白名单（非空=仅允许这些域名/子域；空=不额外限制）"),
    FieldSpec("web_fetch_domains_deny", "list", [], item_type="str",
              desc="web_fetch 域名黑名单（deny 优先；私网/回环/链路本地始终硬拒）"),
    FieldSpec("browser_enabled", "bool", False,
              desc="内置浏览器（O2-2）：默认关；启用即授权浏览器工具面（回环走动态授权：占用探测→确认门→条目；非安全边界）"),
    FieldSpec("browser_domains_allow", "list", [], item_type="str",
              desc="内置浏览器公网域名白名单（非空=仅允许这些域名/子域；回环不适用——动态授权）"),
    FieldSpec("browser_domains_deny", "list", [], item_type="str",
              desc="内置浏览器域名黑名单（deny 优先；私网/链路本地始终硬拒）"),
    FieldSpec("shell_allow_hosts", "list", [], item_type="str",
              desc="壳服务远程 Host 白名单（额外主机名/IP——环回默认始终允许；serve 启动时读取）"),
    FieldSpec("shell_allow_origins", "list", [], item_type="str",
              desc="壳服务远程 Origin 白名单（完整 origin，如 https://wuxing.example.com）"),
    FieldSpec("browser_evaluate_enabled", "bool", False,
              desc="browser_evaluate 显式档（O2-2 P3）：默认关；需与 browser_enabled 双开才注册（脚本执行面——SEC 复核见设计 §11.1）"),
    FieldSpec("browser_identity_mode", "str", "memory",
              desc="浏览器身份档（O2-2 §11.5-①）：memory=按工作区内存态（退出即清——默认）/ persist=按工作区持久（跨重启；设置「数据与维护→浏览器身份」）/ storage-state=登录态档（§11.5-③ Playwright 格式文件只读注入）"),
    FieldSpec("browser_lan_allow", "list", [], item_type="str",
              desc="内置浏览器 LAN 白名单（CIDR；仅 RFC1918/ULA 子网可入；默认空=私网硬拒；首访逐地址确认——§11.5-③）"),
    FieldSpec("browser_storage_state_path", "str", "",
              desc="storage-state 登录态档文件路径（Playwright 格式 JSON；只读；值不入日志/模型；≤2MB——§11.5-③）"),
    FieldSpec("code_mode_enabled", "bool", False,
              desc="A4 Code Mode（脚本执行通道）开关（默认关；脚本内调用受白名单+守卫链约束）"),
    FieldSpec("code_mode_timeout_s", "float", 120.0,
              desc="run_script 子进程超时（秒；超时杀进程树）"),
    FieldSpec("code_mode_max_calls", "int", 64,
              desc="单次脚本内工具调用上限（超限 loud 拒绝）"),
    FieldSpec("code_mode_output_max_chars", "int", 20000,
              desc="脚本 stdout 回传上限（超限截断+全文落盘 .wuxing/code/）"),
    FieldSpec("code_mode_tools", "tuple",
              ("read_file", "grep", "glob", "read_dependency",
               "write_file", "write_artifact", "bash"),
              desc="脚本内可调用工具子集（再与单元白名单取交集；run_script/ask_user/delegate 恒禁）"),
    FieldSpec("use_real_shape", "bool", True,
              desc="真实形状化（默认开）：用【默认模型】拆分任务 DAG（与域级路由无关）；无凭据自动降级 mock 并在报告提示，可在设置关闭"),
    FieldSpec("llm", "str", "mock", enum=VALID_PROVIDER_TYPES,
             desc="模型规格：供应商:模型名（示例 deepseek:deepseek-v4-flash）"),
    FieldSpec("providers", "dict", {},
              desc="供应商注册表：id → {type, base_url?, credential_ref?, "
                   "display_name?, models?[{{id, display_name?, context_window?, max_tokens?}}]}"),
    FieldSpec("router", "dict", {}, desc="域级模型路由（域 → 模型规格；未指定的域用 _default）"),
    FieldSpec("default_tools", "tuple", ("write_artifact", "read_dependency",
                                          "read_file", "write_file", "bash", "grep", "glob",
                                          "session_search", "load_skill"),
              desc="全局工具白名单（引擎级工具不受过滤）"),
    FieldSpec("llm_max_retries", "int", 4, desc="请求失败时的重试上限（供应商级）"),
    FieldSpec("llm_timeout", "float", 180.0, desc="单次请求超时（秒）——思考型模型长调用需适当放宽"),
    FieldSpec("brain_enabled", "bool", False, desc="智脑（默认关——验证收益后启用）"),
    FieldSpec("brain_max_cases", "int", 500),
    FieldSpec("cache_similar_threshold", "float", 0.75,
              desc="R3 语义缓存相似阈值（0=关闭；0.75 微漂移命中/真变体不误判）"),
    FieldSpec("fsc_enabled", "bool", True,
              desc="FSC 碎片会话延续（跨轮工作流键匹配复用——默认开，可自主关闭）"),
    FieldSpec("skill_evolution_enabled", "bool", True,
              desc="技能自进化（高效任务自评审→沉淀 SKILL.md——默认开）"),
    FieldSpec("progress_heartbeat_enabled", "bool", True,
              desc="进度心跳（模型自报进度→progress 事件——无固定定时器）"),
    FieldSpec("mode_default", "str", "minimal-standard",
              enum=("minimal-pure", "minimal-standard", "theroad"),
              desc="双模式默认（会话创建时固定；仅空白可切——缓存前缀纪律；旧值 wayfinder 兼容读）"),
    FieldSpec("mode_picker_enabled", "bool", True,
              desc="输入区模式选择器显隐（关闭后新会话一律用默认模式）"),
    FieldSpec("assembly_preset", "str", "standard",
              desc="装配预设名（E2-4 组合树；会话 sidecar 可覆盖；见 wuxing.presets）"),
    FieldSpec("minimal_pure_tools", "tuple",
              ("bash", "read_file", "write_file", "write_artifact", "read_dependency"),
              desc="极简·纯净核心工具集（与域白名单取交集）"),
    FieldSpec("minimal_pure_auto_confirm", "bool", True,
              desc="极简·纯净不打断（auto_confirm；danger_guard 拦截保留）"),
    FieldSpec("ui_theme", "str", "ink", enum=("ink", "plain"),
              desc="界面主题：ink=水墨（默认）/ plain=纯白；壳读取后切换素材与品牌墨迹"),
    FieldSpec("fsc_retention_rounds", "int", 4, desc="FSC 会话保留轮数（K=4）"),
    FieldSpec("fsc_max_session_chars", "int", 65536,
              desc="FSC 单会话字符上限（超限不再复用）"),
    FieldSpec("fsc_max_reuse", "int", 3, desc="FSC 单会话复用次数上限"),
    FieldSpec("fsc_total_char_budget", "int", 262144, desc="FSC 池总字符预算"),
    FieldSpec("fsc_fallback_digest", "bool", True,
              desc="低匹配回退：上一轮全部碎片上下文压缩 → 本轮前缀注入"),
    FieldSpec("fsc_digest_max_chars", "int", 7000,
              desc="跨轮碎片摘要字符上限（低匹配回退；2026-09-23 放宽 2000→7000）"),
    FieldSpec("conversation_max_chars", "int", 10000,
              desc="会话历史段字符上限（B 模式；2026-09-23 放宽 4000→10000）"),
    FieldSpec("task_reply_enabled", "bool", True,
              desc="pi 式总体回复（默认开）：终端任务后由模型生成一条面向用户的总体回复消息"),
    FieldSpec("task_reply_max_chars", "int", 800,
              desc="总体回复字符上限（超出截断）"),
    FieldSpec("context_budget_tokens", "int", 0,
              desc="上下文窗口预算（估算 token；0=关闭；会话级可覆盖）"),
    FieldSpec("auto_trim_enabled", "bool", True,
              desc="自动机械裁剪（默认开）：接近窗口（window − reserve）触发既有确定性裁剪链；关闭 = 现状"),
    FieldSpec("auto_trim_reserve_tokens", "int", 16384,
              desc="自动裁剪触发预留（token）：触发线含 window − reserve 头寸；滞回至 max(window−2×reserve, window/2)"),
    FieldSpec("auto_trim_trigger_ratio", "float", 0.8,
              desc="触发比例上限（DSH 对齐）：触发线 ≤ ratio×window；非法值（不在 (0,1]）→ 自动链禁用"),
    FieldSpec("auto_trim_output_reserve_tokens", "int", 8192,
              desc="输出预留 O（token）：触发线 = min(ratio×window, window−reserve−O) 的输出头寸防护"),
    FieldSpec("auto_compact_llm_enabled", "bool", False,
              desc="LLM 摘要压缩（默认关）：接近窗口时保留最近 keep_recent，旧轮生成持久化摘要（失败降级机械链）"),
    FieldSpec("auto_compact_keep_recent_tokens", "int", 20000,
              desc="LLM 摘要压缩保留最近 token（pi keepRecent 同值）"),
    FieldSpec("context_golden_pct", "float", 0.2,
              desc="黄金期档位阈值（窗口占比 ≤ 该值为黄金期；0<golden<managed≤1）"),
    FieldSpec("context_managed_pct", "float", 0.5,
              desc="严管档位阈值（窗口占比 > 该值为严管——建议开新会话；0<golden<managed≤1）"),
    FieldSpec("design_question_soft_cap", "int", 3,
              desc="循迹设计会话每轮问题软上限（提示词约束——引擎不硬限）"),
    FieldSpec("design_round_cap", "int", 6,
              desc="循迹设计会话总轮数软上限（提示词/壳级约束——引擎不硬限）"),
    FieldSpec("model_context_windows", "dict",
              {"deepseek-flash": 1000000, "deepseek-v4-pro": 1000000},
              desc="模型→上下文窗口表（API 不返回——实测；配置可覆盖）"),
    FieldSpec("default_context_window", "int", 200000, desc="未知模型窗口兜底"),
    FieldSpec("fsc_audit_ratio", "float", 0.6, desc="会话 60% 严格审查阈值（方案 A）"),
    FieldSpec("fsc_switch_ratio", "float", 0.8, desc="会话 80% 切换新会话阈值"),
    FieldSpec("confirm_auto", "bool", False,
              desc="人工介入：False=默认人工确认（interrupt on），True=全自动（CI/headless）"),
    FieldSpec("resources", "dict", {},
              desc="外部资源声明 {name: {type: file|dir|url, path, optional}}——配置生态面"),
    FieldSpec("context_max_chars", "int", 8192,
              desc="工具结果压缩阈值（字符——头尾保留+中间摘要；压缩点不破前缀）"),
    FieldSpec("context_tool_limits", "dict",
              {"read_file": 32768, "read_dependency": 32768, "bash": 16384},
              desc="按工具来源的压缩上限（字符）——未列出工具用 context_max_chars"),
    FieldSpec("sandbox_enabled", "bool", True,
              desc="原生沙箱（R3-2）：工作目录限定于工作区 + 敏感环境变量剥离；"
                   "网络允许；完整性 partial（原生强制能力有限）"),
    FieldSpec("sandbox_mode", "str", "native", enum=("native", "container"),
              desc="沙箱档位（BOX-2）：native=内置（默认）/ container=外置容器"
                   "（需命令模板；失败可见不回退）"),
    FieldSpec("sandbox_container_template", "str", "",
              desc="外置容器命令模板：须含 {workdir} 与 {cmd}/{cmd_b64}（推荐 {cmd_b64}）；"
                   "示例 docker run --rm -i -v {workdir}:/ws -w /ws <image> sh -c {cmd_b64}"),
    FieldSpec("bash_shell_path", "str", "",
              desc="bash 工具 shell 选择：空=自动（Windows git-bash / macOS zsh / Linux bash→sh）；"
                   "关键字 git-bash·wsl·powershell·pwsh·cmd·zsh·bash·sh；或绝对路径自定义"
                   "（kind 按文件名推断；解析失败 loud）"),
    FieldSpec("bash_timeout_s", "float", 120.0,
              desc="bash 工具默认超时（秒；调用方 timeout 参数覆盖，clamp 1..600）"),
    FieldSpec("permission_profile", "str", "workspace-write",
              enum=("read-only", "workspace-write", "full-access"),
              desc="权限剖面（SEC3）：read-only=只读工具集；workspace-write=写入限工作区（默认）；"
                   "full-access=放行工作区外写入（危险命令黑名单与内部数据面保护仍生效）"),
    FieldSpec("content_trust_sanitize", "bool", True,
              desc="不可信内容净化（SEC1）：中和伪边界/隐形字符/高置信注入短语；关闭=仅信封"),
    FieldSpec("mcp_servers", "list", [], item_type="mcp",
              desc="MCP 服务列表：名称 + 启动命令 + 参数 + 权限声明；未声明权限的工具默认拦截"),
    FieldSpec("mcp_project_enabled", "bool", False,
              desc="项目级 MCP 信任开关（仅用户级 ~/.wuxing/config.jsonc 或 env "
                   "WUXING_MCP_PROJECT_ENABLED 生效；工作区设置被忽略）——开启后才加载 "
                   "<ws>/.agents/mcp.json（P2 统一便携根）"),
    FieldSpec("extension_enabled", "bool", True,
              desc="E0-A 扩展机制（默认开）：加载 ~/.wuxing/extensions 与 <工作区>/.wuxing/extensions 的"
                   "自定义工具与事件钩子；扩展=进程内完全信任代码，置 false 整体关闭"),
    FieldSpec("extension_dirs", "list", [], item_type="str",
              desc="附加扩展目录（相对路径按工作区解析；工具经 domains 声明并入域白名单，"
                   "不受 default_tools 粗筛）"),
    FieldSpec("tool_retrieval_threshold", "int", 14,
              desc="工具检索阈值：工具数超过才启用 top-k（0=关闭——小工具集零折腾；"
                   "2026-10-03 Wave-1 工具面扩张后 10→14）"),
    FieldSpec("tool_retrieval_top_k", "int", 8, desc="工具检索 top-k 选择数"),
    FieldSpec("task_context_max_chars", "int", 400,
              desc="任务背景投影阈值（确定性截断——碎片聚焦；0=关闭投影）"),
]

_SPEC_MAP = {s.name: s for s in FIELD_SPECS}


def _check_providers(value, errors: list):
    """providers 注册表条目校验（R3-1）：id/type/base_url/credential_ref/models。

    条目内未知字段不报错——部署侧字段（如 headers）原样保留（DSH 字段保留语义）。
    """
    if not isinstance(value, dict):
        errors.append("providers: 期望 dict")
        return
    for pid, entry in value.items():
        prefix = f"providers.{pid}"
        if not isinstance(pid, str) or not PROVIDER_ID_RE.match(pid):
            errors.append(f"{prefix}: 非法供应商 id（需 [A-Za-z0-9_-]{{1,32}}）")
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: 期望对象（{{type, base_url?, ...}}）")
            continue
        ptype = entry.get("type")
        if ptype not in PROVIDER_TYPES:
            errors.append(f"{prefix}.type: 非法类型 {ptype!r}（允许 {PROVIDER_TYPES}）")
        base_url = entry.get("base_url")
        if base_url is not None and not (isinstance(base_url, str)
                                        and re.match(r"^https?://", base_url)):
            errors.append(f"{prefix}.base_url: 需 http(s) URL")
        ref = entry.get("credential_ref")
        if ref is not None and not (isinstance(ref, str)
                                    and (ref == "" or _CREDENTIAL_REF_RE.match(ref))):
            errors.append(f"{prefix}.credential_ref: 需环境变量名（或空串=原生认证链）")
        tmo = entry.get("timeout")
        if tmo is not None and (isinstance(tmo, bool)
                                or not isinstance(tmo, (int, float))
                                or float(tmo) <= 0):
            errors.append(f"{prefix}.timeout: 需正数（秒；可选覆盖全局 llm_timeout）")
        name = entry.get("display_name")
        if name is not None and not isinstance(name, str):
            errors.append(f"{prefix}.display_name: 期望字符串")
        models = entry.get("models")
        if models is None:
            continue
        if not isinstance(models, list):
            errors.append(f"{prefix}.models: 期望数组")
            continue
        for i, m in enumerate(models):
            if not isinstance(m, dict) or not isinstance(m.get("id"), str) or not m["id"]:
                errors.append(f"{prefix}.models[{i}].id: 必填非空字符串")
                continue
            if m.get("display_name") is not None and not isinstance(m.get("display_name"), str):
                errors.append(f"{prefix}.models[{i}].display_name: 期望字符串")
            for cap in ("context_window", "max_tokens"):
                v = m.get(cap)
                if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 0):
                    errors.append(f"{prefix}.models[{i}].{cap}: 需非负整数")


def _check_value(spec: FieldSpec, value, errors: list, prefix: str):
    name = f"{prefix}{spec.name}"
    # 类型检查
    if spec.type == "int" and not isinstance(value, int):
        errors.append(f"{name}: 期望 int，实际 {type(value).__name__}")
    elif spec.type == "float" and not isinstance(value, (int, float)):
        errors.append(f"{name}: 期望 float，实际 {type(value).__name__}")
    elif spec.type == "bool" and not isinstance(value, bool):
        errors.append(f"{name}: 期望 bool，实际 {type(value).__name__}")
    elif spec.type == "str" and not isinstance(value, str):
        errors.append(f"{name}: 期望 str，实际 {type(value).__name__}")
    elif spec.type == "dict" and not isinstance(value, dict):
        errors.append(f"{name}: 期望 dict，实际 {type(value).__name__}")
    elif spec.type == "tuple" and not isinstance(value, (tuple, list)):
        errors.append(f"{name}: 期望 list/tuple，实际 {type(value).__name__}")
    elif spec.type == "list" and not isinstance(value, list):
        errors.append(f"{name}: 期望 list，实际 {type(value).__name__}")
    elif spec.type == "list" and spec.item_type == "mcp":
        # L2-1 + R3-2/M1：MCP 条目校验（serverName 契约 / command|url / 唯一性——早报）
        seen_names = []
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"{name}[{i}]: 期望对象（{{name, command|url, ...}}）")
                continue
            sname = item.get("name")
            if not isinstance(sname, str) or sname.startswith("_"):
                errors.append(f"{name}[{i}].name: 必填非空字符串")
            elif not _MCP_SERVER_NAME_RE.match(sname):
                errors.append(
                    f"{name}[{i}].name: 需 [A-Za-z0-9_-]{{1,32}}（MCP 服务器名）")
            else:
                seen_names.append(sname)
            command = item.get("command")
            url = item.get("url")
            has_cmd = isinstance(command, str) and bool(command)
            has_url = isinstance(url, str) and url.startswith(("http://", "https://"))
            if not has_cmd and not has_url:
                errors.append(
                    f"{name}[{i}].command: 需 command（stdio）或 url（streamable-http）")
            transport = item.get("transport")
            if transport is not None and transport not in ("stdio", "streamable-http"):
                errors.append(f"{name}[{i}].transport: 需 stdio|streamable-http")
            env = item.get("env")
            if env is not None and (not isinstance(env, dict) or not all(
                    isinstance(k2, str) and k2 and isinstance(v2, str) and v2
                    for k2, v2 in env.items())):
                errors.append(f"{name}[{i}].env: 期望 {{变量名: 环境变量名}}（非空字符串对）")
        dups = sorted({n for n in seen_names if seen_names.count(n) > 1})
        if dups:
            errors.append(f"{name}: 服务器名重复：{dups}（需作用域内唯一）")
    elif spec.type == "list" and spec.item_type == "str":
        # E0-A：字符串列表（如 extension_dirs）——非空字符串项
        for i, item in enumerate(value):
            if not isinstance(item, str) or not item.strip():
                errors.append(f"{name}[{i}]: 期望非空字符串（路径）")
    # 枚举检查（R5-1：provider/model 引用形式跳过——存在性由引擎构造期解析报错）
    if spec.enum and isinstance(value, str) and "/" not in value:
        # llm 字段支持 "type:model" 引用形式 → 只检 type 部分（R5-1）；
        # 其余枚举字段（session_mode/ui_theme/sandbox_mode/permission_profile）
        # 严格相等——"full-access:junk" 不得借 split 通过（C5/E0-4/P3-5）
        if spec.name == "llm" and ":" in value:
            checked = value.split(":", 1)[0]
            if checked not in spec.enum:
                errors.append(
                    f"{name}: 非法 provider 类型 '{checked}'（允许 {spec.enum}）")
        elif value not in spec.enum:
            errors.append(f"{name}: 非法取值 '{value}'（允许 {spec.enum}）")


def validate_config(data: dict) -> list:
    """返回错误列表（空 = 合法）。未知字段记为警告级错误（防拼写错）。

    $schema 白名单：JSON Schema 注释字段（IDE 补全引用）——config.example.jsonc 自带字段。
    """
    errors = []
    for key, value in data.items():
        if key == "$schema":
            continue  # IDE 注释字段，非引擎配置
        if key == "router" and isinstance(value, dict):
            # router 嵌套：域值必须是合法 spec（provider/model 引用跳过类型检查）
            if not isinstance(value, dict):
                errors.append("router: 期望 dict")
                continue
            for domain, spec in value.items():
                if isinstance(spec, str):
                    if "/" in spec:
                        continue
                    ptype = spec.split(":", 1)[0] if ":" in spec else spec
                    if ptype not in VALID_PROVIDER_TYPES:
                        errors.append(f"router.{domain}: 非法 provider 类型 '{ptype}'")
                elif isinstance(spec, dict) and "provider" in spec:
                    if not isinstance(spec.get("provider"), str) or not spec["provider"]:
                        errors.append(
                            f"router.{domain}.provider: 需为非空字符串（供应商 id）")
            continue
        if key == "providers":
            _check_providers(value, errors)
            continue
        if key == "mode_default" and value == "wayfinder":
            continue  # 旧值兼容读（批 1 更名：wayfinder → theroad；写侧新值）
        if key in _SPEC_MAP:
            _check_value(_SPEC_MAP[key], value, errors, "")
        else:
            errors.append(f"未知字段: {key}")
    # 交叉校验（批 2）：黄金期阈值对（0 < golden < managed ≤ 1）
    g = data.get("context_golden_pct")
    m = data.get("context_managed_pct")
    if isinstance(g, (int, float)) and isinstance(m, (int, float)) \
            and not isinstance(g, bool) and not isinstance(m, bool) \
            and not (0 < g < m <= 1):
        errors.append(
            "context_golden_pct/context_managed_pct: 需满足 "
            f"0 < 黄金 < 严管 ≤ 1（当前 {g}/{m}）")
    # 交叉校验（真测裁决 W2）：安全上限 ≥ 基线
    for hard_key, base_key in (("max_loop_rounds_hard", "max_loop_rounds"),
                               ("max_unit_budget_hard", "max_unit_budget")):
        hard = data.get(hard_key)
        base = data.get(base_key)
        if isinstance(hard, int) and not isinstance(hard, bool) \
                and isinstance(base, int) and not isinstance(base, bool) \
                and hard < base:
            errors.append(f"{hard_key} 不能小于 {base_key}"
                          f"（{hard} < {base}）")
    # 交叉校验（真测裁决 W4.3）：尝试上限 ≥ 1
    _fma = data.get("fragment_max_attempts")
    if isinstance(_fma, int) and not isinstance(_fma, bool) and _fma < 1:
        errors.append(f"fragment_max_attempts 必须 ≥ 1（当前 {_fma}）")
    # S1-A：自动恢复参数非负（0=关闭重试 / 无需等待）
    _prm = data.get("provider_retry_max")
    if isinstance(_prm, int) and not isinstance(_prm, bool) and _prm < 0:
        errors.append(f"provider_retry_max 必须 ≥ 0（当前 {_prm}）")
    _prb = data.get("provider_retry_backoff_s")
    if isinstance(_prb, (int, float)) and not isinstance(_prb, bool) \
            and float(_prb) < 0:
        errors.append(f"provider_retry_backoff_s 必须 ≥ 0（当前 {_prb}）")
    # G7：自动压缩预留/保留区非负；比例上限合法（E2-2 修订）
    for _key in ("auto_trim_reserve_tokens", "auto_compact_keep_recent_tokens",
                 "auto_trim_output_reserve_tokens"):
        _v = data.get(_key)
        if isinstance(_v, int) and not isinstance(_v, bool) and _v < 0:
            errors.append(f"{_key} 必须 ≥ 0（当前 {_v}）")
    _tr = data.get("auto_trim_trigger_ratio")
    if isinstance(_tr, (int, float)) and not isinstance(_tr, bool) \
            and not (0 < float(_tr) <= 1):
        errors.append(f"auto_trim_trigger_ratio 必须 (0, 1]（当前 {_tr}）")
    # 交叉校验（BOX-2）：container 档必须提供合法模板（loud——不静默回退）
    if data.get("sandbox_mode") == "container":
        _tpl = data.get("sandbox_container_template")
        if not isinstance(_tpl, str) or _tpl.strip() == "":
            errors.append(
                "sandbox_mode=container 需提供 sandbox_container_template"
                "（含 {workdir} 与 {cmd}/{cmd_b64}）")
        else:
            try:
                validate_container_template(_tpl)
            except ValueError as _e:
                errors.append(f"sandbox_container_template: {_e}")
    return errors


def gen_schema() -> dict:
    """生成 JSON Schema（IDE 校验/自动补全——$schema 引用体验）。"""
    properties = {}
    for s in FIELD_SPECS:
        t = {"int": "integer", "float": "number", "bool": "boolean",
             "str": "string", "tuple": "array", "dict": "object",
             "list": "array"}[s.type]
        prop = {"type": t, "description": s.desc}
        if s.enum:
            prop["enum"] = list(s.enum)
        properties[s.name] = prop
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
