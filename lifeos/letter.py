"""一封信：每周末写给你的，不是成绩单。

写这一周的瞬间、你的天气、她、你做到的事、你放下的事，最后留一个问题。
数据报表（时间账本、采纳率）仍在 review.weekly 里，只是不再站在前面。
"""

from collections import Counter
from datetime import date, timedelta

from . import config, db, llm, now, shi, yi

QUESTIONS = [
    "这周哪一刻，你最像你自己？",
    "有什么事，你其实可以不做，却还是做了？为什么？",
    "这周她让你笑的瞬间是什么？",
    "如果下周只能做好一件事，你会选什么？",
    "这周有没有一件事，是你为自己而做的？",
    "你最近在逃避什么吗？它真的那么可怕吗？",
    "这周你对谁心怀感激？告诉他/她了吗？",
    "哪件小事让你觉得生活还挺好的？",
    "如果一年后回看这一周，你希望记住什么？",
    "你最近的忙碌，是在靠近你想要的生活，还是在远离它？",
]


def gather(conn, end: date) -> dict:
    start = end - timedelta(days=6)
    s, e = start.isoformat(), end.isoformat()
    in_week = "substr({col},1,10) BETWEEN ? AND ?"
    states = db.rows(conn.execute(f"SELECT feeling, at FROM states WHERE {in_week.format(col='at')}", (s, e)))
    moments = db.rows(conn.execute(
        f"SELECT content, domain, mood, importance FROM memories WHERE {in_week.format(col='occurred_at')} "
        "AND type NOT IN ('summary', 'prospective') AND status != 'archived' ORDER BY importance DESC, mood DESC LIMIT 8",
        (s, e)))
    her = [m for m in moments if m["domain"] == "关系"]
    done = db.rows(conn.execute(
        f"SELECT title, domain FROM tasks WHERE status = 'done' AND {in_week.format(col='done_at')}", (s, e)))
    let_go = db.rows(conn.execute(
        f"SELECT title FROM tasks WHERE status = 'let_go' AND {in_week.format(col='done_at')}", (s, e)))
    sold = db.rows(conn.execute(f"SELECT model, sell_price FROM items WHERE {in_week.format(col='sold_at')}", (s, e)))
    wishes_done = db.rows(conn.execute("SELECT content FROM wishes WHERE status = '已实现'"))
    casts = [c for c in yi.history(conn, 50) if s <= c["day"] <= e]
    world = [t for t in shi.trends(conn, 50) if t["direction"] and s <= t["observed_at"][:10] <= e]
    return {
        "start": s, "end": e,
        "weather": Counter(x["feeling"] for x in states),
        "moments": [m["content"] for m in moments if m["domain"] != "关系"][:5],
        "her": [m["content"] for m in her][:5],
        "done": [d["title"] for d in done],
        "let_go": [x["title"] for x in let_go],
        "sold": sold,
        "wishes_done": [w["content"] for w in wishes_done],
        "question": QUESTIONS[end.isocalendar().week % len(QUESTIONS)],
        "casts": casts,
        "world": world,
    }


def _template(d: dict) -> str:
    cur = config.currency()
    L = [f"# ✉️ 写给这一周的你（{d['start']} → {d['end']}）", ""]
    if d["weather"]:
        weather = "、".join(f"{now.FEELINGS.get(f, {}).get('icon', '')}{f} {n} 次" for f, n in d["weather"].most_common())
        L += ["## 你的天气", "", f"这周你告诉我的感受：{weather}。"]
        tired = d["weather"].get("疲惫", 0) + d["weather"].get("低落", 0)
        if tired > sum(d["weather"].values()) / 2:
            L.append("累的时候比较多。不用急着调整什么，先好好休息。")
        L.append("")
    if d["moments"]:
        L += ["## 这一周的瞬间", ""] + [f"- {m}" for m in d["moments"]] + [""]
    if d["her"] or d["wishes_done"]:
        L += ["## 她", ""] + [f"- {m}" for m in d["her"]]
        if d["wishes_done"]:
            L.append(f"- 已经实现的愿望：{'、'.join(d['wishes_done'])} 🎉")
        L.append("")
    if d["done"] or d["sold"]:
        L += ["## 你做到的", ""] + [f"- {t}" for t in d["done"][:10]]
        L += [f"- 卖出了 {s['model']}（{cur}{s['sell_price']:.0f}）" for s in d["sold"]]
        L.append("")
    if d["casts"]:
        L += ["## 这周的卦", ""]
        for c in d["casts"]:
            q = c["question"] or "今日"
            L.append(f"- {c['day']} {q}：{c['title']}" + (f"。后来：{c['outcome']}" if c["outcome"] else ""))
        L.append("")
    if d["world"]:
        L += ["## 外面的势", ""] + [f"- {'顺' if t['direction'] > 0 else '逆'}｜{t['title']}" for t in d["world"][:3]] + [""]
    if d["let_go"]:
        L += ["## 你放下的", "", "、".join(d["let_go"]) + "。放下也是一种选择。", ""]
    if len(L) <= 2:
        L += ["这周没有留下什么记录。没关系，日子不一定要被记下来才算过了。", ""]
    L += ["## 一个问题", "", d["question"], "", "（不用回答给谁听。想到了，随手记一句就好。）"]
    return "\n".join(L)


def render(conn, end: date | None = None) -> str:
    """不调用 AI 的信（预览、离线时用）。"""
    return _template(gather(conn, end or date.today()))


def write(conn, end: date | None = None, save: bool = True) -> dict:
    end = end or date.today()
    d = gather(conn, end)
    text = _template(d)
    warm = llm.complete_text(
        "你在给一位朋友写每周的信。他是建筑师，在准备 RIBA Part 3，业余买卖相机镜头，很爱他的女朋友。"
        "根据下面的素材，用第二人称、温和克制的中文写一封 300 字以内的信：提到具体的瞬间和她；"
        "肯定他做到的事；如果他累了，允许他休息；不评分、不提效率、不给待办清单；最后原样保留那个问题。",
        text, effort="medium",
    )
    if warm:
        text = f"# ✉️ 写给这一周的你（{d['start']} → {d['end']}）\n\n{warm}"
    if save:
        iso = end.isocalendar()
        path = config.home() / "letters" / f"{iso.year}-W{iso.week:02d}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return {"markdown": text, "question": d["question"]}
