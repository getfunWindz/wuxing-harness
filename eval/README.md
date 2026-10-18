# eval/ — 评测任务集与历史数据

| 路径 | 内容 |
|---|---|
| `tasks.v1.json` | 评测任务集 v1（`python -m wuxing.evaluate` 默认读取） |
| `baseline.json` | 当前基线（`--baseline` 对比口径） |
| `accuracy_tasks/` | 精确测试任务集 |
| `archive/` | **历史评测数据**（按日期/批次归档；含早期根目录散件的归档迁移） |

- **新评测输出请落本目录**：`python -m wuxing.evaluate` 默认写 `eval/eval_v4flash<ts>.json`（2026-09-16 起；此前默认在仓库根目录，已归档整理）。
- 归档件为**负结果/历史对照留档**，供追溯，不作为当前基线。
