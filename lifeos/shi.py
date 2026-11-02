"""势：天下大势、节气、天气。人活在环境里，顺势事半功倍，逆势要知道自己在逆势。

- 大势（trends）：你自己观察到的趋势，或从新闻源提炼的趋势；每条带领域、顺逆、强弱，随时间衰减
- 节气：二十四节气（日期为近似值，误差约一天）及时令提示
- 天气：Open-Meteo 免费接口（无需 key），每天缓存一次；失败时静默跳过
"""

import json
import math
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

from . import config, db, llm

HALF_LIFE_DAYS = 45  # 一条势的影响力大约一个半月减半

# (月, 日, 名称, 时令提示) —— 北半球、公历近似日期
SOLAR_TERMS = [
    (1, 5, "小寒", "最冷的时候还没到，早睡晚起，养藏。"),
    (1, 20, "大寒", "一年最冷之时，也是岁末，收尾、团聚。"),
    (2, 4, "立春", "一年之计：想想今年和她一起要去的地方。"),
    (2, 19, "雨水", "万物开始萌动，适合播下一个小计划。"),
    (3, 5, "惊蛰", "春雷乍动，身体醒来，适合重新开始运动。"),
    (3, 20, "春分", "昼夜平分，看看生活的天平是否平衡。"),
    (4, 4, "清明", "踏青、怀人、整理。"),
    (4, 20, "谷雨", "雨生百谷，适合耕耘需要时间的事。"),
    (5, 5, "立夏", "万物生长，可以把节奏提起来。"),
    (5, 21, "小满", "小满即可，不求圆满。"),
    (6, 5, "芒种", "忙着播种，也别忘了休息。"),
    (6, 21, "夏至", "白昼最长，多在户外，多拍光。"),
    (7, 7, "小暑", "开始炎热，放慢节奏。"),
    (7, 22, "大暑", "一年最热，静心，少做大决定。"),
    (8, 7, "立秋", "暑去凉来，开始收心。"),
    (8, 23, "处暑", "暑气消退，适合整理和复盘。"),
    (9, 7, "白露", "早晚转凉，注意身体。"),
    (9, 22, "秋分", "昼夜再次平分，回看这一年过半的生活。"),
    (10, 8, "寒露", "天气转寒，早点回家。"),
    (10, 23, "霜降", "秋天最后一个节气，收获与告别。"),
    (11, 7, "立冬", "万物收藏：早睡，进补，把精力收回来。"),
    (11, 22, "小雪", "开始下雪的季节，适合室内的事、读书。"),
    (12, 7, "大雪", "藏，养，陪伴。"),
    (12, 21, "冬至", "一阳来复，最长的夜之后，白天开始变长。"),
]

WEATHER_CODES = [
    (0, "晴", "☀️"), (3, "多云", "⛅"), (48, "雾", "🌫"), (57, "毛毛雨", "🌦"), (67, "雨", "🌧"),
    (77, "雪", "🌨"), (82, "阵雨", "🌧"), (86, "阵雪", "🌨"), (99, "雷雨", "⛈"),
]


# ------------------------------------------------------------------ 节气

def _lunar(on: date):
    try:
        from lunar_python import Solar  # 可选依赖：pip install lunar_python
    except ImportError:
        return None
    return Solar.fromYmd(on.year, on.month, on.day).getLunar()


def almanac(on: date | None = None) -> dict | None:
    """农历与黄历宜忌——只作为文化参考展示，不进入任何决策。"""
    lunar = _lunar(on or date.today())
    if not lunar:
        return None
    return {"lunar": f"{lunar.getYearInGanZhi()}年 {lunar.getMonthInChinese()}月{lunar.getDayInChinese()}",
            "yi": lunar.getDayYi()[:6], "ji": lunar.getDayJi()[:6]}


def solar_term(on: date | None = None) -> dict:
    on = on or date.today()
    tips = {name: tip for _, _, name, tip in SOLAR_TERMS}
    lunar = _lunar(on)
    if lunar:  # 精确节气（寿星天文历算法）
        prev, nxt = lunar.getPrevJieQi(True), lunar.getNextJieQi(False)
        nd = nxt.getSolar()
        return {"name": prev.getName(), "tip": tips.get(prev.getName(), ""), "next": nxt.getName(),
                "days_to_next": (date(nd.getYear(), nd.getMonth(), nd.getDay()) - on).days, "exact": True}
    prev = None
    for m, d, name, tip in SOLAR_TERMS:
        if (m, d) <= (on.month, on.day):
            prev = (m, d, name, tip)
    prev = prev or SOLAR_TERMS[-1]
    idx = SOLAR_TERMS.index(prev)
    nxt = SOLAR_TERMS[(idx + 1) % len(SOLAR_TERMS)]
    nxt_date = date(on.year + (1 if (nxt[0], nxt[1]) < (on.month, on.day) else 0), nxt[0], nxt[1])
    cur = {"name": prev[2], "tip": prev[3], "next": nxt[2], "days_to_next": (nxt_date - on).days, "exact": False}
    return cur


# ------------------------------------------------------------------ 天气

def weather(conn, on: date | None = None) -> dict | None:
    on = on or date.today()
    key = f"weather:{on.isoformat()}"
    cached = db.get_meta(conn, key)
    if cached is not None:
        return cached or None
    env = config.rules().get("environment", {})
    lat, lon = env.get("latitude"), env.get("longitude")
    if lat is None or lon is None or os.environ.get("LIFEOS_OFFLINE"):
        return None
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
           "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
           "&hourly=temperature_2m,precipitation_probability,weathercode&timezone=auto&forecast_days=1")
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            data = json.loads(r.read())
        daily = data["daily"]
        code = int(daily["weathercode"][0])
        label, icon = next((lab, ic) for c, lab, ic in WEATHER_CODES if code <= c)
        w = {"label": label, "icon": icon, "code": code, "city": env.get("city", ""),
             "tmin": round(daily["temperature_2m_min"][0]), "tmax": round(daily["temperature_2m_max"][0]),
             "rain": daily.get("precipitation_probability_max", [None])[0]}
        w["wet"] = code >= 51 or (w["rain"] or 0) >= 60
        hourly = data.get("hourly") or {}
        w["hourly"] = {str(int(t[11:13])): {"t": round(tt) if tt is not None else None, "p": p, "c": c}
                       for t, tt, p, c in zip(hourly.get("time", []), hourly.get("temperature_2m", []),
                                              hourly.get("precipitation_probability", []), hourly.get("weathercode", []))}
    except (OSError, ValueError, KeyError, StopIteration):
        w = {}
    db.set_meta(conn, key, w)
    return w or None


# ------------------------------------------------------------------ 大势

def add(conn, title: str, domain: str | None = None, direction: int = 0, strength: int = 2,
        summary: str | None = None, source: str = "me", url: str | None = None, feed: str | None = None) -> int:
    tid = conn.execute(
        "INSERT INTO trends(title, summary, domain, direction, strength, source, url, observed_at, feed) VALUES(?,?,?,?,?,?,?,?,?)",
        (title, summary, domain, max(-1, min(1, direction)), max(1, min(5, strength)), source, url, db.now(), feed),
    ).lastrowid
    conn.commit()
    return tid


def retire(conn, trend_id: int) -> None:
    conn.execute("UPDATE trends SET status = 'retired' WHERE id = ?", (trend_id,))
    conn.commit()
    _feed_vote(conn, trend_id, -1)


def keep(conn, trend_id: int) -> None:
    """标记"这条有用"。"""
    conn.execute("UPDATE trends SET strength = MIN(strength + 1, 5) WHERE id = ?", (trend_id,))
    conn.commit()
    _feed_vote(conn, trend_id, +1)


def _feed_vote(conn, trend_id: int, vote: int) -> None:
    row = conn.execute("SELECT feed FROM trends WHERE id = ?", (trend_id,)).fetchone()
    if row and row[0]:
        weights = db.get_meta(conn, "feed_weights", {})
        weights[row[0]] = round(max(0.1, min(3.0, weights.get(row[0], 1.0) + 0.2 * vote)), 2)
        db.set_meta(conn, "feed_weights", weights)


def digest(conn, days: int = 7) -> str:
    """一段"本周大势"简报（给信和机器人用）。"""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    recent = [t for t in trends(conn, 100) if t["observed_at"] >= since]
    mom = momentum(conn)
    lines = ["🌏 本周大势"]
    if mom:
        lines.append("各领域之势：" + "，".join(f"{k}{'顺' if v > 0 else '逆'}{abs(v)}" for k, v in sorted(mom.items(), key=lambda x: -abs(x[1]))))
    for t in sorted(recent, key=lambda t: -t["weight"])[:5]:
        lines.append(f"· [{ {1: '顺', -1: '逆', 0: '观'}[t['direction']] }] {t['title']}" + (f"——{t['summary']}" if t["summary"] else ""))
    if len(lines) == 1:
        lines.append("这周没有新的观察。")
    return "\n".join(lines)


def trends(conn, limit: int = 30) -> list[dict]:
    out = db.rows(conn.execute("SELECT * FROM trends WHERE status = 'active' ORDER BY observed_at DESC LIMIT ?", (limit,)))
    for t in out:
        t["weight"] = round(_decay(t["observed_at"]) * t["strength"], 2)
    return out


def _decay(observed_at: str) -> float:
    days = (datetime.now() - datetime.fromisoformat(observed_at)).total_seconds() / 86400
    return math.pow(0.5, max(days, 0) / HALF_LIFE_DAYS)


def momentum(conn) -> dict:
    """每个领域的势：Σ 顺逆 × 强弱 × 时间衰减。正 = 顺势，负 = 逆势。"""
    out: dict = {}
    for t in trends(conn, 500):
        if t["domain"] and t["direction"]:
            out[t["domain"]] = round(out.get(t["domain"], 0) + t["direction"] * t["weight"], 2)
    return out


def factor(mom: dict, domain: str | None) -> float:
    """势对建议的乘数：顺势最多 ×1.3，逆势最少 ×0.7。"""
    v = max(-6.0, min(6.0, mom.get(domain or "", 0)))
    return 1 + 0.05 * v


def describe(mom: dict, domain: str | None) -> str | None:
    v = mom.get(domain or "", 0)
    if v >= 1.5:
        return f"「{domain}」正顺势"
    if v <= -1.5:
        return f"「{domain}」近来逆势"
    return None


# ------------------------------------------------------------------ 看看外面：新闻源

def _guess_domain(text: str) -> str | None:
    lower = text.lower()
    best, hits = None, 0
    for name, d in config.domains().items():
        n = sum(1 for k in d.get("keywords", []) if k.lower() in lower)
        if n > hits:
            best, hits = name, n
    return best


def _fetch_feed(url: str, limit: int = 8) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": "LifeOS/0.3 (personal)"})
    with urllib.request.urlopen(req, timeout=10) as r:
        root = ET.fromstring(r.read())
    items = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = next((c.text for c in it if c.tag.split("}")[-1] == "title"), None)
        link = next((c.text or c.get("href") for c in it if c.tag.split("}")[-1] == "link"), None)
        if title:
            items.append({"title": re.sub(r"\s+", " ", title).strip(), "url": link})
        if len(items) >= limit:
            break
    return items


TREND_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["trends"],
    "properties": {"trends": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["title", "summary", "domain", "direction", "strength", "source_index"],
        "properties": {"title": {"type": "string"}, "summary": {"type": "string"}, "domain": {"type": "string"},
                       "direction": {"type": "integer"}, "strength": {"type": "integer"},
                       "source_index": {"type": "integer"}}}}},
}


def fetch(conn) -> dict:
    """读配置里的新闻源。有 Claude 时提炼成和你有关的趋势；没有时只把标题记为'观察'。"""
    feeds = config.rules().get("environment", {}).get("feeds", [])
    headlines, errors = [], []
    weights = db.get_meta(conn, "feed_weights", {})
    for f in feeds:
        w = weights.get(f["url"], 1.0)
        if w <= 0.2:
            continue  # 你一再标记"过时了"的源，先歇一歇
        try:
            for h in _fetch_feed(f["url"], limit=max(2, round(8 * w))):
                headlines.append({**h, "domain": f.get("domain"), "feed": f["url"]})
        except (OSError, ET.ParseError) as e:
            errors.append(f"{f['url']}：{e}")
    if not headlines:
        return {"added": 0, "errors": errors}
    seen = {r[0] for r in conn.execute("SELECT title FROM trends").fetchall()}
    domains = "、".join(config.domains())
    ai = llm.complete_json(
        "你在帮一位住在英国的年轻建筑师（在考 RIBA Part 3，业余转卖二手相机镜头，研究 AI 视频自媒体，计划和女友去冰岛）"
        f"看'天下大势'。从下面的新闻标题里，只挑出真正会影响他生活或事业的 0-5 个趋势。domain 只能是：{domains}。"
        "direction：对他是顺势 1、逆势 -1、只需观察 0。strength 1-5。summary 一句话说明为什么和他有关。"
        "source_index 填主要依据的那条标题的编号。宁缺毋滥。",
        "\n".join(f"- ({i}) [{h['domain'] or ''}] {h['title']}" for i, h in enumerate(headlines)),
        TREND_SCHEMA,
    )
    added = 0
    if ai:
        for t in ai["trends"]:
            if t["title"] not in seen:
                src = headlines[t["source_index"]] if 0 <= t["source_index"] < len(headlines) else {}
                add(conn, t["title"], t["domain"] if t["domain"] in config.domains() else None,
                    t["direction"], t["strength"], t["summary"], source="ai", url=src.get("url"), feed=src.get("feed"))
                added += 1
    else:
        for h in headlines:
            if h["title"] not in seen:
                add(conn, h["title"], h["domain"] or _guess_domain(h["title"]), 0, 1, None, "news", h["url"], h["feed"])
                added += 1
    return {"added": added, "errors": errors, "engine": "claude" if ai else "rules"}
