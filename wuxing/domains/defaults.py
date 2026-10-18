"""默认 4 域模板（Q5-B：数量/定义留待测试集验证阶段定案——此处为可替换初始值）。

success_markers：合格输出的关键词标记（runner 契约校验用，真 LLM 冒烟后契约化——
   原 hardcode 在 runner 的 keyword_map 只覆盖 plan/execute/verify，user 域缺失导致
   3 轮预算耗尽永远 failed——真 LLM 冒烟抓到的隐藏缺陷）。
artifact_kind：产物 kind（写文件命名）。
"""
from wuxing.protocols import DomainDefinition

DEFAULT_DOMAINS = {
    "plan": DomainDefinition(
        domain_id="plan", title="规划域",
        input_schema={"type": "object", "required": ["goal"]},
        output_schema={"type": "object", "required": ["plan"]},
        tool_whitelist=("write_artifact", "write_file", "load_skill", "delegate", "grep", "glob", "session_search", "tool_search", "todo_write", "ask_user", "web_fetch", "mcp:*"),  # 3c + SK + MCP + write_file + 搜索/检索（Wave-1）+ X6 + todo（E2-5）+ ask（A10）+ web_fetch（E2-5）
        quality_notes="产出可执行的方案计划，含步骤与验收标准。"
                    "**必须包含『实施工作流』一节：逐条标注工作流标签与目录**"
                    "（形如：`工作流：docs` 或 `工作流：backend/src`）——"
                    "后续碎片按工作流标签归并会话（FSC C 通道——用户裁决）。"
                    "**机制事实：写出计划产物即视为完成——第一轮就写产物**（先产出再按需补充）",
        prompt_skeleton="任务背景：{task}\n请为任务制定方案：{goal}",  # C-2：共同上下文前置（跨碎片前缀共享）
        success_markers=("方案", "计划", "规划", "plan", "design"),
        artifact_kind="plan",
    ),
    "execute": DomainDefinition(
        domain_id="execute", title="执行域",
        input_schema={"type": "object", "required": ["goal", "plan"]},
        output_schema={"type": "object", "required": ["result"]},
        tool_whitelist=("write_artifact", "write_file", "read_dependency", "read_file", "bash", "grep", "glob", "session_search", "load_skill", "delegate", "tool_search", "todo_write", "ask_user", "web_fetch", "run_script", "mcp:*"),  # 3c + read_file + bash + 搜索/检索（Wave-1）+ SK + MCP + write_file + X6 + todo + ask（A10）+ web_fetch（E2-5）+ run_script（A4 Code Mode）
        quality_notes="产物必须实现规划中的目标，可验证；"
                    "产物必须使用写工具（write_artifact/write_file）落盘到工作区——写入物证是完成前提。"
                    "**机制事实：产出本碎片要求的目标产物本身（代码/文档/数据等成品——"
                    "不是关于如何完成的计划、方案或说明；计划类产物属 plan 域）即视为完成——"
                    "第一轮就产出目标产物**（先产出再按需补充）",
        prompt_skeleton="任务背景：{task}\n方案：{plan}\n目标：{goal}",  # C-2
        success_markers=("执行", "完成", "实现", "done", "complete", "finished"),
        artifact_kind="result",
        require_write=True,  # P0 T3：无写物证不得判完成（S5）
    ),
    "verify": DomainDefinition(
        domain_id="verify", title="验证域",
        input_schema={"type": "object", "required": ["result"]},
        output_schema={"type": "object", "required": ["verdict"]},
        tool_whitelist=("write_artifact", "write_file", "read_dependency", "read_file", "grep", "glob", "run_tests", "session_search", "load_skill", "tool_search", "mcp:*"),  # P0 T4 + SK + 搜索/检索（Wave-1）+ MCP + write_file + X6 + O2-1 run_tests
        quality_notes="基于提供的产物内容给出验收结论——必须逐条核查验收标准（#1/#2…）"
                    "并给出『结论：通过』或『结论：不通过』；"
                    "即使结论是不通过也必须明确给出，不得只描述检查过程。"
                    "**输出契约（硬性）**：回复的最后一句必须是『结论：通过』或『结论：不通过』；"
                    "**分层判定（P0-1b）**：逐条核查后给出结构化条目"
                    "（每行 `#n：通过｜不通过｜存疑｜证据：…`）；"
                    "仅当存在验收项『不通过』或产物缺失/不存在时给出『结论：不通过』；"
                    "验收项全部通过（含存疑）时结论『通过』——存疑项与范围外发现"
                    "（如检查中发现的额外缺陷）必须写入"
                    "『【额外发现（不影响本次验收）】』段供审查，但不得据此判不通过；"
                    "产物不存在——『结论：不通过（产物缺失）』；"
                    "**写入文件的结论不作为判定依据**——结论必须出现在回复文本最后一句。"
                    "**效率约束**：下方『待验产物内容』为验收参考——优先直接验收，不要反复读文件；"
                    "**但若其为『交付摘要（模型无收口文本——自动生成）』（回退摘要，非交付物正文）"
                    "或明显不含实现/数据正文，必须用 read_file 读取工作区真实交付物"
                    "（代码/数据文件）后判定**——不得仅因回退摘要不完整就判"
                    "『不通过（不可核验）』；"
                    "**索引纪律（P0-1 D）**：若提供『工作区交付物索引』，"
                    "须至少用 read_file 读取与验收标准直接相关的真实文件后判定——"
                    "索引里的路径才是交付物本体；"
                    "无论是否读了文件，**最后一句必须是结论**（你只有很少轮数）；"
                    "**运行证据（O2-3）**：交付物含测试时用 `run_tests` 实跑"
                    "（python -m pytest/unittest），以运行结果作为验收证据",
        prompt_skeleton="任务背景：{task}\n待验产物内容：{result}\n待验产物路径：{paths}\n"
                        "请验收并逐条核查验收标准（若产物含验收标准段）。"
                        "**待验产物内容已在上方提供——直接基于它验收，不要反复读文件**；"
                        "**若内容为『交付摘要（模型无收口文本——自动生成）』（回退摘要，仅作索引）"
                        "→ 必须以 read_file 读取工作区真实交付物（代码/数据文件）后验收**；"
                        "**若提供『工作区交付物索引』→ 至少 read_file 读取相关真实文件后判定**；"
                        "**若交付物含测试 → 可用 `run_tests` 实跑"
                        "（python -m pytest/unittest）并引用运行结果作为证据**；"
                        "**输出契约：回复最后一句必须是『结论：通过』或『结论：不通过』**——"
                        "请用 `#n：通过｜不通过｜存疑｜证据：…` 逐条列出验收项；"
                        "范围外发现/存疑写入『【额外发现（不影响本次验收）】』段；"
                        "仅『不通过』项或验收不满足/产物缺失 → 结论不通过，不得只描述检查过程；"
                        "**写入文件的结论不作为判定依据（结论必须在回复文本中）**；"
                        "无论读不读文件，最后一句必须是结论",
        success_markers=("结论", "通过", "不通过"),
        artifact_kind="verdict",
        require_read=True,  # P0 T3：无读物证不得判通过（S5）
    ),
    "user": DomainDefinition(
        domain_id="user", title="用户域",
        input_schema={"type": "object", "required": ["goal"]},
        output_schema={"type": "object", "required": ["acceptance"]},
        tool_whitelist=("write_artifact", "write_file", "read_dependency", "read_file", "grep", "glob", "run_tests", "load_skill", "tool_search", "mcp:*", "browser_navigate", "browser_snapshot", "browser_screenshot", "browser_click", "browser_type", "browser_wait", "browser_evaluate"),  # SK：碎片级技能被动调用 + MCP + write_file + X6（批 1 一致性）+ O2-1 run_tests + O2-3 read 核查 + O2-2 浏览器（user 作业面：P1 三工具 + P2 操作面 + P3 evaluate显式档——注册受双闸）
        quality_notes="以最终用户体验为作业面：① 定义验收与体验标准；"
                    "② 对真实交付物做实际核查（read_file/glob 查看，必要时 run_tests 实跑测试并引用结果）；"
                    "③ 产出『验收与体验审查』文档——标准 + 实际发现 + 证据（读了什么/跑了什么）+ 结论与建议；"
                    "涉及可交互界面时，用内置浏览器访问并核查实际页面表现，必要时 click/type 真实互动后再快照（以快照为证据）；"
                    "不得只写标准不做核查。",
        prompt_skeleton="任务背景：{task}\n请定义验收视角：{goal}\n待核查交付物路径：{paths}\n"
                        "先做实际核查（读交付物、必要时 run_tests 实跑），"
                        "再写审查文档（标准＋发现＋证据＋结论）。",  # C-2 + O2-3
        success_markers=("用户", "验收", "体验"),
        artifact_kind="acceptance",
        conditional=True,  # P8：320 套件 user 仅 2.5%——低频条件域
    ),
}


# 循迹设计域（双模式批 3 · 设计 §5.2）：**独立常量，不进 DEFAULT_DOMAINS**
# ——仅在 theroad 会话按需动态注册（registry.register），不改变默认域集合。
DESIGN_DOMAIN = DomainDefinition(
    domain_id="design", title="设计域",
    input_schema={"type": "object", "required": ["goal"]},
    output_schema={"type": "object", "required": ["design"]},
    tool_whitelist=("read_file", "read_dependency", "bash", "grep", "glob",
                    "session_search", "web_fetch",
                    "write_map", "write_spec", "unclaim_ticket",
                    "write_artifact", "load_skill"),
    quality_notes=(
        "循迹设计会话：**侦察 → 拷问 → 地图**，只做设计不做执行。"
        "① 侦察：用 read/bash 自查工作区与资料，得出事实清单（AFK——不要问用户能自查的事）；"
        "② 拷问（HITL）：每轮最多 3 个问题，每个问题附推荐答案；一次只问当前真正阻塞的；"
        "总轮数上限 6（软约束）——尽早收敛到地图；"
        "③ 地图：信息充分且用户确认后，调用 write_map 写/更新 WUXING.md（目的地/路线/"
        "决策记录/未定/范围外）；write_map 只在用户确认后调用，不得擅自写。"
        "④ 规格（spec）：票据全部关闭且地图就绪后，合成七段规格"
        "（Problem Statement/Solution/User Stories/Implementation Decisions/"
        "Testing Decisions/Out of Scope/Further Notes；**不写文件路径与代码片段**，"
        "原型片段除外），用户确认后调用 write_spec；规格是临时物（验收后可清理）。"
        "⑤ 实施票据（【票据】块）：规格就绪后提议**垂直切片**（每票含 目标/验收标准/"
        "依赖边；单上下文可完成、可独立验收），用户 quiz 批准后由壳发布；发布后交给执行。"
        "输出契约【票据】行：`- 标题｜目标：…｜验收：甲；乙｜依赖：T-1`\n"
        "⑥ 认领视图（G8）：上下文出现 [票据认领] 时，向用户确认陈旧认领"
        "（无对应活动任务的）是否清除；用户确认后调用 unclaim_ticket 释放。\n"
        "**通道纪律（真测 REAL-6）**：运行期决策与票据**只走受控块**"
        "（【决策】/【票据】）；`write_map` 的 `decisions` 参数仅用于首次建档/历史迁移，"
        "不得用于记录运行期决策或声称关闭票据——票据关闭与 DAG 落图由引擎按块解析。\n"
        "**输出契约**：回复末尾附块（无内容可省略对应块）：\n【事实】\n- …\n"
        "【问题】\n1. 问题（推荐：答案；依赖：Q-1）（每题登记为决策票据 Q-n）\n"
        "【决策】\n- Q-n：<决策>｜理由：<理由>（用户回答后按 id 关闭票据；"
        "需回滚历史决策加 `｜回滚：D-x`）"),
    prompt_skeleton="任务背景：{task}\n设计会话输入：{goal}",
    success_markers=("问题", "地图", "事实", "设计", "侦察"),
    artifact_kind="design",
)
