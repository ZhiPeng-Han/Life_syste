"""照片回响（借鉴 Journiv 的"那年今日"+ 照片库）：你是摄影师，回忆最好带着那天的光。

只索引你在 rules.toml [photos] folders 里指定的文件夹（可以是 Immich 的存储目录）。
拍摄时间优先读 EXIF DateTimeOriginal，其次文件名里的日期，最后用修改时间。
照片不会离开你的电脑；网页只能通过编号取到已索引的照片。
"""

import os
import re
from datetime import date, datetime
from pathlib import Path

from . import config, db

EXTS = {".jpg", ".jpeg", ".heic", ".png", ".webp"}
EXIF_RE = re.compile(rb"(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})")
NAME_RE = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")


def taken_at(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            head = f.read(256 * 1024)
        m = EXIF_RE.search(head)
        if m:
            y, mo, d, h, mi, s = (int(x) for x in m.groups())
            return datetime(y, mo, d, h, mi, s).isoformat()
    except (OSError, ValueError):
        pass
    m = NAME_RE.search(path.name)
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def scan(conn) -> dict:
    folders = config.rules().get("photos", {}).get("folders", [])
    added = 0
    for folder in folders:
        root = Path(os.path.expanduser(folder))
        if not root.is_dir():
            continue
        known = {r[0] for r in conn.execute("SELECT path FROM photos").fetchall()}
        for p in root.rglob("*"):
            if p.suffix.lower() in EXTS and p.is_file() and str(p) not in known:
                conn.execute("INSERT OR IGNORE INTO photos(path, taken_at) VALUES(?, ?)", (str(p), taken_at(p)))
                added += 1
        conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
    return {"added": added, "total": total, "folders": folders}


def on_this_day(conn, on: date | None = None, limit: int = 3) -> list[dict]:
    """往年的今天拍的照片（不含今年）。"""
    on = on or date.today()
    rows = db.rows(conn.execute(
        "SELECT id, taken_at FROM photos WHERE substr(taken_at, 6, 5) = ? AND substr(taken_at, 1, 4) < ? ORDER BY RANDOM() LIMIT ?",
        (on.strftime("%m-%d"), str(on.year), limit)))
    for r in rows:
        r["years_ago"] = on.year - int(r["taken_at"][:4])
    return rows


def path_of(conn, photo_id: int) -> Path | None:
    row = conn.execute("SELECT path FROM photos WHERE id = ?", (photo_id,)).fetchone()
    return Path(row[0]) if row and Path(row[0]).is_file() else None
