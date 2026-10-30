"""每日规划器。

1. 铺设固定块与受保护块（rules.toml 里的 blocks）
2. 计算空闲时段，按能量曲线匹配任务（上午=高能量，下午=中，晚上=低）
3. 同领域任务连排，减少切换；只排满 (1 - buffer_ratio) 的空闲时间
4. 生成"今天只需记住的 3 件事" + 各种提醒（她、复习、滞销、待确认）
"""

from datetime import date, datetime, timedelta

from . import business, cards, config, db, decisions, meals, memory, relationship

ENERGY_RANK = {"high": 3, "medium": 2, "low": 1}


def _t(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def slot_energy(start_min: int) -> str:
    return "high" if start_min < 12 * 60 else "medium" if start_min < 17 * 60 else "low"


def blocks_for(on: date) -> list[dict]:
    wd = on.isoweekday()
    out = []
    for b in config.rules().get("blocks", []):
        if wd in b.get("weekdays", []):
            out.append({"start": _t(b["start"]), "end": _t(b["end"]), "title": b["name"], "domain": b.get("domain"),
                        "kind": "fixed" if b.get("fixed") else "protected"})
    return sorted(out, key=lambda b: b["start"])


def free_slots(blocks: list[dict]) -> list[tuple[int, int]]:
    g = config.rules().get("general", {})
    cursor, end = _t(g.get("day_start", "07:00")), _t(g.get("day_end", "23:00"))
    slots = []
    for b in blocks:
        if b["start"] - cursor >= 15:
            slots.append((cursor, b["start"]))
        cursor = max(cursor, b["end"])
    if end - cursor >= 15:
        slots.append((cursor, end))
    return slots


def task_score(task: dict, on: date, slot_e: str | None = None, prev_domain: str | None = None) -> float:
    s = task["priority"] * config.domain_weight(task.get("domain") or "")
    if task.get("due"):
        days = (date.fromisoformat(task["due"]) - on).days
        s *= 2.0 if days < 0 else 1.8 if days == 0 else 1.4 if days <= 3 else 1.0
    if slot_e:
        diff = ENERGY_RANK.get(task.get("energy", "medium"), 2) - ENERGY_RANK[slot_e]
        s *= 1.2 if diff == 0 else 0.9 if diff < 0 else 0.6  # 高能量任务放进低能量时段惩罚最大
    if task.get("domain") == "关系" and slot_e == "high":
        s *= 0.4  # 和她有关的事放到晚上/约会时
    if prev_domain and task.get("domain") == prev_domain:
        s += 0.5  # 少切换
    return s


def plan(on: date | None = None, conn=None, record: bool = True) -> dict:
    conn = conn or db.connect()
    on = on or date.today()
    blocks = blocks_for(on)
    slots = free_slots(blocks)
    tasks = db.rows(conn.execute("SELECT * FROM tasks WHERE status = 'todo'"))
    tasks = [t for t in tasks if not t.get("due") or date.fromisoformat(t["due"]) >= on - timedelta(days=30)]
    budget = sum(e - s for s, e in slots) * (1 - config.rules().get("general", {}).get("buffer_ratio", 0.2))

    scheduled, used, remaining = [], 0, list(tasks)
    # 和她有关的任务直接挂到今天的约会块里，变成"可以一起做/聊的事"，不占用空闲时间
    love_blocks = [b for b in blocks if b["domain"] == "关系"]
    if love_blocks:
        together = sorted((t for t in remaining if t["domain"] == "关系"), key=lambda t: -task_score(t, on))[:2]
        love_blocks[0]["with"] = [{"id": t["id"], "title": t["title"]} for t in together]
        for t in together:
            remaining.remove(t)
    for s, e in slots:
        cursor, prev = s, None
        while remaining and used < budget:
            room = e - cursor
            fits = [t for t in remaining if (t["est_minutes"] or 30) <= room]
            if not fits:
                break
            best = max(fits, key=lambda t: task_score(t, on, slot_energy(cursor), prev))
            dur = best["est_minutes"] or 30
            scheduled.append({"start": cursor, "end": cursor + dur, "title": best["title"], "domain": best["domain"],
                              "kind": "task", "task_id": best["id"]})
            cursor += dur
            used += dur
            prev = best["domain"]
            remaining.remove(best)

    timeline = sorted(blocks + scheduled, key=lambda b: b["start"])
    for b in timeline:
        b["time"] = f"{_fmt(b['start'])}–{_fmt(b['end'])}"

    top3 = _top3(on, blocks, scheduled, tasks)
    nudges = _nudges(conn, on)
    result = {
        "date": on.isoformat(),
        "weekday": "一二三四五六日"[on.weekday()],
        "top3": top3,
        "timeline": timeline,
        "unscheduled": [t["title"] for t in remaining][:10],
        "nudges": nudges,
        "dinner": meals.tonight(conn, on),
        "autonomy_level": decisions.LEVEL_NAMES[decisions.level(conn, "daily_plan")],
    }
    if record:
        key = f"plan:{on.isoformat()}"
        sid = db.get_meta(conn, key)
        if sid is None:
            sid = decisions.suggest(conn, "daily_plan", " / ".join(top3), "规则 + 任务评分自动生成")
            db.set_meta(conn, key, sid)
        result["suggestion_id"] = sid
    return result


def _top3(on, blocks, scheduled, tasks) -> list[str]:
    out = []
    love = [b for b in blocks if b["domain"] == "关系"]
    if love:
        out.append(f"❤️ {_fmt(love[0]['start'])} {love[0]['title']}")
    ranked = sorted(scheduled, key=lambda b: -task_score(next(t for t in tasks if t["id"] == b["task_id"]), on))
    for b in ranked:
        if len(out) >= 3:
            break
        out.append(f"{_fmt(b['start'])} {b['title']}")
    deep = [b for b in blocks if b["kind"] == "protected" and b["domain"] != "关系"]
    for b in deep:
        if len(out) >= 3:
            break
        out.append(f"{_fmt(b['start'])} {b['title']}")
    return out[:3]


def _nudges(conn, on: date) -> list[str]:
    out = []
    for d in relationship.upcoming_dates(conn, on, horizon=45):
        if d["remind_today"] or d["days_left"] <= 7:
            out.append(f"🎁 {d['person']}的「{d['name']}」还有 {d['days_left']} 天（{d['date']}）")
    ideas = relationship.ideas(conn, on)
    if ideas:
        out.append(f"💡 今日微惊喜：{ideas[0]['idea']}（关于「{ideas[0]['wish']}」）")
    dinner = meals.tonight(conn, on)
    if dinner and dinner["minutes"]:
        out.append(f"🍳 今晚：{dinner['dish']}{'（轻食）' if dinner['light'] else ''}")
    c = cards.stats(conn)
    if c["due_today"]:
        out.append(f"📚 Part 3 卡片到期 {c['due_today']} 张：lifeos card review")
    s = business.stats(conn)
    if s["stale"]:
        out.append(f"📦 滞销 {len(s['stale'])} 件（{', '.join(s['stale'][:3])}），考虑降价或换平台")
    n = len(memory.pending_confirm(conn))
    if n:
        out.append(f"❓ 有 {n} 条记忆 AI 不太确定，请确认：lifeos confirm")
    dr = decisions.due_reviews(conn)
    if dr:
        out.append(f"🔁 {len(dr)} 个过去的决策到了复盘时间：lifeos decide review")
    for p in decisions.promotion_candidates(conn):
        out.append(f"⬆️ 「{p['category']}」最近采纳率 {p['rate']:.0%}，可升级 {p['from']} → {p['to']}：lifeos autonomy set {p['category']} +1")
    return out


def render(p: dict) -> str:
    lines = [f"📅 {p['date']} 周{p['weekday']}    决策模式：{p['autonomy_level']}", "", "🎯 今天只需记住的 3 件事"]
    lines += [f"  {i}. {t}" for i, t in enumerate(p["top3"], 1)] or ["  （无）"]
    lines += ["", "🕐 时间块"]
    icon = {"fixed": "▓", "protected": "█", "task": "░"}
    for b in p["timeline"]:
        lines.append(f"  {b['time']} {icon[b['kind']]} {b['title']}")
        lines += [f"               └ 可以一起做：{w['title']}（任务 #{w['id']}）" for w in b.get("with", [])]
    if p["unscheduled"]:
        lines += ["", "⏳ 今天排不下（明天再说）：" + "；".join(p["unscheduled"][:5])]
    if p["nudges"]:
        lines += ["", "🔔 提醒"] + [f"  {n}" for n in p["nudges"]]
    if "suggestion_id" in p:
        lines += ["", f"👍/👎 这个日程好用吗？ lifeos fb {p['suggestion_id']} accept|reject|modify \"原因\""]
    return "\n".join(lines)
