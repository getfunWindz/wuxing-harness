"""算法全部参数（决策记录：修订稿 Q2/Q10）——修改此文件即调参，不触碰算法代码。"""
from dataclasses import dataclass, field


@dataclass
class AlgorithmConfig:
    # §3.1.1① IFPUG 交付物复杂度权重（低/中/高）
    weight_text: dict = field(default_factory=lambda: {"low": 3, "mid": 4, "high": 6})
    weight_code: dict = field(default_factory=lambda: {"low": 4, "mid": 5, "high": 7})
    weight_data: dict = field(default_factory=lambda: {"low": 7, "mid": 10, "high": 15})
    weight_decision: dict = field(default_factory=lambda: {"low": 3, "mid": 4, "high": 6})

    # §3.1.1② 结构分锚点（圈复杂度分级）
    struct_depth_weight: float = 1.0
    struct_branch_weight: float = 0.5
    struct_denom: float = 50.0          # struct/50 归一化

    # §3.1.1③ 协调指数（COCOMO 开放度量 v2：领域熵分级 + 深依赖放大）
    coord_organic: float = 1.05
    coord_semidetached: float = 1.12
    coord_embedded: float = 1.20
    deep_dependency_threshold: int = 4   # 依赖深度 ≥ 4 视为深依赖
    coord_entropy_bins: tuple = (0.35, 0.80)   # 领域熵（绝对）分级：<0.35 Organic / 0.35~0.8 Semi / ≥0.8 Embedded
    # 阶段1-T1c C 臂分桶结构 key（替代开放主领域）：
    bucket_size_bands: tuple = (50.0, 150.0, 400.0)      # 规模层：total_effort 分档（4 层）
    bucket_entropy_bands: tuple = (0.35, 0.80)           # 熵层（与协调指数同构，3 层）

    # §3.1.1⑤ 难度分档（ds < b0→L1, < b1→L2, < b2→L3, < b3→L4, ≥ b3→L5）
    ds_bins: tuple = (2.0, 3.1, 4.4, 5.1)   # Q10 校准结果（24 任务样例集，错分率 16.7%→4.2%）

    # §7 快路径开关
    fast_path_max_difficulty: int = 2
    hierarchical_enabled: bool = True   # 分层分割总开关（Q11 A 臂置 False）

    # §3.2 参数合成 v2（阶段1 开放结构度量）：b(n) = α·b_结构 + β·b_交付物 + γ·b_L
    # 结构项零枚举：标签量(多领域/工种节点更复杂) + 下游影响面 + 工时占比
    alpha: float = 1 / 3
    beta: float = 1 / 3
    gamma: float = 1 / 3
    # 废弃（阶段1）：真 LLM 开放标签命中 0%，不再参与计算（保留字段防配置破坏）
    bias_domain: dict = field(default_factory=lambda: {"写作": -0.2, "编程": 0.2, "分析": 0.0, "数据": 0.1})
    bias_trade: dict = field(default_factory=lambda: {"创作": -0.2, "实现": 0.2, "评审": 0.0, "测试": 0.1, "管理": 0.0})
    # 交付物偏置（通用概念，真 LLM 100% 命中 → 查表保留）
    bias_deliverable: dict = field(default_factory=lambda: {"text": -0.2, "code": 0.2, "data": 0.1, "decision": 0.0})
    # 结构项权重与归一（b_struct ∈ [0,1]）
    struct_tag_weight: float = 0.4       # 标签量（domains+trades 数）
    struct_fanout_weight: float = 0.3    # 下游影响面（后代数占比）
    struct_effort_weight: float = 0.3    # 工时占比
    struct_tag_norm: float = 6.0         # 标签量归一参考（观测 max≈6）
    struct_scale: float = 1.0            # 结构项整体缩放（阶段1收尾：mock T40 局部回退的可调旋钮；阶段2真实标定后重标定）
    bias_level: dict = field(default_factory=lambda: {1: -0.4, 2: -0.2, 3: 0.0, 4: 0.2, 5: 0.4})
    gamma_softmax: float = 1.0          # §3.2 重要度放大系数

    # §3.2 确定性合并规则 v1（mock 阶段替代 LLM 原子性合并，真 LLM 阶段由 merge_nodes 替换）
    merge_window: int = 3                # 块节点数上限
    merge_drop_ratio: float = 0.55       # share 骤降封块阈值（阶段2-B微调定案：mega 0.0437→0.0187，余口径不变）
    merge_cross_group: bool = True       # C方案定案：组变更不再强制分块，cap 按评估口径（b_cap）

    # §3.3 黄金比阈值（Q1）
    theta_low: float = 0.382          # 黄金比下界（诊断语义：r<0.382=高价值密度碎片，不剥离；剥离决策仅用上界）
    theta_high: float = 0.618
    low_importance_threshold: float = 0.382   # 颜色权重低于此值视为低重要度
    rebalance_max_rounds: int = 3
    recursion_depth_limit: int = 2
    min_fragment_size: float = 0.5      # 碎片规模下限（share×S 计）
    sim_threshold: float = 0.7          # 碎片相似度阈值 μ

    # §3.4 Key 分词
    top_k_keys: int = 5
    stopwords: set = field(default_factory=lambda: {"的", "了", "和", "是", "在", "与", "及", "或",
                                                    "the", "a", "an", "of", "to", "in", "for", "and"})
    key_min_len: int = 2
    # §3.1.1③ 协调指数细化（实现期发现：原判定过宽会误伤多工种写作任务）
    main_domain_ratio_threshold: float = 0.6   # 主领域占比 ≥ 0.6 视为单领域主导（不跨域）
    cross_trade_min: int = 3                   # 工种数 ≥ 3 才算跨工种
# Q11 实验参数（2026-08-29 审查清理：曾重复定义两遍，保留一份）
    exp_success_threshold: float = 0.2   # 粒度偏差 ≤ 20% 记为一次成功切割
    exp_low_target: float = 0.6          # 成功率下限：低于则偏置向 0 微调
    exp_high_target: float = 0.9         # 成功率上限：高于则回弹半步
    exp_adapt_step: float = 0.08         # 微调步长（stage2-C臂优化定案：0.05→0.08，domain C −10.6%，guard无劣化）
    exp_ceiling_step: float = 0.01        # effort_ceiling 微调步长（小步长防过调，精细策略待讨论）
    exp_bias_clamp: float = 0.5          # 参数钳制区间
    exp_warmup_ratio: float = 0.6        # warm-up 集比例（C 臂学习；0.65 实测过调+test集过小，回退 0.6）
    exp_min_adapt_samples: int = 2        # 冷启动保护：统计样本 ≥2 才微调（T40 标定重标结果：3 过保守）
    exp_repeats: int = 5                 # 随机划分重复次数
    exp_coord_weight: float = 0.5        # 成本指标：协调权重（× 跨碎片依赖边数）
    exp_fragment_weight: float = 0.5     # 兼容旧字段（未使用，留待敏感性分析）
    # §3.2 工时语义（WBS 8/80 规则调研结论，2026-08 用户确认）
    effort_interval: tuple = (8.0, 80.0)      # 碎片目标工时区间 [8, 80]（1 天~2 周）
    effort_base_by_level: dict = field(default_factory=lambda: {1: 6, 2: 10, 3: 16, 4: 24, 5: 36})
    effort_trade_coef: dict = field(default_factory=lambda: {"创作": 0.9, "实现": 1.0, "测试": 0.8,
                                                              "分析": 1.1, "调研": 0.7, "管理": 0.8, "评审": 0.6})
    effort_ref_pts: float = 5.0               # 规模缩放参考点（mid text = 5）
    effort_ceiling: float = 1.15              # 工时上限系数（B微调v5.2定案：cap软目标 1.15=46h；钳制不破8/80上限80）
    # §3.2 动态窗口规则表（WBS 7×7 参考，难度档 → 每碎片最大节点数）
    merge_window_by_level: dict = field(default_factory=lambda: {1: 2, 2: 3, 3: 5, 4: 7, 5: 7})  # 用户决策 2/3/5/7
    exp_ceiling_step_mega: float = 0.05   # mega 任务（≥exp_mega_threshold）ceiling 微调步长
    exp_mega_threshold: float = 200.0     # 大任务判定阈值（总工时，h）
    exp_ema_decay: float = 0.9           # C 臂方向统计指数衰减（用户确认 EMA 方案，≈7 任务半衰期）
    # 8.2.2 融合式（v5 定案）：回退式（False）vs 加权融合（True）——v5 数据：融合式 ≥ 回退式 5/5 口径，默认 True
    exp_hybrid_mode: bool = True         # v5 默认融合式（mega ΔC-B 0→−0.0037）
    exp_hybrid_scale: float = 5.0        # 融合权重 w = min(1, seen/scale)
    # 优化方向2（anti-collapse 校准正则）：校准目标 = 错误率 + λ·塌缩惩罚（KL 分布/均匀）
    calib_collapse_lambda: float = 0.3
    # 优化方向1（ds 动态范围）：规模项权重（0.3·ln(1+节点数)）
    ds_scale_nodes: float = 0.0   # 实验定案：规模项对切割质量为负（见 difficulty 注释），默认关闭；可调
    # §5 三级合规门禁（用户决策：合规数值收紧，方案 3）
    hard_effort_interval: tuple = (4.0, 120.0)   # 硬合规（必须满足，防"不切"退化）
    exp_ceiling_clamp: float = 1.2               # C 臂 ceiling 钳制上限（1.5→1.2，对应 96h）
    m_level_cap: float = 80.0             # M 级上限（effort_bounds hi 的绝对上限；B 臂=40，默认=不收紧）

    # §3.2/§3.3/§3.4 LLM 调用点开关（Q6 护栏：默认关→确定性规则兜底；真 LLM 接入后开启）
    llm_merge_enabled: bool = False       # merge_nodes 替代确定性合并（须覆盖/不重复/收缩无环）
    llm_rebalance_enabled: bool = False   # rebalance_suggest 提供迁移建议（确定性规则兜底）
    llm_key_scoring_enabled: bool = False # score_keys 替代规则打分（失败回退规则分）
