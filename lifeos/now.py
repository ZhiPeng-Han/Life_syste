"""此刻：系统的新中心。

不是"今天你应该做什么"，而是"你现在怎么样？想的话，我给你一个可能性"。
- 感受是正当的理由：累了就建议休息，而不是塞一件"低能量任务"
- 一次只给一个建议，可以换、可以不做
- 杂事放在"口袋"里，跳过三次会问你要不要放下
"""

import random
import re
from datetime import date, datetime, timedelta

from . import config, daily, db, family, llm, mind, photos, planner, relationship, shi, tasks, tianshi, yi

FEELINGS = {
    "充沛": {"icon": "☀️", "energy": 8, "mood": 8, "allow": {"high", "medium", "low"}, "care": 0.6,
             "say": "你状态不错"},
    "平静": {"icon": "🌤", "energy": 6, "mood": 7, "allow": {"high", "medium", "low"}, "care": 1.0,
             "say": "你现在挺平静"},
    "疲惫": {"icon": "🌙", "energy": 3, "mood": 5, "allow": {"low"}, "care": 3.0,
             "say": "你有点累了"},
    "烦躁": {"icon": "🌪", "energy": 5, "mood": 3, "allow": {"low", "medium"}, "care": 2.5,
             "say": "你有点烦"},
    "低落": {"icon": "🌧", "energy": 3, "mood": 3, "allow": {"low"}, "care": 3.5,
             "say": "你心情不太好"},
}
# 心情低落时不建议碰的领域（除非真的有期限）
HEAVY_WHEN_LOW = {"器材事业", "建筑工作", "自媒体"}


def _is_evening(at: datetime) -> bool:
    return at.hour >= 18


def log_state(conn, feeling: str, minutes: int | None = None, note: str | None = None) -> None:
    conn.execute("INSERT INTO states(at, feeling, minutes, note) VALUES(?,?,?,?)",
                 (db.now(), feeling, minutes, note))
    conn.commit()


def _due_soon(task: dict, today: date, days: int = 1) -> bool:
    return bool(task.get("due")) and date.fromisoformat(task["due"]) <= today + timedelta(days=days)


def _task_reason(task: dict, feeling: str, today: date) -> str:
    parts = []
    if _due_soon(task, today):
        d = (date.fromisoformat(task["due"]) - today).days
        parts.append("它有期限" + ("，今天就到" if d == 0 else "，明天就到" if d == 1 else "，日期已经过了，还要做吗？"))
    if task.get("energy") == "low":
        parts.append("不太费脑")
    if task.get("domain") == "关系":
        parts.append("和她有关")
    parts.append(f"大约 {task.get('est_minutes') or 30} 分钟")
    if (task.get("skips") or 0) >= 2:
        parts.append("你跳过它几次了，如果不重要也可以放下")
    return f"{FEELINGS[feeling]['say']}。" + "，".join(parts) + "。"


def _tian_note(stance: str | None, mom: dict, domain: str | None, f: float) -> str:
    notes = []
    if stance and abs(f - 1) >= 0.05:
        notes.append(f"今日卦象{yi.STANCES[stance]['desc']}")
    d = shi.describe(mom, domain)
    if d:
        notes.append(d)
    return f"（{'；'.join(notes)}）" if notes else ""


def candidates(conn, feeling: str, minutes: int | None = None, at: datetime | None = None,
               place: str | None = None) -> list[dict]:
    """place：地利——你此刻在哪里。给了就只留在那里做得了的事（有期限的事除外）。"""
    f = FEELINGS.get(feeling, FEELINGS["平静"])
    at = at or datetime.now()
    today = at.date()
    ctx = planner.context(conn)
    stance = ctx["stance"]
    wx = shi.weather(conn, today)
    pulse = mind.pulse(conn, at)
    out = []
    for t in db.rows(conn.execute("SELECT * FROM tasks WHERE status = 'todo'")):
        if minutes is not None and (t["est_minutes"] or 30) > minutes:
            continue
        urgent = _due_soon(t, today)
        if t["energy"] not in f["allow"] and not urgent:
            continue
        if feeling in ("低落", "疲惫") and t["domain"] in HEAVY_WHEN_LOW and not urgent:
            continue
        need = tianshi.need_of(t["title"], t["domain"])
        if not tianshi.fits(place, need) and not urgent:
            continue
        score = planner.task_score(t, today, planner.slot_energy(at.hour * 60 + at.minute))
        if urgent:
            score *= 3
        if t["domain"] == "关系":
            # 烦躁、低落的时候先照顾好自己，再去照顾关系；平静的晚上最适合和她相关的事
            score *= 0.4 if feeling in ("烦躁", "低落") else 1.3 if _is_evening(at) else 1.0
        score /= 1 + 0.4 * (t["skips"] or 0)
        # 有期限的事是事实：天时不改变它，也不给它加注
        tian = 1.0 if urgent else yi.factor(stance, t["domain"], t["energy"], "task", t["skips"] or 0) * shi.factor(ctx["mom"], t["domain"])
        note = "" if urgent else _tian_note(stance, ctx["mom"], t["domain"], tian)
        # 记忆的影响：最近常想起的事、她的愿望、和她之间的安静、常和累的日子一起出现的事
        mf, mnote = (1.0, "") if urgent else mind.nudge(pulse, t["title"], t["domain"], feeling)
        out.append({"kind": "task", "task_id": t["id"], "title": t["title"], "domain": t["domain"], "energy": t["energy"],
                    "minutes": t["est_minutes"] or 30, "score": score * tian * mf, "need": need, "urgent": urgent,
                    "due_in": (date.fromisoformat(t["due"]) - today).days if t["due"] else None,
                    "tian_note": note.strip("（）"), "mind_note": mnote, "skips": t["skips"] or 0,
                    "reason": _task_reason(t, feeling, today) + note + (f"（{mnote}）" if mnote else "")})
    for i, o in enumerate(config.rules().get("now_options", [])):
        if feeling not in o.get("feelings", []):
            continue
        if minutes is not None and o.get("minutes", 0) > minutes:
            continue
        when = o.get("when", "any")
        if (when == "evening" and not _is_evening(at)) or (when == "day" and (at.hour < 7 or at.hour >= 18)):
            continue
        if o.get("outdoor") and wx and wx.get("wet"):
            continue  # 外面在下雨
        need = o.get("need") or ("leave" if o.get("outdoor") else tianshi.need_of(o["title"], None))
        if not tianshi.fits(place, need):
            continue
        tian = yi.factor(stance, None, kind="care")
        out.append({"kind": "care", "option_id": i, "title": o["title"], "domain": "此刻", "need": need,
                    "minutes": o.get("minutes", 0), "score": 4.0 * f["care"] * tian,
                    "tian_note": _tian_note(stance, {}, None, tian).strip("（）"),
                    "reason": f"{f['say']}。这不是任务，是照顾一下自己。" + _tian_note(stance, {}, None, tian)})
    return sorted(out, key=lambda c: -c["score"])


# ------------------------------------------------------------------ 此刻宜：天时、地利、人和

OUTSIDE = {"leave", "out", "camera"}


def _last_feeling(conn, at: datetime) -> str | None:
    row = conn.execute("SELECT feeling, at FROM states ORDER BY id DESC LIMIT 1").fetchone()
    if row and row[0] in FEELINGS and row[1] >= (at - timedelta(hours=4)).isoformat(timespec="seconds"):
        return row[0]
    return None


def _active_block(at: datetime) -> dict | None:
    m = at.hour * 60 + at.minute
    return next((b for b in planner.blocks_for(at.date()) if b["start"] <= m < b["end"]), None)


def right_now(conn, at: datetime | None = None, place: str | None = None, feeling: str | None = None,
              her: bool | None = None, exclude: list[str] | None = None, minutes: int | None = None) -> dict:
    """不用先回答任何问题：根据天时（时辰、天光、天气、时令之卦、今日之卦、节律）、
    地利（你在哪里、这件事要在哪里做）、人和（你最近的感受、她在不在身边）推荐此刻去做什么。"""
    at = at or datetime.now()
    t = tianshi.now(conn, at)
    if place:
        tianshi.set_place(conn, place)
        guessed = False
    else:
        place, guessed = tianshi.guess_place(conn, at)
    if her is not None:
        tianshi.set_with_her(conn, her)
    else:
        her = tianshi.with_her(conn, at)
    known = feeling or _last_feeling(conn, at)
    feel = known or "平静"
    season_stance = t["season"]["hex"]["stance"]
    block = _active_block(at)
    wx = t["weather"] or {}
    cands = candidates(conn, feel, minutes, at, place)

    # 天时本身给出的可能性
    late = t["part"] == "深夜" or at.hour >= 23
    if late:
        cands.append({"kind": "moment", "key": "m:sleep", "title": "收一收，说晚安，去睡吧", "domain": "此刻", "need": "any",
                      "minutes": 15, "score": 50.0, "tian_note": f"已经{t['shichen']}了", "reason": "夜深了。明天的事，明天的你会做。"})
    if block and not late:
        kind_title = {"关系": "放下手机，好好和她在一起", "建筑工作": "专心做手上的项目，别的先放一放"}.get(
            block["domain"] or "", "就做这件事，别的先放一放")
        cands.append({"kind": "block", "key": f"b:{block['title']}", "title": f"{block['title']}：{kind_title}",
                      "domain": block["domain"], "need": "any", "minutes": block["end"] - at.hour * 60 - at.minute,
                      "score": 6.0 if block["kind"] == "fixed" else 24.0 if block["domain"] == "关系" else 8.0,
                      "tian_note": f"现在是你给自己定下的「{block['title']}」的时间（到 {planner._fmt(block['end'])}）",
                      "reason": "这是你自己定下的节律，不是系统安排的。想换也可以。"})
    if t["golden"] and not wx.get("wet_now") and place in ("家", "外面") and feel in ("平静", "充沛", "低落"):
        cands.append({"kind": "moment", "key": "m:golden", "title": "带上相机出去，拍 20 分钟黄金时刻的光", "domain": "此刻",
                      "need": "camera", "minutes": 20, "score": 13.0,
                      "tian_note": t["light"], "reason": "一天里光最好的时候就这一会儿，错过就要等明天。"})

    out = []
    for c in cands:
        key = c.get("key") or _key(c)
        if key in set(exclude or []):
            continue
        need = c.get("need", "any")
        score = c["score"]
        tian = [c["tian_note"]] if c.get("tian_note") else []
        ren = []
        if not tianshi.fits(place, need):
            # 只有有期限的事会走到这里：它仍然在，但等你到了合适的地方再做
            score *= 0.35
            ren.append(f"等你{'出门' if need in OUTSIDE else '回到家' if need == 'home' else '坐到电脑前'}时再做")
        if c.get("urgent") and c.get("due_in", 0) >= 1:
            score *= 0.6  # 明天才到期：今天做完更安心，但不必压过此刻难得的事
        if block and block["kind"] == "fixed" and c["kind"] == "task" and c.get("domain") != block["domain"] and not c.get("urgent"):
            score *= 0.5
        if c["kind"] in ("task", "care") and not c.get("urgent"):
            # 时令之卦：一年里阴阳消长的大节奏，影响只有今日之卦的一半
            sf = 1 + 0.5 * (yi.factor(season_stance, c.get("domain"), c.get("energy"),
                                      "care" if c["kind"] == "care" else "task") - 1)
            score *= sf
            if abs(sf - 1) >= 0.05:
                tian.append(f"{t['season']['hex']['name']}卦当令，{t['season']['hex']['stance_desc']}")
            if block and c.get("domain") == block["domain"]:
                score *= 1.8
                tian.append(f"正是「{block['title']}」的时间")
            if late and c["kind"] == "task":
                score *= 0.2
        if need in OUTSIDE and c["kind"] != "moment":
            if wx.get("wet_now"):
                if need != "out":
                    continue
                score *= 0.6
                tian.append("外面在下雨")
            elif not t["daylight"]:
                score *= 0.6 if need == "out" else 0.5
                tian.append("天已经黑了")
            elif wx.get("dry_soon") or not wx:
                score *= 1.3
                tian.append("天亮着" + ("，接下来两小时不下雨" if wx else ""))
        if her:
            if re.search(r"发.{0,3}消息|打电话|视频", c["title"]):
                continue  # 她就在身边
            if c.get("domain") == "关系" or "她" in c["title"]:
                score *= 1.6
                ren.append("她就在身边")
            elif c["kind"] == "task" and not c.get("urgent"):
                score *= 0.6
        if known:
            ren.append(FEELINGS[known]["say"])
        if c.get("mind_note"):
            ren.append(c["mind_note"])
        if c.get("urgent"):
            ren.append("它有期限")
        dili = f"你在{place}" + ("（猜的）" if guessed else "") + f"，这件事{tianshi.NEED_LABEL.get(need, '哪里都能做')}"
        out.append({**c, "key": key, "score": round(score, 3),
                    "why": [{"k": "天时", "t": "；".join(dict.fromkeys(x for x in tian if x)) or "此时无妨"},
                            {"k": "地利", "t": dili},
                            {"k": "人和", "t": "；".join(ren) or "还不知道你现在感觉怎样，点一下下面的感受会更准"}]})
    out.sort(key=lambda c: -c["score"])
    seen_titles: set = set()
    out = [c for c in out if not (c["title"] in seen_titles or seen_titles.add(c["title"]))]
    return {"tian": t, "line": tianshi.line(t), "place": place, "guessed": guessed,
            "places": {k: v["icon"] for k, v in tianshi.PLACES.items()}, "feeling": known, "with_her": her,
            "block": block["title"] if block else None,
            "pick": out[0] if out else None, "alts": out[1:3]}


def render_right_now(r: dict) -> str:
    lines = [f"🧭 此刻 · {r['line']}"]
    p = r["pick"]
    if not p:
        return "\n".join(lines + ["🍃 什么都不用做。好好待着。"])
    lines.append(f"此刻宜：{p['title']}")
    lines += [f"  {w['k']}：{w['t']}" for w in p["why"]]
    if r["alts"]:
        lines.append("或者：" + "；".join(a["title"] for a in r["alts"]))
    return "\n".join(lines)


def suggest(conn, feeling: str, minutes: int | None = None, exclude: list[str] | None = None,
            decide: bool = False, at: datetime | None = None, place: str | None = None) -> dict:
    """给一个可能性。decide=True 表示"帮我决定"：直接选分数最高的，不再随机。"""
    exclude = set(exclude or [])
    cands = [c for c in candidates(conn, feeling, minutes, at, place) if _key(c) not in exclude]
    if not cands:
        return {"kind": "none", "title": "什么都不用做", "reason": "口袋里没有适合此刻的事。那就好好待着吧。", "key": "none"}
    if decide:
        pick = cands[0]
    else:
        # 在前几个里按分数加权随机，避免每次都是同一张脸
        top = cands[:4]
        pick = random.choices(top, weights=[c["score"] for c in top])[0]
    pick["key"] = _key(pick)
    pick["feeling"] = feeling
    return pick


def _key(c: dict) -> str:
    if c.get("key"):
        return c["key"]
    return f"t{c['task_id']}" if c["kind"] == "task" else f"o{c['option_id']}"


def skip(conn, task_id: int) -> dict:
    conn.execute("UPDATE tasks SET skips = COALESCE(skips, 0) + 1 WHERE id = ?", (task_id,))
    conn.commit()
    skips = conn.execute("SELECT skips FROM tasks WHERE id = ?", (task_id,)).fetchone()[0]
    return {"skips": skips, "ask_let_go": skips >= 3}


# "现在不想"时可选的温和自问（借鉴 Super Productivity 的拖延助手）。可以完全跳过。
SKIP_REASONS = {
    "太大了": "那就拆小：写下它的第一小步，我把这一小步放进口袋。",
    "不知道从哪开始": "写下你能想到的第一个动作，哪怕是\"打开文件\"。",
    "有点抗拒": "只做 5 分钟，到点就可以停。不想停再继续。",
    "现在不是时候": "好，它会在口袋里等你。",
    "就是不想": "没关系。不想也是一种真实的感受。",
}


def skip_reason(conn, task_id: int, reason: str, first_step: str | None = None) -> dict:
    conn.execute("INSERT INTO skip_reasons(task_id, reason, at) VALUES(?,?,?)", (task_id, reason, db.now()))
    conn.commit()
    out = {"reply": SKIP_REASONS.get(reason, "好。")}
    if first_step and first_step.strip():
        t = conn.execute("SELECT domain, project FROM tasks WHERE id = ?", (task_id,)).fetchone()
        out["new_task_id"] = tasks.add(conn, f"第一步：{first_step.strip()}", t[0] if t else "生活维持", 4, "low", 10,
                                       project=t[1] if t else None, source="first_step")
    return out


def skip_patterns(conn) -> list[dict]:
    return db.rows(conn.execute("SELECT reason, COUNT(*) n FROM skip_reasons GROUP BY reason ORDER BY n DESC"))


def let_go(conn, task_id: int) -> None:
    """放下不是失败，是选择。"""
    conn.execute("UPDATE tasks SET status = 'let_go', done_at = ? WHERE id = ?", (db.now(), task_id))
    conn.commit()


# ------------------------------------------------------------------ 口袋

def pocket(conn, at: date | None = None) -> dict:
    today = at or date.today()
    todo = db.rows(conn.execute("SELECT * FROM tasks WHERE status = 'todo' ORDER BY priority DESC, id"))
    with_date = sorted((t for t in todo if t["due"]), key=lambda t: t["due"])
    groups: dict = {}
    for t in todo:
        if not t["due"]:
            groups.setdefault(t["domain"] or "其他", []).append(t)
    for t in with_date:
        t["days_left"] = (date.fromisoformat(t["due"]) - today).days
    return {"dated": with_date, "groups": groups, "count": len(todo)}


# ------------------------------------------------------------------ 回响：过去的记忆在今天轻轻出现

def echo(conn, at: date | None = None) -> str | None:
    today = at or date.today()
    options = []
    for label, delta in (("一年前的今天", 365), ("一个月前的今天", 30), ("一周前的今天", 7)):
        day = (today - timedelta(days=delta)).isoformat()
        for m in db.rows(conn.execute(
            "SELECT content FROM memories WHERE substr(occurred_at,1,10) = ? AND type NOT IN ('summary', 'reflection') "
            f"AND status NOT IN {mind.INACTIVE_SQL} AND importance >= 5", (day,)
        )):
            options.append(f"{label}：{m['content']}")
    for w in relationship.wishes(conn):
        days = (today - date.fromisoformat(w["mentioned_at"])).days
        if days >= 10 and w["status"] == "想法":
            options.append(f"{days} 天前她说「{w['content']}」，还记得吗？")
    cutoff = (today - timedelta(days=7)).isoformat()
    for m in db.rows(conn.execute(
        "SELECT content, occurred_at FROM memories WHERE occurred_at < ? AND importance >= 7 "
        f"AND type NOT IN ('summary', 'reflection') AND status NOT IN {mind.INACTIVE_SQL} ORDER BY RANDOM() LIMIT 3",
        (cutoff,),
    )):
        options.append(f"{m['occurred_at'][:10]}：{m['content']}")
    return random.choice(options) if options else None


# ------------------------------------------------------------------ 早安：一段简短的问候，不是时间表

def anchors(on: date, after_minute: int = 0) -> list[str]:
    """今天还没到的节律（不含固定的上班时间）。"""
    return [f"{b['title']}（{planner._fmt(b['start'])}）" for b in planner.blocks_for(on)
            if b["kind"] != "fixed" and b["start"] >= after_minute]


def _countdown(days: int) -> str:
    return "就是今天" if days == 0 else f"还有 {days} 天"


def morning(conn, on: date | None = None) -> str:
    on = on or date.today()
    p = pocket(conn, on)
    term = shi.solar_term(on)
    alm = shi.almanac(on)
    note = daily.notes(conn, on)
    lines = [f"早安。今天是周{'一二三四五六日'[on.weekday()]}" + (f"，农历{alm['lunar'].split(' ')[-1]}" if alm else "")
             + f"，{term['name']}时节。{term['tip']}"]
    if note.get("morning"):
        lines.append(f"💬 {note['morning']}")
    sea = tianshi.season(on)
    lines.append(f"🌗 {sea['hex']['symbol']} {sea['hex']['name']}卦当令（{sea['month']}）：{sea['text']}"
                 f"　{sea['term']}{['初', '二', '三'][sea['hou']['n'] - 1]}候：{sea['hou']['text']}")
    wx = shi.weather(conn, on)
    sn = tianshi.sun(on)
    if wx or sn:
        parts = [f"{wx['city']}{wx['label']}，{wx['tmin']}–{wx['tmax']}°C"] if wx else []
        if sn:
            parts.append(f"日出 {sn['rise']:%H:%M}，日落 {sn['set']:%H:%M}，黄金时刻 {sn['golden']:%H:%M} 起")
        lines.append(f"{wx['icon'] if wx else '☀️'} " + "；".join(parts))
    tc = yi.today_cast(conn, on.isoformat())
    if tc:
        p0 = tc["primary"]
        lines.append(f"☯ 今日之卦：{p0['symbol']} {p0['full']}，{p0['stance_desc']}。{p0['xiang']}")
    else:
        lines.append("☯ 想的话，心里想着今天，起一卦。")
    a = [x for x in anchors(on) if "❤️" in x or "🍳" in x]
    if a:
        lines.append("🌿 今天的节律：" + "；".join(a))
    for d in relationship.upcoming_dates(conn, on, horizon=14):
        lines.append(f"🎁 {d['name']}还有 {d['days_left']} 天")
    hz = family.horizons(conn, on)
    if hz["ahead"]:
        lines.append("✨ 盼头：" + "；".join(f"{h['title']}（{_countdown(h['days_left'])}）" for h in hz["ahead"][:2]))
    elif hz["empty_soon"]:
        lines.append("✨ 地平线上空了。想不想放一件期待的事？")
    for r in family.rituals(conn, on):
        if r["gentle"]:
            lines.append(f"🕯 {'今天是' if r['today'] else '这一期还没'}「{r['name']}」")
    ph = photos.on_this_day(conn, on, limit=1)
    if ph:
        lines.append(f"📷 {ph[0]['years_ago']} 年前的今天，你拍过照片。")
    soon = [t for t in p["dated"] if t["days_left"] <= 2]
    if soon:
        lines.append("⏳ 真正有期限的：" + "；".join(
            f"{t['title']}（{'今天' if t['days_left'] == 0 else '明天' if t['days_left'] == 1 else '已过期' if t['days_left'] < 0 else '后天'}）" for t in soon))
    lines.append(f"🫧 口袋里还有 {p['count']} 件事，它们会等你。")
    e = echo(conn, on)
    if e:
        lines.append(f"✨ {e}")
    fresh = [r for r in mind.reflections(conn) if r["occurred_at"][:10] >= (on - timedelta(days=1)).isoformat()]
    if fresh:
        lines.append(f"🧠 我注意到：{fresh[0]['content']}")
    top = sorted(shi.trends(conn, 50), key=lambda t: -t["weight"])
    if top and top[0]["weight"] >= 1:
        t = top[0]
        lines.append(f"🌏 大势：{t['title']}（{'顺' if t['direction'] > 0 else '逆' if t['direction'] < 0 else '观'}）")
    if note.get("shi"):
        lines.append(f"🧭 {note['shi']}")
    if note.get("her"):
        lines.append(f"❤️ {note['her']}")
    lines.append("需要的时候问我「此刻宜」。什么都不问，也很好。")
    return "\n".join(lines)


def render_suggestion(s: dict) -> str:
    if s["kind"] == "none":
        return f"🍃 {s['title']}\n{s['reason']}"
    icon = "🌿" if s["kind"] == "care" else "🫧"
    return f"{icon} {s['title']}\n{s['reason']}\n（不想做也没关系。）"


def ai_note(conn, feeling: str, note: str | None, suggestion: dict) -> str | None:
    """配置了 Claude 时，用一两句真正懂你的话代替模板理由。"""
    if not note:
        return None
    remembered = mind.context(conn, f"{note} {suggestion['title']}", k=10)
    return llm.complete_text(
        "你是一个温和、克制的朋友，不是效率教练。用户此刻说了自己的状态。用一两句中文回应他的感受，"
        "然后自然地提一下这个建议（他可以不做）。不说教，不用感叹号，不超过 60 字。",
        f"他的感受：{feeling}。他说：{note}\n建议：{suggestion['title']}\n\n你记得的（只在自然时提起，不要罗列）：\n{remembered}",
        effort="low",
    )
