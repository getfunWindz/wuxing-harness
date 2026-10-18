# WUXING（无形）Harness

> **LLM 是辅佐者（每一环的把关者），机制是裁决者。**

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

远程访问通过你自选的 overlay / 隧道（Tailscale、Cloudflare Tunnel、frp 等）；WUXING 只提供支持层，不运营穿透服务。

## 安全模型

- 凭据只写不读：密钥不进 config、不进日志、不进提交；设置页永不回显已保存值。
- 沙箱默认 native（cwd 限定 + 敏感环境变量剥离 + 超时杀进程树）；可选外置容器档，失败可见、不静默回退。
- 内容信任（SEC1）与扩展审查（SEC2）默认开启；扩展代码视为完全信任配置。
- `web_fetch` 与浏览器工具默认关闭；启用即引擎级网络授权，域名双表 + 私网硬拒。
- 远程壳服务必须配置 token；非环回绑定无 token 拒绝启动；Host/Origin 白名单；失败限速与审计。
- LAN 明文 HTTP 是已知台阶（同网可嗅探首次 token 换发）；生产建议 overlay/隧道加密。

## 贡献

- 先写失败测试，再实现；行为修复先复现。
- 一次提交只做一件事：`<type>(<scope>): <subject>`（feat/fix/docs/test/refactor/chore）。
- 只 stage 自己的文件，禁止 `git add -A` / `git add .`。
- 不提交密钥、凭据、运行产物、构建产物、日志。
- 修改协议先改 Python 契约，再 `python -m scripts.gen_protocol_ts`，禁止手改 `generated.ts`。
- UI/浏览器断言必须用真实鼠标事件（`page.mouse` / `page.click`），合成 `element.click()` 不作为交互可用性证据。
- 新增配置参数必须双写 `config.py` + `config_schema.py`；缓存键变更必须同步更新文档。

## License

MIT。见 [LICENSE](LICENSE)。
