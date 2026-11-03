"""个人实验（N-of-1）：把"我觉得"变成"我知道"。

比较实验期与之前等长基线期的签到指标均值。样本小、无随机化，结论只作参考，
但比凭感觉强得多；重要结论建议用 A-B-A-B 交替重复验证。
"""

import statistics
from datetime import date, timedelta

from . import db

METRICS = ("mood", "energy", "sleep_hours", "love_minutes", "exercised")


def add(conn, name: str, metric: str, start: str, end: str, hypothesis: str = "") -> int:
    if metric not in METRICS:
        raise ValueError(f"metric 必须是 {METRICS} 之一")
    eid = conn.execute(
        "INSERT INTO experiments(name, hypothesis, metric, start, end) VALUES(?,?,?,?,?)",
        (name, hypothesis, metric, start, end),
    ).lastrowid
    conn.commit()
    return eid


def _values(conn, metric: str, start: date, end: date) -> list[float]:
    return [
        r[0]
        for r in conn.execute(
            f"SELECT {metric} FROM checkins WHERE day BETWEEN ? AND ? AND {metric} IS NOT NULL",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
    ]


def analyze(conn, exp_id: int) -> dict:
    e = dict(conn.execute("SELECT * FROM experiments WHERE id = ?", (exp_id,)).fetchone())
    start, end = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
    length = (end - start).days + 1
    base_end = start - timedelta(days=1)
    base_start = base_end - timedelta(days=length - 1)
    exp_vals = _values(conn, e["metric"], start, min(end, date.today()))
    base_vals = _values(conn, e["metric"], base_start, base_end)
    out = {"experiment": e["name"], "metric": e["metric"], "n_exp": len(exp_vals), "n_base": len(base_vals)}
    if len(exp_vals) < 3 or len(base_vals) < 3:
        out["conclusion"] = "数据不足（每段至少需要 3 次签到）"
        return out
    m_exp, m_base = statistics.mean(exp_vals), statistics.mean(base_vals)
    sd = statistics.pstdev(exp_vals + base_vals) or 1
    effect = (m_exp - m_base) / sd
    out.update({"mean_exp": round(m_exp, 2), "mean_base": round(m_base, 2), "effect_size": round(effect, 2)})
    if abs(effect) < 0.2:
        out["conclusion"] = "几乎没有差异"
    else:
        out["conclusion"] = f"实验期{'更高' if effect > 0 else '更低'}（效应量 {effect:.2f}，{'较明显' if abs(effect) >= 0.5 else '轻微'}）"
    if date.today() > end and e["status"] == "running":
        conn.execute("UPDATE experiments SET status = 'done', result = ? WHERE id = ?", (out["conclusion"], exp_id))
        conn.commit()
    return out


def list_all(conn) -> list[dict]:
    return db.rows(conn.execute("SELECT * FROM experiments ORDER BY id DESC"))
