"""决策引擎的"放权"部分：建议 → 反馈 → 自主等级升降；以及决策日志与校准。

L0 仅记录 / L1 建议 / L2 默认（不反对就执行）/ L3 自动+汇报 / L4 托管
"""

from datetime import date, timedelta

from . import config, db

LEVEL_NAMES = {0: "L0 仅记录", 1: "L1 建议", 2: "L2 默认", 3: "L3 自动+汇报", 4: "L4 托管"}


def _policy() -> dict:
    return config.rules().get("autonomy", {})


def level(conn, category: str) -> int:
    row = conn.execute("SELECT level FROM autonomy WHERE category = ?", (category,)).fetchone()
    if row:
        return row[0]
    return _policy().get(category, {}).get("level", 1)


def set_level(conn, category: str, new_level: int) -> int:
    cap = _policy().get(category, {}).get("cap", 4)
    new_level = max(0, min(new_level, cap))
    conn.execute(
        "INSERT INTO autonomy(category, level, changed_at) VALUES(?,?,?) "
        "ON CONFLICT(category) DO UPDATE SET level = excluded.level, changed_at = excluded.changed_at",
        (category, new_level, db.now()),
    )
    conn.commit()
    return new_level


def suggest(conn, category: str, content: str, rationale: str = "") -> int:
    lvl = level(conn, category)
    status = "auto" if lvl >= 3 else "pending"
    sid = conn.execute(
        "INSERT INTO suggestions(category, content, rationale, level, status, created_at) VALUES(?,?,?,?,?,?)",
        (category, content, rationale, lvl, status, db.now()),
    ).lastrowid
    conn.commit()
    return sid


def feedback(conn, suggestion_id: int, verdict: str, reason: str = "", severe: bool = False) -> dict:
    """verdict: accept / reject / modify。severe=True 表示"错得离谱"，立即降一级。"""
    status = {"accept": "accepted", "reject": "rejected", "modify": "modified"}[verdict]
    row = conn.execute("SELECT category FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not row:
        raise ValueError(f"建议 {suggestion_id} 不存在")
    conn.execute(
        "UPDATE suggestions SET status = ?, feedback = ?, severe = ?, resolved_at = ? WHERE id = ?",
        (status, reason, int(severe), db.now(), suggestion_id),
    )
    conn.commit()
    result = {"id": suggestion_id, "status": status}
    if severe:
        new = set_level(conn, row[0], level(conn, row[0]) - 1)
        result["demoted_to"] = LEVEL_NAMES[new]
        _insight(conn, f"「{row[0]}」因一次严重错误被降为 {LEVEL_NAMES[new]}。原因：{reason}", "autonomy")
    return result


def acceptance(conn, category: str, last_n: int | None = None) -> dict:
    last_n = last_n or config.rules().get("autonomy_policy", {}).get("min_samples", 20)
    rows = conn.execute(
        "SELECT status FROM suggestions WHERE category = ? AND status IN ('accepted','rejected','modified') "
        "ORDER BY id DESC LIMIT ?",
        (category, last_n),
    ).fetchall()
    n = len(rows)
    accepted = sum(1 for r in rows if r[0] == "accepted")
    return {"category": category, "n": n, "accepted": accepted, "rate": round(accepted / n, 3) if n else None}


def promotion_candidates(conn) -> list[dict]:
    policy = config.rules().get("autonomy_policy", {})
    min_n, rate = policy.get("min_samples", 20), policy.get("promote_rate", 0.9)
    out = []
    for cat, p in _policy().items():
        a = acceptance(conn, cat, min_n)
        cur = level(conn, cat)
        if a["n"] >= min_n and a["rate"] >= rate and cur < p.get("cap", 4):
            out.append({**a, "from": LEVEL_NAMES[cur], "to": LEVEL_NAMES[cur + 1]})
    return out


def overview(conn) -> list[dict]:
    return [
        {"category": cat, "desc": p.get("desc", ""), "level": LEVEL_NAMES[level(conn, cat)],
         "cap": LEVEL_NAMES[p.get("cap", 4)], **acceptance(conn, cat)}
        for cat, p in _policy().items()
    ]


def pending(conn) -> list[dict]:
    return db.rows(conn.execute("SELECT * FROM suggestions WHERE status = 'pending' ORDER BY id DESC LIMIT 30"))


def _insight(conn, content: str, kind: str) -> None:
    conn.execute("INSERT INTO insights(content, kind, created_at) VALUES(?,?,?)", (content, kind, db.now()))
    conn.commit()


# ------------------------------------------------------------------ 决策日志与校准

def log_decision(conn, question: str, choice: str, prediction: str, confidence: float,
                 category: str = "", suggestion: str = "", review_in_days: int = 14) -> int:
    did = conn.execute(
        """INSERT INTO decisions(category, question, suggestion, choice, prediction, confidence, decided_at, review_on)
           VALUES(?,?,?,?,?,?,?,?)""",
        (category, question, suggestion, choice, prediction, confidence, db.now(),
         (date.today() + timedelta(days=review_in_days)).isoformat()),
    ).lastrowid
    conn.commit()
    return did


def review_decision(conn, decision_id: int, outcome: str, correct: bool, lesson: str = "") -> None:
    conn.execute(
        "UPDATE decisions SET outcome = ?, correct = ?, lesson = ?, reviewed_at = ? WHERE id = ?",
        (outcome, int(correct), lesson, db.now(), decision_id),
    )
    conn.commit()


def due_reviews(conn) -> list[dict]:
    return db.rows(conn.execute(
        "SELECT * FROM decisions WHERE reviewed_at IS NULL AND review_on <= ? ORDER BY review_on", (db.today(),)
    ))


def calibration(conn) -> list[dict]:
    """你说"70% 把握"的事，实际成功率是多少？按信心分桶。"""
    rows = conn.execute("SELECT confidence, correct FROM decisions WHERE correct IS NOT NULL").fetchall()
    buckets: dict = {}
    for conf, correct in rows:
        b = min(int(conf * 10) * 10, 90)
        bucket = buckets.setdefault(b, [0, 0])
        bucket[0] += 1
        bucket[1] += correct
    return [{"confidence": f"{b}-{b + 10}%", "n": n, "hit_rate": round(c / n, 2)} for b, (n, c) in sorted(buckets.items())]
