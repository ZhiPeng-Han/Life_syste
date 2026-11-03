"""家：盼头、仪式、北极星、我们去过的地方。

回应两个恐惧：被琐事困住、家变成没有生命力的机器。
- 盼头（借鉴 SharedMoments 的倒计时）：地平线上永远有一件期待的事
- 仪式：不打卡、不计断档；只是在这一期还没过的时候，温和地提一句
- 北极星：两个人一起写下的方向，每年重写，旧版本保留
- 地图（借鉴 MappedLove）：你们一起去过的地方
"""

import json
import urllib.parse
import urllib.request
from datetime import date, timedelta

from . import db, memory

WEEKDAY = "一二三四五六日"


# ------------------------------------------------------------------ 盼头

def add_horizon(conn, title: str, when: str, with_her: bool = True, wish_id: int | None = None) -> int:
    hid = conn.execute(
        "INSERT INTO horizons(title, date, with_her, wish_id, created_at) VALUES(?,?,?,?,?)",
        (title, when, int(with_her), wish_id, db.now()),
    ).lastrowid
    from . import mind

    mind.link_horizon(conn, hid, title)
    conn.commit()
    return hid


def horizons(conn, on: date | None = None) -> dict:
    on = on or date.today()
    rows = db.rows(conn.execute("SELECT * FROM horizons ORDER BY date"))
    ahead, to_reflect, lived = [], [], []
    for h in rows:
        h["days_left"] = (date.fromisoformat(h["date"]) - on).days
        if h["status"] == "ahead" and h["days_left"] >= 0:
            ahead.append(h)
        elif h["status"] == "ahead":
            to_reflect.append(h)  # 日子已经过了，等你说一句"怎么样"
        else:
            lived.append(h)
    near = [h for h in ahead if h["days_left"] <= 30]
    return {"ahead": ahead, "to_reflect": to_reflect, "lived": lived[-10:][::-1],
            "empty_soon": not near,  # 一个月内没有盼头了
            "ideas": _horizon_ideas(conn) if not near else []}


def _horizon_ideas(conn) -> list[str]:
    from . import relationship

    ideas = [f"她说过「{w['content']}」" for w in relationship.wishes(conn)][:3]
    return ideas + ["一顿想吃很久的饭", "一个周末的短途", "一部一起等的电影"]


def live_horizon(conn, horizon_id: int, reflection: str = "") -> None:
    """盼头到了：记一句怎么样，它会变成一段记忆。"""
    h = conn.execute("SELECT title, date FROM horizons WHERE id = ?", (horizon_id,)).fetchone()
    conn.execute("UPDATE horizons SET status = 'lived', reflection = ? WHERE id = ?", (reflection, horizon_id))
    conn.commit()
    if h and reflection.strip():
        memory.capture(f"{h[0]}：{reflection}", source="horizon", conn=conn)


# ------------------------------------------------------------------ 仪式

def add_ritual(conn, name: str, cadence: str, weekday: int | None = None, month: int | None = None,
               day: int | None = None, note: str | None = None) -> int:
    rid = conn.execute(
        "INSERT INTO rituals(name, cadence, weekday, month, day, note, created_at) VALUES(?,?,?,?,?,?,?)",
        (name, cadence, weekday, month, day, note, db.now()),
    ).lastrowid
    conn.commit()
    return rid


def _period(r: dict, on: date) -> tuple[date, date]:
    if r["cadence"] == "weekly":
        start = on - timedelta(days=on.weekday())
        return start, start + timedelta(days=6)
    if r["cadence"] == "monthly":
        start = on.replace(day=1)
        nxt = (start + timedelta(days=32)).replace(day=1)
        return start, nxt - timedelta(days=1)
    return date(on.year, 1, 1), date(on.year, 12, 31)


def rituals(conn, on: date | None = None) -> list[dict]:
    on = on or date.today()
    out = []
    for r in db.rows(conn.execute("SELECT * FROM rituals WHERE active = 1 ORDER BY id")):
        start, end = _period(r, on)
        done = conn.execute("SELECT day, note FROM ritual_log WHERE ritual_id = ? AND day BETWEEN ? AND ? ORDER BY day DESC",
                            (r["id"], start.isoformat(), end.isoformat())).fetchone()
        r["done_this_period"] = dict(done) if done else None
        # 只在"今天就是那一天"或"这一期快结束了还没做"时温和地提一句
        if r["cadence"] == "weekly":
            r["today"] = r["weekday"] == on.isoweekday()
        elif r["cadence"] == "yearly":
            r["today"] = (r["month"], r["day"]) == (on.month, on.day)
        else:
            r["today"] = (r["day"] or 0) == on.day
        r["gentle"] = not done and (r["today"] or (end - on).days <= 2)
        r["when"] = {"weekly": f"每周{WEEKDAY[(r['weekday'] or 1) - 1]}", "monthly": f"每月{r['day'] or ''}{'日' if r['day'] else ''}",
                     "yearly": f"每年 {r['month']}/{r['day']}"}[r["cadence"]]
        out.append(r)
    return out


def log_ritual(conn, ritual_id: int, note: str = "", on: date | None = None) -> None:
    conn.execute("INSERT INTO ritual_log(ritual_id, day, note) VALUES(?,?,?)",
                 (ritual_id, (on.isoformat() if on else db.today()), note))
    conn.commit()
    if note.strip():
        name = conn.execute("SELECT name FROM rituals WHERE id = ?", (ritual_id,)).fetchone()[0]
        memory.capture(f"{name}：{note}", source="ritual", conn=conn)


# ------------------------------------------------------------------ 北极星

def north_star(conn) -> dict:
    return db.get_meta(conn, "north_star", {"text": "", "updated_at": None, "history": []})


def set_north_star(conn, text: str) -> dict:
    ns = north_star(conn)
    if ns["text"]:
        ns["history"].insert(0, {"text": ns["text"], "until": db.today()})
    ns.update(text=text, updated_at=db.today())
    db.set_meta(conn, "north_star", ns)
    return ns


# ------------------------------------------------------------------ 我们去过的地方

def geocode(name: str) -> tuple[float, float] | None:
    """Open-Meteo 免费地理编码（无需 key）。"""
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": name, "count": 1, "language": "zh"})
    try:
        with urllib.request.urlopen(url, timeout=6) as r:
            res = json.loads(r.read()).get("results") or []
        return (res[0]["latitude"], res[0]["longitude"]) if res else None
    except (OSError, ValueError, KeyError):
        return None


def add_place(conn, name: str, visited_on: str | None = None, lat: float | None = None, lon: float | None = None,
              with_her: bool = True, note: str | None = None) -> dict:
    if lat is None or lon is None:
        found = geocode(name)
        if found:
            lat, lon = found
    pid = conn.execute("INSERT INTO places(name, lat, lon, visited_on, with_her, note) VALUES(?,?,?,?,?,?)",
                       (name, lat, lon, visited_on, int(with_her), note)).lastrowid
    from . import mind

    mind.link_place(conn, pid, name)
    conn.commit()
    return {"id": pid, "name": name, "lat": lat, "lon": lon}


def places(conn) -> list[dict]:
    return db.rows(conn.execute("SELECT * FROM places ORDER BY visited_on DESC, id DESC"))


# ------------------------------------------------------------------ 初始化

DEFAULT_RITUALS = [
    ("周日一起做饭", "weekly", 7, None, None, "做什么不重要，一起做才重要"),
    ("每月一张同样角度的合照", "monthly", None, None, 1, "同一个地方、同一个角度；十年后那一叠照片就是这个家"),
    ("一起重写我们的北极星", "yearly", None, 1, 1, "新年第一天，一句话就够"),
]


def seed(conn) -> None:
    if db.get_meta(conn, "family_seeded"):
        return
    for name, cadence, wd, m, d, note in DEFAULT_RITUALS:
        add_ritual(conn, name, cadence, wd, m, d, note)
    db.set_meta(conn, "family_seeded", db.now())
