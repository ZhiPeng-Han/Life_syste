"""感情模块：她的愿望清单、重要日期、惊喜引擎。

原则：系统负责"记住"和"启发"，执行与表达永远是你自己的。只记录你的观察，不接入她的任何账号。
"""

import json
from datetime import date, timedelta

from . import db, llm

WISH_STATUSES = ["想法", "规划中", "进行中", "已实现"]

# 每类愿望的三种尺度惊喜：微（5-30 分钟）/ 中（1-3 小时）/ 大（需提前数周）
IDEAS = {
    "travel": [
        ("微", "建一个你们共享的「{w}」灵感清单，今晚发给她第一张你拍的/找到的图，问她最期待哪一幕"),
        ("中", "安排一个主题夜：做一顿当地风味的晚餐 + 一起看一部相关纪录片 + 一起写行程草稿"),
        ("大", "把行程定下来：选好日期、订第一晚住宿，用一张手写卡片告诉她"),
    ],
    "health": [
        ("微", "今晚做一道她喜欢的轻食（菜单已安排），只说'好吃'，不提热量和体重"),
        ("中", "约她周末一起去徒步或长距离散步，路上拍几张她的好看照片"),
        ("大", "一起报名一个她自己挑的运动课程或目标活动（例如为冰岛徒步做准备），你陪练"),
    ],
    "project": [
        ("微", "把你们的想法写成一页纸，今晚问她：最想负责哪一部分？"),
        ("中", "开一次 30 分钟「合伙人会议」（有议程、有记录），会后去吃饭——工作和约会分开"),
        ("大", "一起把第一个版本做出来并庆祝：例如上线你们的器材橱窗页面，卖出第一单后一起吃顿好的"),
    ],
    "gift": [
        ("微", "记下她提过的那件小东西，下次路过顺手带回来"),
        ("中", "包装好，附一张写着'你上次说过……'的卡片"),
        ("大", "在一个特别的日子送出，并配上你拍的照片"),
    ],
    "experience": [
        ("微", "今天给她发一张你拍的、和这件事有关的照片"),
        ("中", "把它安排进下一个周六约会"),
        ("大", "围绕它策划一次完整的小旅行或纪念日"),
    ],
}


def add_wish(conn, content: str, category: str = "other", person: str = "她", project: str | None = None, notes=None) -> int:
    wid = conn.execute(
        "INSERT INTO wishes(person, content, category, mentioned_at, project, notes) VALUES(?,?,?,?,?,?)",
        (person, content, category, db.today(), project, notes),
    ).lastrowid
    from . import mind

    mind.link_wish(conn, wid, content, project)
    conn.commit()
    return wid


def set_wish_status(conn, wish_id: int, status: str) -> None:
    conn.execute("UPDATE wishes SET status = ? WHERE id = ?", (status, wish_id))
    conn.commit()


def wishes(conn, include_done: bool = False) -> list[dict]:
    sql = "SELECT * FROM wishes" + ("" if include_done else " WHERE status != '已实现'") + " ORDER BY id"
    return db.rows(conn.execute(sql))


def add_date(conn, name: str, month: int, day: int, person: str = "她", remind=(30, 7, 1)) -> int:
    did = conn.execute(
        "INSERT INTO important_dates(person, name, month, day, remind_days) VALUES(?,?,?,?,?)",
        (person, name, month, day, json.dumps(list(remind))),
    ).lastrowid
    conn.commit()
    return did


def upcoming_dates(conn, on: date | None = None, horizon: int = 60) -> list[dict]:
    on = on or date.today()
    out = []
    for d in db.rows(conn.execute("SELECT * FROM important_dates")):
        try:
            nxt = date(on.year, d["month"], d["day"])
        except ValueError:  # 2 月 29 日
            nxt = date(on.year, d["month"], 28)
        if nxt < on:
            nxt = nxt.replace(year=on.year + 1)
        days = (nxt - on).days
        if days <= horizon:
            remind = days in json.loads(d["remind_days"]) or days == 0
            out.append({**d, "date": nxt.isoformat(), "days_left": days, "remind_today": remind})
    return sorted(out, key=lambda x: x["days_left"])


def ideas(conn, on: date | None = None) -> list[dict]:
    """惊喜建议。每天轮换不同的愿望，避免每天看到同样的话。"""
    on = on or date.today()
    active = wishes(conn)
    if not active:
        return []
    out = []
    for offset, scale_idx in ((0, 0), (1, 1), (2, 2)):
        w = active[(on.toordinal() + offset) % len(active)]
        scale, template = IDEAS.get(w["category"], IDEAS["experience"])[scale_idx]
        out.append({"scale": scale, "wish_id": w["id"], "wish": w["content"], "idea": template.format(w=w["content"])})
    return out


def ai_ideas(conn) -> str | None:
    """配置了 Claude 时，结合近期关系记忆生成更个性化的惊喜方案。"""
    recent = db.rows(
        conn.execute("SELECT content FROM memories WHERE domain = '关系' ORDER BY occurred_at DESC LIMIT 30")
    )
    past = db.rows(
        conn.execute("SELECT content, feedback FROM suggestions WHERE category = 'surprise' AND status != 'pending' ORDER BY id DESC LIMIT 20")
    )
    prompt = (
        "她的愿望清单：\n" + "\n".join(f"- {w['content']}（{w['status']}）" for w in wishes(conn))
        + "\n\n近期和她有关的记忆：\n" + "\n".join(f"- {m['content']}" for m in recent)
        + "\n\n过去的惊喜及反馈：\n" + "\n".join(f"- {p['content']} → {p['feedback'] or ''}" for p in past)
    )
    from . import mind

    remembered = mind.context(conn, "她 喜欢 不喜欢 想要 " + " ".join(w["content"] for w in wishes(conn)), k=12)
    if remembered:
        prompt += "\n\n关于她，你还记得（包括事实和领悟）：\n" + remembered
    return llm.complete_text(
        "你是用户的关系顾问。给出本周 3 个惊喜方案（微/中/大各一个），每个包含：做什么、为什么她会喜欢（引用她说过的话）、"
        "准备清单。语气真诚，不要油腻；减肥相关只做支持，绝不评价她的身材；情话和表达留给用户自己。",
        prompt,
        effort="medium",
        slow_ok=True,
    )


def love_minutes_week(conn, end: date | None = None) -> int:
    end = end or date.today()
    start = (end - timedelta(days=6)).isoformat()
    logged = conn.execute(
        "SELECT COALESCE(SUM(minutes), 0) FROM timelog WHERE domain = '关系' AND day BETWEEN ? AND ?", (start, end.isoformat())
    ).fetchone()[0]
    checkin = conn.execute(
        "SELECT COALESCE(SUM(love_minutes), 0) FROM checkins WHERE day BETWEEN ? AND ?", (start, end.isoformat())
    ).fetchone()[0]
    return max(logged, checkin)
