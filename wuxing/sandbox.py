"""沙箱策略（R3-2 原生档 + BOX-2 外置容器档 · 2026-09-27 用户裁决）。

形态：原生档（默认）与**外置容器档**（用户配置命令模板——Docker/Podman/WSL 等自担）。

原生档（默认）：
- 命令在工作区内执行（cwd = 工作区；工具层文件操作已限定工作区）；
- 敏感环境变量剥离（bash 白名单——API key/代理类不传入子进程）；
- 网络：**允许**；完整性：**partial**——原生强制能力有限，诚实上报。

外置容器档（显式开启，需命令模板）：
- bash 执行渲染模板后交给用户容器运行时（{workdir} + {cmd}/{cmd_b64}）；
- 失败可见（错误前缀 ``container:``），**绝不静默回退**原生执行；
- 完整性：**container**（隔离强度由用户运行时与镜像决定——文档明示）；
- 网络：由模板/运行时决定（策略行标 `runtime-controlled`）——推荐模板
  `--network none` 默断网，需联网时显式放行（CU5）。
"""
import base64
import hashlib

INTEGRITY_NATIVE = "partial"
INTEGRITY_CONTAINER = "container"
NETWORK_POLICY = "allowed"              # 原生档：网络允许（如实上报，不虚标）
NETWORK_POLICY_CONTAINER = "runtime-controlled"   # 容器档：由模板/运行时决定（CU5）
MODES = ("native", "container")


def validate_container_template(template: str) -> None:
    """模板占位符校验（不合规 → ValueError——配置层 loud，不静默）。"""
    if not isinstance(template, str) or template.strip() == "":
        raise ValueError("容器模板为空")
    if "{workdir}" not in template:
        raise ValueError("容器模板缺 {workdir} 占位符")
    if "{cmd}" not in template and "{cmd_b64}" not in template:
        raise ValueError("容器模板需含 {cmd} 或 {cmd_b64} 占位符（推荐 {cmd_b64}）")


def render_container_command(template: str, workdir, command: str) -> str:
    """渲染容器命令模板——{workdir} 逐字替换；{cmd_b64} 推荐（任意引号/换行安全）。"""
    validate_container_template(template)
    b64 = base64.b64encode(str(command).encode("utf-8")).decode("ascii")
    return (template.replace("{workdir}", str(workdir))
                    .replace("{cmd_b64}", b64)
                    .replace("{cmd}", str(command)))


def template_hash(template: str) -> str:
    """模板内容指纹（trace/装配可见——短摘要，不记模板全文）。"""
    return hashlib.sha256(str(template or "").encode("utf-8")).hexdigest()[:12]


def policy_line(enabled: bool, workdir, mode: str = "native",
                template: str = "") -> str:
    """模型可见策略行（字节稳定——同状态两次一致；KV cache 友好）。"""
    if mode == "container":
        return (f"sandbox: on (mode: container, integrity: {INTEGRITY_CONTAINER}, "
                f"template: {template_hash(template)}, "
                f"network: {NETWORK_POLICY_CONTAINER}, "
                f"workdir: {workdir})")
    if not enabled:
        return "sandbox: off"
    return (f"sandbox: on (integrity: {INTEGRITY_NATIVE}, "
            f"network: {NETWORK_POLICY}, workdir: {workdir})")


def describe(enabled: bool, mode: str = "native") -> str:
    """工具描述用一行说明（人类可读）。"""
    if mode == "container":
        return ("沙箱: 外置容器档——bash 执行路由到用户容器运行时"
                "（模板自定义；失败可见不回退）")
    if not enabled:
        return "沙箱: 关闭——继承本机环境"
    return ("沙箱: 开启——工作目录限定工作区 + 敏感环境变量剥离"
            "（网络允许；完整性 partial）")
