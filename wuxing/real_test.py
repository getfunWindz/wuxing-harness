"""真实测试（用户方案 2026-09-07）：多用户画像 × 自动注入 × 双口径缓存度量。

用户确认四项：
  1. 第 5-7 轮自动注入规则化（计划词→按计划执行；审查词→接受建议；兜底→继续）
  2. 双口径：单轮 cache_read_ratio + 会话累计 cumulative_ratio
  3. 失败轮次继续（真实用户行为——记录状态不中断）
  4. 图像可多重复（探索期单次；结论期建议 3 次）

画像（延伸设计）：
  novice  一知半解型（用户原文 9 轮——最大用户群/多轮/短提示）
  expert  行家型（首轮完整需求+技术栈+验收标准——少轮/长提示）
  precise 特定功能型（单点深挖——3-4 轮）
"""
import csv
import json
import logging
import pathlib
import re
import time

logger = logging.getLogger(__name__)

# ---------- 自动注入规则（规则优先级：计划 > 审查 > 兜底） ----------

_PLAN_RE = re.compile(
    r"(步骤|计划|方案|阶段|里程碑|实施|roadmap|step|plan|schedule)", re.IGNORECASE)
_REVIEW_RE = re.compile(
    r"(建议|审查|修改|缺陷|问题|bug|修复|检查|优化|review|fix)", re.IGNORECASE)


def auto_next(model_text: str) -> str:
    """根据模型输出决定下一轮注入（第 5-7 轮规则化——零成本零 LLM）。"""
    text = model_text or ""
    if _PLAN_RE.search(text):
        return "好的，按计划执行"
    if _REVIEW_RE.search(text):
        return "接受建议，开始修改"
    return "继续"


# ---------- 画像剧本 ----------

PROFILES = {
    "novice": {
        "name": "一知半解型",
        "turns": [
            {"kind": "static", "text": "我想要做一个基于springboot与vue的学校官网，"
                                        "这个系统面向xx学校的校务处，我需要你先给我一份实现方案"},
            {"kind": "static", "text": "你的方案很好，但我觉得有部分地方我还是不太懂，"
                                        "我需要你给我做一个全面的解释"},
            {"kind": "static", "text": "我已经明白了，接下来开始实现"},
            {"kind": "static", "text": "我发现你的代码似乎有bug，全面检查一下"},
            {"kind": "auto"},  # 5
            {"kind": "auto"},  # 6
            {"kind": "auto"},  # 7
            {"kind": "static", "text": "我需要你在当前官网中加入教师的信息页面"},
            {"kind": "static", "text": "我需要你生成一个该官网的实验报告，"
                                        "这是这一官网任务的文本交付物"},
        ],
    },
    "expert": {
        "name": "行家型",
        "turns": [
            {"kind": "static", "text":
                "项目概况：为 XX 学校校务处建设校园官网系统。背景：现有信息发布靠公告栏与"
                "微信群，需要统一门户。用户角色：管理员/教师/学生/访客。技术栈：后端 "
                "SpringBoot 3.x + MySQL 8 + Redis，前端 Vue3 + Vite + Element Plus + "
                "Pinia，RESTful 接口 + JWT 鉴权，前后端分离部署 Nginx。核心模块：首页展示、"
                "新闻公告、通知中心、用户与权限管理、文件上传。非功能需求：响应式布局、"
                "接口分页规范 page/size、统一响应体 code/message/data、日志留痕。验收标准："
                "①接口文档完整（OpenAPI）②前后端可独立启动 ③Service 层单测覆盖核心逻辑 "
                "④关键流程可演示。"
                "本轮要求：一次性并行交付以下 6 个独立子模块的骨架（互相无依赖，各自独立落盘）："
                "①后端 Maven 工程与启动类 ②统一响应体与全局异常处理 ③JWT 鉴权与 RBAC 骨架 "
                "④新闻公告 CRUD 接口骨架 ⑤Vue 前端工程与路由 ⑥教师信息模块骨架。"
                "请在同一轮内全部产出。"},
            {"kind": "static", "text":
                "方案方向认可。按以下补充细化后先更新方案再实现：①分页统一 page/size "
                "返回 {list,total}；②错误码枚举化（4xxxx 业务/5xxxx 系统）；③所有接口带 "
                "traceId 并记录请求日志；④前端路由懒加载 + 登录守卫 + 权限指令；"
                "⑤测试：Service 单测 + 关键 Controller MockMvc。"},
            {"kind": "static", "text":
                "开始实现时注意分层推进：先脚手架（后端 Maven 单模块 + 前端 Vite 工程）→ "
                "通用层（统一响应/异常/分页）→ 用户与鉴权 → 新闻公告 → 首页聚合。"
                "实现完成后逐条对照验收标准自查，把不符合项修复并在交付物中说明。"},
            {"kind": "static", "text":
                "新增教师信息模块：列表接口（分页 page/size + 按姓名与职称搜索，返回 "
                "{list,total}）/详情接口，前端新增教师页面与路由（复用现有权限指令与懒加载），"
                "补 Service 单测与 MockMvc 测试，同步更新接口文档与 README"
                "（启动命令/环境变量/测试命令）。"},
            {"kind": "static", "text":
                "生成项目实验报告（文本交付物，结构完整、术语准确、面向校内评阅）："
                "项目背景与目标 / 技术选型与理由 / 架构与模块划分 / 数据库设计要点 / "
                "关键实现（JWT 鉴权、分页、统一异常）/ 测试与验证证据（单测与 MockMvc 结果）/ "
                "遗留问题与下一步计划。"},
        ],
    },
    "beginner": {
        "name": "新手型",
        "turns": [
            {"kind": "static", "text": "写一个学生成绩管理系统"},
            {"kind": "static", "text": "加个登录"},
            {"kind": "static", "text": "全面检查一下代码，不要出bug"},
            {"kind": "static", "text": "加成绩统计"},
            {"kind": "static", "text": "加班级管理"},
            {"kind": "static", "text": "全面检查一下代码，不要出bug"},
            {"kind": "static", "text": "生成实验报告"},
        ],
    },
    "precise": {
        "name": "特定功能型",
        "turns": [
            {"kind": "static", "text":
                "需求：在当前项目中实现登录接口的 JWT 校验中间件及配套交付。"
                "本轮请并行交付以下 4 个独立子任务（互不依赖，各自落盘）："
                "①JWT 校验中间件实现（含密钥配置读取）②中间件单元测试"
                "（覆盖正常/过期/篡改/缺失 header 四类用例）③接口文档"
                "（请求/响应/错误码）④接入说明（如何在现有路由注册）。"
                "技术约束：遵循现有目录规范，测试须可运行。"},
            {"kind": "static", "text":
                "扩展阶段：本轮并行交付 3 个独立子任务：①权限校验扩展"
                "（基于角色的接口白名单）②令牌刷新端点（refresh token 流程）"
                "③失败审计日志（记录校验失败原因与时间戳）。"
                "每项独立落盘，并各自附测试或可验证命令。"},
            {"kind": "static", "text":
                "交付收口：本轮并行输出 3 个独立产出：①全部变更的接口契约汇总"
                "（OpenAPI 片段）②安全边界说明（重放/时序/密钥轮换）"
                "③回归验证清单（可逐条执行）。"},
        ],
    },
    # ---------- 通用化画像（用户裁决 2026-09-11：面向通用场景，保留编程强势） ----------
    "writer": {
        "name": "写作型",
        "turns": [
            {"kind": "static", "text":
                "需求：为校园读书节制定整合传播方案。目标受众为全校师生"
                "（细分群体：低年级学生/高年级学生/教职工），需输出传播目标"
                "（含可量化 KPI：触达率/参与率）、活动主题与调性、两周传播节奏。"
                "先给出方案框架（目标—策略—执行—预算—评估五段式）。"},
            {"kind": "static", "text":
                "基于框架展开完整策划案：每段包含执行主体、时间节点、产出物与"
                "验收口径；预算按场地、物料、奖品、传播四类编制，给出合计与占比。"},
            {"kind": "static", "text":
                "补充风险预案（舆情/天气/参与度不足/物资延期），并对全文进行"
                "术语与格式校审（标题层级、数据口径一致性、错别字）。"},
            {"kind": "static", "text":
                "基于策划案输出公众号推文（500 字：主标题/副标题/行动号召 CTA），"
                "面向学生受众调整文案调性并与策划案口径保持一致。"},
            {"kind": "static", "text":
                "最终交付：整理面向校方的《方案摘要》（一页纸：核心指标、预算总览、"
                "关键风险与应对）。"},
        ],
    },
    "analyst": {
        "name": "分析型",
        "turns": [
            {"kind": "static", "text":
                "数据分析任务：工作区需产出数据资产 data/scores.csv"
                "（20 名学生，字段：姓名、语文、数学、英语；60-100 分；"
                "固定随机种子保证可复现）。请用 Python 完成描述性统计"
                "（各科均值/中位数/标准差/极值）并输出分析摘要（注明统计口径）。"},
            {"kind": "static", "text":
                "在数据资产基础上执行进阶分析：①总分排名（Top5）"
                "②偏科指数（单科与个人均分的最大偏离）Top5"
                "③各科分布直方图数据（分箱）。"},
            {"kind": "static", "text":
                "输出正式分析报告：数据说明（口径与局限性）、统计分析结果、"
                "排名与偏科分析、结论与建议四部分。"},
            {"kind": "static", "text":
                "报告补充决策建议章节：三条可执行的教学改进建议，"
                "每条附数据依据与预期影响。"},
        ],
    },
    "planner": {
        "name": "规划型",
        "turns": [
            {"kind": "static", "text":
                "职业转型规划：目标岗位=数据分析师，周期=3 个月。约束："
                "工作日 2h/天、周末 4h/天、预算 3000 元、现有基础=Excel 中级。"
                "请输出学习计划与路径规划（阶段划分、里程碑、资源矩阵、"
                "验收标准、风险与应对）。"},
            {"kind": "static", "text":
                "细化第一阶段（第 1-4 周）：按周拆解学习内容、练习任务、"
                "产出物与验收口径（每周可验收）。"},
            {"kind": "static", "text":
                "资源推荐：书籍/在线课程/练手项目各不少于两项，给出选择理由、"
                "替代方案与成本估算。"},
            {"kind": "static", "text":
                "整合为正式规划文档：总时间表、资源预算表、每周检查清单"
                "（可勾选）。"},
            {"kind": "static", "text":
                "风险应对专章：若第 6 周进度落后两周，输出追赶方案"
                "（含取舍与优先级调整）。"},
        ],
    },
    "scripter": {
        "name": "脚本型",
        "turns": [
            {"kind": "static", "text":
                "工程任务：实现 CLI 脚本 tools/rename.py——批量重命名 data/ 目录下 "
                ".txt 文件为 日期_序号.txt（按 mtime 升序，mtime 相同按文件名升序，"
                "序号补零宽度自适应）。要求参数化（目录/日期格式/连接符可配置）、"
                "幂等性说明、干跑模式（--dry-run）。"},
            {"kind": "static", "text":
                "增量交付：为脚本补充健壮性——①目录不存在/无匹配文件的错误码与提示 "
                "②目标文件名冲突策略 ③异常处理与退出码定义。"},
            {"kind": "static", "text":
                "质量保障：补充单元测试（覆盖重命名逻辑、dry-run、冲突与异常路径），"
                "并给出可运行的测试命令与预期输出。"},
            {"kind": "static", "text":
                "审查与修复：对脚本执行静态审查（边界条件、路径安全、编码处理），"
                "输出缺陷清单与修复记录。"},
            {"kind": "static", "text":
                "交付收口：输出 README（用法/参数/示例/退出码/测试命令）"
                "与变更说明。"},
        ],
    },
}


# ---------- Runner 核心 ----------

def extract_last_text(res) -> str:
    """从 TaskResult 提取模型最后一次输出文本（供自动注入判断）。"""
    units = getattr(res, "units", None) or []
    for u in reversed(units):
        logs = getattr(u, "logs", None) or []
        for line in reversed(logs):
            s = str(line)
            if s and not s.startswith(("[tool", "[guard", "[warn", "[repair",
                                       "[cache")):
                return s
    return ""


def _round_request_stats(eng, trace_before: int) -> tuple:
    """本轮 trace 增量 → (llm_calls, hit_calls)。

    请求级对照（**旁系指标——不得简称「缓存命中率」**）：有任一缓存命中的请求/总请求；
    token 级唯一口径（用户裁决 2026-09-30·pi 同义）= 命中 token/完整 prompt 量。
    """
    try:
        rows = eng.trace.load()
    except Exception:
        return 0, 0
    calls = [r for r in rows[trace_before:] if r.get("event") == "llm_call"]
    return len(calls), sum(1 for c in calls if (c.get("cache_read") or 0) > 0)


def _round_fsc_count(eng, trace_before: int) -> int:
    """本轮 session_reused 事件数（FSC 复用计数——观测）。"""
    try:
        rows = eng.trace.load()
    except Exception:
        # trace 不可读 → 计 0（观测指标尽力而为，不阻断测试）
        return 0
    return sum(1 for r in rows[trace_before:]
               if r.get("event") == "session_reused")


def _round_speed_stats(eng, trace_before: int) -> dict:
    """本轮单元时长与最大并发（trace ts 增量——宽任务速度上限观测）。"""
    try:
        rows = eng.trace.load()
    except Exception:
        return {"unit_count": 0, "max_concurrency": 0, "longest_unit_s": 0.0}
    started = {}
    spans = []
    for r in rows[trace_before:]:
        if r.get("event") == "unit_started":
            started[r.get("unit_id")] = r.get("ts")
        elif r.get("event") == "unit_done":
            t0 = started.pop(r.get("unit_id"), None)
            if t0 is not None and r.get("ts"):
                spans.append((t0, r["ts"]))
    if not spans:
        return {"unit_count": 0, "max_concurrency": 0, "longest_unit_s": 0.0}
    events = []
    for a, b in spans:
        events.append((a, 1))
        events.append((b, -1))
    events.sort()
    cur = mx = 0
    for _, d in events:
        cur += d
        mx = max(mx, cur)
    return {"unit_count": len(spans),
            "max_concurrency": mx,
            "longest_unit_s": round(max(b - a for a, b in spans), 2)}


def run_profile(profile_name: str, workdir, llm=None, real_shape: bool = False,
                max_turns: int | None = None,
                max_parallel: int | None = None,
                fsc: bool = False) -> list:
    """驱动单个画像剧本（独立工作区——隔离会话）。

    llm：None=mock / spec(str/dict) / provider 实例。
    失败继续（真实用户行为）；每轮双口径度量；报告落盘（JSON+CSV）。
    max_parallel：S3 并行度实验（None=配置默认 2）。
    fsc：启用碎片会话延续（opt-in——池统计进报告）。
    """
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine

    profile = PROFILES[profile_name]
    workdir = pathlib.Path(workdir)
    cfg = EngineConfig(use_real_shape=real_shape)
    if max_parallel is not None:
        cfg.max_parallel_units = int(max_parallel)
    cfg.fsc_enabled = bool(fsc)
    eng = Engine(cfg=cfg, workdir=workdir, llm=llm, auto_confirm=True)
    sess = eng.start_session()
    rows = []
    cumulative_in = cumulative_cr = 0
    last_text = ""
    for i, turn in enumerate(profile["turns"], start=1):
        if max_turns is not None and i > max_turns:
            break
        if turn["kind"] == "static":
            prompt, injected = turn["text"], "static"
        else:
            prompt, injected = auto_next(last_text), "auto"
        # 请求级口径原料（2026-09-11）：本轮 llm_call 增量
        try:
            trace_before = len(eng.trace.load())
        except Exception:
            trace_before = 0
        t0 = time.time()
        try:
            res = sess.send(prompt)
            status = res.status
            usage = (res.metrics or {}).get("usage", {}) or {}
            new_artifacts = [a.path for a in (res.artifacts or [])]
        except Exception as e:  # 失败继续（真实用户行为）
            status = "error"
            usage = {}
            new_artifacts = []
            res = None
            print(f"[real-test] 第{i}轮异常（继续）：{type(e).__name__}: {e}")
        dur = round(time.time() - t0, 2)
        llm_calls, hit_calls = _round_request_stats(eng, trace_before)
        fsc_reused = _round_fsc_count(eng, trace_before)
        speed = _round_speed_stats(eng, trace_before)
        inp = int(usage.get("input", 0) or 0)
        cr = int(usage.get("cache_read", 0) or 0)
        miss = usage.get("cache_miss")  # DeepSeek 官方字段（直接问询 API）
        cumulative_in += inp
        cumulative_cr += cr
        rows.append({
            "round": i,
            "profile": profile_name,
            "injected": injected,
            "prompt": prompt[:160],
            "status": status,
            "duration_s": dur,
            "input": inp,
            "output": int(usage.get("output", 0) or 0),
            "reasoning_tokens": int(usage.get("reasoning_tokens", 0) or 0),
            "cache_read": cr,
            "cache_write": int(usage.get("cache_write", 0) or 0),
            **({"cache_miss": int(miss)} if miss is not None else {}),
            # 口径修正：零输入轮记 None（无数据不参与均值）
            "cache_read_ratio": round(cr / inp, 4) if inp else None,
            "cumulative_ratio": round(cumulative_cr / cumulative_in, 4)
            if cumulative_in else 0.0,
            "context_tokens": cumulative_in,
            "artifacts": len(sess.artifacts()),
            "new_artifacts": new_artifacts[:5],
            # 请求级口径（2026-09-11）：有任一命中的请求占比（与 token 级区分）
            "llm_calls": llm_calls,
            "hit_calls": hit_calls,
            "request_hit_rate": round(hit_calls / llm_calls, 4) if llm_calls else None,
            "fsc_reused": fsc_reused,
            **speed,
        })
        last_text = extract_last_text(res) if res is not None else ""
        # FSC 池统计：实时取（初始化时抓会全 0——修 2026-09-11 pilot 暴露）
        fsc_stats = (eng.orchestrator.session_pool.stats()
                     if eng.orchestrator.session_pool is not None else {})
        _save_reports(workdir, profile_name, rows, fsc_stats)
        _cr = rows[-1]["cache_read_ratio"]
        _cr_s = f"{_cr:.3f}" if _cr is not None else "n/a"
        print(f"[real-test] 第{i}/{len(profile['turns'])} 轮 status={status} "
              f"命中率={_cr_s} "
              f"累计={rows[-1]['cumulative_ratio']:.3f} 耗时={dur}s")
    return rows


def _save_reports(workdir: pathlib.Path, profile_name: str, rows: list,
                  fsc_stats: dict | None = None):
    """报告落盘（JSON 完整 + CSV 矩阵——逐轮覆盖写）。"""
    try:
        # N2：效率指标（快的主指标——每 done 耗时/有效轮均值）
        done = sum(1 for r in rows if r.get("status") == "done")
        wall = sum(r.get("duration_s", 0) for r in rows)
        eff = [r["cache_read_ratio"] for r in rows
               if r.get("cache_read_ratio") is not None]
        # 2026-09-11 口径固化：请求级（有任一命中请求占比）与 token 级（官方
        # hit/(hit+miss)）并列输出——控制台对照不再混淆
        total_calls = sum(int(r.get("llm_calls", 0) or 0) for r in rows)
        total_hit_calls = sum(int(r.get("hit_calls", 0) or 0) for r in rows)
        token_ratio = rows[-1].get("cumulative_ratio", 0.0) if rows else 0.0
        summary = {
            "done": done,
            "turns": len(rows),
            "wall_s": round(wall, 1),
            "sec_per_done": round(wall / done, 1) if done else None,
            "effective_rounds": len(eff),
            "avg_effective_ratio": round(sum(eff) / len(eff), 4) if eff else 0.0,
            "request_hit_rate": round(total_hit_calls / total_calls, 4)
            if total_calls else 0.0,
            "token_hit_rate": token_ratio,
            "reasoning_tokens": sum(int(r.get("reasoning_tokens", 0) or 0)
                                    for r in rows),
            "fsc": fsc_stats or {},
            "speed": {
                "max_concurrency": max((r.get("max_concurrency", 0) or 0)
                                       for r in rows) if rows else 0,
                "longest_unit_s": max((r.get("longest_unit_s", 0) or 0)
                                      for r in rows) if rows else 0.0,
            },
        }
        payload = {"profile": profile_name, "summary": summary, "turns": rows}
        (workdir / "real_test_report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        fields = ["round", "injected", "status", "duration_s", "input", "output",
                  "reasoning_tokens", "cache_read", "cache_write",
                  "cache_read_ratio", "cumulative_ratio", "context_tokens",
                  "artifacts", "llm_calls", "hit_calls", "request_hit_rate",
                  "fsc_reused", "prompt"]
        with open(workdir / "real_test_report.csv", "w", encoding="utf-8",
                  newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
    except OSError as exc:
        logger.debug("实测报告写出失败（观测不阻断）：%s", exc)
