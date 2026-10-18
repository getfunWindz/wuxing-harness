"""85 样本 human_difficulty 重标（阶段2 待办 #1：标注质量是校准瓶颈）。

标定基准（语义为锚，结构校验——真实形状化视图）：
- L1 单一小任务（单步骤/单工单）；L2 常规任务（客服波次/小型创作/小型活动）；
  L3 中复杂度（多步骤单领域/活动策划/RPG 创作模块）；L4 跨模块项目（体系搭建）；
  L5 超大规模（全国/集团级）。
- 工时模型输出 T 受形状化粒度影响（客服工单形状化 8 节点后 T 被放大到 300h+，
  属模型伪影）→ 语义层级为主锚，T/N 仅复核。
- calibration 27（认真标定）不动；本文件只重标 mega/professional/domain 85。

用法：python golden_ratio/relabel.py（输出应用摘要 + 112 重校准结果）
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from golden_ratio.calibrate import calibrate
from golden_ratio.config import AlgorithmConfig

REAL = pathlib.Path(__file__).resolve().parent / "data" / "real_suites"

# 建议表（语义层级判断；原值留痕）
SUGGEST = {
    # mega（项目级）
    "M01": 5, "M02": 5, "M03": 4, "M04": 3, "M05": 5, "M06": 5, "M07": 4, "M08": 5,
    "M09": 4, "M10": 5, "M11": 4, "M12": 3, "M13": 5, "M14": 4, "M15": 5, "M16": 5,
    "M17": 4, "M18": 4,
    # professional（专业项目级）
    "P01": 4, "P02": 4, "P03": 4, "P04": 3, "P05": 5, "P06": 5, "P07": 5, "P08": 5,
    "P09": 3, "P10": 3, "P11": 5, "P12": 5, "P13": 4, "P14": 5, "P15": 5, "P16": 5,
    "P17": 5, "P18": 5, "P19": 4, "P20": 5,
    # domain 客服/角色/活动/创作类（语义降级为主）
    "T1": 2, "T2": 2, "T3": 2, "T4": 2, "T5": 1, "T6": 2, "T7": 2, "T8": 1,
    "T9": 2, "T10": 2, "T11": 2, "T12": 2,
    "B1": 2, "B2": 2, "B3": 2, "B4": 2, "B5": 3, "B6": 2, "B7": 3, "B8": 2,
    "S01": 3, "S02": 3, "S03": 3, "S04": 3, "S05": 2, "S06": 2,
    "R01": 2, "R02": 3, "R03": 2, "R04": 3, "R05": 3, "R06": 2,
    "D45": 5, "D46": 5, "D47": 4,
    # L1-L12（mobile data）原标 L2 合理 → 保持（不入表即不动）
}


def main():
    applied = 0
    for name in ("mega", "professional", "domain"):
        path = REAL / f"{name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for t in data["tasks"]:
            sug = SUGGEST.get(t["id"])
            if sug and t.get("human_difficulty") != sug:
                t["human_difficulty_old"] = t.get("human_difficulty")
                t["human_difficulty"] = sug
                t["human_difficulty_method"] = "semantic-relabel-v1"
                applied += 1
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"重标应用: {applied} 个（mega/professional/domain 33+20+32=85 中，标注不变的样本未计数）")

    # 112 全量重校准（校准集 = calibration 27 + 重标后 85）
    tasks = []
    for name in ("calibration", "mega", "professional", "domain"):
        tasks += json.loads((REAL / f"{name}.json").read_text(encoding="utf-8"))["tasks"]
    report = calibrate(tasks, AlgorithmConfig())
    print(f"112 全量校准: 旧bins错分 {report['before_rate']:.1%} → 新bins {report['best_bins']} 错分 {report['after_rate']:.1%}")
    from collections import Counter
    wrong = Counter()
    for d in report["details"]:
        if d["human"] != d["after_pred"]:
            wrong[(d["human"], d["after_pred"])] += 1
    print("误分组合(human→pred):", dict(sorted(wrong.items())))


if __name__ == "__main__":
    main()
