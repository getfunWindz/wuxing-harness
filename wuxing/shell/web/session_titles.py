"""会话标题（用户裁决 2026-09-19）：大模型对第一次对话内容总结取名。

不重命名会话文件（B 模式 append 路径稳定）——标题存 sidecar：
`<workdir>/.wuxing/session-titles.json`（name → title）。
失败一律降级（空串 → UI 回退文件名），不阻断列表。
"""
import json
import logging
import pathlib
import re

logger = logging.getLogger(__name__)

_TITLE_LIMIT = 16
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_QUOTES = "“”\"'‘’「」『』《》"
_TRIM = "。.、，,；;：:！!？?~—·- 　"

TITLE_PROMPT = (
    "你是归档助手。为下面这段用户与编程助手的会话起一个简短的中文标题，"
    "不超过 12 个字，不要标点、引号或句号，直接输出标题本身。"
)


def titles_path(workdir) -> pathlib.Path:
    return pathlib.Path(workdir) / ".wuxing" / "session-titles.json"


def load_titles(workdir) -> dict:
    try:
        data = json.loads(titles_path(workdir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()
            if isinstance(v, str) and v.strip()}


def save_title(workdir, name: str, title: str) -> None:
    """写缓存（读-改-写；失败静默——标题缓存不是生命线）。"""
    target = titles_path(workdir)
    data = load_titles(workdir)
    data[str(name)] = str(title)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(target)
    except OSError as exc:
        logger.debug("会话标题侧车写入失败（不阻断）：%s", exc)


def _rows(path) -> list:
    try:
        text = pathlib.Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def first_user_text(path) -> str:
    """首条用户内容（兼容三种行形状：{role,content} / {user_text} / {messages:[…]}）。"""
    for row in _rows(path):
        if row.get("role") == "user" and str(row.get("content") or "").strip():
            return str(row["content"]).strip()
        if str(row.get("user_text") or "").strip():
            return str(row["user_text"]).strip()
        messages = row.get("messages")
        if isinstance(messages, list):
            for msg in messages:
                if (isinstance(msg, dict) and msg.get("role") == "user"
                        and str(msg.get("content") or "").strip()):
                    return str(msg["content"]).strip()
    return ""


def sanitize_title(raw: str, limit: int = _TITLE_LIMIT) -> str:
    text = str(raw or "")
    if text.strip() == "":
        return ""
    text = text.splitlines()[0]
    text = _ILLEGAL.sub("", text)
    text = "".join(ch for ch in text if ch not in _QUOTES)
    text = " ".join(text.split()).strip(_TRIM)
    return text[:limit]


def generate_title(path, llm) -> str:
    """LLM 总结首轮 → 标题；无内容/失败 → 空串（调用方回退）。"""
    text = first_user_text(path)
    if text == "":
        return ""
    messages = [
        {"role": "system", "content": TITLE_PROMPT},
        {"role": "user", "content": text[:2000]},
    ]
    try:
        out = llm.chat(messages)
    except Exception:
        # 标题模型调用失败 → 空串（标题属优化面，失败不阻断主链）
        return ""
    raw = getattr(out, "text", None)
    if raw is None and isinstance(out, dict):
        raw = out.get("content") or out.get("text") or ""
    return sanitize_title(str(raw or ""))
