#!/usr/bin/env python3
"""生成 WUXING iOS AppIcon 与颜色资源（确定性、无外部 SVG 依赖）。

图形来源：壳前端 favicon（120×120 viewBox）——墨色笔触 + 朱砂梅花。
输出：WuxingShell/Resources/Assets.xcassets/{AppIcon.appiconset,LaunchBackground.colorset,AccentColor.colorset}
"""
from __future__ import annotations

import json
import math
import pathlib

from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parents[1]
ASSETS = ROOT / "WuxingShell" / "Resources" / "Assets.xcassets"
ICONSET = ASSETS / "AppIcon.appiconset"

PAPER = (244, 241, 234)
INK = (35, 33, 30)
CINNABAR = (165, 63, 51)

VIEW = 120.0
MASTER = 1024
SS = 4  # supersampling
SCALE = MASTER / VIEW * SS


def cubic(p0, p1, p2, p3, steps=80):
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1.0 - t
        x = u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0]
        y = u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]
        out.append((x * SCALE, y * SCALE))
    return out


def draw_stroke(draw, points, width):
    w = max(1, int(round(width * SCALE)))
    # 用密集圆点盖章（而不是单条 polyline）：避免粗线 joint 的白色缝隙
    r = w / 2.0
    for x, y in points:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=INK)


def make_master() -> Image.Image:
    size = MASTER * SS
    img = Image.new("RGB", (size, size), PAPER)
    draw = ImageDraw.Draw(img)

    # 主笔触：favicon 的三段三次贝塞尔
    seg1 = cubic((10, 112), (28, 100), (34, 88), (48, 78))
    seg2 = cubic((48, 78), (60, 69), (60, 59), (70, 50))
    seg3 = cubic((70, 50), (80, 41), (92, 36), (108, 32))
    draw_stroke(draw, seg1 + seg2[1:] + seg3[1:], 7.0)

    # 副笔触
    draw_stroke(draw, cubic((12, 112), (24, 105), (30, 98), (36, 88)), 4.0)

    # 朱砂梅花：五瓣绕中心 (84,44) 旋转
    cx, cy = 84 * SCALE, 44 * SCALE
    rx, ry = 7.2 * SCALE, 10.0 * SCALE
    offset = 14.0 * SCALE
    petals = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pdraw = ImageDraw.Draw(petals)
    for i in range(5):
        layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer)
        pcx, pcy = cx, cy - offset
        ldraw.ellipse((pcx - rx, pcy - ry, pcx + rx, pcy + ry), fill=CINNABAR + (255,))
        layer = layer.rotate(-72.0 * i, resample=Image.Resampling.BICUBIC, center=(cx, cy))
        petals = Image.alpha_composite(petals, layer)
    img = Image.alpha_composite(img.convert("RGBA"), petals).convert("RGB")

    # 花心 + 落点
    draw = ImageDraw.Draw(img)
    r = 2.6 * SCALE
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=INK)
    dx, dy, dr = 26 * SCALE, 70 * SCALE, 5.0 * SCALE
    draw.ellipse((dx - dr, dy - dr, dx + dr, dy + dr), fill=CINNABAR)

    return img.resize((MASTER, MASTER), Image.Resampling.LANCZOS)


def write_json(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    ICONSET.mkdir(parents=True, exist_ok=True)
    write_json(ASSETS / "Contents.json", {"info": {"author": "xcode", "version": 1}})

    master = make_master()
    # (filename, pixel size, idiom, scale, point size)
    entries = [
        ("icon-40.png", 40, "iphone", "2x", "20x20"),
        ("icon-60.png", 60, "iphone", "3x", "20x20"),
        ("icon-58.png", 58, "iphone", "2x", "29x29"),
        ("icon-87.png", 87, "iphone", "3x", "29x29"),
        ("icon-80.png", 80, "iphone", "2x", "40x40"),
        ("icon-120-40x3.png", 120, "iphone", "3x", "40x40"),
        ("icon-120-60x2.png", 120, "iphone", "2x", "60x60"),
        ("icon-180.png", 180, "iphone", "3x", "60x60"),
        ("icon-1024.png", 1024, "ios-marketing", "1x", "1024x1024"),
    ]
    written = set()
    for filename, px, _, _, _ in entries:
        if filename in written:
            continue
        master.resize((px, px), Image.Resampling.LANCZOS).save(ICONSET / filename, "PNG")
        written.add(filename)

    write_json(
        ICONSET / "Contents.json",
        {
            "images": [
                {"filename": f, "idiom": idiom, "scale": scale, "size": size}
                for f, _, idiom, scale, size in entries
            ],
            "info": {"author": "xcode", "version": 1},
        },
    )

    write_json(
        ASSETS / "LaunchBackground.colorset" / "Contents.json",
        {
            "colors": [
                {
                    "color": {
                        "color-space": "srgb",
                        "components": {
                            "alpha": "1.000",
                            "blue": "0.918",
                            "green": "0.945",
                            "red": "0.957",
                        },
                    },
                    "idiom": "universal",
                }
            ],
            "info": {"author": "xcode", "version": 1},
        },
    )
    write_json(
        ASSETS / "AccentColor.colorset" / "Contents.json",
        {
            "colors": [
                {
                    "color": {
                        "color-space": "srgb",
                        "components": {
                            "alpha": "1.000",
                            "blue": "0.200",
                            "green": "0.247",
                            "red": "0.647",
                        },
                    },
                    "idiom": "universal",
                }
            ],
            "info": {"author": "xcode", "version": 1},
        },
    )
    print(f"wrote {len(written)} icon files to {ICONSET}")


if __name__ == "__main__":
    main()
