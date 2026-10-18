"""任务 Key 分词（修订稿 §3.4）：语言检测 → 分词 → 停用词过滤 → 打分 → top-K。"""
import re

import jieba

from golden_ratio.models import KeyToken

_EN_RE = re.compile(r"[a-zA-Z]+")


def _detect_lang(text):
    zh = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    en = len(_EN_RE.findall(text))
    if zh == 0 and en == 0:
        return "none"
    return "zh" if zh >= en else "en"


def extract_keys(text, cfg=None, top_k=None, llm=None):
    """
    llm 参数：llm_key_scoring_enabled 且 llm 提供时，用 score_keys 的分数替换规则分数
    （Mock/真 LLM 同契约：{word: score}）；LLM 打分异常时回退规则分数。
    """
    if cfg is None:
        from golden_ratio.config import AlgorithmConfig
        cfg = AlgorithmConfig()
    top_k = top_k or cfg.top_k_keys
    lang = _detect_lang(text)
    if lang == "zh":
        raw = [w for w in jieba.lcut(text)
               if len(w) >= cfg.key_min_len and w not in cfg.stopwords]
        raw = [w for w in raw if not re.fullmatch(r"\W+", w)]
    else:
        raw = [w.lower() for w in _EN_RE.findall(text)]
        raw = [w for w in raw if len(w) >= cfg.key_min_len and w not in cfg.stopwords]

    # 打分：TF × 长度惩罚（§3.4 步骤4 退化方案；llm 可选替代）
    freq = {}
    for w in raw:
        freq[w] = freq.get(w, 0.0) + 1.0
    scored = sorted(freq.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    cand = scored[:top_k]
    if llm is not None and getattr(cfg, "llm_key_scoring_enabled", False):
        try:
            llm_scores = llm.score_keys([w for w, _ in cand]) or {}
            return [KeyToken(word=w, lang=lang,
                             score=round(float(llm_scores.get(w, cnt)), 3))
                    for w, cnt in cand]
        except Exception:
            pass                                # LLM 打分失败 → 规则分数兜底
    return [KeyToken(word=w, lang=lang, score=round(1.0 * cnt, 3))
            for w, cnt in cand]
