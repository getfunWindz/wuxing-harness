# WUXING（无形）Harness

> **LLM 是辅佐者（每一环的把关者），机制是裁决者。**

> **阅读顺序**：每任务先读 [`AGENTS.md`](AGENTS.md)（精炼任务宪章）；本文件是详细介绍与机制参考，**按需查阅**。

WUXING 是一个面向通用任务的编程 harness：它把任务文本形状化为可执行计划，按域（plan / execute / verify / user）路由给受控 agent loop，用 DAG 编排碎片，用确认门与验收机制约束模型，最终产出可核查的产物与报告。

它不绑定某一家模型，也不把“模型说完成了”当作完成；完成由可复现的证据与机制判定。

## 特性

- **任务形状化**：把自然语言任务拆成目标、约束、交付物与验收线索（唯一 LLM 形状化点）。
- **域路由**：plan / execute / verify / user 常驻域；按任务与交付物选择执行面。
- **受控 agent loop**：轮数上限、调用预算、域工具白名单、产物契约校验、provenance 溯源。
- **DAG 编排**：碎片依赖图、无依赖并行（默认上限 8，硬上限 10）、共享上下文、路径锁。
- **人机确认**：确认门（四要素文案）、提问工具、浏览器回环访问确认；默认不自动确认。
- **证据优先验收**：`run_tests`、验收 rubric、verify 通过才判 done；失败分类（provider / budget / stalled）贯穿卡片、事件、报告。
- **会话与上下文**：会话/分支、碎片会话延续（FSC）、上下文窗口预算、自动裁剪/压缩、缓存命中观测（CH 口径）。
- **技能与扩展**：SKILL.md 渐进披露、curator 生命周期、自沉淀查重、MCP 工具、事件钩子、preset 组合。
- **多模型**：OpenAI 兼容 / Anthropic / Responses / DeepSeek 等 provider；域级模型路由；密钥只写不读。
- **多端**：Web 壳 + Electron；Android / HarmonyOS / iOS 薄壳承载同一套 Web UI。
- **安全边界**：凭据 write-only、native/container 沙箱、内容信任、扩展审查、远程鉴权档（token + 来源白名单）。

## 快速开始

前置：Python 3.10+；Node.js 24（仅壳前端开发/构建需要）。

```bash
pip install -e .
wuxing                     # 启动后台服务并打开浏览器（http://127.0.0.60:8723）
wuxing shell serve         # 仅前台服务
wuxing run "任务" --workdir .   # headless 运行
```

在壳的「设置 → 模型与供应商」中配置 provider、模型与域路由；也可以复制 `wuxing/config.example.jsonc` 手工配置。API key 建议用环境变量（变量名 = `<PROVIDER_ID>_API_KEY`，大写），或在设置页保存到本机凭据文档（**write-only，界面永不回读**）。

## 工作方式

```
任务文本
  → 形状化（golden_ratio：目标/约束/交付物/验收线索）
  → 域路由（plan / execute / verify / user）
  → 受控 agent loop（护栏 + 工具白名单 + 契约校验 + 溯源）
  → DAG 编排（依赖 / 并行 / 共享上下文）
  → verify（可执行测试 + 验收 rubric）
  → 产物清单 + 报告 + 事件流
```

壳只通过引擎公开 API（`run_task` / `resume_task` / `confirm_unit`）交互；协议类型由 Python 契约生成，前端不手写协议。

## 资源目录

技能扫描顺序（后者覆盖同名）：内置 `wuxing/resources/skills/`（旧 `builtin_skills/` 兼容回退）→ 用户 `~/.wuxing/skills/` → 用户便携 `~/.agents/skills/` → 项目 `.skills/`（legacy 兼容，进程内一次告警）→ 项目便携 `.agents/skills/`（canonical）。技能 sidecar 位于 `~/.wuxing/state/skills/`（旧路径兼容读）。

MCP 统一便携根 `.agents/mcp.json`：用户 `~/.agents/mcp.json` 始终加载；项目 `<ws>/.agents/mcp.json` 默认不加载，需用户级全局 `mcp_project_enabled: true` 或 env `WUXING_MCP_PROJECT_ENABLED=1`（工作区不能开启）；`config.jsonc:mcp_servers` 保留兼容。

## 机制参考

> 面向需要理解「为什么」的模型 / agent；日常任务只需读 [`AGENTS.md`](AGENTS.md)。

### 受控 loop 与护栏

- `max_loop_rounds`（默认 6；硬上限 12）：到达基线后进入评分/自评，不直接失败；硬上限才停。
- `max_unit_budget`（默认 5；硬上限 12）：单单元 LLM 调用预算。
- `fragment_max_attempts`（默认 2）：同碎片最大尝试次数（含首次）。
- 工具白名单：按域配置；`mcp:*` 允许该域使用 MCP 工具面。
- 契约校验：产物 schema / 存在性 / kind；`execute` 要求写物证，`verify` 要求读物证。
- provenance：单元完成即 append-only 记录；`delegate` 子任务必须带 parent 链接。

### DAG 编排

- 碎片 = 节点；依赖 = 边；就绪集并行执行。
- `max_parallel_units` 默认 8（硬上限 10）；`max_parallel_tools` 默认 8。
- 重叠写入路径 → 串行依赖边（防互抢）；声明式并发 / 独占屏障由机制处理。
- worktree 隔离是显式档：run 在独立 git worktree 执行，完成出 Review 卡，应用 / 丢弃由用户决定；非 git 工作区 loud 拒绝。

### 确认门

- `confirm_threshold`（默认 0.0）+ `confirm_threshold_difficulty`（0.5）决定哪些动作需要确认；`confirm_auto` 默认 false。
- 确认门覆盖：危险命令、外部写入、浏览器回环访问、LAN / 登录态、扩展 / 装配变更等。
- 确认文案结构化四要素；技术细节默认折叠，不丢信息。
- 用户拒绝或超时 → 不执行；不要重试绕过。

### 验证与证据

- `run_tests` 只允许白名单命令（pytest / unittest），复用 bash 沙箱；在 verify / user 域可用。
- verify 的结论必须在回复文本最后一句；写在文件里的结论不作为判定依据。
- 验收项全部通过（含存疑）→ 通过；存在不通过项或产物缺失 → 不通过；范围外发现写入「额外发现」，不据此判不通过。
- 自报告与实测不一致时，以实测为准；不要编造测试输出。

### 上下文、缓存、会话

- 上下文窗口：机械判定（运行时实测 token），模型不自行估算。
- 自动裁剪：触发线默认 0.8×窗口，保留 16384，输出预留 8192；机械链默认开。
- 自动压缩：机械链默认开；LLM 摘要链可选（默认关）。
- 黄金期 / 管理期：窗口占用 20% / 50% 两个提示节点。
- 缓存键：ReplyCache = `{domain_id}|{prompt}`；ShapeCache = 规范化 task_text。改键会坏命中统计。
- FSC：碎片会话延续，按工作流归并；字符预算与保留轮数可配。
- 会话模式：`minimal-pure`（极简·纯净）/ `minimal-standard`（极简·标准）/ 循迹（theroad）；循迹用 `WUXING.md` 地图 + 票据。
- 分支：对话可 fork（redo / continue），血缘可见；上下文投影编辑 restore = 回到原文，append-only。

### 技能、MCP、扩展

- 技能：`SKILL.md`（name / description / 正文 / 可选脚本）；渐进披露；`load_skill` 按需加载。
- 技能治理：curator 生命周期（stale / archive / pinned，可恢复，绝不删除）；自沉淀默认开；沉淀前强制近义查重（命中不落盘）。
- MCP：`mcp_servers` 配置；工具统一 Tool 协议；工具数超过 20 时启用 ToolSearch 延迟披露（`mcp_always_load` 豁免）。
- 扩展：`extension_enabled` 默认开；事件钩子支持 allow / deny / ask + `updated_input`（deny > ask > allow）；生命周期事件包括 Subagent 起止、压缩前后、UserPromptSubmit。
- 扩展代码视为完全信任配置；分发前用 `scripts.check_extension` 审查（动态执行 + 静态扫描）。

### 模型与 providers

- `providers.<id>`：`type`（openai / anthropic / responses / deepseek）、`base_url`、`models`、可选 `timeout`。
- `llm` = 默认模型（`<provider>/<model>`）；`router` = 域级模型路由。
- API key 解析：环境变量 `<ID>_API_KEY`（大写）优先；或设置页保存到本机凭据文档（**write-only，界面永不回读**）。
- 密钥永不进 config、日志、提交；env 遮蔽时拒绝写入凭据文档。
- 智脑（brain）默认关：收集常开，A/B 收益未证明；需要时显式开启。
- provider 抖动与预算耗尽要归因为 `failure_class`，不要归因模型能力。

### 安全边界

- 沙箱：`sandbox_mode=native`（cwd 限定 + 剥离敏感 env + 超时杀进程树）或 `container`（显式模板；失败可见，不静默回退）。
- 权限剖面：`permission_profile` 默认 `workspace-write`；只读 / 工作区写 / 全权由机制控制。
- 内容信任（SEC1）：外部内容默认净化；扩展审查（SEC2）；确认门审计（SEC3）。
- `web_fetch` 默认关；启用即引擎级网络授权；域名双表 + 私网硬拒 + G6 截断落盘。
- 浏览器工具默认关；启用后仍有回环访问护栏（占用探测 → 指纹 → 条目 → 确认 → 重验），身份隔离 / 持久化 / LAN 档显式配置。
- 远程壳：token 解析 = 显式 > `WUXING_SHELL_TOKEN` > 本机凭据文档；Bearer / `X-Wuxing-Token` / cookie；失败限速；非环回绑定无 token 拒绝启动；`shell_allow_hosts` / `shell_allow_origins` 白名单。
- LAN 明文 HTTP 是已知台阶（同网可嗅探首次 token 换发）；生产用 overlay / 隧道加密。

### 移动端接入

- 手机与电脑同一网络（或 overlay / 隧道）→ `wuxing shell serve --host <LAN地址>` + token → App 填 URL / token。
- 接入步骤、令牌纪律与吊销：见 [REMOTE_ACCESS.md](REMOTE_ACCESS.md)。
- Android：Java + WebView + Keystore；HarmonyOS：ArkTS + ArkWeb + AssetStore；iOS：WKWebView + Keychain。
- iOS 是**无签名 CI 产物 + Sideloadly 免费重签**（7 天有效），不是 App Store 分发。
- 移动端只承载 Web UI；原生桥最小集（通知 / 剪贴板）；不要假设 Web Notification API 在所有 WebView 可用。

## 仓库结构

| 路径 | 内容 |
|---|---|
| `wuxing/` | 引擎、域注册表、受控 loop、DAG 编排、工具、配置、壳服务 |
| `wuxing/shell/web/` | 壳 HTTP 服务 / 事件 / 管理器 / 静态产物 |
| `golden_ratio/` | 算法层（形状化 / 分割 / 分词） |
| `apps/shell/` | TS 壳（Web 前端 + Electron 桌面外壳） |
| `apps/mobile/` | 移动端薄壳：`android/`、`harmony/`、`ios/` |
| `e2e/` | 壳 E2E 夹具与浏览器断言套件 |
| `eval/` | 评测任务集与历史评测数据 |
| `scripts/` | 构建、门禁、协议生成、仓库卫生检查 |
| `workflow/` | 工作流规则单一来源（`rules.yaml`）与生成索引（`RULES.md`） |
| `.github/` | CI 与 iOS 无签名构建工作流 |

## 常用命令

```bash
python -m pytest wuxing/tests/ -q        # 引擎测试
python -m pytest golden_ratio/tests/ -q  # 算法回归
python -m scripts.ci_check               # 本地 CI 门禁（pytest×2 + ruff + 协议 + 前端）
ruff check wuxing golden_ratio scripts e2e --ignore BLE001,S110,B017
python -m scripts.repo_hygiene           # 推送前卫生检查
python -m scripts.gen_protocol_ts --check

cd apps/shell
npm ci
npm run check                            # typecheck + 架构红线 + 单测 + build
npm run deploy                           # 构建并部署到 wuxing/shell/web/static/next/

python e2e/shell/run_all.py              # 壳 E2E 全量（需先 deploy）
```

## 移动端

三端薄壳共享同一套 Web UI，连接电脑上的壳服务（URL + token）：

- **Android**：`apps/mobile/android/README.md`（Java + WebView + Keystore）。
- **HarmonyOS**：`apps/mobile/harmony/README.md`（ArkTS + ArkWeb + AssetStore）。
- **iOS**：`apps/mobile/ios/README.md`（WKWebView + Keychain；GitHub Actions 产出**无签名 IPA**，用 Sideloadly + 免费 Apple ID 重签安装）。

远程访问通过你自选的 overlay / 隧道（Tailscale、Cloudflare Tunnel、frp 等）；WUXING 只提供支持层，不运营穿透服务。接入步骤与令牌/吊销纪律见 [REMOTE_ACCESS.md](REMOTE_ACCESS.md)。

## 安全模型

- 凭据只写不读：密钥不进 config、不进日志、不进提交；设置页永不回显已保存值。
- 沙箱默认 native（cwd 限定 + 敏感环境变量剥离 + 超时杀进程树）；可选外置容器档，失败可见、不静默回退。
- 内容信任（SEC1）与扩展审查（SEC2）默认开启；扩展代码视为完全信任配置。
- `web_fetch` 与浏览器工具默认关闭；启用即引擎级网络授权，域名双表 + 私网硬拒。
- 远程壳服务必须配置 token；非环回绑定无 token 拒绝启动；Host/Origin 白名单；失败限速与审计。
- LAN 明文 HTTP 是已知台阶（同网可嗅探首次 token 换发）；生产建议 overlay/隧道加密。

## 贡献

### 硬规则

1. **先读后改**：宽范围改动前读完整文件；不要凭搜索片段猜结构。
2. **TDD**：先写失败测试（最小复现）→ 跑确认失败 → 最小实现 → 跑通过；行为修复先复现。
3. **最小 diff**：不做与目标无关的重构；不删看起来有意的代码，先问。
4. **证据先于声明**：声称完成 / 修复 / 通过前，运行验证命令并展示输出；不要用「应该可以」。
5. **只 stage 自己的文件**：`git add <path>` 显式路径；禁止 `git add -A` / `git add .`；提交前 `git status` 核对。
6. **提交格式**：`<type>(<scope>): <subject>`；type = feat / fix / docs / test / refactor / style / chore；一次提交只做一件事。
7. **不提交**：密钥、token、凭据、`.env`、日志、构建产物、缓存、`real_test/` 实验资产、临时脚本。
8. **不改生成物**：`generated.ts`、`static/next/`、`node_modules/`、`dist/`、构建产物。
9. **协议 / 配置纪律**：改事件 / 契约先改 Python 源 → 重新生成；新配置双写 + 测试。
10. **UI 断言纪律**：菜单 / 弹层 / 交互用真实鼠标事件（Puppeteer `page.mouse` / `page.click`）；合成 `element.click()` 不算交互可用性证据。
11. **安全纪律**：不绕过确认门 / 沙箱 / 白名单；不把密钥写进代码或日志；扩展代码按完全信任处理。
12. **移动端**：改 Web UI 后先 `npm run deploy` 再 E2E；iOS / Android / 鸿蒙真机验证单独记录证据，不把模拟器结果冒充真机。

### 流程

1. 读相关文件与测试；确认改动边界。
2. 写失败测试 / 复现；小步实现。
3. 跑相关测试 → 广域回归 → `python -m scripts.ci_check`（提交前可选）。
4. `git diff` 自查；只 stage 自己的文件；提交。
5. 涉及协议 / 配置 / 移动端时，补对应门禁与文档。
6. 重大行为变更先开 issue / 讨论，不要直接改公共契约。

## License

MIT。见 [LICENSE](LICENSE)。
