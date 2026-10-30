"""任务池。"""

from . import db


def add(conn, title: str, domain: str = "生活维持", priority: int = 3, energy: str = "medium",
        minutes: int = 30, due: str | None = None, project: str | None = None, source: str = "manual") -> int:
    tid = conn.execute(
        """INSERT INTO tasks(title, domain, project, priority, energy, est_minutes, due, source, created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (title, domain, project, priority, energy, minutes, due, source, db.now()),
    ).lastrowid
    conn.commit()
    return tid


def done(conn, task_id: int) -> None:
    conn.execute("UPDATE tasks SET status = 'done', done_at = ? WHERE id = ?", (db.now(), task_id))
    conn.commit()


def drop(conn, task_id: int) -> None:
    conn.execute("UPDATE tasks SET status = 'dropped', done_at = ? WHERE id = ?", (db.now(), task_id))
    conn.commit()


def list_open(conn, domain: str | None = None, project: str | None = None) -> list[dict]:
    sql, args = "SELECT * FROM tasks WHERE status = 'todo'", []
    if domain:
        sql += " AND domain = ?"
        args.append(domain)
    if project:
        sql += " AND project = ?"
        args.append(project)
    return db.rows(conn.execute(sql + " ORDER BY priority DESC, due IS NULL, due, id", args))
