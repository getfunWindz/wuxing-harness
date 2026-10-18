"""G8-M3 E2E 种子：地图 + 设计态 + 已认领 ready 票据（陈旧展示与提交 409）。

用法：python e2e/shell/g8_seed.py <workdir> [holder]
- holder 缺省 ghost-session：认领者无活动 run → annotate_claims 标 stale（陈旧展示）；
- 地图 + 规格 + ready 票据齐备 → session_plan 判 execution（提交期认领路径触发）。
"""
import pathlib
import sys
import time


def main():
    wd = pathlib.Path(sys.argv[1]).resolve()
    holder = sys.argv[2] if len(sys.argv) > 2 else "ghost-session"
    wd.mkdir(parents=True, exist_ok=True)
    from wuxing import design_state, map_doc, tickets

    map_doc.write_sections(
        wd, project="G8 演示", destination="验证并行与认领",
        route="- [ ] 切片一\n- [ ] 切片二",
        decisions="2026-09-27 · 种子 · 认领冲突演示 · E2E",
        fog="无", out_of_scope="无")
    design_state.save(wd, {
        "session": "", "round": 1, "phase": "map", "questions": [],
        "facts": ["E2E 种子"],
        "map_path": "WUXING.md",
        "map_hash": map_doc.file_hash(map_doc.map_path(wd)),
        "spec_path": ".wuxing/specs/demo.md", "spec_slug": "demo",
        "spec_hash": "seed",
    })
    specs = wd / ".wuxing" / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    (specs / "demo.md").write_text("# 演示规格\n", encoding="utf-8")

    existing = tickets.load(wd)
    t1 = next((t for t in existing if t.get("title") == "切片一"), None)
    if t1 is None:
        t1 = tickets.create(wd, title="切片一", goal="A",
                            acceptance=["A 可用"], spec="demo")
        tickets.update(wd, t1["id"], {"status": "ready"})
        tickets.claim_many(wd, [t1["id"]], by=holder)
    print(f"seeded {wd} holder={holder} ticket={t1['id']} at={time.time():.0f}")


if __name__ == "__main__":
    main()
