"""会话标题（2026-09-19 用户裁决）：大模型对第一次对话内容总结取名。

- `first_user_text`：从会话文件提取首条用户内容（兼容三种行形状：
  单条 {role,content} / B 模式轮次 {user_text} / seed 行 {messages:[...]}）；
- `sanitize_title`：单行、去引号标点、限长；
- `generate_title`：调 LLM（chat 返回带 .text 或 dict）——失败返回空串（降级，UI 回退文件名）；
- 标题缓存：`<workdir>/.wuxing/session-titles.json`（不重命名文件——append 路径稳定）。
"""
import json

from wuxing.shell.web import session_titles


class _StubLlm:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append(messages)
        return type("Res", (), {"text": self.text})()


def test_first_user_text_三种行形状(tmp_path):
    p = tmp_path / "conversation-x.jsonl"
    p.write_text(
        '{"role":"user","content":"生成一份变更摘要"}\n'
        '{"round":1,"user_text":"第二轮"}\n',
        encoding="utf-8")
    assert session_titles.first_user_text(p) == "生成一份变更摘要"
    p2 = tmp_path / "conversation-y.jsonl"
    p2.write_text(
        '{"round":0,"state":"seed","messages":[{"role":"system","content":"s"},'
        '{"role":"user","content":"修复登录"}]}\n',
        encoding="utf-8")
    assert session_titles.first_user_text(p2) == "修复登录"
    assert session_titles.first_user_text(tmp_path / "missing.jsonl") == ""


def test_sanitize_title(tmp_path):
    assert session_titles.sanitize_title('  "变更摘要会话"  ') == "变更摘要会话"
    assert session_titles.sanitize_title("第一行\n第二行") == "第一行"
    assert session_titles.sanitize_title("a" * 40).__len__() <= 16
    assert session_titles.sanitize_title("") == ""
    assert session_titles.sanitize_title("含<非法>:字符/的标题") == "含非法字符的标题"


def test_generate_title_调模型并限长(tmp_path):
    p = tmp_path / "conversation-z.jsonl"
    p.write_text('{"role":"user","content":"把 README 的安装章节改成三步"}\n',
                 encoding="utf-8")
    llm = _StubLlm("README 安装三步改写")
    title = session_titles.generate_title(p, llm)
    assert title == "README 安装三步改写"
    assert llm.calls and "README" in llm.calls[0][-1]["content"]
    # 失败降级：LLM 抛错 → 空串（不阻断列表）
    class _Boom:
        def chat(self, messages, tools=None):
            raise RuntimeError("no key")
    assert session_titles.generate_title(p, _Boom()) == ""


def test_titles_cache_读写(tmp_path):
    key = session_titles.titles_path(tmp_path)
    assert key.name == "session-titles.json"
    assert session_titles.load_titles(tmp_path) == {}
    session_titles.save_title(tmp_path, "conversation-1.jsonl", "变更摘要")
    assert session_titles.load_titles(tmp_path) == {"conversation-1.jsonl": "变更摘要"}
    raw = json.loads(key.read_text(encoding="utf-8"))
    assert raw["conversation-1.jsonl"] == "变更摘要"
