# e2e/ — 壳端到端（E2E）资产

> 从 `real_test/`（本地证据区）迁入的**入库** E2E 套件资产（U14，2026-09-30）。
> 全量套件运行：`python e2e/shell/run_all.py`（本地 = CI 同口径）。
> CI：`.github/workflows/ci.yml` 的 `e2e` job（windows-latest + 预装 Edge；push/PR 全量）。

## 夹具策略（洁净基线——用户裁决 2026-09-30）

- **仓库零预置**：`fake-ws` / `fake-ws2` / `g8-par-ws` / `g8-claim-ws` 全部在夹具启动时
  **运行时生成**（`serve_fake.py` 重建种子；g8 由 `g8_m3_check.js` 清空并经 API 注册）；
  `fake-ws-keep` 由 `wayfinder_check.js` create 阶段写出。仓库不提交任何用户态工作区数据。
- **隔离**：夹具仅读写 `e2e/shell/` 下的运行目录（`.runtime/`）与系统临时目录；
  配置/凭据已沙盒到夹具目录（`serve_fake.py` monkeypatch `user_config_path` /
  `_global_config_dir` / `credentials_path`）——**绝不触碰真实 `~/.wuxing` 与用户工作区**。
- **持久性**：用户自建工作区不会被任何夹具重置清除；永久删除仅走 UI 两步确认（u5 套件锁定）。

## 本地运行

```bash
cd apps/shell && npm run deploy            # 先部署前端到 wuxing/shell/web/static/next
cd ../.. && python e2e/shell/run_all.py    # 全量（自动管理夹具与服务）
python e2e/shell/run_all.py --list         # 套件清单
python e2e/shell/run_all.py --only u5      # 单套件
```

单套件直跑（调试用）：

```bash
python e2e/shell/restart_fixture.py                     # 零态夹具（8833）
SHELL_URL=http://127.0.0.60:8833/next/ node e2e/shell/u5_remaining_check.js
python e2e/shell/restart_fixture.py restore             # wayfinder verify 前置
```

## 依赖

- Node 24 + `cd e2e/shell && npm install`（puppeteer-core；浏览器用系统 Edge，可 `EDGE_PATH` 覆盖）
- Python 3.10 + 仓库依赖（`pip install -e .`）

## 目录说明

| 文件 | 角色 |
|---|---|
| `shell/serve_fake.py` | 假引擎夹具（零 LLM；夹具运行时生成；title 延迟环境变量 `FAKE_TITLE_DELAY_MS`） |
| `shell/serve_fake_modes.py` | 模式化夹具（A 套件自管理；base_dir 传入，场景级隔离） |
| `shell/g8_seed.py` | G8 夹具种子（地图+规格+已认领票据） |
| `shell/restart_fixture.py` | 夹具严格重启（零态 / restore 两态；Windows） |
| `shell/run_all.py` | 全量 runner（CI 与本地同入口） |
| `shell/*_check.js` | 浏览器断言套件（真实鼠标事件；失败退出非零） |
| `shell/ui_fixes_check.js` | UI-1~4 回归断言（搜索跳转/切换时序/幽灵会话/陈旧上下文） |
