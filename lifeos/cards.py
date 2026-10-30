"""Part 3 间隔复习卡片（SM-2 算法）。后续迭代可换成 FSRS（open-spaced-repetition/py-fsrs）。"""

from datetime import date, timedelta

from . import db


def add(conn, front: str, back: str, deck: str = "Part3") -> int:
    cid = conn.execute(
        "INSERT INTO cards(deck, front, back, due) VALUES(?,?,?,?)", (deck, front, back, db.today())
    ).lastrowid
    conn.commit()
    return cid


def due(conn, on: str | None = None, deck: str | None = None) -> list[dict]:
    sql = "SELECT * FROM cards WHERE due <= ?"
    args = [on or db.today()]
    if deck:
        sql += " AND deck = ?"
        args.append(deck)
    return db.rows(conn.execute(sql + " ORDER BY due, id", args))


def review(conn, card_id: int, grade: int, on: date | None = None) -> dict:
    """grade: 0-5（0=完全忘了，3=想起来但费劲，5=秒答）。"""
    on = on or date.today()
    c = dict(conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone())
    grade = max(0, min(5, grade))
    if grade < 3:
        reps, interval, lapses = 0, 1, c["lapses"] + 1
    else:
        reps = c["reps"] + 1
        interval = 1 if reps == 1 else 6 if reps == 2 else round(c["interval"] * c["ease"])
        lapses = c["lapses"]
    ease = max(1.3, c["ease"] + 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    nxt = (on + timedelta(days=interval)).isoformat()
    conn.execute(
        "UPDATE cards SET ease = ?, interval = ?, reps = ?, due = ?, lapses = ? WHERE id = ?",
        (ease, interval, reps, nxt, lapses, card_id),
    )
    conn.commit()
    return {"id": card_id, "next_due": nxt, "interval": interval, "ease": round(ease, 2)}


def stats(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    mature = conn.execute("SELECT COUNT(*) FROM cards WHERE interval >= 21").fetchone()[0]
    return {"total": total, "due_today": len(due(conn)), "mature": mature}
