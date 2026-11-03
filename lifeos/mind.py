"""记忆中枢：在后台把一切连成一张网，让它影响系统的每个角落。

你不需要去翻看它。它安静地做五件事：
1. 时间：分清"事情发生的时候"和"你记下它的时候"（昨天、上周六、三天前、10月3号……）
2. 连接：记忆、她的愿望、盼头、去过的地方、器材、卦、口袋里的事，
   凡是提到同一件事（冰岛、陶艺、50/1.4），就挂到同一个节点上
3. 回忆：AI 每次开口之前，先想起和眼前这件事最相关的记忆和事实，而不是"最近的几条"
4. 领悟：定期从许多条记忆里看出更高一层的规律（借鉴 Generative Agents 的 reflection），
   每条都带着证据；你说"不对"，它就不再提
5. 更新：人会变。新的事实取代旧的事实时，旧的标为"曾经是"，不删除

它影响的地方：此刻的建议、捡漏评估、问卦、惊喜方案、每周的信、早安、《我的说明书》、
以及每一次 AI 回应时常驻的"核心记忆"。
"""

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta

from . import config, db, llm

# 不再参与回忆的状态：你删掉的、被新事实取代的、已经不成立的领悟
INACTIVE = ("archived", "superseded", "faded")
INACTIVE_SQL = "('archived', 'superseded', 'faded')"
TOPIC_KINDS = ("topic", "place", "project", "model")
LOW_FEELINGS = ("疲惫", "烦躁", "低落")


# ------------------------------------------------------------------ 1. 时间

_CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "半": 0}
_WD = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _num(s: str) -> int:
    if s.isdigit():
        return int(s)
    if len(s) == 1:
        return _CN.get(s, 1)
    if s.startswith("十"):
        return 10 + _CN.get(s[1:], 0)
    if s.endswith("十"):
        return _CN.get(s[0], 1) * 10
    if "十" in s:
        a, b = s.split("十", 1)
        return _CN.get(a, 1) * 10 + _CN.get(b, 0)
    return 1


def when_of(text: str, base: datetime | None = None) -> datetime | None:
    """从一句话里读出事情发生的日子（只往过去看）。读不出就返回 None。"""
    base = base or datetime.now()
    d = base.date()

    def at(day: date) -> datetime:
        return base if day == d else datetime.combine(day, time(12, 0))

    for pat, n in (("大前天", 3), ("前天", 2), ("昨天|昨晚|昨日|昨儿", 1)):
        if re.search(pat, text):
            return at(d - timedelta(days=n))
    m = re.search(r"(\d{1,3}|[一二两三四五六七八九十]+)\s*(天|周|个星期|星期|个月|年)(?:以)?前", text)
    if m:
        n = _num(m.group(1))
        days = {"天": 1, "周": 7, "个星期": 7, "星期": 7, "个月": 30, "年": 365}[m.group(2)] * n
        return at(d - timedelta(days=days))
    m = re.search(r"上(?:个)?(?:周|星期|礼拜)([一二三四五六日天])", text)
    if m:
        monday = d - timedelta(days=d.weekday())
        return at(monday - timedelta(days=7) + timedelta(days=_WD[m.group(1)]))
    m = re.search(r"(?<![下这本])(?:周|星期|礼拜)([一二三四五六日天])", text)
    if m:
        back = (d.weekday() - _WD[m.group(1)]) % 7
        return at(d - timedelta(days=back))
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
    if m:
        try:
            day = date(d.year, int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        return at(day if day <= d else day.replace(year=d.year - 1))
    for pat, n in (("上周|上个星期|上礼拜", 7), ("上个月", 30), ("去年", 365), ("前年", 730)):
        if re.search(pat, text):
            return at(d - timedelta(days=n))
    return None


# ------------------------------------------------------------------ 2. 连接

def _seed_topics(conn) -> None:
    for name in config.rules().get("memory", {}).get("topics", []):
        db.entity(conn, "topic", name)


def dictionary(conn) -> list[dict]:
    """系统认识的"事物"：主题、地点、项目、器材型号。"""
    _seed_topics(conn)
    kinds = ",".join("?" * len(TOPIC_KINDS))
    ents = db.rows(conn.execute(f"SELECT id, kind, name FROM entities WHERE kind IN ({kinds})", TOPIC_KINDS))
    return [e for e in ents if len(e["name"]) >= 2]


def _models_in(text: str) -> list[str]:
    from . import business, extract

    out = []
    for m in extract.MODEL_RE.finditer(text):
        raw = m.group(0).strip()
        # 只认像镜头/机身型号的写法：含 / 或"字母+数字"
        if "/" in raw or re.search(r"[A-Za-z]{1,4}\d", raw):
            out.append(business.normalize_model(raw))
    return out


def topics_in(conn, text: str) -> list[int]:
    """这句话提到了哪些系统认识的事物（返回实体 id）。"""
    lower = text.lower()
    found = [e["id"] for e in dictionary(conn) if e["kind"] != "model" and e["name"].lower() in lower]
    for model in _models_in(text):
        found.append(db.entity(conn, "model", model))
    return list(dict.fromkeys(found))


_OBJ_RE = re.compile(r"(?:想要|想去|想学|想吃|想买|想做|想看|想试|想|去|学)([^\s，,。！!？?的了]{2,10})")
_CUT_RE = re.compile(r"看|玩|吃|旅|一起|和|跟|的|呀|啊|吧")


def derive_topic(text: str) -> str | None:
    """从"她想去冰岛看极光"里取出"冰岛"，从"想学陶艺"里取出"陶艺"。"""
    m = _OBJ_RE.search(text)
    if m:
        head = _CUT_RE.split(m.group(1))[0].strip()
        if 2 <= len(head) <= 6:
            return head
    clean = _CUT_RE.split(text.strip())[0].strip()
    return clean if 2 <= len(clean) <= 6 and not re.search(r"[，,。 ]", clean) else None


def attach(conn, ref: str, ref_id: int, entity_id: int) -> None:
    if ref == "memories":
        conn.execute("INSERT OR IGNORE INTO memory_entities VALUES(?, ?)", (ref_id, entity_id))
    else:
        conn.execute("INSERT OR IGNORE INTO links VALUES(?, ?, ?)", (entity_id, ref, ref_id))


def link_text(conn, ref: str, ref_id: int, text: str, extra: list[int] | None = None) -> list[int]:
    ids = list(dict.fromkeys(topics_in(conn, text or "") + (extra or [])))
    for eid in ids:
        attach(conn, ref, ref_id, eid)
    return ids


def link_wish(conn, wish_id: int, content: str, project: str | None = None) -> None:
    extra = []
    topic = derive_topic(content)
    if topic:
        extra.append(db.entity(conn, "topic", topic))
    if project:
        pid = db.entity(conn, "project", project)
        extra.append(pid)
        for t in extra[:-1]:
            db.relate(conn, t, pid, "related", note="她的愿望", bump=1)
    her = db.entity(conn, "person", "她")
    for eid in link_text(conn, "wishes", wish_id, content, extra):
        db.relate(conn, eid, her, "related", note="她的愿望", bump=1)


def link_horizon(conn, horizon_id: int, title: str) -> None:
    topic = derive_topic(title)
    link_text(conn, "horizons", horizon_id, title, [db.entity(conn, "topic", topic)] if topic else [])


def link_place(conn, place_id: int, name: str) -> None:
    attach(conn, "places", place_id, db.entity(conn, "place", name))


def link_item(conn, item_id: int, model: str) -> None:
    from . import business

    attach(conn, "items", item_id, db.entity(conn, "model", business.normalize_model(model)))


def link_task(conn, task_id: int, title: str, project: str | None = None) -> None:
    link_text(conn, "tasks", task_id, title, [db.entity(conn, "project", project)] if project else [])


def reindex(conn) -> dict:
    """把已有的记录全部重新连一遍（幂等）。升级后第一次运行时自动执行。"""
    n = Counter()
    for w in db.rows(conn.execute("SELECT id, content, project FROM wishes")):
        link_wish(conn, w["id"], w["content"], w["project"])
        n["wishes"] += 1
    for h in db.rows(conn.execute("SELECT id, title FROM horizons")):
        link_horizon(conn, h["id"], h["title"])
        n["horizons"] += 1
    for p in db.rows(conn.execute("SELECT id, name FROM places")):
        link_place(conn, p["id"], p["name"])
        n["places"] += 1
    for i in db.rows(conn.execute("SELECT id, model FROM items")):
        link_item(conn, i["id"], i["model"])
        n["items"] += 1
    for c in db.rows(conn.execute("SELECT id, question FROM casts WHERE question IS NOT NULL")):
        link_text(conn, "casts", c["id"], c["question"])
        n["casts"] += 1
    for t in db.rows(conn.execute("SELECT id, title, project FROM tasks")):
        link_task(conn, t["id"], t["title"], t["project"])
        n["tasks"] += 1
    for m in db.rows(conn.execute(f"SELECT id, content FROM memories WHERE status NOT IN {INACTIVE_SQL} "
                                  "AND type NOT IN ('summary', 'reflection')")):
        link_text(conn, "memories", m["id"], m["content"])
        n["memories"] += 1
    db.set_meta(conn, "mind_indexed", db.now())
    conn.commit()
    return dict(n)


def _expand(conn, ids: list[int]) -> list[int]:
    """把一个主题扩展到和它强相关的项目/主题（冰岛 ↔ 冰岛之旅）。"""
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    kinds = ",".join("?" * len(TOPIC_KINDS))
    near = conn.execute(
        f"""SELECT e.id FROM relations r JOIN entities e
              ON e.id = CASE WHEN r.source_id IN ({marks}) THEN r.target_id ELSE r.source_id END
            WHERE (r.source_id IN ({marks}) OR r.target_id IN ({marks})) AND r.strength >= 1
              AND r.status != 'rejected' AND e.kind IN ({kinds})""",
        (*ids, *ids, *ids, *TOPIC_KINDS),
    ).fetchall()
    return list(dict.fromkeys(ids + [r[0] for r in near]))


def about(conn, name: str) -> dict:
    """关于一件事，系统知道的一切。"""
    ents = [r[0] for r in conn.execute("SELECT id FROM entities WHERE name = ? COLLATE NOCASE", (name,))]
    ids = _expand(conn, ents)
    out = {"name": name, "memories": [], "wishes": [], "horizons": [], "places": [], "items": [], "casts": [],
           "tasks": [], "funds": []}
    if ids:
        marks = ",".join("?" * len(ids))
        out["memories"] = db.rows(conn.execute(
            f"""SELECT DISTINCT m.id, m.type, m.domain, m.content, m.occurred_at, m.importance FROM memories m
                JOIN memory_entities me ON me.memory_id = m.id
                WHERE me.entity_id IN ({marks}) AND m.status NOT IN {INACTIVE_SQL} AND m.type != 'summary'
                ORDER BY m.occurred_at DESC LIMIT 30""", ids))
        refs = defaultdict(set)
        for ref, rid in conn.execute(f"SELECT ref, ref_id FROM links WHERE entity_id IN ({marks})", ids):
            refs[ref].add(rid)
        cols = {"wishes": "id, content, status, mentioned_at", "horizons": "id, title, date, status, reflection",
                "places": "id, name, visited_on", "items": "id, code, model, status, buy_price, sell_price",
                "casts": "id, day, question, hex, outcome", "tasks": "id, title, status, due"}
        for ref, rids in refs.items():
            if ref in cols:
                m2 = ",".join("?" * len(rids))
                out[ref] = db.rows(conn.execute(f"SELECT {cols[ref]} FROM {ref} WHERE id IN ({m2})", tuple(rids)))
    from . import business

    out["funds"] = [f for f in business.funds(conn) if name.lower() in f["name"].lower()]
    return out


def about_lines(conn, name: str) -> list[str]:
    from . import yi

    a = about(conn, name)
    cur = config.currency()
    today = date.today()
    L = [f"她 {w['mentioned_at']} 说过「{w['content']}」（{w['status']}）" for w in a["wishes"]]
    for h in a["horizons"]:
        if h["status"] == "ahead":
            L.append(f"盼头「{h['title']}」还有 {(date.fromisoformat(h['date']) - today).days} 天")
        else:
            L.append(f"「{h['title']}」已经一起经历过" + (f"：{h['reflection']}" if h["reflection"] else ""))
    L += [f"去过 {p['name']}" + (f"（{p['visited_on']}）" if p["visited_on"] else "") for p in a["places"]]
    for f in a["funds"]:
        L.append(f"{f['name']}：已攒 {cur}{f['saved']:.0f}" + (f" / {cur}{f['target']}" if f["target"] else ""))
    for i in a["items"]:
        state = f"卖出 {cur}{i['sell_price']:.0f}" if i["sell_price"] else "在库"
        L.append(f"{i['code']} {i['model']}：收 {cur}{i['buy_price']:.0f}，{state}")
    for c in a["casts"]:
        L.append(f"{c['day']} 为「{c['question']}」起过一卦：{yi.info(c['hex'])['full']}"
                 + (f"；后来：{c['outcome']}" if c["outcome"] else ""))
    L += [f"口袋里还有：{t['title']}" for t in a["tasks"] if t["status"] == "todo"]
    return L


# ------------------------------------------------------------------ 3. 回忆

def recall(conn, query: str, k: int = 8, touch: bool = True, at: datetime | None = None) -> list[dict]:
    """和眼前这件事最相关的记忆：字面相关 + 网上相连 + 时近 + 重要。"""
    from . import memory

    at = at or datetime.now()
    rows = db.rows(conn.execute(f"SELECT * FROM memories WHERE status NOT IN {INACTIVE_SQL}"))
    topic_ids = set(_expand(conn, topics_in(conn, query)))
    linked = set()
    if topic_ids:
        marks = ",".join("?" * len(topic_ids))
        linked = {r[0] for r in conn.execute(
            f"SELECT memory_id FROM memory_entities WHERE entity_id IN ({marks})", tuple(topic_ids))}
    about_her = bool(re.search(r"她|女友|女朋友", query))
    pool = []
    for m in rows:
        rel = memory.similarity(query, m["content"])
        bonus = 1.0 if m["id"] in linked else 0
        if about_her and m["domain"] == "关系":
            bonus += 0.4
        if rel <= 0.05 and not bonus:
            continue
        s = memory.score(m, query, at) + bonus
        s += {"reflection": 0.4, "semantic": 0.3, "summary": -0.4}.get(m["type"], 0)
        if m["status"] == "needs_confirm":
            s -= 0.3
        m["score"] = round(s, 3)
        pool.append(m)
    pool.sort(key=lambda m: -m["score"])
    top = pool[:k]
    if touch and top:
        conn.executemany("UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                         [(db.now(), m["id"]) for m in top])
        conn.commit()
    return top


_LABEL = {"reflection": "（领悟）", "semantic": "（事实）", "summary": "（那天）", "prospective": "（打算）"}


def context(conn, query: str, k: int = 8) -> str:
    """给 AI 的"回忆"：相关记忆 + 相关的事。没有就返回空字符串。"""
    L = []
    mems = recall(conn, query, k)
    if mems:
        L.append("相关的记忆：")
        L += [f"- {m['occurred_at'][:10]} [{m['domain'] or ''}]{_LABEL.get(m['type'], '')} {m['content']}" for m in mems]
    names = [r[0] for r in conn.execute(
        f"SELECT name FROM entities WHERE id IN ({','.join('?' * len(ids))})", ids)] if (ids := topics_in(conn, query)) else []
    for name in names[:3]:
        lines = about_lines(conn, name)
        if lines:
            L.append(f"关于「{name}」：")
            L += [f"- {x}" for x in lines[:8]]
    return "\n".join(L)


def known(conn, limit: int = 12) -> str:
    """常驻核心记忆的"它所知道的"：领悟 + 稳定事实（不含被取代的）。"""
    rows = db.rows(conn.execute(
        "SELECT type, content FROM memories WHERE type IN ('reflection', 'semantic') AND status = 'active' "
        "ORDER BY CASE type WHEN 'reflection' THEN 0 ELSE 1 END, importance DESC, occurred_at DESC LIMIT ?", (limit,)))
    return "\n".join(f"- {_LABEL[r['type']]}{r['content']}" for r in rows)


# ------------------------------------------------------------------ 此刻的脉搏：给建议用的轻量信号

def pulse(conn, at: datetime | None = None) -> dict:
    at = at or datetime.now()
    week = (at - timedelta(days=7)).isoformat()
    kinds = ",".join("?" * len(TOPIC_KINDS))
    hot = [r[0] for r in conn.execute(
        f"""SELECT e.name FROM memory_entities me JOIN memories m ON m.id = me.memory_id JOIN entities e ON e.id = me.entity_id
            WHERE e.kind IN ({kinds}) AND m.occurred_at >= ? AND m.type NOT IN ('summary', 'reflection')
              AND m.status NOT IN {INACTIVE_SQL}
            GROUP BY e.id HAVING COUNT(*) >= 2 ORDER BY COUNT(*) DESC LIMIT 5""", (*TOPIC_KINDS, week))]
    wish_topics = [r[0] for r in conn.execute(
        f"""SELECT DISTINCT e.name FROM links l JOIN wishes w ON w.id = l.ref_id AND l.ref = 'wishes'
            JOIN entities e ON e.id = l.entity_id WHERE w.status NOT IN ('已实现', '放下') AND e.kind IN ({kinds})""",
        TOPIC_KINDS)]
    last_her = conn.execute(
        f"SELECT MAX(occurred_at) FROM memories WHERE domain = '关系' AND type NOT IN ('summary', 'reflection') "
        f"AND status NOT IN {INACTIVE_SQL}").fetchone()[0]
    recent_any = conn.execute(
        "SELECT COUNT(*) FROM memories WHERE occurred_at >= ? AND type NOT IN ('summary', 'reflection')", (week,)).fetchone()[0]
    her_quiet = (at - datetime.fromisoformat(last_her)).days if last_her else None
    strain = [r[0][len("strain:"):] for r in conn.execute(
        "SELECT rkey FROM memories WHERE type = 'reflection' AND status = 'active' AND rkey LIKE 'strain:%'")]
    return {"hot": hot, "wish_topics": wish_topics, "her_quiet": her_quiet if recent_any >= 3 else None, "strain": strain}


def nudge(p: dict, title: str, domain: str | None, feeling: str) -> tuple[float, str]:
    """记忆对一件事的轻微影响：返回（系数, 理由）。只影响轻重，不改变事实。"""
    f, notes = 1.0, []
    low = title.lower()
    hot = next((h for h in p["hot"] if h.lower() in low), None)
    if hot:
        f *= 1.15
        notes.append(f"最近你常想起「{hot}」")
    wish = next((w for w in p["wish_topics"] if w.lower() in low), None)
    if wish:
        f *= 1.2
        notes.append("和她的愿望有关")
    if domain == "关系" and (p["her_quiet"] or 0) >= 5 and feeling not in ("烦躁", "低落"):
        f *= 1.3
        notes.append(f"这 {p['her_quiet']} 天没记下和她的事")
    if domain in p["strain"] and feeling in LOW_FEELINGS:
        f *= 0.8
        notes.append("这类事常和你累的日子一起出现，今天可以轻一点")
    return f, "；".join(notes)


# ------------------------------------------------------------------ 4. 领悟

def _save_reflection(conn, key: str, content: str, domain: str | None, evidence: list[int],
                     confidence: float = 0.7, importance: int = 7) -> int | None:
    old = conn.execute("SELECT id, status FROM memories WHERE type = 'reflection' AND rkey = ?", (key,)).fetchone()
    tags = json.dumps({"evidence": evidence[:20]})
    if old and old["status"] == "archived":
        return None  # 你说过"不对"，就不再提
    if old:
        conn.execute("UPDATE memories SET content = ?, domain = ?, tags = ?, confidence = ?, importance = ?, status = 'active', "
                     "occurred_at = ? WHERE id = ?", (content, domain, tags, confidence, importance, db.now(), old["id"]))
        return old["id"]
    return conn.execute(
        """INSERT INTO memories(type, domain, content, occurred_at, importance, confidence, tags, status, rkey, created_at)
           VALUES('reflection', ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
        (domain, content, db.now(), importance, confidence, tags, key, db.now())).lastrowid


def _rule_reflections(conn, at: datetime) -> list[tuple]:
    out = []
    month = (at - timedelta(days=30)).isoformat()
    kinds = ",".join("?" * len(TOPIC_KINDS))
    # a. 反复出现的事
    for eid, name, n in conn.execute(
        f"""SELECT e.id, e.name, COUNT(*) FROM memory_entities me JOIN memories m ON m.id = me.memory_id
            JOIN entities e ON e.id = me.entity_id
            WHERE e.kind IN ({kinds}) AND m.occurred_at >= ? AND m.type NOT IN ('summary', 'reflection')
              AND m.status NOT IN {INACTIVE_SQL}
            GROUP BY e.id HAVING COUNT(*) >= 3""", (*TOPIC_KINDS, month)).fetchall():
        mems = db.rows(conn.execute(
            f"SELECT m.id, m.domain FROM memories m JOIN memory_entities me ON me.memory_id = m.id "
            f"WHERE me.entity_id = ? AND m.occurred_at >= ? AND m.type NOT IN ('summary', 'reflection')", (eid, month)))
        her = sum(1 for m in mems if m["domain"] == "关系")
        domain = Counter(m["domain"] for m in mems).most_common(1)[0][0]
        if her >= 2:
            text = f"这一个月里，和她有关的记忆 {her} 次提到「{name}」。说了几次的事，往往比说出口的更重要。"
        else:
            text = f"这一个月，「{name}」在你的记忆里出现了 {n} 次。它可能正占着你的心。"
        out.append((f"topic:{name}", text, domain, [m["id"] for m in mems], 0.8))
    # b. 和她之间的安静
    ten = (at - timedelta(days=10)).isoformat()
    recent = db.rows(conn.execute(
        f"SELECT id, domain FROM memories WHERE occurred_at >= ? AND type NOT IN ('summary', 'reflection') "
        f"AND status NOT IN {INACTIVE_SQL}", (ten,)))
    if len(recent) >= 5 and not any(m["domain"] == "关系" for m in recent):
        out.append(("her:quiet", f"过去 10 天你记下了 {len(recent)} 件事，没有一件和她有关。也许只是没记，也许值得留意。",
                    "关系", [m["id"] for m in recent], 0.6))
    # c/d. 累的日子、好的日子，常和什么在一起
    since = (at - timedelta(days=60)).isoformat()
    day_feel = defaultdict(set)
    for f, a in conn.execute("SELECT feeling, at FROM states WHERE at >= ?", (since,)):
        day_feel[a[:10]].add(f)
    mems = db.rows(conn.execute(
        f"SELECT id, domain, substr(occurred_at, 1, 10) day, mood FROM memories WHERE occurred_at >= ? "
        f"AND type NOT IN ('summary', 'reflection', 'prospective') AND status NOT IN {INACTIVE_SQL} AND domain IS NOT NULL",
        (since,)))
    if mems:
        all_share = Counter(m["domain"] for m in mems)
        total = sum(all_share.values())
        for key, label, is_day in (
            ("strain", "你感觉累或烦的那些天", lambda m: day_feel.get(m["day"], set()) & set(LOW_FEELINGS)),
            ("joy", "你状态好的那些天", lambda m: "充沛" in day_feel.get(m["day"], set()) or (m["mood"] or 0) >= 8),
        ):
            picked = [m for m in mems if is_day(m)]
            days = {m["day"] for m in picked}
            if len(days) < 3:
                continue
            share = Counter(m["domain"] for m in picked)
            n = sum(share.values())
            for domain, c in share.most_common(2):
                ratio = (c / n) / (all_share[domain] / total)
                if c < 3 or ratio < 1.5:
                    continue
                if key == "strain" and domain == "关系":
                    text = f"{label}，和她有关的记忆也特别多。也许是有摩擦，也许是她在陪你，值得想一想是哪一种。"
                else:
                    tail = "不一定是它让你累，但它们常常一起出现。" if key == "strain" else "这也许是你的一处源泉。"
                    text = f"{label}，记忆里「{domain}」特别多（{c / n:.0%}，平时 {all_share[domain] / total:.0%}）。{tail}"
                out.append((f"{key}:{domain}", text, domain, [m["id"] for m in picked if m["domain"] == domain], 0.6))
    return out


AI_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["insights", "supersede"],
    "properties": {
        "insights": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["content", "domain", "evidence", "confidence"],
            "properties": {"content": {"type": "string"}, "domain": {"type": "string"},
                           "evidence": {"type": "array", "items": {"type": "integer"}},
                           "confidence": {"type": "number"}}}},
        "supersede": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["old", "new"],
            "properties": {"old": {"type": "integer"}, "new": {"type": "integer"}}}},
    },
}


def _ai_reflections(conn) -> dict | None:
    mems = db.rows(conn.execute(
        f"SELECT id, type, domain, content, substr(occurred_at, 1, 10) day FROM memories "
        f"WHERE type NOT IN ('summary', 'reflection') AND status NOT IN {INACTIVE_SQL} ORDER BY occurred_at DESC LIMIT 120"))
    if len(mems) < 8:
        return None
    existing = db.rows(conn.execute("SELECT content, status FROM memories WHERE type = 'reflection'"))
    prompt = ("记忆（id | 日期 | 类型 | 领域 | 内容）：\n"
              + "\n".join(f"{m['id']} | {m['day']} | {m['type']} | {m['domain']} | {m['content']}" for m in mems)
              + "\n\n已有的领悟（不要重复；status=archived 的是他说过不对的，不要再提类似的）：\n"
              + "\n".join(f"- [{e['status']}] {e['content']}" for e in existing))
    return llm.complete_json(
        "你是 LifeOS 的记忆官，在为一位建筑师做'反思'（Generative Agents 的 reflection）。"
        "从这些记忆里找出最多 3 条更高一层的领悟：跨越多条记忆的规律、变化、她反复在意的事、他自己没说出口的牵挂。"
        "每条一两句中文，温和、具体，不诊断、不评判、不给待办；必须列出支撑它的记忆 id；confidence 0-1。"
        "另外，如果有 semantic 类型的旧事实被新的 semantic 事实取代（比如喜好变了），在 supersede 里给出 old/new 的 id；没有就给空数组。",
        prompt, AI_SCHEMA, effort="medium")


def reflect(conn, at: datetime | None = None, use_ai: bool | None = None) -> list[str]:
    at = at or datetime.now()
    made, keys = [], set()
    for key, text, domain, evidence, conf in _rule_reflections(conn, at):
        if _save_reflection(conn, key, text, domain, evidence, conf):
            made.append(text)
        keys.add(key)
    # 规则领悟不再成立时，悄悄淡出
    for r in db.rows(conn.execute("SELECT id, rkey FROM memories WHERE type = 'reflection' AND status = 'active' "
                                  "AND rkey NOT LIKE 'ai:%'")):
        if r["rkey"] not in keys:
            conn.execute("UPDATE memories SET status = 'faded' WHERE id = ?", (r["id"],))
    if use_ai is None:
        last = db.get_meta(conn, "mind_ai_reflect")
        use_ai = llm.available() and (not last or (at - datetime.fromisoformat(last)).days >= 7)
    if use_ai:
        res = _ai_reflections(conn)
        if res:
            valid = {r[0] for r in conn.execute("SELECT id FROM memories")}
            for ins in res.get("insights", [])[:3]:
                ev = [i for i in ins.get("evidence", []) if i in valid]
                if not ev or not ins.get("content"):
                    continue
                key = "ai:" + hashlib.sha1(ins["content"].encode()).hexdigest()[:10]
                if _save_reflection(conn, key, ins["content"], ins.get("domain"), ev, ins.get("confidence", 0.6)):
                    made.append(ins["content"])
            for s in res.get("supersede", []):
                supersede(conn, s["old"], s["new"])
            db.set_meta(conn, "mind_ai_reflect", at.isoformat(timespec="seconds"))
    conn.commit()
    return made


def reflections(conn, include_faded: bool = False) -> list[dict]:
    status = "('active', 'faded')" if include_faded else "('active')"
    return db.rows(conn.execute(
        f"SELECT id, domain, content, occurred_at, confidence, tags, status FROM memories "
        f"WHERE type = 'reflection' AND status IN {status} ORDER BY occurred_at DESC"))


# ------------------------------------------------------------------ 5. 更新

_CHANGE_RE = re.compile(r"不再|不喜欢|不爱|不吃|其实|已经不|改成|换成|现在更|变成|戒了|开始喜欢")


def supersede(conn, old_id: int, new_id: int) -> None:
    conn.execute("UPDATE memories SET status = 'superseded', superseded_by = ? WHERE id = ? AND type = 'semantic'",
                 (new_id, old_id))


def check_supersede(conn, mem_id: int) -> int | None:
    """新的事实如果和某条旧事实说的是同一件事、但变了，就让旧的退场。返回被取代的 id。"""
    from . import memory

    new = conn.execute("SELECT * FROM memories WHERE id = ?", (mem_id,)).fetchone()
    if not new or new["type"] != "semantic" or not _CHANGE_RE.search(new["content"]):
        return None
    best, best_sim = None, 0.3
    for old in db.rows(conn.execute(
            "SELECT id, content FROM memories WHERE type = 'semantic' AND status = 'active' AND id != ? "
            "AND COALESCE(domain, '') = COALESCE(?, '')", (mem_id, new["domain"]))):
        sim = memory.similarity(old["content"], new["content"])
        if sim > best_sim:
            best, best_sim = old["id"], sim
    if best:
        supersede(conn, best, mem_id)
    return best


# ------------------------------------------------------------------ 每晚

def nightly(conn, day: str | None = None) -> dict:
    """晚安之后：巩固今天、更新领悟。升级后第一次会把旧记录全部连一遍。"""
    from . import memory

    if not db.get_meta(conn, "mind_indexed"):
        reindex(conn)
    s = memory.consolidate(day, conn)
    return {"summary": s, "reflections": reflect(conn)}
