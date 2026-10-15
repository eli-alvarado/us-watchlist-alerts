#!/usr/bin/env python3
"""Render side-by-side.png from the replay (Pillow is docs-only, not a runtime dep)."""
from __future__ import annotations
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "side-by-side.png")

BG = (17, 18, 21)
CARD = (26, 28, 33)
MUTED = (154, 160, 166)
WHITE = (240, 242, 245)
GOLD = (245, 197, 66)
GREEN = (61, 214, 140)
RED = (255, 93, 93)
LINE = (50, 54, 62)

W, H = 1400, 920


def font(size, bold=False):
    path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(path, size)


def rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def main():
    import replay
    report = replay.run()
    a = report["audit"]
    news_at = {}
    for e in a["events"]:
        news_at[e["now"]] = news_at.get(e["now"], 0) + 1
    ticks = []
    for w, wo in zip(report["with_skill"], report["without_skill"]):
        label = w["now"][11:16]
        if w["now"].startswith("2026-10-17"):
            label = "Sat"
        wo_n = len(wo["alerts"])
        news = news_at.get(w["now"], 0)
        ticks.append({
            "label": label,
            "with": len(w["alerts"]),
            "without": wo_n,
            "news": news,
            "repeats": wo_n - news,
            "after": bool(w.get("last_close")),
            "closed": bool(w.get("skipped")),
        })

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    d.text((48, 36), "Same 3 important moves caught.  58 extra pings avoided.", font=font(32, True), fill=GOLD)
    d.text((48, 84), "Replayed Thursday 2026-10-15. Same watch list both sides. Fewer pings is the point — not fewer discoveries.",
           font=font(18), fill=MUTED)

    # Two summary cards
    rounded(d, (48, 130, 680, 310), 18, CARD)
    rounded(d, (720, 130, 1352, 310), 18, CARD)
    d.rectangle((48, 130, 56, 310), fill=GREEN)
    d.rectangle((720, 130, 728, 310), fill=RED)
    d.text((80, 150), "WITH the skill", font=font(20, True), fill=GREEN)
    d.text((752, 150), "WITHOUT memory", font=font(20, True), fill=RED)
    d.text((80, 186), "3", font=font(64, True), fill=GREEN)
    d.text((752, 186), "61", font=font(64, True), fill=RED)
    d.text((170, 220), "pings  =  the 3 real events", font=font(20), fill=WHITE)
    d.text((880, 220), "pings  =  3 news  +  58 repeats", font=font(20), fill=WHITE)
    d.text((80, 266), "Then quiet: close, after hours, Saturday", font=font(16), fill=MUTED)
    d.text((752, 266), "Same two headlines every 15 minutes", font=font(16), fill=MUTED)

    # Timeline
    d.text((48, 340), "One day, checked every 15 minutes", font=font(22, True), fill=WHITE)
    d.text((48, 374), "Each dot is a ping. Green = first time that news was sent. Gray-red = the same condition again.",
           font=font(16), fill=MUTED)

    x0, x1 = 170, 1340
    n = len(ticks)
    gap = (x1 - x0) / max(n - 1, 1)

    def x_at(i):
        return x0 + i * gap

    # section bands
    first_after = next((i for i, t in enumerate(ticks) if t["after"]), n - 1)
    first_sat = next((i for i, t in enumerate(ticks) if t["closed"]), n - 1)
    y_band_top, y_band_bot = 420, 780
    rounded(d, (x_at(0) - 18, y_band_top, x_at(first_after) - gap / 2, y_band_bot), 12, (22, 24, 28))
    rounded(d, (x_at(first_after) - gap / 2, y_band_top, x_at(first_sat) - gap / 2, y_band_bot), 12, (28, 24, 22))
    rounded(d, (x_at(first_sat) - gap / 2, y_band_top, x_at(n - 1) + 18, y_band_bot), 12, (28, 22, 24))
    d.text((x_at(0), 432), "Regular hours", font=font(13, True), fill=MUTED)
    d.text((x_at(first_after), 432), "After the bell", font=font(13, True), fill=MUTED)
    d.text((x_at(first_sat) - 10, 432), "Sat", font=font(13, True), fill=MUTED)

    def row(y, title, color, kind):
        d.text((48, y - 8), title, font=font(16, True), fill=color)
        for i, t in enumerate(ticks):
            cx = x_at(i)
            if kind == "with":
                news, repeats = t["with"], 0
            else:
                news, repeats = t["news"], t["repeats"]
            count = news + repeats
            if count == 0:
                d.ellipse((cx - 4, y + 28, cx + 4, y + 36), fill=LINE)
                continue
            dots = [GREEN] * news + [RED] * repeats
            for k, fill in enumerate(dots):
                cy = y + 32 - k * 16
                r = 7
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
        for i, t in enumerate(ticks):
            if t["label"] in ("09:30", "09:45", "12:00", "16:00", "Sat"):
                d.text((x_at(i) - 16, y + 52), t["label"], font=font(12), fill=MUTED)

    row(500, "With skill", GREEN, "with")
    row(640, "Without", RED, "without")

    d.text((48, 820),
           f"Audit: {a['distinct_events']} distinct events, all also sent by the skill.  "
           f"{a['repeats']} repeats  ({a['repeats_regular_hours']} during the session,  "
           f"{a['repeats_after_hours']} after 4pm,  {a['repeats_closed_weekend']} Saturday).  "
           "Skill missed none.",
           font=font(16), fill=WHITE)
    d.text((48, 856), "REPLAYED Yahoo 15-minute bars — not a live feed.  AAPL > $340 · NVDA session low −3% · NVDA last print −3%.",
           font=font(14), fill=MUTED)

    img.save(OUT, "PNG")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
