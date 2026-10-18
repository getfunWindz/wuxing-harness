# AGENTS.md

本文件面向**模型 / agent**：说明 WUXING 是什么、如何按它的机制工作，以及在本仓库贡献代码时的硬规则。人类读者先看 [README](README.md)。

> **WUXING 的哲学：LLM 是辅佐者（每一环的把关者），机制是裁决者。**
> 模型可以提出方案、写代码、做判断；但「是否完成」「是否通过」「是否允许」由机制与证据判定。不要用自然语言声称绕过机制。

---

## 1. WUXING 是什么

WUXING 是一个面向通用任务的编程 harness：

1. **形状化**：把任务文本拆成目标、约束、交付物与验收线索（`golden_ratio`，唯一 LLM 形状化点）。
2. **域路由**：把碎片路由到 `plan` / `execute` / `verify` / `user` 域（循迹模式另有 `design` 域）。
3. **受控 agent loop**：每个单元有轮数上限、调用预算、域工具白名单、产物契约校验、provenance 溯源。
4. **DAG 编排**：按碎片依赖图调度；无依赖碎片并行；共享已完成碎片的经验；路径锁防互抢。
5. **确认门**：需要人决定时挂起（确认 / 提问 / 浏览器访问），默认不自动确认。
6. **验收**：`verify` 通过才算 done；可执行测试（`run_tests`）+ 验收 rubric；失败分类贯穿事件/报告/卡片。
7. **多端**：Web 壳、Electron、Android/HarmonyOS/iOS 薄壳共享同一套 Web UI。

三层职责：

| 层 | 负责 | 不负责 |
|---|---|---|
| 模型 | 理解、规划、实现、验收判断、写文案 | 决定机制是否放行、伪造证据 |
| 机制 | 路由、护栏、预算、白名单、契约、确认门、状态机 | 替模型写业务代码 |
| 用户 | 目标、取舍、确认、验收偏好 | 手工执行机械步骤 |

---

## 2. 模型使用 WUXING 的工作流

### 2.1 任务进入

- 先判断任务实质：是**问答/决策**、**代码/文档交付**，还是**需要真实环境验证**。
- 目标、范围、验收标准不清晰时，先问；不要用假设填充关键约束。
- 可自查的事实先自查（读文件、跑只读命令），不要把能自查的事丢给用户。

### 2.2 形状化与路由

- 形状化产出目标、约束、交付物、验收线索；它是后续碎片与验收的锚点。
- 路由按交付物选择域：
  - `plan`：侦察、方案、工作流拆分、票据/地图；
  - `execute`：真正产出代码/文档/数据；
  - `verify`：对交付物逐条验收，给出结论；
  - `user`：从最终用户体验出发做可执行审查（条件域，按需激活）。
- 碎片拆分遵循**垂直切片**：每片可独立完成、可独立验收；避免「先写一半再等下一片」。

### 2.3 执行纪律

- 先读后改：宽范围改动前读完整文件；不要凭搜索片段猜结构。
- 最小改动：只改与目标相关的文件；不做顺手重构。
- 写物证：`execute` 域要求真实写盘（`write_artifact` / `write_file` / `bash` 写文件）；只写「计划/说明」不算执行完成。
- TDD：新功能/修复先写失败测试，再实现；行为修复先复现（至少稳定复现再修）。
- 工具白名单：只调用当前域允许的工具；白名单外调用会被拦截并记录。
- 预算：轮数与调用预算有限；优先产出可验收的最小完整结果，不要空转。

### 2.4 确认与提问

- 触发确认门时，机制会给出四要素文案（做什么 / 为什么 / 影响 / 可逆性）；不要用技术黑话替代。
- `ask_user` 用于真正阻塞的决策；一次问当前最阻塞的问题，附推荐答案与理由。
- 浏览器回环访问、LAN 暴露、危险命令等确认必须由用户明确允许；拒绝/超时一律 fail-closed。
- 用户说「按推荐」时，采用推荐值并在结果中说明采用了什么。

### 2.5 验收与收口

- **done = verify 通过**；不是模型说完成，也不是文件存在。
- 交付物含测试时用 `run_tests` 实跑（pytest/unittest），引用真实输出作为证据。
- verify 回复最后一句必须是「结论：通过」或「结论：不通过」；逐条列出验收项与证据。
- 失败要诚实：`failure_class` = `provider`（基础设施）/ `budget`（预算耗尽）/ `stalled`（停滞）；不要用「已完成」掩盖失败。
- 报告写清：产物路径、验证命令与结果、未决项、范围外发现。

### 2.6 会话与上下文

- 长会话优先保留「目标/约束/已决策/未决」；历史可折叠、可压缩。
- 上下文接近窗口时，机制会裁剪/压缩；不要依赖已被裁剪的细节，必要时重新读文件。
- 缓存命中率（CH）= 最近一次请求的 `cache_read / input`；≥70% 优秀，≥80% 梦幻线。不要用累计 token 口径冒充。
- 碎片会话延续（FSC）复用同一工作流的经验；跨会话引用时注意作用域与字符预算。

---

## 3. 机制参考（模型需要知道的「为什么」）

### 3.1 受控 loop 与护栏

- `max_loop_rounds`（默认 6；硬上限 12）：到达基线后进入评分/自评，不直接失败；硬上限才停。
- `max_unit_budget`（默认 5；硬上限 12）：单单元 LLM 调用预算。
- `fragment_max_attempts`（默认 2）：同碎片最大尝试次数（含首次）。
- 工具白名单：按域配置；`mcp:*` 允许该域使用 MCP 工具面。
- 契约校验：产物 schema/存在性/kind；`execute` 要求写物证，`verify` 要求读物证。
- provenance：单元完成即 append-only 记录；`delegate` 子任务必须带 parent 链接。

### 3.2 DAG 编排

- 碎片 = 节点；依赖 = 边；就绪集并行执行。
- `max_parallel_units` 默认 8（硬上限 10）；`max_parallel_tools` 默认 8。
- 重叠写入路径 → 串行依赖边（防互抢）；声明式并发/独占屏障由机制处理。
- worktree 隔离是显式档：run 在独立 git worktree 执行，完成出 Review 卡，应用/丢弃由用户决定；非 git 工作区 loud 拒绝。

### 3.3 确认门

- `confirm_threshold`（默认 0.0）+ `confirm_threshold_difficulty`（0.5）决定哪些动作需要确认；`confirm_auto` 默认 false。
- 确认门覆盖：危险命令、外部写入、浏览器回环访问、LAN/登录态、扩展/装配变更等。
- 确认文案结构化四要素；技术细节默认折叠，不丢信息。
- 用户拒绝或超时 → 不执行；不要重试绕过。

### 3.4 验证与证据

- `run_tests` 只允许白名单命令（pytest/unittest），复用 bash 沙箱；在 verify/user 域可用。
- verify 的结论必须在回复文本最后一句；写在文件里的结论不作为判定依据。
- 验收项全部通过（含存疑）→ 通过；存在不通过项或产物缺失 → 不通过；范围外发现写入「额外发现」，不据此判不通过。
- 自报告与实测不一致时，以实测为准；不要编造测试输出。

### 3.5 上下文、缓存、会话

- 上下文窗口：机械判定（运行时实测 token），模型不自行估算。
- 自动裁剪：触发线默认 0.8×窗口，保留 16384，输出预留 8192；机械链默认开。
- 自动压缩：机械链默认开；LLM 摘要链可选（默认关）。
- 黄金期/管理期：窗口占用 20% / 50% 两个提示节点。
- 缓存键：ReplyCache = `{domain_id}|{prompt}`；ShapeCache = 规范化 task_text。改键会坏命中统计。
- FSC：碎片会话延续，按工作流归并；字符预算与保留轮数可配。
- 会话模式：`minimal-pure`（极简·纯净）/ `minimal-standard`（极简·标准）/ 循迹（theroad）；循迹用 `WUXING.md` 地图 + 票据。
- 分支：对话可 fork（redo/continue），血缘可见；上下文投影编辑 restore=回到原文，append-only。

### 3.6 技能、MCP、扩展

- 技能：`SKILL.md`（name/description/正文/可选脚本）；渐进披露；`load_skill` 按需加载。
- 技能治理：curator 生命周期（stale/archive/pinned，可恢复，绝不删除）；自沉淀默认开；沉淀前强制近义查重（命中不落盘）。
- MCP：`mcp_servers` 配置；工具统一 Tool 协议；工具数超过 20 时启用 ToolSearch 延迟披露（`mcp_always_load` 豁免）。
- 扩展：`extension_enabled` 默认开；事件钩子支持 allow/deny/ask + `updated_input`（deny > ask > allow）；生命周期事件包括 Subagent 起止、压缩前后、UserPromptSubmit。
- 扩展代码视为完全信任配置；分发前用 `scripts.check_extension` 审查（动态执行 + 静态扫描）。

### 3.7 模型与 providers

- `providers.<id>`：`type`（openai / anthropic / responses / deepseek）、`base_url`、`models`、可选 `timeout`。
- `llm` = 默认模型（`<provider>/<model>`）；`router` = 域级模型路由。
- API key 解析：环境变量 `<ID>_API_KEY`（大写）优先；或设置页保存到本机凭据文档（**write-only，界面永不回读**）。
- 密钥永不进 config、日志、提交；env 遮蔽时拒绝写入凭据文档。
- 智脑（brain）默认关：收集常开，A/B 收益未证明；需要时显式开启。
- provider 抖动与预算耗尽要归因为 `failure_class`，不要归因模型能力。

### 3.8 安全边界

- 沙箱：`sandbox_mode=native`（cwd 限定 + 剥离敏感 env + 超时杀进程树）或 `container`（显式模板；失败可见，不静默回退）。
- 权限剖面：`permission_profile` 默认 `workspace-write`；只读/工作区写/全权由机制控制。
- 内容信任（SEC1）：外部内容默认净化；扩展审查（SEC2）；确认门审计（SEC3）。
- `web_fetch` 默认关；启用即引擎级网络授权；域名双表 + 私网硬拒 + G6 截断落盘。
- 浏览器工具默认关；启用后仍有回环访问护栏（占用探测 → 指纹 → 条目 → 确认 → 重验），身份隔离/持久化/LAN 档显式配置。
- 远程壳：token 解析=显式 > `WUXING_SHELL_TOKEN` > 本机凭据文档；Bearer / `X-Wuxing-Token` / cookie；失败限速；非环回绑定无 token 拒绝启动；`shell_allow_hosts` / `shell_allow_origins` 白名单。
- LAN 明文 HTTP 是已知台阶（同网可嗅探首次 token 换发）；生产用 overlay/隧道加密。

### 3.9 移动端接入

- 手机与电脑同一网络（或 overlay/隧道）→ `wuxing shell serve --host <LAN地址>` + token → App 填 URL/token。
- 接入步骤、令牌纪律与吊销：见 [REMOTE_ACCESS.md](REMOTE_ACCESS.md)。
- Android：Java + WebView + Keystore；HarmonyOS：ArkTS + ArkWeb + AssetStore；iOS：WKWebView + Keychain。
- iOS 是**无签名 CI 产物 + Sideloadly 免费重签**（7 天有效），不是 App Store 分发。
- 移动端只承载 Web UI；原生桥最小集（通知/剪贴板）；不要假设 Web Notification API 在所有 WebView 可用。

---

## 4. 常用命令

```bash
pip install -e .
wuxing                                  # 后台服务 + 浏览器
wuxing shell serve                      # 前台服务
wuxing shell serve --host 0.0.0.0       # 远程绑定（必须先配置 token）
wuxing run "任务" --workdir .           # headless
```

开发与门禁：

```bash
python -m pytest wuxing/tests/ -q
python -m pytest golden_ratio/tests/ -q
python -m scripts.ci_check
ruff check wuxing golden_ratio scripts e2e --ignore BLE001,S110,B017
python -m scripts.repo_hygiene
python -m scripts.gen_protocol_ts --check

cd apps/shell
npm ci
npm run check
npm run deploy

python e2e/shell/run_all.py             # 先 deploy
```

移动端构建见 `apps/mobile/android/README.md`、`apps/mobile/harmony/README.md`、`apps/mobile/ios/README.md`。

---

## 5. 仓库地图

```
wuxing/          引擎（registry / runner / orchestrator / shell / tools / config）
golden_ratio/    算法层（形状化/分割/分词）
apps/shell/      TS 壳（web + Electron）
apps/mobile/     Android / HarmonyOS / iOS 薄壳
e2e/             壳 E2E 夹具与断言
eval/            评测任务集
scripts/         门禁、协议生成、仓库卫生
.github/         CI 与 iOS 无签名构建
```

边界：

- `wuxing/shell/` 禁止 import 引擎内部模块（AST 测试强制）；壳只走 `run_task` / `resume_task` / `confirm_unit`。
- 协议契约源在 Python（`wuxing/shell/web/contracts.py` + `wuxing/events.py` + `version.py`）；`apps/shell/web/src/protocol/generated.ts` 由脚本生成，禁止手改。
- `config.py` 是 SSOT；`config_schema.py` 必须双写；新参数双写并依赖一致性测试。

---

## 6. 在本仓库工作的硬规则

1. **先读后改**：宽范围改动前读完整文件；不要凭搜索片段猜结构。
2. **TDD**：先写失败测试（最小复现）→ 跑确认失败 → 最小实现 → 跑通过；行为修复先复现。
3. **最小 diff**：不做与目标无关的重构；不删看起来有意的代码，先问。
4. **证据先于声明**：声称完成/修复/通过前，运行验证命令并展示输出；不要用「应该可以」。
5. **只 stage 自己的文件**：`git add <path>` 显式路径；禁止 `git add -A` / `git add .`；提交前 `git status` 核对。
6. **提交格式**：`<type>(<scope>): <subject>`；type = feat/fix/docs/test/refactor/style/chore；一次提交只做一件事。
7. **不提交**：密钥、token、凭据、`.env`、日志、构建产物、缓存、`real_test/` 实验资产、临时脚本。
8. **不改生成物**：`generated.ts`、`static/next/`、`node_modules/`、`dist/`、构建产物。
9. **协议/配置纪律**：改事件/契约先改 Python 源 → 重新生成；新配置双写 + 测试。
10. **UI 断言纪律**：菜单/弹层/交互用真实鼠标事件（Puppeteer `page.mouse` / `page.click`）；合成 `element.click()` 不算交互可用性证据。
11. **安全纪律**：不绕过确认门/沙箱/白名单；不把密钥写进代码或日志；扩展代码按完全信任处理。
12. **移动端**：改 Web UI 后先 `npm run deploy` 再 E2E；iOS/Android/鸿蒙真机验证单独记录证据，不把模拟器结果冒充真机。

---

## 7. 贡献流程（建议）

1. 读相关文件与测试；确认改动边界。
2. 写失败测试 / 复现；小步实现。
3. 跑相关测试 → 广域回归 → `python -m scripts.ci_check`（提交前可选）。
4. `git diff` 自查；只 stage 自己的文件；提交。
5. 涉及协议/配置/移动端时，补对应门禁与文档。
6. 重大行为变更先开 issue/讨论，不要直接改公共契约。

---

## 8. 用户覆盖

如果用户指令与本文冲突：先指出冲突与风险，请求明确确认；不要静默绕过机制。用户明确要求覆盖后，按用户指令执行，并在结果中记录覆盖点。

---

## 9. License

MIT。贡献即同意以 MIT 许可证分发。
