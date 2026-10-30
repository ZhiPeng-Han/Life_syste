"""记忆系统：捕获 → 存储 → 检索 → 巩固。

检索打分借鉴 Generative Agents（Park et al., 2023）的 memory stream：
score = 时近性 + 重要性 + 相关性。被检索到的记忆会"复活"（更新 last_accessed）。
"""

import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta

from . import business, config, db, extract, llm

CONFIRM_THRESHOLD = 0.7


def capture(text: str, source: str = "cli", conn=None) -> dict:
    conn = conn or db.connect()
    raw_id = conn.execute(
        "INSERT INTO raw_inputs(text, source, created_at) VALUES(?, ?, ?)", (text, source, db.now())
    ).lastrowid
    data = extract.extract(text)
    summary = {"engine": data.get("engine"), "memories": [], "tasks": [], "wishes": [], "items": []}

    for m in data.get("memories", []):
        status = "needs_confirm" if m.get("confidence", 1) < CONFIRM_THRESHOLD else "active"
        mem_id = conn.execute(
            """INSERT INTO memories(raw_id, type, domain, content, occurred_at, importance, confidence, mood,
                                    status, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                raw_id, m["type"], m.get("domain"), m["content"], db.now(),
                max(1, min(10, m.get("importance", 5))), m.get("confidence", 1),
                m.get("mood") or None, status, db.now(),
            ),
        ).lastrowid
        entity_ids = []
        if m.get("domain"):
            entity_ids.append(db.entity(conn, "domain", m["domain"]))
        for person in m.get("people", []):
            entity_ids.append(db.entity(conn, "person", person))
        for eid in entity_ids:
            conn.execute("INSERT OR IGNORE INTO memory_entities VALUES(?, ?)", (mem_id, eid))
        # 共现即证据：同一条记忆里出现的实体之间关系加强
        for i, a in enumerate(entity_ids):
            for b in entity_ids[i + 1 :]:
                db.relate(conn, a, b, "related", bump=0.5)
        summary["memories"].append({"id": mem_id, "domain": m.get("domain"), "content": m["content"], "status": status})

    for t in data.get("tasks", []):
        task_id = conn.execute(
            """INSERT INTO tasks(title, domain, priority, energy, est_minutes, due, source, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (
                t["title"], t.get("domain"), max(1, min(5, t.get("priority", 3))), t.get("energy", "medium"),
                t.get("est_minutes") or 30, t.get("due") or None, "capture", db.now(),
            ),
        ).lastrowid
        summary["tasks"].append({"id": task_id, "title": t["title"], "due": t.get("due")})

    for w in data.get("wishes", []):
        wish_id = conn.execute(
            "INSERT INTO wishes(person, content, category, mentioned_at) VALUES(?,?,?,?)",
            (w.get("person") or "她", w["content"], w.get("category", "other"), db.today()),
        ).lastrowid
        summary["wishes"].append({"id": wish_id, "content": w["content"]})

    for it in data.get("items", []):
        if it["action"] == "buy":
            item = business.add_item(
                conn, it["model"], it["price"], platform=it.get("platform") or None, defects=it.get("defects", [])
            )
            summary["items"].append({"action": "buy", "code": item["code"], "model": it["model"], "price": it["price"]})
        else:
            sold = business.sell_by_model(conn, it["model"], it["price"], it.get("platform") or None)
            summary["items"].append(
                {"action": "sell", "code": sold["code"] if sold else None, "model": it["model"], "price": it["price"]}
            )
    conn.commit()
    return summary


# ------------------------------------------------------------------ 检索

def _tokens(text: str) -> Counter:
    text = text.lower()
    words = re.findall(r"[a-z0-9.]+", text)
    han = re.sub(r"[^一-鿿]", "", text)
    bigrams = [han[i : i + 2] for i in range(len(han) - 1)] or list(han)
    return Counter(words + bigrams)


def similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    dot = sum(ta[k] * tb[k] for k in ta.keys() & tb.keys())
    return dot / math.sqrt(sum(v * v for v in ta.values()) * sum(v * v for v in tb.values()))


def score(mem: dict, query: str, at: datetime) -> float:
    last = datetime.fromisoformat(mem.get("last_accessed") or mem["occurred_at"])
    hours = max((at - last).total_seconds() / 3600, 0)
    recency = 0.995**hours
    importance = (mem.get("importance") or 5) / 10
    relevance = similarity(query, mem["content"]) if query else 0
    return recency + importance + 2 * relevance


def search(query: str = "", limit: int = 10, domain: str | None = None, conn=None, touch: bool = True) -> list[dict]:
    conn = conn or db.connect()
    sql = "SELECT * FROM memories WHERE status != 'archived'"
    args: list = []
    if domain:
        sql += " AND domain = ?"
        args.append(domain)
    mems = db.rows(conn.execute(sql, args))
    at = datetime.now()
    for m in mems:
        m["score"] = round(score(m, query, at), 3)
        m["relevance"] = round(similarity(query, m["content"]), 3) if query else 0
    if query:
        mems = [m for m in mems if m["relevance"] > 0.05]
    mems.sort(key=lambda m: m["score"], reverse=True)
    top = mems[:limit]
    if touch and query:
        conn.executemany(
            "UPDATE memories SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
            [(db.now(), m["id"]) for m in top],
        )
        conn.commit()
    return top


def timeline(days: int = 30, conn=None) -> list[dict]:
    conn = conn or db.connect()
    since = (datetime.now() - timedelta(days=days)).isoformat()
    return db.rows(
        conn.execute(
            "SELECT * FROM memories WHERE occurred_at >= ? AND status != 'archived' ORDER BY occurred_at DESC", (since,)
        )
    )


def pending_confirm(conn=None) -> list[dict]:
    conn = conn or db.connect()
    return db.rows(conn.execute("SELECT * FROM memories WHERE status = 'needs_confirm' ORDER BY id"))


def confirm(mem_id: int, keep: bool = True, conn=None) -> None:
    conn = conn or db.connect()
    conn.execute("UPDATE memories SET status = ? WHERE id = ?", ("active" if keep else "archived", mem_id))
    conn.commit()


# ------------------------------------------------------------------ 巩固

def consolidate(day: str | None = None, conn=None) -> dict | None:
    """把某天的记忆压缩成一条日摘要（type=summary）。已存在则覆盖。"""
    conn = conn or db.connect()
    day = day or db.today()
    mems = db.rows(
        conn.execute(
            "SELECT * FROM memories WHERE substr(occurred_at, 1, 10) = ? AND type != 'summary' AND status != 'archived'",
            (day,),
        )
    )
    if not mems:
        return None
    by_domain = Counter(m["domain"] for m in mems)
    top = sorted(mems, key=lambda m: m["importance"], reverse=True)[:5]
    text = llm.complete_text(
        "你是 LifeOS 的记忆官。把用户一天的记忆压缩成 3-5 句中文日摘要：要点、情绪、和女友相关的事、值得以后记住的事实。不要编造。",
        "\n".join(f"- [{m['domain']}] {m['content']}" for m in mems),
        effort="low",
    )
    if not text:
        dist = "、".join(f"{d} {n} 条" for d, n in by_domain.most_common())
        text = f"{day}：共 {len(mems)} 条记忆（{dist}）。要点：" + "；".join(m["content"] for m in top)
    conn.execute("DELETE FROM memories WHERE type = 'summary' AND substr(occurred_at, 1, 10) = ?", (day,))
    conn.execute(
        """INSERT INTO memories(type, domain, content, occurred_at, importance, tags, created_at)
           VALUES('summary', '日摘要', ?, ?, 6, ?, ?)""",
        (text, f"{day}T23:59:00", json.dumps(["daily"]), db.now()),
    )
    conn.commit()
    return {"day": day, "summary": text, "count": len(mems)}


# ------------------------------------------------------------------ 星图数据

def graph(conn=None) -> dict:
    conn = conn or db.connect()
    ents = db.rows(conn.execute("SELECT id, kind, name FROM entities"))
    counts = dict(conn.execute("SELECT entity_id, COUNT(*) FROM memory_entities GROUP BY entity_id").fetchall())
    rels = db.rows(conn.execute("SELECT source_id, target_id, kind, strength, status, note FROM relations"))
    nodes = [{**e, "size": counts.get(e["id"], 0)} for e in ents]
    return {"nodes": nodes, "edges": rels, "weights": {d: config.domain_weight(d) for d in config.domains()}}
