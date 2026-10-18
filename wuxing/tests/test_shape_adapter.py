"""真测修复（REAL-1）：形状化适配器必须接受引擎 provider 的原生返回形态。

真测发现：`DeepSeekLlmProvider.chat`（无 tools）直接返回 **str**——适配器只认
`.text`/dict，取词为空 → `json.loads("")` 失败 → 真实形状化必然降级 mock。
本文件覆盖：str / 代码围栏 / 对象 / dict 四种返回形态。
"""
from wuxing.llm.shape_adapter import DefaultModelShapeLlm


class _StrProvider:
    def __init__(self, text):
        self._text = text

    def chat(self, messages, tools=None):
        return self._text


class _ObjProvider:
    def __init__(self, text):
        self._text = text

    def chat(self, messages, tools=None):
        class _R:
            pass

        r = _R()
        r.text = self._text
        return r


def test_chat_parses_plain_str_response():
    """真测主症：provider.chat 返回 str（DeepSeek/OpenAI 兼容无 tools 路径）。"""
    llm = DefaultModelShapeLlm(_StrProvider('{"nodes": [1]}'))
    assert llm._chat([{"role": "user", "content": "x"}]) == {"nodes": [1]}


def test_chat_strips_markdown_code_fence():
    """LLM 常见输出形态：```json 围栏——必须容错（否则一次失败即降级）。"""
    llm = DefaultModelShapeLlm(_StrProvider('```json\n{"ok": true}\n```'))
    assert llm._chat([{"role": "user", "content": "x"}]) == {"ok": True}


def test_chat_keeps_object_and_dict_response_shapes():
    """既有形态不回归：对象 .text / dict content。"""
    assert DefaultModelShapeLlm(_ObjProvider('{"a": 1}'))._chat([]) == {"a": 1}

    class _DictProvider:
        def chat(self, messages, tools=None):
            return {"content": '{"b": 2}'}

    assert DefaultModelShapeLlm(_DictProvider())._chat([]) == {"b": 2}
