# WUXING 工作流规则索引

> 本文件由 `workflow/rules.yaml` 生成——禁手改；更新：`python -m scripts.workflow_gen`；对拍：`python -m scripts.workflow_gen --check`。
> 本文件是**按需查阅**的规则索引；每任务必读的精炼手册是根 `AGENTS.md`。

## 任务类型 → 流程技能

| id | 场景 | 技能链 | 证据合同 |
|---|---|---|---|
| `bug` | 缺陷/报错/测试失败/异常 | `systematic-debugging` | `E-bug` |
| `implement` | 功能/修复的生产代码实现 | `test-driven-development` | `E-impl` |
| `multi_step` | 重构/迁移/搭建/新项目 | `writing-plans` + `executing-plans` | `E-plan` |
| `feature_design` | 新功能/方案/创意设计（含方案裁决） | `brainstorming` | `E-design` |
| `doc_writing` | 正式文档（方案/报告/README/说明书） | `doc-coauthoring` | `E-doc` |
| `research` | 调研（外部项目/材料/一手来源） | — | `E-research` |
| `review` | 审查（代码/UI/全面审查） | — | `E-review` |
| `merge` | 合并/交付前 | `requesting-code-review` + `finishing-a-development-branch` | `E-merge` |
| `review_received` | 收到外部评审意见 | `receiving-code-review` | `E-rcv` |
| `isolation` | 需要隔离工作区（实验/并行） | `using-git-worktrees` | `E-iso` |

## 规则速查

### L0 · 不可违背

- **`L0-SEC-1`**（all）触发：任何接触凭据（key/token/密码）的操作：接入、调试、配置、文档；必须：不入库、不进日志、不进文档/提交；key 走环境变量或会话内传递；发现泄露立即报告用户；证据：repo_hygiene 通过 + 提交 diff 自查无凭据模式
- **`L0-TRUTH-1`**（all）触发：任何对完成度/通过与否的陈述；测试、实验、评测结果上报；必须：只陈述实际执行的命令与原始输出；失败/降级/部分完成如实标注；不伪造、不夸大、不隐瞒；证据：命令 + 原始输出（会话或报告，可复核对）
- **`L0-USER-1`**（all）触发：删除/覆盖用户数据、越工作区写、不可逆变更、改动范围超出任务授权；必须：先征得用户确认；不确定先问，不擅自扩大范围；证据：用户确认记录（会话）
- **`L0-PHIL-1`**（all）触发：任何机制/流程/判定设计（含本工作流系统自身）；必须：LLM 只作辅佐（把关者），最终裁决由机械机制承担；不引入不可审计的 LLM 硬判定；证据：设计文档中的裁决路径说明

### L1 · 工程铁律

- **`L1-TDD-1`**（implement, bug）触发：编写/修改运行行为的生产代码；必须：遵循红-绿流程；红/绿是否显式执行由模型自选，非代码工作不启用；证据：红/绿输出（如执行） + 通过输出
- **`L1-BUG-1`**（bug）触发：bug/报错/测试失败/异常行为；必须：先复现（机制性缺陷 3 次可复现）→ 定位根因 → 再修复；禁止猜测性乱改；证据：复现命令/输出 + 根因（文件:行/链路） + 修复后同命令复跑
- **`L1-EVID-1`**（all）触发：准备声称完成/修复/通过（含收口/提交/交付）；必须：先运行相关验证并展示输出；缺证不得声明；证据：验证命令 + 输出（贴会话或落文件）
- **`L1-PLAN-1`**（multi_step, implement）触发：多步骤任务（重构/迁移/搭建/新项目）或含显著不确定性的功能；必须：先产计划（步骤 + 验收标准）再动手；执行期按计划勾选；证据：计划文件（docs/plans/）或对话内计划
- **`L1-REG-1`**（implement, bug, multi_step）触发：行为类改动完成；必须：相关测试 + 全量回归全绿；算法层改动跑 golden_ratio/tests/；前端改动 npm run check；涉壳交互跑 E2E；证据：测试命令与结果计数 + E2E / 前端门禁输出
- **`L1-MOUSE-1`**（review, merge）触发：以浏览器断言作为 UI 交互可用性证据；必须：真实鼠标/键盘事件（CDP/Playwright/Puppeteer）；禁 element.click() 合成点击；证据：真实事件脚本 + 断言输出/截图
- **`L1-COMMIT-1`**（all）触发：完成一个有意义阶段；必须：一次提交只做一件事；不攒大批；提交前 git diff 自查（不提交调试代码/临时文件）；证据：提交序列（git log） + diff 自查
- **`L1-DOC-1`**（all）触发：用户裁决 / 设计分歧 / 重大变更；必须：落决策记录/README/设计文档；禁止仅口头留痕；证据：文档条目（日期 + 条目）
- **`L1-READ-1`**（implement, bug, multi_step）触发：修改文件（宽范围改动尤甚）；必须：先读相关文件全文再改，不凭假设动刀；证据：改动说明可核（引用的实现/调用点）
- **`L1-FREEZE-1`**（all）触发：拟启动真 LLM 接入/评分/A-B 测试；必须：开发达到预期前不启动；须用户显式解冻；证据：用户解冻记录
- **`L1-ORIG-1`**（all）触发：引入外部项目参照（实现/目录/命名/机制）时；必须：实现可搬用但须融合适配（涉我方机制差异处重构，非照搬）；命名不得与外部完全一致；证据：评审/diff 可核（无完全同名；差异点有说明）

### L2 · 项目约定

- **`L2-SHELL-1`**（implement, bug）触发：修改壳/引擎边界或前端协议；必须：壳只走 Engine 公开 API（run_task/resume_task/confirm_unit）；AST import 测试强制；证据：wuxing/tests/test_import_direction.py 通过 + ci_check 通过
- **`L2-CACHE-1`**（implement, bug）触发：修改 ReplyCache / ShapeCache 键或命中统计；必须：ReplyCache key = {domain_id}|{prompt}；ShapeCache = task_text 规范化；改键同步文档与统计口径；证据：相关缓存测试通过 + 缓存基准复验
- **`L2-CONFIG-1`**（implement）触发：新增/修改引擎配置参数；必须：config.py EngineConfig 与 config_schema.py FIELD_SPECS 双写；依赖一致性测试守卫；证据：配置一致性测试通过
- **`L2-CRED-1`**（implement）触发：修改凭据存储/设置页/API；必须：凭据 write-only；UI/API 永不回读值；env 遮蔽时拒绝写入；证据：相关测试通过 + repo_hygiene 通过
- **`L2-PROV-1`**（implement）触发：修改单元完成/委派链路；必须：单元完成即写 provenance 链（append-only）；delegate 子任务带 parent 链接；证据：provenance 测试通过
- **`L2-PROTO-1`**（implement）触发：新增/修改壳事件或契约；必须：先改 Python 契约 → gen_protocol_ts → 对拍；禁手改 generated.ts；证据：python -m scripts.gen_protocol_ts --check 通过
- **`L2-INJECT-1`**（implement）触发：修改提示词段/消息段装配；必须：核对《注入规范》§5 前缀稳定清单；系统段字节稳定性与节级哈希守卫；证据：wuxing/tests/test_prompt_sections.py 通过
- **`L2-MODULE-1`**（implement, multi_step）触发：新增模块或拆解巨型文件；必须：注解覆盖 ≥60%；静默异常回退必须注释或降级日志；新模块入 ruff；≤800 行目标；提取模块不得 import engine；证据：test_import_direction.py 通过 + ruff 通过
- **`L2-GIT-1`**（all）触发：提交改动；必须：只 stage 本会话文件；显式路径 git add；提交前 git status 核对；不用 git add -A/.；证据：git status / git log 摘要
- **`L2-HYGIENE-1`**（all）触发：提交前；必须：不提交调试代码/临时文件/日志/构建产物/实验资产；不改 .gitignore 覆盖目录；证据：git diff 自查 + repo_hygiene 通过
- **`L2-GATE-1`**（implement, bug, multi_step, merge）触发：行为类改动完成/收口；必须：相关测试 + 全量回归 + ci_check；前端 npm run check；壳交互 E2E；全面审查按需触发；证据：ci_check 输出 + E2E / 前端门禁输出
- **`L2-DOCS-1`**（doc_writing, review, merge）触发：新增/移动/归档文档；必须：按 docs/README 命名与登记；用户裁决落决策记录；收口计划归档；证据：docs/README 索引更新 + 决策记录条目
- **`L2-SKILL-1`**（all）触发：任务收口且处理链高效可复用；必须：自评审后沉淀 SKILL.md；沉淀前强制近义查重；同名不覆盖；证据：trace skill_evolved / skill_evolve_skipped + 技能目录变更
- **`L2-MOBILE-1`**（implement, review）触发：修改 Web UI 或移动端薄壳；必须：先 npm run deploy 再 E2E；真机证据单独记录；不把模拟器结果冒充真机；证据：deploy 记录 + E2E / 真机日志

### L3 · 建议

- **`L3-OPT-1`**（all）触发：评估流程/机制/文档改动提案；必须：先问机械负载与上下文注入增量；优先净减（合并去重 > 有理由微增 > 零增）；仅形式收益不做；证据：提案中的强度评估
