"""此刻宜的选择库：口袋里的事之外，"此刻"还可以做的事。

- 默认库在 config/moments.toml，你自己的在 data/moments.toml（同 key 覆盖），也可以在网页上添加、停用
- 每一条都标了：在哪里做得了（地利）、多久、适合什么感受、什么时候（天时）、天气、她在不在身边（人和）、和哪些姿态相合
- 它会从你的选择里学习：常点"好"的更常出现，常点"换一个"的慢慢沉下去，刚做过的让一让
"""

import hashlib
import json
import tomllib
from datetime import datetime, timedelta

from . import config, db

FIELDS = ("title", "cat", "need", "minutes", "feelings", "whn", "weather", "her", "energy", "stances", "why")
# 时间性强的选择：错过就没有了，所以在它的时候更重一点
TIMELY = {"golden": 2.5, "noon": 1.3, "dark": 1.2, "night": 1.2, "morning": 1.1, "weekend": 1.1}


def _read(path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "rb") as f:
        return tomllib.load(f).get("moment", [])


def library() -> list[dict]:
    """默认库 + 你的 data/moments.toml（同 key 覆盖，新 key 追加）。"""
    merged: dict = {}
    for m in _read(config.config_dir() / "moments.toml") + _read(config.home() / "moments.toml"):
        if m.get("key") and m.get("title"):
            merged[m["key"]] = {**merged.get(m["key"], {}), **m}
    return list(merged.values())


def _row(m: dict) -> dict:
    return {"title": m["title"], "cat": m.get("cat", "心"), "need": m.get("need", "any"), "minutes": int(m.get("min", m.get("minutes", 15))),
            "feelings": json.dumps(m.get("feel", []), ensure_ascii=False), "whn": m.get("when", "any"),
            "weather": m.get("weather", "any"), "her": m.get("her", "any"), "energy": m.get("energy", "low"),
            "stances": json.dumps(m.get("stance", []), ensure_ascii=False), "why": m.get("why", "")}


def sync(conn) -> None:
    """把库同步进数据库。库文件没变就什么都不做；你停用过的不会被重新打开。"""
    lib = library()
    digest = hashlib.sha1(json.dumps(lib, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if db.get_meta(conn, "moments_hash") == digest:
        return
    for m in lib:
        r = _row(m)
        conn.execute(
            f"INSERT INTO moments(key, {', '.join(FIELDS)}, source, created_at) VALUES(?, {', '.join('?' * len(FIELDS))}, 'library', ?) "
            f"ON CONFLICT(key) DO UPDATE SET {', '.join(f'{k} = excluded.{k}' for k in FIELDS)} WHERE moments.source = 'library'",
            (m["key"], *[r[k] for k in FIELDS], db.now()))
    db.set_meta(conn, "moments_hash", digest)
    conn.commit()


def has_library(conn) -> bool:
    sync(conn)
    return conn.execute("SELECT COUNT(*) FROM moments WHERE active = 1").fetchone()[0] >= 10


def add(conn, title: str, need: str = "any", minutes: int = 15, cat: str = "我的", feelings: list | None = None,
        whn: str = "any", her: str = "any", why: str = "") -> str:
    key = "me-" + hashlib.sha1(f"{title}{db.now()}".encode()).hexdigest()[:8]
    conn.execute(
        "INSERT INTO moments(key, title, cat, need, minutes, feelings, whn, her, why, source, created_at) VALUES(?,?,?,?,?,?,?,?,?,'me',?)",
        (key, title.strip(), cat, need, int(minutes), json.dumps(feelings or [], ensure_ascii=False), whn, her, why, db.now()))
    conn.commit()
    return key


def set_active(conn, key: str, active: bool) -> None:
    conn.execute("UPDATE moments SET active = ? WHERE key = ?", (int(active), key))
    conn.commit()


def log(conn, key: str, action: str, title: str = "", place: str | None = None, feeling: str | None = None,
        part: str | None = None) -> None:
    if action not in ("ok", "next", "done", "not_now"):
        raise ValueError(action)
    conn.execute("INSERT INTO moment_log(at, key, title, action, place, feeling, part) VALUES(?,?,?,?,?,?,?)",
                 (db.now(), key, title, action, place, feeling, part))
    conn.commit()


def stats(conn, days: int = 90) -> dict:
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    out: dict = {}
    for key, action, at in conn.execute("SELECT key, action, at FROM moment_log WHERE at >= ?", (since,)):
        s = out.setdefault(key, {"yes": 0, "no": 0, "last_yes": ""})
        if action in ("ok", "done"):
            s["yes"] += 1
            s["last_yes"] = max(s["last_yes"], at)
        else:
            s["no"] += 1
    return out


def listing(conn) -> list[dict]:
    sync(conn)
    st = stats(conn)
    out = []
    for m in db.rows(conn.execute("SELECT * FROM moments ORDER BY active DESC, cat, id")):
        m["feelings"], m["stances"] = json.loads(m["feelings"] or "[]"), json.loads(m["stances"] or "[]")
        s = st.get(m["key"], {})
        m["yes"], m["no"] = s.get("yes", 0), s.get("no", 0)
        out.append(m)
    return out


def _when_ok(whn: str, at: datetime, t: dict) -> bool:
    h = at.hour + at.minute / 60
    return {
        "any": True, "morning": 5 <= h < 11, "day": 7 <= h < 18, "noon": 11.5 <= h < 14.5, "evening": 17 <= h < 23,
        "night": h >= 21 or h < 2, "daylight": t["daylight"], "golden": t["golden"],
        "dark": not t["daylight"] and (h >= 16 or h < 6) and h < 23, "weekend": at.weekday() >= 5,
    }.get(whn, True)


def candidates(conn, at: datetime, t: dict, feeling: str, care: float, place: str | None, her: bool,
               minutes: int | None, stance: str | None, season_stance: str | None) -> list[dict]:
    """此刻能做、此刻合适的选择，带分数和理由。"""
    from . import tianshi

    sync(conn)
    st = stats(conn)
    wx = t.get("weather") or {}
    recent = (at - timedelta(hours=36)).isoformat(timespec="seconds")
    out = []
    for m in db.rows(conn.execute("SELECT * FROM moments WHERE active = 1")):
        feels = json.loads(m["feelings"] or "[]")
        if feels and feeling not in feels:
            continue
        if minutes is not None and m["minutes"] > minutes:
            continue
        if not _when_ok(m["whn"], at, t):
            continue
        if m["weather"] == "dry" and wx.get("wet_now"):
            continue
        if (m["her"] == "with" and not her) or (m["her"] == "without" and her):
            continue
        if not tianshi.fits(place, m["need"]):
            continue
        score = 4.0 * care
        notes = []
        if m["whn"] in TIMELY:
            score *= TIMELY[m["whn"]]
            if m["whn"] == "golden":
                notes.append(t.get("light") or "黄金时刻")
            elif m["whn"] in ("dark", "night"):
                notes.append("天黑了，正是时候")
            elif m["whn"] == "noon":
                notes.append("午间")
        if m["weather"] == "wet" and wx.get("wet_now"):
            score *= 1.6
            notes.append("正下着雨，这件事恰好适合雨天")
        stances = json.loads(m["stances"] or "[]")
        if stance and stance in stances:
            score *= 1.15
        if season_stance and season_stance in stances:
            score *= 1.08
        s = st.get(m["key"])
        learned = ""
        if s:
            f = max(0.5, min(1.6, (2 + s["yes"]) / (2 + 0.6 * s["no"])))
            score *= f
            if f >= 1.2:
                learned = "你常选这个"
            if s["last_yes"] >= recent:
                score *= 0.5
                learned = "刚做过，换换别的也好"
        out.append({"kind": "care", "key": f"l:{m['key']}", "title": m["title"], "cat": m["cat"],
                    "domain": "关系" if m["cat"] == "她" else "此刻", "need": m["need"], "minutes": m["minutes"],
                    "score": score, "tian_note": "；".join(notes), "mind_note": learned,
                    "reason": m["why"] or "这不是任务，是照顾一下自己。", "source": m["source"]})
    return out
