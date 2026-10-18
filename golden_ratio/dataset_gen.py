"""训练集优化 v5.1 生成器：扩充样本 + under 方向覆盖 + 标定自洽性验证。

背景（诊断发现）：
- 三套件方向分布单侧（ok/over 无 under）→ C 臂 under 分支从未触发；
- mega 12 / 专业 10 样本量过小（桶样本 1~4，C 臂无增量根因）；
- 期望碎片数必须 ≤ 节点数（节点不可再分）——新增样本强制校验。

用法：python golden_ratio/dataset_gen.py（幂等：重复运行会重写相同添加任务，检查 id 冲突后跳过）
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from golden_ratio.calibrate import build_dag
from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape
from golden_ratio.experiment import _run_task, arm_config, granularity_deviation
from golden_ratio.llm import MockLLM

DATA = pathlib.Path(__file__).resolve().parent / "data"


def N(nid, text, domain, trades, complexity, deliverable, weight):
    return {"id": nid, "text": text, "domain": domain, "trades": trades,
            "complexity": complexity, "deliverable": deliverable, "weight": weight}


def make_tasks():
    """候选新任务（id 从现有编号后接）。"""
    pro = [
        # ---- medical +2 ----
        {"id": "P11", "domain_tag": "medical", "human_difficulty": 4, "message": "互联网医院在线问诊平台建设",
         "nodes": [N("n1", "问诊流程调研", {"分析": 0.9}, ["调研"], "mid", "text", 0.6),
                   N("n2", "平台功能设计", {"写作": 0.8}, ["创作"], "high", "text", 0.7),
                   N("n3", "医生端功能开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "处方审核规则配置", {"数据": 0.8}, ["实现"], "mid", "data", 0.6),
                   N("n5", "上线试运行", {"编程": 0.7}, ["测试"], "mid", "code", 0.5)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 3},
        {"id": "P12", "domain_tag": "medical", "human_difficulty": 5, "message": "医院电子病历质控体系",
         "nodes": [N("n1", "质控指标构建", {"数据": 0.9}, ["实现"], "high", "data", 0.8),
                   N("n2", "病历语料标注与模型训练", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n3", "质控规则引擎开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "病历质量报告体系", {"写作": 0.8}, ["创作"], "mid", "text", 0.5)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
        # ---- legal +2 ----
        {"id": "P13", "domain_tag": "legal", "human_difficulty": 4, "message": "跨境数据合规体系搭建",
         "nodes": [N("n1", "域外法规比对研究", {"分析": 0.9}, ["调研"], "high", "text", 0.6),
                   N("n2", "数据资产盘点", {"数据": 0.9}, ["实现"], "mid", "data", 0.6),
                   N("n3", "合规制度编制", {"写作": 0.9}, ["创作"], "high", "text", 0.8),
                   N("n4", "技术合规整改", {"编程": 0.8}, ["实现"], "high", "code", 0.9),
                   N("n5", "合规审计", {"分析": 0.8}, ["测试"], "mid", "decision", 0.5)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 4},
        {"id": "P14", "domain_tag": "legal", "human_difficulty": 5, "message": "集团合同全生命周期管理系统",
         "nodes": [N("n1", "合同模板体系设计", {"写作": 0.9}, ["创作"], "high", "text", 0.7),
                   N("n2", "合同结构化数据建模", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n3", "审批流与风控规则开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "存量合同迁移", {"数据": 0.8}, ["实现"], "high", "data", 0.7)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
        # ---- finance +2 ----
        {"id": "P15", "domain_tag": "finance", "human_difficulty": 4, "message": "银行核心系统下移项目",
         "nodes": [N("n1", "核心系统资产梳理", {"数据": 0.9}, ["调研"], "high", "data", 0.7),
                   N("n2", "下移架构设计", {"写作": 0.8}, ["创作"], "high", "text", 0.8),
                   N("n3", "核心账务系统开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "联机迁移与切流", {"数据": 0.8}, ["实现"], "high", "data", 0.9),
                   N("n5", "监管报送验证", {"分析": 0.8}, ["测试"], "mid", "decision", 0.5)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 4},
        {"id": "P16", "domain_tag": "finance", "human_difficulty": 5, "message": "反洗钱智能监测体系",
         "nodes": [N("n1", "洗钱风险模型设计", {"数据": 0.9}, ["分析"], "high", "decision", 0.8),
                   N("n2", "海量交易特征工程", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n3", "模型训练与调优", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "监测拦截规则上线", {"编程": 0.8}, ["实现"], "high", "code", 0.8)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
        # ---- research +2 ----
        {"id": "P17", "domain_tag": "research", "human_difficulty": 4, "message": "科研数据管理平台建设",
         "nodes": [N("n1", "科研数据需求调研", {"分析": 0.9}, ["调研"], "mid", "text", 0.6),
                   N("n2", "数据治理规范编制", {"写作": 0.9}, ["创作"], "high", "text", 0.7),
                   N("n3", "数据存储与接口开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "元数据清洗与入库", {"数据": 0.9}, ["实现"], "mid", "data", 0.7),
                   N("n5", "平台试运行", {"编程": 0.7}, ["测试"], "mid", "code", 0.5)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 4},
        {"id": "P18", "domain_tag": "research", "human_difficulty": 5, "message": "大规模人群队列研究项目",
         "nodes": [N("n1", "队列研究方案设计", {"写作": 0.9}, ["创作"], "high", "text", 0.7),
                   N("n2", "多源数据整合与治理", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n3", "队列分析平台开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "随访数据采集系统", {"编程": 0.8}, ["实现"], "high", "code", 0.8)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
        # ---- rpg-mega +2 ----
        {"id": "P19", "domain_tag": "rpg-mega", "human_difficulty": 5, "message": "开放世界资料片开发",
         "nodes": [N("n1", "资料片世界观设计", {"写作": 0.9}, ["创作"], "high", "text", 0.7),
                   N("n2", "大地图内容制作", {"写作": 0.8}, ["创作"], "high", "text", 0.8),
                   N("n3", "核心玩法系统开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "数值平衡调优", {"分析": 0.9}, ["分析"], "high", "decision", 0.8),
                   N("n5", "发行前质量保障", {"编程": 0.7}, ["测试"], "high", "code", 0.6)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 4},
        {"id": "P20", "domain_tag": "rpg-mega", "human_difficulty": 5, "message": "跨服联盟战系统",
         "nodes": [N("n1", "跨服玩法策划案", {"写作": 0.9}, ["创作"], "high", "text", 0.7),
                   N("n2", "跨服同步数据架构", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n3", "战斗核心引擎开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "联机对战保障", {"编程": 0.8}, ["实现"], "high", "code", 0.8)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
    ]
    mega = [
        {"id": "M13", "human_difficulty": 5, "message": "城市级智慧交通系统建设",
         "nodes": [N("n1", "交通数据接入治理", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n2", "信号控制模型研发", {"分析": 0.9}, ["分析"], "high", "decision", 0.8),
                   N("n3", "调度平台开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "城市路网数字孪生", {"数据": 0.8}, ["实现"], "high", "data", 0.8),
                   N("n5", "整体联调与试运行", {"编程": 0.7}, ["测试"], "mid", "code", 0.5)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 5},
        {"id": "M14", "human_difficulty": 5, "message": "万亿级数据湖平台迁移",
         "nodes": [N("n1", "存量数据资产盘点", {"数据": 0.9}, ["调研"], "high", "data", 0.7),
                   N("n2", "湖仓一体化架构搭建", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n3", "数据管道迁移重写", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "全量数据校验", {"数据": 0.8}, ["实现"], "high", "data", 0.8)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
        {"id": "M15", "human_difficulty": 5, "message": "全国电力调度系统升级",
         "nodes": [N("n1", "调度业务现状调研", {"分析": 0.9}, ["调研"], "high", "text", 0.6),
                   N("n2", "调度自动化架构设计", {"写作": 0.8}, ["创作"], "high", "text", 0.8),
                   N("n3", "核心调度引擎开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "电网数据接入平台", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n5", "容灾演练与切换", {"编程": 0.8}, ["测试"], "high", "code", 0.7)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 5},
        {"id": "M16", "human_difficulty": 5, "message": "大型央行数字货币系统",
         "nodes": [N("n1", "数字货币体系设计", {"写作": 0.9}, ["创作"], "high", "text", 0.8),
                   N("n2", "账本与共识机制研发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n3", "钱包与支付场景落地", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "货币发行结算系统", {"数据": 0.9}, ["实现"], "high", "data", 0.9)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
        {"id": "M17", "human_difficulty": 5, "message": "全球供应链数字孪生系统",
         "nodes": [N("n1", "供应链业务建模", {"分析": 0.9}, ["分析"], "high", "decision", 0.7),
                   N("n2", "全球物流数据采集", {"数据": 0.9}, ["实现"], "high", "data", 0.8),
                   N("n3", "孪生仿真引擎开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "优化决策算法研发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n5", "系统集成与上线", {"编程": 0.7}, ["实现"], "mid", "code", 0.6)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 5},
        {"id": "M18", "human_difficulty": 5, "message": "智能工厂 MES 系统建设",
         "nodes": [N("n1", "产线工艺流程数字化", {"数据": 0.9}, ["实现"], "high", "data", 0.8),
                   N("n2", "MES 核心功能开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n3", "设备数据采集平台", {"数据": 0.9}, ["实现"], "high", "data", 0.8),
                   N("n4", "质量追溯体系", {"数据": 0.8}, ["实现"], "high", "data", 0.7),
                   N("n5", "车间部署与培训", {"写作": 0.7}, ["创作"], "mid", "text", 0.5)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 5},
    ]
    calib = [
        # 三名 under（粗粒度观察场景：节点大、期望更细；双标尺）
        {"id": "T25", "human_difficulty": 4, "message": "企业数据中台建设",
         "nodes": [N("n1", "数据资产盘点与标准", {"数据": 0.9}, ["调研"], "high", "data", 0.7),
                   N("n2", "数据湖仓建设", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n3", "数据服务接口开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "数据质量与安全体系", {"数据": 0.8}, ["实现"], "high", "data", 0.8)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4, "expected_fragments_t40": 6},
        {"id": "T26", "human_difficulty": 5, "message": "全国医保信息化平台建设",
         "nodes": [N("n1", "医保政策与业务流程梳理", {"分析": 0.9}, ["调研"], "high", "text", 0.6),
                   N("n2", "省级数据集中治理", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n3", "结算与基金监管系统", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "跨省异地结算联网", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n5", "全量压力测试与上线", {"编程": 0.8}, ["测试"], "high", "code", 0.7)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"], ["n4", "n5"]],
         "expected_fragments": 4, "expected_fragments_t40": 8},
        {"id": "T27", "human_difficulty": 3, "message": "大型活动综合保障方案",
         "nodes": [N("n1", "活动需求与风险评估", {"分析": 0.9}, ["分析"], "high", "decision", 0.7),
                   N("n2", "安保与交通保障策划", {"写作": 0.9}, ["创作"], "high", "text", 0.7),
                   N("n3", "应急指挥系统部署", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "保障物资调度", {"数据": 0.8}, ["实现"], "mid", "data", 0.6)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 3, "expected_fragments_t40": 4},
    ]
    dom = [
        {"id": "D45", "domain_tag": "banking", "human_difficulty": 5, "message": "核心银行系统现代化改造",
         "nodes": [N("n1", "存量核心系统诊断", {"数据": 0.9}, ["调研"], "high", "data", 0.7),
                   N("n2", "核心重构方案设计", {"写作": 0.9}, ["创作"], "high", "text", 0.8),
                   N("n3", "核心账务引擎重写", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "并行运行与切换", {"数据": 0.8}, ["实现"], "high", "data", 0.8)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
        {"id": "D46", "domain_tag": "telecom", "human_difficulty": 5, "message": "5G 核心网云化改造",
         "nodes": [N("n1", "核心网云化方案设计", {"写作": 0.9}, ["创作"], "high", "text", 0.8),
                   N("n2", "网络功能虚拟化开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n3", "网络数据迁移", {"数据": 0.9}, ["实现"], "high", "data", 0.9),
                   N("n4", "全网割接与保障", {"编程": 0.8}, ["实现"], "high", "code", 0.8)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
        {"id": "D47", "domain_tag": "rpg", "human_difficulty": 4, "message": "大型副本系统重构",
         "nodes": [N("n1", "副本玩法重构设计", {"写作": 0.9}, ["创作"], "high", "text", 0.7),
                   N("n2", "战斗数值体系重做", {"分析": 0.9}, ["分析"], "high", "decision", 0.8),
                   N("n3", "副本引擎重构开发", {"编程": 0.9}, ["实现"], "high", "code", 0.9),
                   N("n4", "回归评测与平衡", {"编程": 0.7}, ["测试"], "mid", "code", 0.5)],
         "edges": [["n1", "n2"], ["n2", "n3"], ["n3", "n4"]],
         "expected_fragments": 4},
    ]
    return pro, mega, calib, dom


def validate_and_run():
    cfg = arm_config("B", AlgorithmConfig())
    llm = MockLLM()
    pro, mega, calib, dom = make_tasks()
    report = []

    for batch, fname, extra_keys in (
            (pro, "professional_tasks.json", []),
            (mega, "mega_tasks.json", []),
            (calib, "calibration_tasks.json", ["expected_fragments_t40"]),
            (dom, "domain_tasks.json", [])):
        existing = json.loads((DATA / fname).read_text(encoding="utf-8"))["tasks"]
        ids = {t["id"] for t in existing}
        for t in batch:
            spec = {"nodes": t["nodes"], "edges": t["edges"]}
            dag = build_dag(spec)
            shape = compute_shape(dag, cfg)
            _, frags, _ = _run_task(dag, cfg, llm)
            exp = t["expected_fragments"]
            gd = granularity_deviation(len(frags), exp)
            status = ("ok" if gd <= cfg.exp_success_threshold
                      else "over" if len(frags) > exp else "under")
            assert exp >= 1, f"{t['id']} 期望<1"
            assert exp <= len(dag.nodes), (f"{t['id']} 期望>{len(dag.nodes)} 节点（不可达）——"
                                           f"期望 {exp} > 节点 {len(dag.nodes)}")
            t40 = t.get("expected_fragments_t40")
            if t40 is not None and t40 > len(dag.nodes):
                t["expected_fragments_t40"] = len(dag.nodes)
                t["note_t40_cap"] = "m40 公式值超过节点数，按可达上限修正"
            if t["id"] in ids:
                report.append((fname, t["id"], t["message"], "SKIP(已存在)"))
                continue
            t["dag_spec"] = spec
            t["task_text"] = t.pop("message")
            t["source"] = "dataset-v5.1"
            existing.append(t)
            ids.add(t["id"])
            report.append((fname, t["id"], t["task_text"], f"L{shape.difficulty} act={len(frags)} exp={exp} {status}"))
        meta = {"version": "v5.1", "note": "扩充+under覆盖（dataset_gen.py 生成）"}
        with open(DATA / fname, "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "tasks": existing}, f, ensure_ascii=False, indent=1)
    return report


if __name__ == "__main__":
    for fname, tid, msg, res in validate_and_run():
        print(f"{fname:32} {tid:6} {msg[:24]:26} {res}")
