"""命理：八字（四柱）、五行、十神、流年——作为一面文化的镜子。

诚实地说清楚：命理没有经过科学验证，同样的八字有千万人。这里只做两件事：
1. 排出四柱、数五行、算出流年流月对日主的"十神"，用它们的传统含义给你一个看这一年的角度（主题词），
2. 绝不进入任何建议的计算——和黄历一样，只展示。

算法：
- 年柱以立春为界，月柱以"节"为界（五虎遁定月干），日柱用儒略日推算（2000-01-01 为戊午日），时柱用五鼠遁。
- 23 点以后算作第二天的子时（"子时换日"）。不同流派对此有分歧，结果下面会提示。
- 节气日期用近似值（误差约一天）；装了 lunar_python 会用它的精确节气。生在节气交界前后一天的，月柱可能差一位。
- 出生时间用当地钟表时间，没有做真太阳时修正。
"""

from datetime import date, datetime, timedelta

from . import db

STEMS = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "子丑寅卯辰巳午未申酉戌亥"
STEM_ELEMENT = "木木火火土土金金水水"
# 地支的本气（藏干里最主要的那个）
BRANCH_MAIN = "癸己甲乙戊丙丁己庚辛戊壬"
BRANCH_ELEMENT = "水土木木土火火土金金土水"
ZODIAC = "鼠牛虎兔龙蛇马羊猴鸡狗猪"
ELEMENTS = "木火土金水"
GEN = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}   # 生
CTRL = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}  # 克

# 节（月的起点）：(月, 日, 月支序号)，近似日期
JIE = [(1, 5, 1), (2, 4, 2), (3, 5, 3), (4, 4, 4), (5, 5, 5), (6, 5, 6), (7, 7, 7), (8, 7, 8), (9, 7, 9),
       (10, 8, 10), (11, 7, 11), (12, 7, 0)]
JIE_NAMES = {1: "小寒", 2: "立春", 3: "惊蛰", 4: "清明", 5: "立夏", 6: "芒种", 7: "小暑", 8: "立秋", 9: "白露",
             10: "寒露", 11: "立冬", 0: "大雪"}

# 十神的传统含义，翻成"这一段时间的主题"，不说吉凶
TEN_GODS = {
    "比肩": ("自我、同伴", "靠自己、和同伴并肩的时候；留意固执，也留意朋友间的钱"),
    "劫财": ("竞争、分享", "身边的竞争和分享都多；花钱、借钱、合伙要先说清楚"),
    "食神": ("表达、享受、作品", "适合输出：作品、视频、设计，也适合好好吃饭、享受生活"),
    "伤官": ("才华、突破、锋芒", "创造力强、想打破规矩的时候；说话容易太冲，对上级和考试规则多一分耐心"),
    "偏财": ("机会、流动的钱", "机会和流动的钱多，适合经营和交易；偏财也意味着投机，按数据来"),
    "正财": ("收入、经营、务实", "踏实挣钱、管好收支的时候；适合把生意做稳"),
    "七杀": ("压力、挑战、魄力", "压力大、挑战多的时候；有章法地扛，别硬拼"),
    "正官": ("规矩、责任、名分", "考试、执业资格、职位、规矩的事突出；适合把 Part 3 这种'名分'拿下"),
    "偏印": ("独思、偏门之学", "想得多、适合钻研冷门的东西；留意想太多、做太少"),
    "正印": ("学习、庇护、贵人", "适合学习、读书、拿证书，也容易得到长辈和贵人的帮助"),
}


def ten_god(day_stem: str, other_stem: str) -> str:
    a, b = STEMS.index(day_stem), STEMS.index(other_stem)
    ea, eb = STEM_ELEMENT[a], STEM_ELEMENT[b]
    same = a % 2 == b % 2
    if ea == eb:
        return "比肩" if same else "劫财"
    if GEN[ea] == eb:
        return "食神" if same else "伤官"
    if CTRL[ea] == eb:
        return "偏财" if same else "正财"
    if CTRL[eb] == ea:
        return "七杀" if same else "正官"
    return "偏印" if same else "正印"  # 生我


def _gz(i: int) -> str:
    return STEMS[i % 10] + BRANCHES[i % 12]


def _jie_dates(year: int) -> list[tuple[date, int]]:
    try:
        from lunar_python import Solar  # 精确节气（可选）

        table = Solar.fromYmd(year, 6, 1).getLunar().getJieQiTable()
        out = []
        for _m, _d, branch in JIE:
            name = JIE_NAMES[branch]
            for key in (name, name.upper()):
                if key in table:
                    s = table[key]
                    d = date(s.getYear(), s.getMonth(), s.getDay())
                    if d.year == year:
                        out.append((d, branch))
                        break
        if len(out) == 12:
            return sorted(out)
    except Exception:  # noqa: BLE001 —— 没装或接口不同，就用近似日期
        pass
    return [(date(year, m, d), b) for m, d, b in JIE]


def pillars(born: datetime) -> dict:
    day = born.date()
    late_zi = born.hour >= 23
    if late_zi:
        day += timedelta(days=1)  # 子时换日
    # 年：立春为界
    li_chun = next(d for d, b in _jie_dates(born.year) if b == 2)
    y = born.year if born.date() >= li_chun else born.year - 1
    year_i = (y - 4) % 60
    # 月：最近的一个"节"
    marks = sorted(_jie_dates(born.year - 1) + _jie_dates(born.year))
    branch = next(b for d, b in reversed(marks) if d <= born.date())
    k = (branch - 2) % 12  # 寅月为 0
    first = ((year_i % 10) % 5 * 2 + 2) % 10  # 五虎遁
    month = STEMS[(first + k) % 10] + BRANCHES[branch]
    # 日：儒略日
    jdn = day.toordinal() + 1721425
    day_i = (jdn + 49) % 60
    # 时：五鼠遁
    hb = ((born.hour + 1) // 2) % 12
    hs = ((day_i % 10) % 5 * 2 + hb) % 10
    return {"year": _gz(year_i), "month": month, "day": _gz(day_i), "hour": STEMS[hs] + BRANCHES[hb],
            "zodiac": ZODIAC[year_i % 12], "late_zi": late_zi}


def chart(born: datetime, on: date | None = None) -> dict:
    on = on or date.today()
    p = pillars(born)
    chars = [p["year"], p["month"], p["day"], p["hour"]]
    dm = p["day"][0]
    count = {e: 0 for e in ELEMENTS}
    for gz in chars:
        count[STEM_ELEMENT[STEMS.index(gz[0])]] += 1
        count[BRANCH_ELEMENT[BRANCHES.index(gz[1])]] += 1
    dme = STEM_ELEMENT[STEMS.index(dm)]
    support = count[dme] + count[next(k for k, v in GEN.items() if v == dme)]  # 同我 + 生我
    gods = {name: ten_god(dm, gz[0]) for name, gz in zip(("年干", "月干", "时干"), (p["year"], p["month"], p["hour"]))}
    gods.update({f"{name}支": ten_god(dm, BRANCH_MAIN[BRANCHES.index(gz[1])])
                 for name, gz in zip(("年", "月", "日", "时"), chars)})
    flow_year = pillars(datetime(on.year, on.month, on.day, 12))
    ly, lm = flow_year["year"], flow_year["month"]
    gy, gm = ten_god(dm, ly[0]), ten_god(dm, lm[0])
    missing = [e for e, n in count.items() if n == 0]
    many = [e for e, n in count.items() if n >= 3]
    return {
        "pillars": p, "day_master": dm, "day_element": dme, "elements": count,
        "strength": "偏强" if support >= 5 else "偏弱" if support <= 2 else "中和",
        "missing": missing, "many": many, "gods": gods,
        "flow": {"year": ly, "year_god": gy, "year_theme": TEN_GODS[gy], "month": lm, "month_god": gm,
                 "month_theme": TEN_GODS[gm]},
        "note": "命理是一面文化的镜子，不是预言，也没有经过科学验证。它不进入任何建议的计算，只给你一个看这段时间的角度。"
                + ("23 点以后出生按第二天的子时排，不同流派有分歧。" if p["late_zi"] else ""),
    }


def birth(conn) -> datetime | None:
    v = db.get_meta(conn, "birth")
    try:
        return datetime.fromisoformat(v) if v else None
    except ValueError:
        return None


def set_birth(conn, value: str) -> datetime:
    born = datetime.fromisoformat(value.strip().replace(" ", "T") if "T" not in value and " " in value.strip() else value.strip())
    db.set_meta(conn, "birth", born.isoformat(timespec="minutes"))
    return born


def mine(conn, on: date | None = None) -> dict | None:
    b = birth(conn)
    return chart(b, on) if b else None


def describe(c: dict) -> list[str]:
    p, f = c["pillars"], c["flow"]
    el = " ".join(f"{e}{n}" for e, n in c["elements"].items())
    lines = [f"四柱：{p['year']}年 {p['month']}月 {p['day']}日 {p['hour']}时（属{p['zodiac']}）",
             f"日主 {c['day_master']}（{c['day_element']}），五行：{el}，粗看{c['strength']}"
             + (f"；缺{''.join(c['missing'])}" if c["missing"] else "") + (f"；{''.join(c['many'])}多" if c["many"] else ""),
             f"流年 {f['year']}：{f['year_god']}——{f['year_theme'][0]}。{f['year_theme'][1]}",
             f"流月 {f['month']}：{f['month_god']}——{f['month_theme'][0]}"]
    return lines
