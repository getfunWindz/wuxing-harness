"""引擎配置（参数外置，修改此文件即调参）。"""
from dataclasses import dataclass, field


@dataclass
class EngineConfig:
    # 护栏（Q10）
    max_loop_rounds: int = 6          # 执行单元轮数基线（到达→机械评分+自评，不失败）
    max_loop_rounds_hard: int = 12    # 轮数安全上限（真测裁决 W2：唯一硬停）
    max_unit_budget_hard: int = 12    # 调用安全上限（W2：唯一硬停）
    fragment_max_attempts: int = 2    # W4.3：同碎片最大尝试次数（含首次；达上限后
                                      # 确认续跑只调度未尝试碎片并留痕）
    max_unit_budget: int = 5          # 执行单元 LLM 调用预算（L4 真跑：3 轮不足
                                      # ——探索1+产出1+声明1 需≥4；5 留余量）
    # S1-A（2026-10-15）：provider 抖动的有界自动恢复
    provider_retry_max: int = 1       # 同候选自动重试次数（0=关闭；不占
                                      # fragment_max_attempts 手动重跑机会）
    provider_retry_backoff_s: float = 15.0  # 重试前固定等待（线性）
    # 工作区（Q8）
    default_artifact_dir: str = "artifacts"
    # 域注册（Q5）
    default_domains: tuple = ("plan", "execute", "verify", "user")
    # 分层把关（Q6）——阈值 0=全自动 1=全确认（P1 默认全自动；P5 深化）
    confirm_threshold: float = 0.0
    # 中间阈值（P6）：(0,1) 时启用难度加权——difficulty 归一化 >= 此门槛才确认
    confirm_threshold_difficulty: float = 0.5
    # 串并行（Q4）——#2 用户裁决 2026-09-11：默认上调 8（模拟真实工作环境；
    # Cursor 参考目标 8、硬上限 10——机制特殊（同键串行/文件锁）略缩）
    max_parallel_units: int = 8
    # #3 用户裁决 2026-09-11：单碎片工具批量并发上限（工具层防失控——
    # 全局上界 = max_parallel_units × max_parallel_tools，确定性有界）
    max_parallel_tools: int = 8
    # 分级放行（2026-09-11 用户裁决）：<soft 正常；[soft,hard) 缓速；
    # >=hard 阻止（让前批先工作）；回落 <soft 自动恢复（滞回，非死熔断）
    tool_concurrency_soft: int = 0    # 0=自动 64（8×8 目标）
    tool_concurrency_hard: int = 0    # 0=自动 100（10 碎片×10 工具硬限）
    tool_throttle_delay_ms: int = 25  # 缓速档每次获取前节流延迟
    # E3-3（X6）：ToolSearch 延迟加载——MCP 工具超阈值时不进提示词工具表
    # （模型经 tool_search 检索后调用；白名单/守卫/权限链不变）
    tool_search_enabled: bool = True
    tool_search_threshold: int = 20   # MCP 工具数**超过**才延迟
    mcp_always_load: tuple = ()       # 永不延迟的 server 名（豁免）
    # E3-5（CU10）：运行时产物清理纪律——sessions/reports 双上限 + 收口 debounce
    # （只清 .wuxing/ 内部；最旧先删；动作落 trace `cleanup`）
    cleanup_enabled: bool = True
    cleanup_interval_s: int = 3600    # 两次清理最短间隔（秒）
    cleanup_sessions_max: int = 300   # .wuxing/sessions 文件数上限
    cleanup_reports_max: int = 300    # .wuxing/reports 文件数上限
    # E2-5（WebFetch）：受控 Web 获取——默认关（未启用不注册）；域名双表；
    # 私网/回环/链路本地在 fetch 路径解析复检（硬拒——不可配置）
    web_fetch_enabled: bool = False
    web_fetch_domains_allow: list = field(default_factory=list)
    web_fetch_domains_deny: list = field(default_factory=list)
    # O2-2（内置浏览器）：默认关（未启用不注册）；公网域名双表；回环走动态授权
    # （占用探测→确认门→允许条目自进化——设计 §3.1；非安全边界）
    browser_enabled: bool = False
    browser_domains_allow: list = field(default_factory=list)
    browser_domains_deny: list = field(default_factory=list)
    # O5 安全门（T1/T2）：壳服务远程来源白名单（服务级——`wuxing shell serve`
    # 启动时读取；默认空 = 仅环回，行为不变）
    shell_allow_hosts: list = field(default_factory=list)
    shell_allow_origins: list = field(default_factory=list)
    # O2-2 P3（evaluate 显式档）：默认关（browser_enabled 与本开关任一关则不注册）；
    # 固定 CDP 参数（非任意透传）；SEC 复核见设计 §11.1
    browser_evaluate_enabled: bool = False
    # O2-2 §11.5-①（身份基线）：memory=按工作区内存态（退出即清——默认）/ persist=按工作区持久
    # （跨重启；设置「数据与维护→浏览器身份」；视图始终用专用 partition）
    # §11.5-③：storage-state=登录态档（Playwright 格式文件只读注入；键含文件短码）
    browser_identity_mode: str = "memory"
    # §11.5-③：LAN 白名单（CIDR；仅 RFC1918/ULA；默认空=私网硬拒）与登录态文件路径
    browser_lan_allow: list = field(default_factory=list)
    browser_storage_state_path: str = ""
    # A4 Code Mode（X7/A7 · Phase 1——脚本执行通道；默认关——新执行面）
    code_mode_enabled: bool = False
    code_mode_timeout_s: float = 120.0
    code_mode_max_calls: int = 64
    code_mode_output_max_chars: int = 20000
    code_mode_tools: tuple = ("read_file", "grep", "glob", "read_dependency",
                              "write_file", "write_artifact", "bash")
    # 真 LLM 形状化（P4）：True = golden_ratio 用 DeepSeekLLM；False = mock 模板。
    # 默认开（用户裁决 2026-09-18：算法测试期经验——形状化质量）；无凭据自动降级
    # mock + 报告引导提示（engine._real_shape_api_key），用户可在设置自主关闭。
    use_real_shape: bool = True
    # P11 配置形态：llm/route 从文件装载（Engine 消费——string 转 provider）
    llm: str = "mock"
    router: dict = field(default_factory=dict)
    # R3-1 供应商注册表（id → {type, base_url?, credential_ref?, display_name?, models?}）
    providers: dict = field(default_factory=dict)
    # 配置补遗：全局工具白名单（pi defaultTools 参考；delegate 等引擎级工具不受过滤）
    default_tools: tuple = ("write_artifact", "read_dependency",
                            "read_file", "write_file", "bash", "grep", "glob",
                            "session_search", "load_skill")
    # 配置补遗：LLM 韧性参数（P12 定案 4 次/60s 硬编码 → 配置化；factory+router 传导）
    llm_max_retries: int = 4
    llm_timeout: float = 180.0  # L4/GLM：thinking+tools 场景 50-90s/调用——60s 频繁截断
    # P14 智脑：默认关（Q7-C——机制沉淀，验证收益后启用）
    brain_enabled: bool = False
    brain_max_cases: int = 500
    # P1 T3：R3 语义缓存相似阈值（0=关闭；0.75=标点/空白微漂移命中，真变体不误判）
    cache_similar_threshold: float = 0.75
    # FSC（2026-09-11 设计；2026-09-12 用户裁决）：碎片会话延续——
    # 默认开（用户可自主关闭 fsc_enabled=False）；FSC 覆盖不到的碎片由跨轮
    # 摘要回退兜底（fsc_fallback_digest）
    fsc_enabled: bool = True
    # 技能自进化（用户裁决 2026-09-12）：高效任务（全 ok + done）→ 自评审→沉淀 skill
    skill_evolution_enabled: bool = True
    # 进度心跳（壳 P1 对齐项⑤）：模型自报进度 → progress 事件（无固定定时器）
    progress_heartbeat_enabled: bool = True
    # pi 式总体回复（Wave-1 Task A1；用户裁决 2026-10-01）：终端任务（done/partial/
    # failed）后由模型生成一条面向用户的总体回复消息；失败/关闭静默回退（不阻断）。
    task_reply_enabled: bool = True
    task_reply_max_chars: int = 800   # 总体回复字符上限（超出截断）
    # 双模式（2026-09-23 设计 v1 已复核 · 批 1）：会话创建时固定、仅空白会话可切、
    # 变更只影响新会话（缓存前缀纪律）。mode_default 合法集见 config_schema FIELD_SPECS enum。
    mode_default: str = "minimal-standard"
    mode_picker_enabled: bool = True       # 输入区模式选择器（chip）显隐
    # E2-4 装配预设：extensions/tools/prompt_segments/skills 组合声明（wuxing.presets；
    # 会话级 sidecar 覆盖此默认；解析失败回退 standard）
    assembly_preset: str = "standard"
    # 极简·纯净分支核心工具集（与域白名单取交集——设计 §4.2）
    minimal_pure_tools: tuple = ("bash", "read_file", "write_file",
                                 "write_artifact", "read_dependency")
    minimal_pure_auto_confirm: bool = True  # 纯净：不打断（danger_guard 拦截保留）
    # 界面主题（2026-09-19 用户裁决）：ink=水墨（默认）/ plain=纯白（壳读取后切换素材与品牌墨迹）
    ui_theme: str = "ink"
    fsc_retention_rounds: int = 4          # K=4（用户裁决）
    fsc_max_session_chars: int = 65536     # 单会话字符上限（≈32K tokens 量级）
    fsc_max_reuse: int = 3
    fsc_total_char_budget: int = 262144    # 池总预算
    # 低匹配回退（用户裁决 2026-09-12）：上一轮全部碎片上下文压缩 → 本轮前缀
    fsc_fallback_digest: bool = True
    fsc_digest_max_chars: int = 7000
    # 会话历史段字符上限（B 模式——build_conversation_msg；2026-09-23 上限放宽 4000→10000）
    conversation_max_chars: int = 10000
    # A 期 A3（2026-09-22）：会话窗口预算（估算 token；0=关闭=现状；
    # 会话级可经 context-sources.json 覆盖）——超限按固定优先级确定性裁剪
    context_budget_tokens: int = 0
    # G7 自动压缩（2026-09-26 用户裁决 · 方案 3）：机械链默认开（window−reserve 触发，
    # 滞回至 max(window−2×reserve, window/2)）；LLM 摘要链可选（默认关；失败降级机械）。
    auto_trim_enabled: bool = True
    auto_trim_reserve_tokens: int = 16384          # pi reserve 同值
    # E2-2（G7 v2 · 2026-10-03）：触发公式余量——比例上限 + 输出预留（DSH 对齐）
    auto_trim_trigger_ratio: float = 0.8           # 触发线 ≤ ratio×window
    auto_trim_output_reserve_tokens: int = 8192    # 输出预留 O（生成输出头寸）
    auto_compact_llm_enabled: bool = False
    auto_compact_keep_recent_tokens: int = 20000   # pi keepRecent 同值
    # 黄金期档位（2026-09-24 批 2 · 设计 §6）：≤golden 黄金 / ≤managed 正常 / >managed 严管
    # （模型窗口百分比——可校准；配置校验：0 < golden < managed ≤ 1）
    context_golden_pct: float = 0.2
    context_managed_pct: float = 0.5
    # 循迹设计会话（双模式批 3 · 设计 §5.2/§7）：软约束（提示词 + 壳呈现；引擎不硬限）
    design_question_soft_cap: int = 3
    design_round_cap: int = 6
    # 上下文窗口机制（2026-09-11 设计）：窗口解析 + 双阈值（60% 审计/80% 切换）
    model_context_windows: dict = field(default_factory=lambda: {
        "deepseek-flash": 1000000, "deepseek-v4-pro": 1000000})
    default_context_window: int = 200000
    fsc_audit_ratio: float = 0.6
    fsc_switch_ratio: float = 0.8
    # P3 T1：人工介入自动化开关（False=默认人工确认，True=全自动——CI/headless）
    confirm_auto: bool = False
    # resources 生态：外部资源声明 {name: {type, path, optional}}（配置生态面）
    resources: dict = field(default_factory=dict)
    # 上下文压缩：工具结果单条超限裁剪（头尾保留——DSH 式；压缩点不破前缀）
    context_max_chars: int = 8192
    # B（2026-09-11 报告 #6）：按工具来源差异化压缩上限（read 数据保真/bash 受控；
    # 未列出工具用 context_max_chars）——消除截断进产物的根因
    # 档位回调（用户裁决 2026-09-11）：read 64K→32K（batch2 实测 >32K 仅
    # beginner 6 条/novice 1 条——保留绝大多数内容同时回收上下文成本）
    context_tool_limits: dict = field(default_factory=lambda: {
        "read_file": 32768, "read_dependency": 32768, "bash": 16384})
    # 沙箱开关（R3-2 原生档默认开）：工作目录限定于工作区 + 敏感环境变量剥离；
    # BOX-2（用户裁决 2026-09-27）新增档位：native（默认）/ container（外置容器，需模板）
    sandbox_enabled: bool = True
    sandbox_mode: str = "native"
    sandbox_container_template: str = ""
    # O1/O4（2026-10-07）：bash 工具 shell 面——git-bash 主 terminal（Windows）/ POSIX 链
    bash_shell_path: str = ""       # 空=自动解析；显式=自定义 shell 绝对路径（存在性校验 loud）
    bash_timeout_s: float = 120.0   # 默认超时（秒）；调用方 timeout 覆盖（clamp 1..600）
    # SEC3（安全三件套 2026-09-30）：权限剖面——read-only/workspace-write/full-access
    # （机制层强制：工具装配过滤 + 路径/bash 守卫分档；危险黑名单恒定）
    permission_profile: str = "workspace-write"
    # SEC1（安全三件套 2026-09-30）：不可信内容净化（信封+隐形+高置信模式；可关做对照）
    content_trust_sanitize: bool = True
    # L2-1（审查 A3）：MCP 服务器配置（配置面接线——此前 McpServerConfig 死路径）
    # 每项：{name, command, args?, permissions?}——permissions 未声明 → 工具默认拦截
    mcp_servers: list = field(default_factory=list)
    # E0-A 扩展机制（设计 2026-09-26 · D2 默认开启可显式关闭）：
    # 目录约定 ~/.wuxing/extensions（用户级）+ <workdir>/.wuxing/extensions（项目级）；
    # extension_dirs 为附加目录（相对路径按工作区解析）。目录不存在 = 零行为；
    # 扩展 = 进程内完全信任代码（只加载可信来源）。
    extension_enabled: bool = True
    extension_dirs: list = field(default_factory=list)
    # M1-2：任务背景投影阈值（确定性截断——碎片聚焦与投影上限）
    task_context_max_chars: int = 400
    # L2-3（FC 层2）：工具检索——超阈值启用 top-k；0=关闭（小工具集零折腾）；
    # 2026-10-03（Wave-1）：默认 10→14——工具面扩张（grep/glob/session_search）后
    # execute 域达 11 个，原值临界误触发裁剪（无 tool_search 找回渠道时剪掉=失联）；
    # 保留给大 MCP 集场景触发
    tool_retrieval_threshold: int = 14
    tool_retrieval_top_k: int = 8
