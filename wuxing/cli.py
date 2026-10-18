"""headless CLI（run/resume/chat/tree + shell 子命令）。"""
import argparse
import json
import os
import pathlib

from wuxing.engine import Engine


def main():
    p = argparse.ArgumentParser(prog="wuxing")
    # 默认入口：不输子命令 → 启动壳（浏览器承载：确保后台服务 + 拉起网页）
    sub = p.add_subparsers(dest="cmd", required=False)
    run = sub.add_parser("run", help="运行任务（headless）")
    run.add_argument("task_text")
    run.add_argument("--workdir", default=None)
    run.add_argument("--auto", action="store_true", help="全自动（跳过人工确认——CI 场景）")
    resume = sub.add_parser("resume", help="断点续跑（task_state.json）")
    resume.add_argument("--workdir", default=None)
    resume.add_argument("--auto", action="store_true", help="全自动（跳过人工确认——CI 场景）")
    tree = sub.add_parser("tree", help="会话树（任务历史树——provenance 聚合）")
    tree.add_argument("--workdir", default=None)
    branch = sub.add_parser("branch", help="对话分支（从既有会话轮派生新会话——G1）")
    branch.add_argument("--workdir", default=None)
    branch.add_argument("--session", required=True, help="来源会话名（.wuxing/ 下）")
    branch.add_argument("--from-round", type=int, required=True,
                        dest="from_round")
    branch.add_argument("--mode", default="redo", choices=("redo", "continue"))
    branch.add_argument("--summary", default="mech",
                        choices=("mech", "llm", "none"))
    branch.add_argument("--focus", default="")
    tickets_cmd = sub.add_parser("tickets", help="实施票据列表（含认领状态——G8）")
    tickets_cmd.add_argument("--workdir", default=None)
    ext = sub.add_parser("ext", help="扩展命令（E2-3）")
    ext_sub = ext.add_subparsers(dest="action", required=True)
    ext_list = ext_sub.add_parser("list", help="列出扩展命令")
    ext_list.add_argument("--workdir", default=None)
    ext_run = ext_sub.add_parser("run", help="执行扩展命令")
    ext_run.add_argument("name")
    ext_run.add_argument("--args", default="{}", help="JSON 对象参数")
    ext_run.add_argument("--workdir", default=None)
    skills_cmd = sub.add_parser("skills", help="技能运维（近义报告等）")
    skills_sub = skills_cmd.add_subparsers(dest="skills_action", required=True)
    near_dup = skills_sub.add_parser(
        "near-dup", help="近义检测报告（只报告，不自动合并/不修改）")
    near_dup.add_argument("--json", action="store_true", help="输出 JSON")
    near_dup.add_argument("--dir", default=None,
                          help="技能目录（默认 ~/.wuxing/skills）")
    chat = sub.add_parser("chat", help="会话式交互（B 模式：同一任务内多轮——"
                                          "历史前缀累积、交付物跨轮复用）",
                          description="会话式交互（B 模式：同一任务内多轮——历史前缀累积、"
                                      "交付物跨轮复用；每行输入=一轮，EOF//exit 退出）")
    chat.add_argument("--workdir", default=None)
    chat.add_argument("--auto", action="store_true",
                      help="全自动（跳过人工确认——CI 场景）")
    shell = sub.add_parser("shell", help="Web 壳（serve/app——浏览器与桌面双承载）")
    shell_sub = shell.add_subparsers(dest="action", required=True)
    shell_serve = shell_sub.add_parser("serve", help="启动本地服务（常驻；浏览器访问）")
    shell_serve.add_argument("--port", type=int, default=8723)
    shell_serve.add_argument(
        "--host", default=None,
        help="绑定地址（默认 127.0.0.60 环回；非环回=远程模式，需 WUXING_SHELL_TOKEN）")
    shell_app = shell_sub.add_parser("app", help="桌面窗口（pywebview 薄壳）")
    shell_app.add_argument("--port", type=int, default=8723)
    args = p.parse_args()
    if args.cmd is None:
        # 默认：壳（浏览器承载）——确保后台服务并拉起网页；
        # 桌面应用承载由后续 Electron 壳承担（pywebview 不再是默认路径，
        # 仅保留为显式 `wuxing shell app`）。
        from wuxing.shell.web.launcher import run_web
        return run_web()
    if args.cmd == "shell":
        from wuxing.shell.web.launcher import run_app, run_serve
        if args.action == "serve":
            return run_serve(port=args.port, host=args.host)
        return run_app(port=args.port)
    if args.cmd == "chat":
        # B 模式会话循环：每行输入 = 一轮（EOF 退出）；轮次持久化 conversation.jsonl
        eng = Engine(workdir=args.workdir, auto_confirm=args.auto)
        sess = eng.start_session()
        try:
            while True:
                try:
                    line = input("wuxing> ")
                except EOFError:
                    break
                line = line.strip()
                if not line or line in ("/exit", "/quit"):
                    break
                res = sess.send(line)
                print(res.report)
                print(f"status={res.status} round={sess.round_no}")
        except KeyboardInterrupt:
            # 交互式会话 Ctrl+C：安静退出 REPL（不打印堆栈）
            pass
        return
    if args.cmd == "tree":
        from wuxing.session_tree import build_task_tree
        wd = pathlib.Path(args.workdir) if args.workdir else pathlib.Path.cwd()
        tree_root = build_task_tree(wd)
        if tree_root is None:
            print("（无任务历史：该工作区没有 task_state.json）")
        else:
            print("\n".join(tree_root.to_lines()))
        return
    if args.cmd == "branch":
        eng = Engine(workdir=args.workdir)
        try:
            res = eng.branch_conversation(args.session, args.from_round,
                                          mode=args.mode,
                                          summary=args.summary,
                                          focus=args.focus)
        except ValueError as e:
            print(f"error: {e}")
            return 2
        print(f"新会话：{res['session']}")
        print(f"模式：{res['mode']} · 分支自 第 {res['from_round']} 轮 · "
              f"摘要：{res['summary_mode']}"
              f"（请求 {res['summary_mode_requested']}）")
        if res.get("redo_text"):
            print(f"回填文本：{res['redo_text']}")
        if res.get("summary"):
            print("\n" + res["summary"])
        return 0
    if args.cmd == "tickets":
        from wuxing import tickets as _tickets
        wd = pathlib.Path(args.workdir) if args.workdir else pathlib.Path.cwd()
        rows = _tickets.load(wd)
        if not rows:
            print("（无票据：该工作区没有 .wuxing/tickets.jsonl）")
            return 0
        for t in rows:
            claimed = str(t.get("claimed_by") or "")
            suffix = f" · 认领：{claimed}" if claimed else ""
            print(f"{t.get('id')} [{t.get('status')}] "
                  f"{t.get('title') or ''}{suffix}")
        return 0
    if args.cmd == "ext":
        eng = Engine(workdir=args.workdir)
        if args.action == "list":
            rows = eng.list_commands()
            if not rows:
                print("（无扩展命令）")
            for c in rows:
                print(f"{c['name']} [{c['source']}] {c['description']}")
            return 0
        try:
            run_args = json.loads(args.args or "{}")
        except ValueError:
            print("error: --args 需要 JSON 对象")
            return 2
        if not isinstance(run_args, dict):
            print("error: --args 需要 JSON 对象")
            return 2
        try:
            res = eng.run_command(args.name, run_args)
        except KeyError as exc:
            print(f"error: {exc}")
            return 2
        print(res.get("text") or res.get("error") or json.dumps(
            res, ensure_ascii=False))
        return 0 if res.get("status") == "ok" else 1
    if args.cmd == "skills":
        from wuxing import skill_curator
        sdir = (pathlib.Path(args.dir) if args.dir
                else pathlib.Path(os.path.expanduser("~")) / ".wuxing" / "skills")
        report = skill_curator.near_duplicate_report(sdir)
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(skill_curator.format_near_duplicate_report(report))
        return 0
    if args.cmd == "run":
        eng = Engine(workdir=args.workdir, auto_confirm=args.auto)
        result = eng.run_task(args.task_text)
        print(result.report)
        print(f"\nstatus={result.status}")
    elif args.cmd == "resume":
        eng = Engine(workdir=args.workdir, auto_confirm=args.auto)
        result = eng.resume_task()
        print(result.report)
        print(f"\nstatus={result.status}")

if __name__ == "__main__":
    raise SystemExit(main() or 0)
