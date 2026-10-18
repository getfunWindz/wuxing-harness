"""pywebview 薄窗（壳 P1 · B5）——惰性导入（CI/测试不依赖 pywebview）。"""

import logging

logger = logging.getLogger(__name__)


class WindowUnavailable(RuntimeError):
    """pywebview 不可用（未安装/无 GUI 环境）——调用方回退浏览器 URL。"""


def _import_webview():
    try:
        import webview
    except Exception as exc:  # ImportError/平台异常统一转语义异常
        raise WindowUnavailable(f"pywebview 不可用：{exc}") from exc
    return webview


def open_window(url: str, title: str = "WUXING Harness") -> None:
    """打开桌面窗口（阻塞直到关闭；关闭不影响服务进程）。"""
    webview = _import_webview()
    # 会话导出（Blob + a[download]）依赖下载能力——pywebview 默认关闭，
    # 桌面承载下会表现为「导出按钮无任何反应」（用户反馈 2026-09-14）。
    try:
        webview.settings["ALLOW_DOWNLOADS"] = True
    except Exception as exc:
        logger.debug("pywebview 下载开关设置失败（不阻断）：%s", exc)
    webview.create_window(title, url)
    webview.start()
