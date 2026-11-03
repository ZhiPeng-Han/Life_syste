"""每周菜单与购物清单（L2：系统给默认菜单，你可以换）。"""

import random
from datetime import date, timedelta

from . import config, db

WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def week_start(on: date | None = None) -> date:
    on = on or date.today()
    return on - timedelta(days=on.weekday())


def plan_week(conn, on: date | None = None, regenerate: bool = False) -> dict:
    start = week_start(on)
    key = f"menu:{start.isoformat()}"
    saved = db.get_meta(conn, key)
    if saved and not regenerate:
        return saved
    recipes = [r for r in config.recipes() if r.get("minutes", 0) > 0]
    if not recipes:
        return {"week": start.isoformat(), "days": [], "shopping": []}
    last = db.get_meta(conn, f"menu:{(start - timedelta(days=7)).isoformat()}", {}) or {}
    last_names = {d["dish"] for d in last.get("days", [])}
    rng = random.Random(start.toordinal() + (random.randint(1, 10**6) if regenerate else 0))

    def weight(r):
        w = 1.0 + (1.0 if r.get("she_likes") else 0) - (0.7 if r["name"] in last_names else 0)
        return max(w, 0.1)

    need_light = config.rules().get("meals", {}).get("light_dinners_per_week", 4)
    light = [r for r in recipes if r.get("light")]
    chosen = _pick(rng, light, min(need_light, len(light), 6), weight)
    pool = [r for r in recipes if r not in chosen] or recipes
    chosen += _pick(rng, pool, 6 - len(chosen), weight)
    rng.shuffle(chosen)
    days = [{"day": "", "dish": r["name"], "light": r.get("light", False), "minutes": r.get("minutes")} for r in chosen]
    days.insert(5, {"day": "", "dish": "约会 / 外出", "light": False, "minutes": 0})  # 周六约会日默认外出
    for i, d in enumerate(days[:7]):
        d["day"] = WEEKDAYS[i]
    shopping = sorted({ing for r in chosen for ing in r.get("ingredients", [])})
    result = {"week": start.isoformat(), "days": days, "shopping": shopping}
    db.set_meta(conn, key, result)
    return result


def _pick(rng, pool, n, weight):
    pool = list(pool)
    out = []
    while pool and len(out) < n:
        r = rng.choices(pool, weights=[weight(x) for x in pool])[0]
        out.append(r)
        pool.remove(r)
    return out


def tonight(conn, on: date | None = None) -> dict | None:
    on = on or date.today()
    menu = plan_week(conn, on)
    days = menu.get("days", [])
    return days[on.weekday()] if len(days) == 7 else None
