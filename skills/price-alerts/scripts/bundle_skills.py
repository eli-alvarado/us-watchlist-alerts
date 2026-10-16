"""Copy root scripts + holiday data into each skill folder so `npx skills add` ships a runner."""
from __future__ import annotations
import os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = ("price-alerts", "watchlist-brief", "watchlist-manager")
PY_FILES = ("alerts.py", "brief.py", "indicators.py", "market_calendar.py",
            "notify.py", "quotes.py", "watchlist.py", "bundle_skills.py",
            "quickstart.py", "schedule.py")


def bundle():
    src_scripts = os.path.join(ROOT, "scripts")
    src_data = os.path.join(ROOT, "data", "holidays_overrides.json")
    src_ex = os.path.join(ROOT, "examples", "watchlist.json")
    src_fx = os.path.join(ROOT, "examples", "quotes-fixture.json")
    copied = []
    for name in SKILLS:
        dest = os.path.join(ROOT, "skills", name, "scripts")
        os.makedirs(dest, exist_ok=True)
        for fn in PY_FILES:
            shutil.copy2(os.path.join(src_scripts, fn), os.path.join(dest, fn))
            copied.append(os.path.join("skills", name, "scripts", fn))
        data_dest = os.path.join(ROOT, "skills", name, "data")
        os.makedirs(data_dest, exist_ok=True)
        shutil.copy2(src_data, os.path.join(data_dest, "holidays_overrides.json"))
        ex_dest = os.path.join(ROOT, "skills", name, "examples")
        os.makedirs(ex_dest, exist_ok=True)
        shutil.copy2(src_ex, os.path.join(ex_dest, "watchlist.json"))
        if os.path.exists(src_fx):
            shutil.copy2(src_fx, os.path.join(ex_dest, "quotes-fixture.json"))
    return copied


if __name__ == "__main__":
    for p in bundle():
        print(p)
    sys.exit(0)
