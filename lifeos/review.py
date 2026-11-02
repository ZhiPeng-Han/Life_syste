"""签到、时间记录、周复盘、"我的说明书"。这是系统自我迭代的主要入口。"""

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from . import business, cards, config, db, decisions, experiments, llm, relationship


# ------------------------------------------------------------------ 每日输入

def checkin(conn, day: str | None = None, energy=None, mood=None, sleep=None, exercised=None, love_minutes=None, note=None) -> dict:
    day = day or db.today()
    conn.execute(
        """INSERT INTO checkins(day, energy, mood, sleep_hours, exercised, love_minutes, note, created_at)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(day) DO UPDATE SET
             energy = COALESCE(excluded.energy, energy), mood = COALESCE(excluded.mood, mood),
             sleep_hours = COALESCE(excluded.sleep_hours, sleep_hours), exercised = COALESCE(excluded.exercised, exercised),
             love_minutes = COALESCE(excluded.love_minutes, love_minutes), note = COALESCE(excluded.note, note)""",
        (day, energy, mood, sleep, exercised, love_minutes, note, db.now()),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM checkins WHERE day = ?", (day,)).fetchone())


def log_time(conn, domain: str, minutes: int, note: str = "", day: str | None = None) -> None:
    conn.execute("INSERT INTO timelog(day, domain, minutes, note) VALUES(?,?,?,?)", (day or db.today(), domain, minutes, note))
    conn.commit()


CHECKIN_QUESTIONS = [
    ("energy", "今天整体能量 1-10？"),
    ("mood", "今天心情 1-10？"),
    ("sleep", "昨晚睡了几小时？"),
    ("exercised", "今天锻炼了吗？(y/n)"),
    ("love_minutes", "今天和她高质量相处了多少分钟？"),
    ("note", "今天最值得记住的一件事？她提到了什么？（这句会进入记忆系统）"),
]


# ------------------------------------------------------------------ 统计工具

def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 5 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return round(statistics.correlation(xs, ys), 2)


def _checkins(conn, start: date, end: date) -> list[dict]:
    return db.rows(conn.execute("SELECT * FROM checkins WHERE day BETWEEN ? AND ? ORDER BY day", (start.isoformat(), end.isoformat())))


def patterns(conn, days: int = 60) -> list[str]:
    """从签到数据里找关于"你"的规律（相关性，非因果）。"""
    end = date.today()
    rows = _checkins(conn, end - timedelta(days=days), end)
    by_day = {r["day"]: r for r in rows}
    out = []
    # 前一晚睡眠 → 当天能量/心情（签到里的 sleep 指的就是"昨晚"）
    for metric, label in (("energy", "能量"), ("mood", "心情")):
        pairs = [(r["sleep_hours"], r[metric]) for r in rows if r["sleep_hours"] is not None and r[metric] is not None]
        r = pearson(*zip(*pairs)) if len(pairs) >= 5 else None
        if r is not None and abs(r) >= 0.3:
            out.append(f"睡眠时长与当天{label}的相关系数 {r}（{len(pairs)} 天数据）——{'睡得越多' + label + '越好' if r > 0 else '关系反常，值得留意'}")
    # 锻炼日 vs 非锻炼日的次日心情
    ex, non = [], []
    for r in rows:
        nxt = by_day.get((date.fromisoformat(r["day"]) + timedelta(days=1)).isoformat())
        if nxt and nxt["mood"] is not None and r["exercised"] is not None:
            (ex if r["exercised"] else non).append(nxt["mood"])
    if len(ex) >= 3 and len(non) >= 3:
        diff = statistics.mean(ex) - statistics.mean(non)
        if abs(diff) >= 0.5:
            out.append(f"锻炼后的第二天，心情平均{'高' if diff > 0 else '低'} {abs(diff):.1f} 分（{len(ex)} vs {len(non)} 天）")
    # 能量按星期
    wk = defaultdict(list)
    for r in rows:
        if r["energy"] is not None:
            wk[date.fromisoformat(r["day"]).isoweekday()].append(r["energy"])
    means = {d: statistics.mean(v) for d, v in wk.items() if len(v) >= 2}
    if len(means) >= 4:
        best, worst = max(means, key=means.get), min(means, key=means.get)
        if means[best] - means[worst] >= 1:
            out.append(f"一周中周{'一二三四五六日'[best - 1]}能量最高（{means[best]:.1f}），周{'一二三四五六日'[worst - 1]}最低（{means[worst]:.1f}）")
    # 和她相处 vs 心情
    pairs = [(r["love_minutes"], r["mood"]) for r in rows if r["love_minutes"] is not None and r["mood"] is not None]
    r = pearson(*zip(*pairs)) if len(pairs) >= 5 else None
    if r is not None and r >= 0.3:
        out.append(f"和她相处的时长与你的心情正相关（r={r}）")
    return out


# ------------------------------------------------------------------ 周复盘

def weekly(conn, end: date | None = None, save: bool = True, coach: bool = True) -> dict:
    end = end or date.today()
    start = end - timedelta(days=6)
    s, e = start.isoformat(), end.isoformat()

    minutes = dict(conn.execute(
        "SELECT domain, SUM(minutes) FROM timelog WHERE day BETWEEN ? AND ? GROUP BY domain", (s, e)
    ).fetchall())
    ledger, insights = [], []
    for name, d in config.domains().items():
        hours = round(minutes.get(name, 0) / 60, 1)
        budget = d.get("budget", 0)
        ledger.append({"domain": name, "hours": hours, "budget": budget, "role": d.get("role")})
        if budget and hours > budget * 1.2 and minutes:
            insights.append(("conflict", f"「{name}」本周 {hours}h，超出预算 {budget}h 的 20% 以上，它挤占了谁？"))
    love_h = round(relationship.love_minutes_week(conn, end) / 60, 1)
    love_budget = config.domains().get("关系", {}).get("budget", 0)
    if love_budget and love_h < love_budget * 0.7:
        insights.append(("conflict", f"❤️ 本周和她的高质量时间 {love_h}h，低于底线 {love_budget}h 的 70%。下周优先保护。"))

    ck = _checkins(conn, start, end)

    def avg(key):
        vals = [r[key] for r in ck if r[key] is not None]
        return round(statistics.mean(vals), 1) if vals else None

    done = db.rows(conn.execute("SELECT domain, COUNT(*) n FROM tasks WHERE status = 'done' AND substr(done_at,1,10) BETWEEN ? AND ? GROUP BY domain", (s, e)))
    sugg = db.rows(conn.execute(
        "SELECT category, status, feedback FROM suggestions WHERE substr(created_at,1,10) BETWEEN ? AND ?", (s, e)
    ))
    acc = defaultdict(Counter)
    reasons = []
    for r in sugg:
        acc[r["category"]][r["status"]] += 1
        if r["status"] in ("rejected", "modified") and r["feedback"]:
            reasons.append(f"[{r['category']}] {r['feedback']}")
    new_wishes = db.rows(conn.execute("SELECT content FROM wishes WHERE mentioned_at BETWEEN ? AND ?", (s, e)))

    for p in patterns(conn):
        insights.append(("pattern", p))
    for p in decisions.promotion_candidates(conn):
        insights.append(("autonomy", f"「{p['category']}」采纳率 {p['rate']:.0%}（{p['n']} 次），建议从 {p['from']} 升到 {p['to']}"))

    data = {
        "start": s, "end": e,
        "ledger": ledger,
        "love_hours": love_h,
        "checkins": {"days": len(ck), "energy": avg("energy"), "mood": avg("mood"), "sleep": avg("sleep_hours"),
                     "exercise_days": sum(1 for r in ck if r["exercised"])},
        "tasks_done": done,
        "business": business.stats(conn),
        "funds": business.funds(conn),
        "wishes": relationship.wishes(conn),
        "new_wishes": [w["content"] for w in new_wishes],
        "upcoming": relationship.upcoming_dates(conn, end, 60),
        "suggestions": {k: dict(v) for k, v in acc.items()},
        "feedback_reasons": reasons,
        "cards": cards.stats(conn),
        "experiments": [experiments.analyze(conn, x["id"]) for x in experiments.list_all(conn) if x["status"] == "running"],
        "insights": [{"kind": k, "content": c} for k, c in insights],
    }
    for k, c in insights:
        exists = conn.execute("SELECT 1 FROM insights WHERE content = ?", (c,)).fetchone()
        if not exists:
            conn.execute("INSERT INTO insights(content, kind, created_at) VALUES(?,?,?)", (c, k, db.now()))
    conn.commit()

    md = render_weekly(data)
    coach = coach and llm.complete_text(
        "你是用户的人生教练。基于这份周复盘数据，用中文给出：1) 本周最值得肯定的一件事 2) 最大的一个失衡及原因猜测 "
        "3) 下周 3 条具体可执行的调整（可以是对 rules.toml 的修改建议）4) 一个关于感情的用心建议。简洁、直接、不说空话。",
        md, effort="medium",
    )
    if coach:
        md += "\n\n## 🤖 AI 教练点评\n\n" + coach
    data["markdown"] = md
    if save:
        iso = end.isocalendar()
        path = config.home() / "reviews" / f"{iso.year}-W{iso.week:02d}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(md, encoding="utf-8")
        data["path"] = str(path)
    return data


def render_weekly(d: dict) -> str:
    cur = config.currency()
    L = [f"# 📅 周复盘 {d['start']} → {d['end']}", "", "## ⏱ 时间账本（实际 / 预算 小时）", ""]
    L += ["| 领域 | 实际 | 预算 | 角色 |", "|---|---|---|---|"]
    for x in d["ledger"]:
        flag = " ⚠️" if x["budget"] and x["hours"] > x["budget"] * 1.2 else ""
        L.append(f"| {x['domain']} | {x['hours']}{flag} | {x['budget']} | {x['role']} |")
    c = d["checkins"]
    L += ["", f"## 🙂 状态（{c['days']} 天签到）", "",
          f"能量 {c['energy']} · 心情 {c['mood']} · 睡眠 {c['sleep']}h · 锻炼 {c['exercise_days']} 天"]
    L += ["", "## ❤️ 关系", "", f"高质量相处：{d['love_hours']}h"]
    if d["new_wishes"]:
        L.append("本周新记下的愿望：" + "；".join(d["new_wishes"]))
    for w in d["wishes"]:
        L.append(f"- [{w['status']}] {w['content']}")
    for u in d["upcoming"][:3]:
        L.append(f"- 🎁 {u['name']}：还有 {u['days_left']} 天")
    b = d["business"]
    L += ["", "## 📷 器材事业", "",
          f"累计成交 {b['sold_count']} 件 · 累计净利润 {cur}{b['profit_total']} · 本月 {cur}{b['profit_month']} · "
          f"时薪 {cur}{b['hourly_rate']} · 平均周转 {b['avg_turnover_days']} 天 · 库存 {b['stock_count']} 件（{cur}{b['stock_value']}）"]
    if b["stale"]:
        L.append(f"滞销：{', '.join(b['stale'])}")
    for f in d["funds"]:
        L.append(f"- {f['name']}：{cur}{f['saved']} / {cur}{f['target']}（{(f['progress'] or 0):.0%}）")
    L += ["", "## ✅ 完成的任务", ""]
    L += [f"- {t['domain']}: {t['n']}" for t in d["tasks_done"]] or ["- 无"]
    L += ["", f"## 📚 Part 3 卡片：共 {d['cards']['total']}，今日到期 {d['cards']['due_today']}，已掌握 {d['cards']['mature']}"]
    if d["experiments"]:
        L += ["", "## 🔬 实验进展", ""] + [f"- {x['experiment']}：{x['conclusion']}" for x in d["experiments"]]
    L += ["", "## 🤖 系统表现（建议采纳情况）", ""]
    zh = {"pending": "待反馈", "accepted": "采纳", "rejected": "否决", "modified": "修改", "auto": "自动执行"}
    L += [f"- {k}：" + "，".join(f"{zh.get(st, st)} {n}" for st, n in v.items()) for k, v in d["suggestions"].items()] or ["- 本周没有反馈数据"]
    if d["feedback_reasons"]:
        L += ["", "你的修改/否决理由（系统据此调整规则）："] + [f"- {r}" for r in d["feedback_reasons"]]
    L += ["", "## 🧠 洞察", ""] + ([f"- ({i['kind']}) {i['content']}" for i in d["insights"]] or ["- 数据还不够，坚持签到两周后会出现规律"])
    L += ["", "## ✍️ 你的反思（手写）", "", "- 本周三个亮点：", "- 一个遗憾，原因：", "- 要修改的规则：", "- 下周三件最重要的事：", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ 我的说明书

def user_manual(conn, save: bool = True) -> str:
    end = date.today()
    L = [f"# 我的说明书（系统自动维护 · 更新于 {end.isoformat()}）", "",
         "> 这是系统对你的理解。不对的地方请直接告诉它（lifeos add \"其实我……\"），它会修正。", ""]
    L += ["## 被数据支持的规律（相关性，非因果）", ""] + ([f"- {p}" for p in patterns(conn, 90)] or ["- 签到数据不足（至少 2 周）"])
    L += ["", "## 决策风格", ""]
    for o in decisions.overview(conn):
        if o["n"]:
            L.append(f"- {o['desc']}：当前 {o['level']}，最近采纳率 {o['rate']:.0%}（{o['n']} 次）")
    rejected = db.rows(conn.execute(
        "SELECT category, feedback FROM suggestions WHERE status IN ('rejected','modified') AND feedback != '' ORDER BY id DESC LIMIT 15"
    ))
    if rejected:
        L += ["", "你最近否决/修改建议的原因（系统需要学会的偏好）："] + [f"- [{r['category']}] {r['feedback']}" for r in rejected]
    cal = decisions.calibration(conn)
    if cal:
        L += ["", "## 判断校准（你说的把握 vs 实际命中）", ""] + [f"- 信心 {c['confidence']}：{c['n']} 次，命中 {c['hit_rate']:.0%}" for c in cal]
    learned = db.get_meta(conn, "defect_discount", {})
    if learned:
        L += ["", "## 器材：从你的成交中学到的瑕疵折价", ""] + [f"- {k}：{v:.0%}" for k, v in learned.items()]
    mins = dict(conn.execute(
        "SELECT domain, SUM(minutes) FROM timelog WHERE day >= ? GROUP BY domain", ((end - timedelta(days=30)).isoformat(),)
    ).fetchall())
    if mins:
        total = sum(mins.values())
        L += ["", "## 近 30 天时间去向", ""] + [f"- {k}：{v / 60:.1f}h（{v / total:.0%}）" for k, v in sorted(mins.items(), key=lambda x: -x[1])]
    from . import mind

    noticed = mind.reflections(conn)
    if noticed:
        L += ["", "## 系统从记忆里领悟到的（你说不对，它就不再提）", ""] + [f"- {r['content']}" for r in noticed[:10]]
    facts = db.rows(conn.execute("SELECT content FROM memories WHERE type = 'semantic' AND status = 'active' ORDER BY importance DESC LIMIT 20"))
    if facts:
        L += ["", "## 关于我的事实（来自记忆）", ""] + [f"- {f['content']}" for f in facts]
    text = "\n".join(L)
    polished = llm.complete_text(
        "把这份数据整理成一份温和、具体的'用户说明书'，保留所有数字，补充 3 条基于数据的、可执行的自我管理建议。不要编造数据里没有的事实。",
        text, effort="medium", slow_ok=True,
    )
    if polished:
        text += "\n\n## 🤖 AI 解读\n\n" + polished
    if save:
        (config.home() / "我的说明书.md").write_text(text, encoding="utf-8")
    return text
