"""周易：一面镜子，不是一个预言。

- 起卦用三枚铜钱法：每爻掷三枚，正面记 3、反面记 2，和为 6/7/8/9
  （6 老阴、9 老阳为变爻）。随机数来自操作系统熵源——这就是"命"里随机的那一半。
- 每卦给出《象传》原文（"君子以……"：在这种处境下君子怎么做）、白话、以及一个"姿态"。
- 姿态只轻微调整建议的轻重，从不改变事实（截止日期、钱、健康、她）。
"""

import json
import secrets

from . import config, db, llm

# 三画卦：自下而上的爻（1=阳，0=阴）
TRIGRAMS = {
    "乾": ((1, 1, 1), "天"), "兑": ((1, 1, 0), "泽"), "离": ((1, 0, 1), "火"), "震": ((1, 0, 0), "雷"),
    "巽": ((0, 1, 1), "风"), "坎": ((0, 1, 0), "水"), "艮": ((0, 0, 1), "山"), "坤": ((0, 0, 0), "地"),
}

# 文王卦序：(卦名, 上卦, 下卦, 《象传》, 姿态, 白话)
HEXAGRAMS = [
    ("乾", "乾", "乾", "天行健，君子以自强不息。", "进", "像天一样运行不息：推进最重要的那件事，稳而不急。"),
    ("坤", "坤", "坤", "地势坤，君子以厚德载物。", "合", "像大地一样承载：照顾好身边的人，包容不完美。"),
    ("屯", "坎", "震", "云雷，屯；君子以经纶。", "守", "万事开头难：先理清头绪，小步开始，不急于求成。"),
    ("蒙", "艮", "坎", "山下出泉，蒙；君子以果行育德。", "学", "启蒙之时：适合学习、请教，果断去做该学的事。"),
    ("需", "坎", "乾", "云上于天，需；君子以饮食宴乐。", "养", "等待时机：吃好、睡好、养精蓄锐，不必强求。"),
    ("讼", "乾", "坎", "天与水违行，讼；君子以作事谋始。", "慎", "易起争执：做事先想清楚开头，避免争辩。"),
    ("师", "坤", "坎", "地中有水，师；君子以容民畜众。", "进", "整合力量：有纪律地推进，照顾好与你同行的人。"),
    ("比", "坎", "坤", "地上有水，比；先王以建万国，亲诸侯。", "合", "亲近：靠近值得亲近的人，彼此扶持。"),
    ("小畜", "巽", "乾", "风行天上，小畜；君子以懿文德。", "学", "小有积蓄：修养自身，积小成多，不宜大动。"),
    ("履", "乾", "兑", "上天下泽，履；君子以辨上下，定民志。", "慎", "如履虎尾：行事谨慎有礼，守好分寸。"),
    ("泰", "坤", "乾", "天地交，泰；后以财成天地之道，辅相天地之宜，以左右民。", "进", "天地相交，通达顺遂：适合一起做事、成事。"),
    ("否", "乾", "坤", "天地不交，否；君子以俭德辟难，不可荣以禄。", "守", "闭塞不通：低调俭朴，守住自己，不求表现。"),
    ("同人", "乾", "离", "天与火，同人；君子以类族辨物。", "合", "与人同心：适合和她、和伙伴一起做事。"),
    ("大有", "离", "乾", "火在天上，大有；君子以遏恶扬善，顺天休命。", "进", "丰盛之时：扬善，分享你所拥有的。"),
    ("谦", "坤", "艮", "地中有山，谦；君子以裒多益寡，称物平施。", "省", "谦：多的减一点，少的补一点，回到平衡。"),
    ("豫", "震", "坤", "雷出地奋，豫；先王以作乐崇德，殷荐之上帝，以配祖考。", "合", "愉悦：适合安排快乐的事、音乐、团聚。"),
    ("随", "兑", "震", "泽中有雷，随；君子以向晦入宴息。", "养", "随时而动：天黑了就休息，顺势而为。"),
    ("蛊", "艮", "巽", "山下有风，蛊；君子以振民育德。", "断", "整治积弊：修理坏掉的东西，清理积压的事。"),
    ("临", "坤", "兑", "泽上有地，临；君子以教思无穷，容保民无疆。", "合", "亲临：去关心、去陪伴、去照顾。"),
    ("观", "巽", "坤", "风行地上，观；先王以省方观民设教。", "省", "观察：多看少动，看清局势再说。"),
    ("噬嗑", "离", "震", "雷电噬嗑；先王以明罚敕法。", "断", "咬合：障碍要果断处理，把拖着的事了结。"),
    ("贲", "艮", "离", "山下有火，贲；君子以明庶政，无敢折狱。", "养", "文饰之美：适合拍照、布置、审美之事；大事不在今天定。"),
    ("剥", "艮", "坤", "山附于地，剥；上以厚下安宅。", "守", "剥落之时：不宜行动，先把根基和家安顿好。"),
    ("复", "坤", "震", "雷在地中，复；先王以至日闭关，商旅不行，后不省方。", "养", "一阳来复：停一停，回到自己，再重新出发。"),
    ("无妄", "乾", "震", "天下雷行，物与无妄；先王以茂对时育万物。", "慎", "不妄为：按本分做事，不投机，不心存侥幸。"),
    ("大畜", "艮", "乾", "天在山中，大畜；君子以多识前言往行，以畜其德。", "学", "大积蓄：多读、多学、多积累。"),
    ("颐", "艮", "震", "山下有雷，颐；君子以慎言语，节饮食。", "养", "颐养：说话少一点，吃得好一点、清淡一点。"),
    ("大过", "兑", "巽", "泽灭木，大过；君子以独立不惧，遯世无闷。", "断", "负担过重：该减就减，独立而不惧。"),
    ("坎", "坎", "坎", "水洊至，习坎；君子以常德行，习教事。", "慎", "重重险陷：稳住常态，反复练习，不冒险。"),
    ("离", "离", "离", "明两作，离；大人以继明照于四方。", "省", "光明：看清楚，依附于对的事和对的人。"),
    ("咸", "兑", "艮", "山上有泽，咸；君子以虚受人。", "合", "感应：放空自己，用心感受她。"),
    ("恒", "震", "巽", "雷风，恒；君子以立不易方。", "守", "恒久：坚持该坚持的，不轻易改变方向。"),
    ("遯", "乾", "艮", "天下有山，遯；君子以远小人，不恶而严。", "养", "退避：适当后退，保护自己的能量。"),
    ("大壮", "震", "乾", "雷在天上，大壮；君子以非礼弗履。", "进", "强盛：有力量，但别用力过猛，不合宜的事不做。"),
    ("晋", "离", "坤", "明出地上，晋；君子以自昭明德。", "进", "上进：展现自己，让人看见你的好。"),
    ("明夷", "坤", "离", "明入地中，明夷；君子以莅众，用晦而明。", "养", "光明受伤：低调一些，保护自己，内心依然明亮。"),
    ("家人", "巽", "离", "风自火出，家人；君子以言有物，而行有恒。", "合", "家人：说实在的话，做持久的事，用心经营这个家。"),
    ("睽", "离", "兑", "上火下泽，睽；君子以同而异。", "省", "背离：求同存异，先找到你们一致的地方。"),
    ("蹇", "坎", "艮", "山上有水，蹇；君子以反身修德。", "守", "艰难：先反求诸己，必要时向人求助。"),
    ("解", "震", "坎", "雷雨作，解；君子以赦过宥罪。", "断", "解脱：原谅、放下、释怀，包括原谅自己。"),
    ("损", "艮", "兑", "山下有泽，损；君子以惩忿窒欲。", "断", "减损：少一点怒气，少一点欲望，减掉不必要的。"),
    ("益", "巽", "震", "风雷，益；君子以见善则迁，有过则改。", "进", "增益：见善就学，有错就改；帮助别人。"),
    ("夬", "兑", "乾", "泽上于天，夬；君子以施禄及下，居德则忌。", "断", "决断：该了结的了结，不要拖。"),
    ("姤", "乾", "巽", "天下有风，姤；后以施命诰四方。", "慎", "不期而遇：保持分寸，看清再决定。"),
    ("萃", "兑", "坤", "泽上于地，萃；君子以除戎器，戒不虞。", "合", "聚集：和人聚在一起，同时防备意外。"),
    ("升", "坤", "巽", "地中生木，升；君子以顺德，积小以高大。", "进", "上升：循序渐进，积小成大。"),
    ("困", "兑", "坎", "泽无水，困；君子以致命遂志。", "养", "困顿：守住志向，先照顾好自己，困局会过去。"),
    ("井", "坎", "巽", "木上有水，井；君子以劳民劝相。", "守", "井：维护让你持续获得滋养的东西，互相帮助。"),
    ("革", "兑", "离", "泽中有火，革；君子以治历明时。", "断", "变革：适合改变规则、调整节律、重新安排生活。"),
    ("鼎", "离", "巽", "木上有火，鼎；君子以正位凝命。", "进", "鼎新：确立新秩序，站稳自己的位置。"),
    ("震", "震", "震", "洊雷，震；君子以恐惧修省。", "省", "震动：受惊之后，反省自己。"),
    ("艮", "艮", "艮", "兼山，艮；君子以思不出其位。", "养", "止：该停就停，心思不越出当下。"),
    ("渐", "巽", "艮", "山上有木，渐；君子以居贤德善俗。", "守", "渐进：慢慢来，像树一样一点点长。"),
    ("归妹", "震", "兑", "泽上有雷，归妹；君子以永终知敝。", "慎", "关系之始：想清楚长远，知道可能的问题。"),
    ("丰", "震", "离", "雷电皆至，丰；君子以折狱致刑。", "断", "丰盛到顶：当断则断，趁明白时做决定。"),
    ("旅", "离", "艮", "山上有火，旅；君子以明慎用刑，而不留狱。", "慎", "在外旅行：谨慎明察，不拖泥带水。"),
    ("巽", "巽", "巽", "随风，巽；君子以申命行事。", "进", "顺入：像风一样，柔和而持续地推进。"),
    ("兑", "兑", "兑", "丽泽，兑；君子以朋友讲习。", "合", "喜悦：和朋友交流、一起学习。"),
    ("涣", "巽", "坎", "风行水上，涣；先王以享于帝立庙。", "省", "涣散：把散掉的心收回来，回到根本。"),
    ("节", "坎", "兑", "泽上有水，节；君子以制数度，议德行。", "守", "节制：给自己设边界，量力而行。"),
    ("中孚", "巽", "兑", "泽上有风，中孚；君子以议狱缓死。", "合", "诚信：真诚待人，宽厚一点。"),
    ("小过", "震", "艮", "山上有雷，小过；君子以行过乎恭，丧过乎哀，用过乎俭。", "慎", "小事可为，大事不宜：把小处做到位。"),
    ("既济", "坎", "离", "水在火上，既济；君子以思患而豫防之。", "慎", "已成：越是顺利，越要想到隐患、提前防备。"),
    ("未济", "离", "坎", "火在水上，未济；君子以慎辨物居方。", "进", "未完成：看清楚，继续往前走。"),
]

# 姿态：对建议的轻微调整（乘数，经 rules.toml [yi] weight 缩放）
STANCES = {
    "进": {"desc": "宜进取", "detail": "做主线上真正重要、需要专注的事。",
           "energy": {"high": 1.3, "low": 0.9}, "domains": {"建筑工作": 1.2, "Part3": 1.2}, "care": 0.8},
    "守": {"desc": "宜守成", "detail": "把手上的事做完，不开新局，不做大决定。",
           "energy": {"low": 1.15, "medium": 1.1, "high": 0.9}, "domains": {"生活维持": 1.2}, "care": 1.0, "deal": "缓"},
    "养": {"desc": "宜休养", "detail": "吃好、睡好，身体和心先回来。",
           "energy": {"high": 0.7}, "domains": {"健康": 1.3}, "care": 1.5, "deal": "缓"},
    "合": {"desc": "宜亲和", "detail": "靠近她，靠近朋友，一起做事。",
           "energy": {}, "domains": {"关系": 1.5}, "care": 1.1},
    "学": {"desc": "宜蓄积", "detail": "学习、读书、积累。",
           "energy": {}, "domains": {"Part3": 1.5, "阅读思考": 1.3}, "care": 0.9},
    "省": {"desc": "宜内省", "detail": "回看、整理、写下来；多看少动。",
           "energy": {"high": 0.9}, "domains": {"阅读思考": 1.4}, "care": 1.2},
    "断": {"desc": "宜决断", "detail": "了结拖着的事，放下不要的。",
           "energy": {}, "domains": {}, "care": 0.9, "skipped": 1.6},
    "慎": {"desc": "宜谨慎", "detail": "不做大额决定，不起争执，稳住。",
           "energy": {"high": 0.9}, "domains": {"器材事业": 0.7}, "care": 1.1, "deal": "慎"},
}

POSITIONS = ["初爻（开始、根基）", "二爻（内里、家）", "三爻（转折、险处）",
             "四爻（靠近外界）", "五爻（核心、主位）", "上爻（终了、过头）"]

QUESTIONS = {
    "进": ["你最想推进的那件事，第一步是什么？", "推进它，会不会挤占你和她的时间？"],
    "守": ["手上有哪件事，做完会让你安心？", "有没有一件你正想开始、其实可以再等等的事？"],
    "养": ["你的身体现在需要什么？", "如果今天什么都不做，你会感到愧疚吗？为什么？"],
    "合": ["她最近在想什么？你问过吗？", "有没有一个很久没联系、但想念的人？"],
    "学": ["最近有什么是你真正想弄懂的？", "Part 3 里哪一块，学了会让你更踏实？"],
    "省": ["这件事里，你最在意的到底是什么？", "如果一年后回看，现在的你会希望自己怎么做？"],
    "断": ["有什么事你已经拖了很久？它还值得做吗？", "放下它，你会失去什么，又会得到什么？"],
    "慎": ["你现在是不是有点急？急的原因是什么？", "最坏的情况是什么？你承受得起吗？"],
}


def _weight() -> float:
    cfg = config.rules().get("yi", {})
    return 0.0 if not cfg.get("enabled", True) else float(cfg.get("weight", 0.5))


def hexagram_of(bits: tuple) -> int:
    """bits：自下而上六爻（1 阳 0 阴）→ 文王卦序 1-64。"""
    lower, upper = tuple(bits[:3]), tuple(bits[3:])
    for i, (_, up, low, *_rest) in enumerate(HEXAGRAMS):
        if TRIGRAMS[up][0] == upper and TRIGRAMS[low][0] == lower:
            return i + 1
    raise ValueError(bits)


def info(n: int) -> dict:
    name, up, low, xiang, stance, plain = HEXAGRAMS[n - 1]
    full = f"{name}为{TRIGRAMS[up][1]}" if up == low else f"{TRIGRAMS[up][1]}{TRIGRAMS[low][1]}{name}"
    return {"n": n, "name": name, "full": full, "symbol": chr(0x4DC0 + n - 1), "upper": up, "lower": low,
            "xiang": xiang, "stance": stance, "stance_desc": STANCES[stance]["desc"], "plain": plain,
            "bits": list(TRIGRAMS[low][0] + TRIGRAMS[up][0])}


def toss_line() -> int:
    """三枚铜钱：正面 3，反面 2。"""
    return sum(3 if secrets.randbelow(2) else 2 for _ in range(3))


def cast(lines: list[int] | None = None) -> dict:
    lines = lines or [toss_line() for _ in range(6)]
    bits = tuple(1 if v in (7, 9) else 0 for v in lines)
    moving = [i for i, v in enumerate(lines) if v in (6, 9)]
    changed_bits = tuple(1 - b if i in moving else b for i, b in enumerate(bits))
    primary = info(hexagram_of(bits))
    result = {"lines": lines, "moving": moving, "primary": primary,
              "moving_positions": [POSITIONS[i] for i in moving]}
    if moving:
        result["changed"] = info(hexagram_of(changed_bits))
    return result


def _change_note(r: dict) -> str:
    k = len(r["moving"])
    if k == 0:
        return "六爻皆静：处境稳定，就按本卦的意思去做。"
    if k <= 2:
        return f"有 {k} 个变爻（{'、'.join(r['moving_positions'])}）：局部在变，留意这些位置。之卦是事情可能的走向。"
    if k <= 4:
        return f"有 {k} 个变爻：变化正在发生，本卦是现在，之卦是正在形成的局面，两者都要看。"
    return f"有 {k} 个变爻：大变之时，现在的局面不会持续太久，多看之卦。"


def interpret(r: dict, question: str | None = None) -> dict:
    p = r["primary"]
    stance = p["stance"]
    out = {
        "title": f"{p['symbol']} {p['full']}" + (f" → {r['changed']['symbol']} {r['changed']['full']}" if r.get("changed") else ""),
        "xiang": p["xiang"],
        "plain": p["plain"],
        "stance": stance,
        "stance_text": f"{STANCES[stance]['desc']}：{STANCES[stance]['detail']}",
        "change": _change_note(r),
        "questions": QUESTIONS[stance],
        "note": "卦是一面镜子，不是预言。它给你一个新角度；事实和你的判断仍然最重要。",
    }
    if r.get("changed"):
        c = r["changed"]
        out["trend"] = f"走向「{c['name']}」：{c['xiang']} {c['plain']}"
    return out


def ai_reflect(conn, r: dict, question: str, context: str) -> str | None:
    p = r["primary"]
    changed = r.get("changed")
    return llm.complete_text(
        "你熟读《周易》，但你诚实：你知道卦不能预测未来。你的角色是借卦象当一面镜子，帮一位想做'君子'的年轻建筑师"
        "看清他问的这件事。用中文，300 字以内：1) 用一两句话讲这一卦（及之卦）描述的处境；2) 结合他的真实情况，"
        "指出这个角度可能照见了什么他没想到的；3) 给出一种'姿态'而不是指令；4) 两个自问。"
        "涉及钱、健康、感情的重大决定，提醒他以事实为准。不说吉凶，不说保证。",
        f"他问：{question}\n本卦：{p['full']}，《象》曰：{p['xiang']}\n"
        + (f"之卦：{changed['full']}，《象》曰：{changed['xiang']}\n" if changed else "")
        + f"变爻：{'、'.join(r['moving_positions']) or '无'}\n\n他的近况：\n{context}",
        effort="medium",
    )


# ------------------------------------------------------------------ 记录与今日之卦

def save(conn, r: dict, question: str | None, kind: str) -> int:
    cid = conn.execute(
        "INSERT INTO casts(at, day, kind, question, lines, hex, changed, stance) VALUES(?,?,?,?,?,?,?,?)",
        (db.now(), db.today(), kind, question, json.dumps(r["lines"]), r["primary"]["n"],
         r["changed"]["n"] if r.get("changed") else None, r["primary"]["stance"]),
    ).lastrowid
    conn.commit()
    return cid


def load(row: dict) -> dict:
    return cast(json.loads(row["lines"]))


def today_cast(conn, day: str | None = None) -> dict | None:
    row = conn.execute("SELECT * FROM casts WHERE kind = 'day' AND day = ? ORDER BY id DESC LIMIT 1",
                       (day or db.today(),)).fetchone()
    if not row:
        return None
    r = load(dict(row))
    return {"id": row["id"], **r, "reading": interpret(r)}


def cast_today(conn) -> dict:
    """每天只起一次卦：起过就返回当天那一卦（命不能重抽）。"""
    existing = today_cast(conn)
    if existing:
        return existing
    r = cast()
    cid = save(conn, r, None, "day")
    return {"id": cid, **r, "reading": interpret(r)}


def history(conn, limit: int = 20) -> list[dict]:
    out = []
    for row in db.rows(conn.execute("SELECT * FROM casts ORDER BY id DESC LIMIT ?", (limit,))):
        p = info(row["hex"])
        c = info(row["changed"]) if row["changed"] else None
        out.append({**row, "title": f"{p['symbol']} {p['name']}" + (f" → {c['symbol']} {c['name']}" if c else "")})
    return out


def note_outcome(conn, cast_id: int, outcome: str) -> None:
    conn.execute("UPDATE casts SET outcome = ? WHERE id = ?", (outcome, cast_id))
    conn.commit()


def today_stance(conn) -> str | None:
    t = today_cast(conn)
    return t["primary"]["stance"] if t else None


def factor(stance: str | None, domain: str | None, energy: str | None = None, kind: str = "task",
           skips: int = 0) -> float:
    """姿态对一条建议的乘数（已按 weight 缩放；weight=0 时恒为 1）。"""
    if not stance:
        return 1.0
    s = STANCES[stance]
    if kind == "care":
        m = s.get("care", 1.0)
    else:
        m = s["domains"].get(domain or "", 1.0) * s["energy"].get(energy or "", 1.0)
        if skips and s.get("skipped"):
            m *= s["skipped"]
    return 1 + _weight() * (m - 1)
