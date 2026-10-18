"""三级合规门禁测试（§5 指标重构：hard/standard/fine）。"""
from golden_ratio.config import AlgorithmConfig
from golden_ratio.experiment import compliance_levels


def test_compliance_levels_standard():
    cfg = AlgorithmConfig()
    assert compliance_levels(30.0, cfg) == "standard"
    assert compliance_levels(90.0, cfg) == "hard"      # >80 但 ≤120
    assert compliance_levels(150.0, cfg) == "violation"
    assert compliance_levels(5.0, cfg) == "hard"       # <8 但 ≥4
    assert compliance_levels(2.0, cfg) == "violation"


def test_compliance_levels_fine_scaled():
    cfg = AlgorithmConfig()
    # 精细目标 = 标准区间（缩放由 effort_bounds 负责，此处固定标准）
    assert compliance_levels(8.0, cfg) == "standard"
    assert compliance_levels(80.0, cfg) == "standard"


def test_effort_cv_metric():
    """碎片均衡度：工时变异系数 CV（对照实验发现 2：gd 块数盲区的补充指标）。"""
    from golden_ratio.experiment import effort_cv
    uniform = [40.0, 40.0, 40.0, 40.0]
    skewed = [10.0, 10.0, 70.0, 70.0]
    cv_u = effort_cv(uniform)
    cv_s = effort_cv(skewed)
    assert cv_u == 0.0                       # 均匀 → CV=0
    assert cv_s > cv_u                       # 失衡 → CV 更大
    assert 0.0 <= cv_s <= 1.0                # 归一化范围


def test_effort_cv_single_fragment():
    from golden_ratio.experiment import effort_cv
    assert effort_cv([42.0]) == 0.0          # 单碎片 CV=0
