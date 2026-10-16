#!/usr/bin/env python3
"""Render docs/hero.gif (~15s). Pillow is docs-only, not a runtime dep."""
from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "hero.gif")

BG = (16, 17, 20)
BAR = (36, 38, 44)
WHITE = (236, 238, 241)
DIM = (138, 144, 152)
GREEN = (80, 220, 140)
GOLD = (245, 197, 66)
CYAN = (110, 198, 230)
AMBER = (232, 176, 80)

W, H = 980, 560
PAD = 22


def font(size, mono=False, bold=False):
    if mono:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    elif bold:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    else:
        path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(path, size)


def window(title):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 36), fill=BAR)
    for i, c in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse((14 + i * 20, 10, 28 + i * 20, 24), fill=c)
    d.text((90, 9), title, font=font(15), fill=DIM)
    return img, d


def type_frames(base_lines, typed, color=CYAN, hold=2):
    """Yield frames while `typed` appears one chunk at a time."""
    frames = []
    acc = ""
    # type in 3–4 char chunks so ~15s total stays readable
    step = 8
    for i in range(0, len(typed) + 1, step):
        acc = typed[:i]
        frames.append(draw_term(base_lines + [("prompt", acc + "█")]))
    for _ in range(hold):
        frames.append(draw_term(base_lines + [("prompt", typed)]))
    return frames


def draw_term(rows):
    img, d = window("us-watchlist-alerts  v0.4.0  ·  FIXTURE DEMO (replayed, not live)")
    d.text((PAD, 48), "FIXTURE / REPLAYED — sample quotes, not a live feed. Never places trades.",
           font=font(14, bold=True), fill=GOLD)
    y = 82
    for kind, text in rows:
        fill = {
            "prompt": CYAN,
            "out": WHITE,
            "alert": GREEN,
            "dim": DIM,
            "banner": AMBER,
        }.get(kind, WHITE)
        # wrap long lines
        fnt = font(16, mono=True)
        d.text((PAD, y), text, font=fnt, fill=fill)
        y += 26
    return img


def main():
    frames = []
    # 1. empty-ish intro
    intro = [("dim", "After npx skills add  →  cd into the skill folder")]
    frames += [draw_term(intro + [("prompt", "█")])] * 2

    cmd1 = "python3 scripts/watchlist.py add AAPL --alert price_above:240"
    frames += type_frames(intro, cmd1, hold=2)

    after_add = intro + [
        ("prompt", cmd1),
        ("out", '{ "symbol": "AAPL", "alerts": [{ "type": "price_above", "value": 240 }] }'),
        ("dim", "watchlist.json written"),
    ]
    frames += [draw_term(after_add + [("prompt", "█")])] * 3

    cmd2 = "python3 scripts/alerts.py --watchlist watchlist.json --fixture examples/quotes-fixture.json"
    frames += type_frames(after_add, cmd2, hold=2)

    fired = after_add + [
        ("prompt", cmd2),
        ("banner", "[2026-10-15 18:30 ET] session=after — market closed, showing last regular close"),
        ("alert", "ALERT AAPL $241.50 is above $240.00"),
        ("dim", "latched — a second run stays silent until price rearms"),
    ]
    frames += [draw_term(fired)] * 8

    # one more beat: silent second run
    quiet = fired + [
        ("prompt", "python3 scripts/alerts.py --watchlist watchlist.json --fixture examples/quotes-fixture.json"),
        ("out", "[2026-10-15 18:30 ET] no new alerts"),
    ]
    frames += [draw_term(quiet)] * 5

    duration = 320  # ms
    frames[0].save(
        OUT, save_all=True, append_images=frames[1:],
        duration=duration, loop=0, optimize=True,
    )
    print(f"wrote {OUT}  frames={len(frames)}  ~{len(frames) * duration / 1000:.1f}s")


if __name__ == "__main__":
    main()
