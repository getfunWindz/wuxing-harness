from golden_ratio.keyify import extract_keys


def test_extract_keys_chinese():
    toks = extract_keys("开发一个带用户系统的网站", top_k=5)
    assert len(toks) >= 1
    assert all(t.lang == "zh" for t in toks)
    assert all(t.score > 0 for t in toks)


def test_extract_keys_english_lowercased():
    toks = extract_keys("Build a User System Website", top_k=5)
    assert all(t.lang == "en" for t in toks)
    assert all(t.word == t.word.lower() for t in toks)


def test_extract_keys_filters_stopwords():
    toks = extract_keys("the website and the user", top_k=10)
    words = [t.word for t in toks]
    assert "the" not in words and "and" not in words


def test_extract_keys_returns_top_k():
    toks = extract_keys("开发一个带用户系统的网站并完成数据库设计", top_k=3)
    assert len(toks) <= 3


def test_extract_keys_sorted_by_score_desc():
    toks = extract_keys("开发一个带用户系统的网站并完成数据库设计", top_k=5)
    scores = [t.score for t in toks]
    assert scores == sorted(scores, reverse=True)
