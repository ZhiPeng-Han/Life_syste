"""天时：此时此地的"时"——时令之卦、七十二候、日出日落、时辰、这几个小时的天气。

- 时令之卦：孟喜卦气说的十二消息卦（辟卦）。一年十二个月，阳气从「复」（一阳来复）长到「乾」（纯阳），
  再从「姤」（一阴始生）消到「坤」（纯阴）。它不是起出来的，是这个季节本来的卦——天时本身。
- 七十二候：每个节气分三候，每候约五天，是古人观察到的物候（《逸周书·时训解》）。
- 日出日落、黄金时刻：按经纬度计算（NOAA 算法），不需要网络。
- 地利：你此刻在哪里（家、公司、外面、路上），以及一件事需要在哪里做。

这些只影响"此刻宜"的轻重和取舍，从不改变事实（期限、钱、健康、她）。
"""

import math
from datetime import date, datetime, timedelta, timezone

from . import config, db, shi, yi

# ------------------------------------------------------------------ 时令之卦（十二消息卦）

# 节气 → (月建, 消息卦序号, 阴阳消长的说明)
_SEASON = [
    (("大雪", "冬至"), "子", 24, "一阳来复：最深的阴里，阳气开始回来。宜静养，把一个重新开始的念头种下，不急着动。"),
    (("小寒", "大寒"), "丑", 19, "二阳渐长：光在回来。宜亲近、关心人，计划可以慢慢成形。"),
    (("立春", "雨水"), "寅", 11, "三阳开泰：阴阳平衡，天地相交。宜开始，宜合作。"),
    (("惊蛰", "春分"), "卯", 34, "四阳壮盛：力量在长。宜行动，但别用力过猛。"),
    (("清明", "谷雨"), "辰", 43, "五阳决一阴：拖着的事，该做决断了。"),
    (("立夏", "小满"), "巳", 1, "纯阳：一年里阳气最盛。宜全力推进，多在户外。"),
    (("芒种", "夏至"), "午", 44, "一阴始生：盛极之中，阴开始回来。留意细小的变化，别透支。"),
    (("小暑", "大暑"), "未", 33, "二阴渐长：适当退一步，保存能量。"),
    (("立秋", "处暑"), "申", 12, "天地不交：外面的事不那么通，宜守住自己，简朴一点。"),
    (("白露", "秋分"), "酉", 20, "四阴在下：多看少动，回看这一年。"),
    (("寒露", "霜降"), "戌", 23, "五阴剥一阳：阳气剥落到只剩最上面一点。宜收、宜藏，把家和根基安顿好，不宜扩张。"),
    (("立冬", "小雪"), "亥", 2, "纯阴：一年里阳气最弱。宜厚德载物：休养、承载、陪伴，静待一阳来复。"),
]

# 七十二候（《逸周书·时训解》）
HOU = {
    "立春": ("东风解冻", "蛰虫始振", "鱼陟负冰"), "雨水": ("獭祭鱼", "候雁北", "草木萌动"),
    "惊蛰": ("桃始华", "仓庚鸣", "鹰化为鸠"), "春分": ("玄鸟至", "雷乃发声", "始电"),
    "清明": ("桐始华", "田鼠化为鴽", "虹始见"), "谷雨": ("萍始生", "鸣鸠拂其羽", "戴胜降于桑"),
    "立夏": ("蝼蝈鸣", "蚯蚓出", "王瓜生"), "小满": ("苦菜秀", "靡草死", "麦秋至"),
    "芒种": ("螳螂生", "鵙始鸣", "反舌无声"), "夏至": ("鹿角解", "蜩始鸣", "半夏生"),
    "小暑": ("温风至", "蟋蟀居壁", "鹰始挚"), "大暑": ("腐草为萤", "土润溽暑", "大雨时行"),
    "立秋": ("凉风至", "白露降", "寒蝉鸣"), "处暑": ("鹰乃祭鸟", "天地始肃", "禾乃登"),
    "白露": ("鸿雁来", "玄鸟归", "群鸟养羞"), "秋分": ("雷始收声", "蛰虫坯户", "水始涸"),
    "寒露": ("鸿雁来宾", "雀入大水为蛤", "菊有黄华"), "霜降": ("豺乃祭兽", "草木黄落", "蛰虫咸俯"),
    "立冬": ("水始冰", "地始冻", "雉入大水为蜃"), "小雪": ("虹藏不见", "天气上升地气下降", "闭塞而成冬"),
    "大雪": ("鹖鴠不鸣", "虎始交", "荔挺出"), "冬至": ("蚯蚓结", "麋角解", "水泉动"),
    "小寒": ("雁北乡", "鹊始巢", "雉始雊"), "大寒": ("鸡始乳", "征鸟厉疾", "水泽腹坚"),
}


def season(on: date | None = None) -> dict:
    """此时节当令的卦，以及当下这一候。"""
    on = on or date.today()
    term = shi.solar_term(on)
    name = term["name"]
    terms, branch, n, text = next(x for x in _SEASON if name in x[0])
    h = yi.info(n)
    # 节气约 15 天，三候各约 5 天
    since = max(0, _term_length(on, term) - term["days_to_next"])
    idx = min(2, since // 5)
    nxt = _SEASON[(_SEASON.index(next(x for x in _SEASON if name in x[0])) + 1) % 12]
    return {
        "term": name, "branch": branch, "month": f"{branch}月",
        "hex": {"n": n, "symbol": h["symbol"], "name": h["name"], "full": h["full"], "bits": h["bits"],
                "stance": h["stance"], "stance_desc": h["stance_desc"], "xiang": h["xiang"]},
        "text": text, "yang": sum(h["bits"]),
        "next_hex": {"symbol": yi.info(nxt[2])["symbol"], "name": yi.info(nxt[2])["name"], "from": nxt[0][0]},
        "hou": {"n": idx + 1, "text": HOU[name][idx], "all": list(HOU[name])},
    }


def _term_length(on: date, term: dict) -> int:
    names = [t[2] for t in shi.SOLAR_TERMS]
    i = names.index(term["name"])
    a, b = shi.SOLAR_TERMS[i], shi.SOLAR_TERMS[(i + 1) % 24]
    start = date(on.year if (a[0], a[1]) <= (on.month, on.day) else on.year - 1, a[0], a[1])
    end = date(start.year + (1 if (b[0], b[1]) < (a[0], a[1]) else 0), b[0], b[1])
    return (end - start).days


# ------------------------------------------------------------------ 日出日落（NOAA 简化算法）

def _sun_event(on: date, lat: float, lon: float, zenith: float, rising: bool) -> datetime | None:
    g = 2 * math.pi / 365 * (on.timetuple().tm_yday - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    cos_ha = math.cos(math.radians(zenith)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    if not -1 <= cos_ha <= 1:
        return None  # 极昼或极夜
    ha = math.degrees(math.acos(cos_ha))
    minutes = 720 - 4 * (lon + ha if rising else lon - ha) - eqtime
    utc = datetime(on.year, on.month, on.day, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return utc.astimezone().replace(tzinfo=None)  # 本机时区


def sun(on: date | None = None) -> dict | None:
    on = on or date.today()
    env = config.rules().get("environment", {})
    lat, lon = env.get("latitude"), env.get("longitude")
    if lat is None or lon is None:
        return None
    rise, set_ = _sun_event(on, lat, lon, 90.833, True), _sun_event(on, lat, lon, 90.833, False)
    if not rise or not set_:
        return None
    golden = _sun_event(on, lat, lon, 84.0, False) or set_ - timedelta(minutes=60)  # 太阳高度 6° 以下
    dusk = _sun_event(on, lat, lon, 96.0, False) or set_ + timedelta(minutes=40)  # 民用暮光结束
    y_rise, y_set = _sun_event(on - timedelta(days=1), lat, lon, 90.833, True), _sun_event(on - timedelta(days=1), lat, lon, 90.833, False)
    length = (set_ - rise).total_seconds() / 60
    change = round(length - (y_set - y_rise).total_seconds() / 60) if y_rise and y_set else 0
    return {"rise": rise, "set": set_, "golden": golden, "dusk": dusk,
            "length": f"{int(length // 60)} 小时 {int(length % 60)} 分", "change": change}


# ------------------------------------------------------------------ 时辰与一天里的时候

SHICHEN = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]


def shichen(at: datetime) -> str:
    return SHICHEN[((at.hour + 1) % 24) // 2] + "时"


def part_of_day(at: datetime, s: dict | None) -> str:
    h = at.hour + at.minute / 60
    if h < 5 or h >= 23:
        return "深夜"
    if s and at < s["rise"]:
        return "天还没亮"
    if h < 9:
        return "清晨"
    if h < 12:
        return "上午"
    if h < 14:
        return "午间"
    if s and s["golden"] <= at < s["set"]:
        return "黄金时刻"
    if s and s["set"] <= at < s["dusk"]:
        return "黄昏"
    if s and at >= s["dusk"]:
        return "入夜" if h < 21 else "夜里"
    return "下午" if h < 18 else "傍晚"


# ------------------------------------------------------------------ 这几个小时的天气

def hours(conn, at: datetime) -> dict | None:
    """现在和接下来两小时：会不会下雨、多少度。只用每天缓存一次的逐小时预报。"""
    wx = shi.weather(conn, at.date())
    if not wx:
        return None
    hourly = wx.get("hourly") or {}
    now_h = hourly.get(str(at.hour))
    nxt = [hourly.get(str(h)) for h in range(at.hour, min(at.hour + 3, 24)) if hourly.get(str(h))]
    wet_now = bool(now_h and (now_h["p"] or 0) >= 50) if now_h else bool(wx.get("wet"))
    dry_soon = bool(nxt) and all((x["p"] or 0) < 40 for x in nxt)
    return {"icon": wx["icon"], "label": wx["label"], "temp": now_h["t"] if now_h else None,
            "wet_now": wet_now, "dry_soon": dry_soon if nxt else not wx.get("wet"),
            "rain": now_h["p"] if now_h else wx.get("rain"), "tmin": wx["tmin"], "tmax": wx["tmax"]}


# ------------------------------------------------------------------ 地利：你在哪里，一件事要在哪里做

PLACES = {
    "家": {"icon": "🏠", "can": {"home", "desk", "work", "leave", "camera", "phone", "any"}},
    "公司": {"icon": "🏢", "can": {"work", "leave", "phone", "any"}},
    "外面": {"icon": "🚶", "can": {"out", "leave", "camera", "phone", "any"}},
    "路上": {"icon": "🚆", "can": {"phone", "any"}},
}
NEED_LABEL = {"out": "要出门", "home": "要在家", "desk": "要坐在电脑前", "work": "要在工作状态",
              "leave": "要出去走走", "camera": "要带相机", "phone": "手机就能做", "any": "哪里都能做"}

# 一件事需要在哪里做：先看关键词，再看领域
NEED_WORDS = [
    ("out", ["寄", "快递", "发货", "超市", "买菜", "邮局", "银行", "取件", "看展", "医院", "理发", "跑步", "徒步", "游泳", "健身房", "散步", "见面"]),
    ("home", ["打扫", "洗衣", "做饭", "做菜", "收纳", "收拾", "垃圾", "整理房间", "熨"]),
    ("camera", ["拍照", "拍摄", "实拍", "样张", "拍光"]),
    ("phone", ["发消息", "问她", "回复", "回消息", "打电话", "联系", "预约", "提醒她"]),
    ("desk", ["写", "画", "改图", "报告", "邮件", "上架", "剪辑", "脚本", "录入", "复习", "卡片", "预算", "清单", "表格", "研究", "查一下", "比较", "添加", "「"]),
]
DOMAIN_NEED = {"建筑工作": "work", "Part3": "desk", "器材事业": "desk", "自媒体": "desk", "生活维持": "home",
               "旅行": "desk", "健康": "leave", "关系": "any", "阅读思考": "any"}


def need_of(title: str, domain: str | None) -> str:
    low = title.lower()
    for need, words in NEED_WORDS:
        if any(w in low for w in words):
            return need
    return DOMAIN_NEED.get(domain or "", "any")


def fits(place: str | None, need: str) -> bool:
    return not place or need in PLACES.get(place, PLACES["家"])["can"]


def guess_place(conn, at: datetime) -> tuple[str, bool]:
    """你说过你在哪里（3 小时内有效），否则按节律猜：工作日的上班时间在公司，其余时间在家。"""
    saved = db.get_meta(conn, "place", {})
    if saved.get("name") in PLACES and saved.get("at", "") >= (at - timedelta(hours=3)).isoformat(timespec="seconds"):
        return saved["name"], False
    from . import planner

    m = at.hour * 60 + at.minute
    for b in planner.blocks_for(at.date()):
        if b["kind"] == "fixed" and b["start"] <= m < b["end"]:
            return "公司", True
    return "家", True


def set_place(conn, name: str) -> None:
    if name in PLACES:
        db.set_meta(conn, "place", {"name": name, "at": db.now()})


def with_her(conn, at: datetime) -> bool:
    saved = db.get_meta(conn, "with_her", {})
    return bool(saved.get("on")) and saved.get("at", "") >= (at - timedelta(hours=3)).isoformat(timespec="seconds")


def her_known(conn, at: datetime) -> bool:
    """3 小时内你说过她在不在身边。"""
    saved = db.get_meta(conn, "with_her", {})
    return bool(saved) and saved.get("at", "") >= (at - timedelta(hours=3)).isoformat(timespec="seconds")


def set_with_her(conn, on: bool) -> None:
    db.set_meta(conn, "with_her", {"on": bool(on), "at": db.now()})


# ------------------------------------------------------------------ 汇总：此刻的天时

def _hm(t: datetime) -> str:
    return t.strftime("%H:%M")


def now(conn, at: datetime | None = None) -> dict:
    at = at or datetime.now()
    s = sun(at.date())
    sea = season(at.date())
    wx = hours(conn, at)
    part = part_of_day(at, s)
    light = None
    if s:
        if at < s["rise"]:
            light = f"日出 {_hm(s['rise'])}"
        elif at < s["golden"]:
            mins = int((s["set"] - at).total_seconds() // 60)
            light = f"日落 {_hm(s['set'])}，天亮着还有 {mins // 60} 小时 {mins % 60} 分" if mins >= 60 else f"{mins} 分钟后日落"
        elif at < s["set"]:
            light = f"黄金时刻，{int((s['set'] - at).total_seconds() // 60)} 分钟后日落（{_hm(s['set'])}）"
        elif at < s["dusk"]:
            light = f"日落了，天光还剩 {int((s['dusk'] - at).total_seconds() // 60)} 分钟"
        else:
            light = f"天黑了（今天日落 {_hm(s['set'])}）"
    return {
        "at": at.isoformat(timespec="minutes"), "time": at.strftime("%H:%M"), "shichen": shichen(at), "part": part,
        "light": light, "daylight": bool(s and s["rise"] <= at < s["dusk"]),
        "golden": bool(s and s["golden"] - timedelta(minutes=30) <= at < s["set"]),
        "sun": {"rise": _hm(s["rise"]), "set": _hm(s["set"]), "golden": _hm(s["golden"]), "length": s["length"],
                "change": s["change"]} if s else None,
        "weather": wx, "season": sea,
    }


def line(t: dict) -> str:
    """一行字的天时，给早安、Siri、工作包用。"""
    sea = t["season"]
    bits = [f"{t['time']} {t['shichen']}·{t['part']}"]
    if t["light"]:
        bits.append(t["light"])
    w = t["weather"]
    if w:
        bits.append(f"{w['icon']}{w['label']}" + (f" {w['temp']}°" if w.get("temp") is not None else "")
                    + ("，正下着雨" if w["wet_now"] else "，接下来两小时不下雨" if w["dry_soon"] else ""))
    bits.append(f"{sea['term']}·{sea['hou']['text']}")
    bits.append(f"{sea['hex']['symbol']}{sea['hex']['name']}当令")
    return "；".join(bits)
