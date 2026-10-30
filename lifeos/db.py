"""SQLite 存储。schema 带版本号，后续迭代通过追加 MIGRATIONS 平滑升级。"""

import json
import sqlite3
from datetime import datetime

from . import config

MIGRATIONS = [
    # v1：初始结构
    """
    CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

    CREATE TABLE raw_inputs (
        id INTEGER PRIMARY KEY,
        text TEXT NOT NULL,
        source TEXT DEFAULT 'cli',
        created_at TEXT NOT NULL
    );

    CREATE TABLE memories (
        id INTEGER PRIMARY KEY,
        raw_id INTEGER REFERENCES raw_inputs(id),
        type TEXT NOT NULL,            -- episodic / semantic / procedural / prospective / normative / summary
        domain TEXT,
        content TEXT NOT NULL,
        occurred_at TEXT NOT NULL,
        importance REAL DEFAULT 5,     -- 1-10
        confidence REAL DEFAULT 1,
        mood INTEGER,
        tags TEXT DEFAULT '[]',
        status TEXT DEFAULT 'active',  -- active / needs_confirm / archived
        access_count INTEGER DEFAULT 0,
        last_accessed TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE entities (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,            -- person / domain / project / item / place / platform / book / principle
        name TEXT NOT NULL,
        attributes TEXT DEFAULT '{}',
        created_at TEXT NOT NULL,
        UNIQUE(kind, name)
    );

    CREATE TABLE memory_entities (
        memory_id INTEGER REFERENCES memories(id),
        entity_id INTEGER REFERENCES entities(id),
        PRIMARY KEY (memory_id, entity_id)
    );

    CREATE TABLE relations (
        id INTEGER PRIMARY KEY,
        source_id INTEGER REFERENCES entities(id),
        target_id INTEGER REFERENCES entities(id),
        kind TEXT NOT NULL,            -- influence / competition / synergy / dependency / related
        strength REAL DEFAULT 1,
        status TEXT DEFAULT 'hypothesis', -- hypothesis / evidenced / validated / rejected
        note TEXT,
        updated_at TEXT NOT NULL,
        UNIQUE(source_id, target_id, kind)
    );

    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        domain TEXT,
        project TEXT,
        status TEXT DEFAULT 'todo',    -- todo / done / dropped
        priority INTEGER DEFAULT 3,    -- 1-5
        energy TEXT DEFAULT 'medium',  -- high / medium / low
        est_minutes INTEGER DEFAULT 30,
        due TEXT,
        batch TEXT,
        source TEXT DEFAULT 'manual',
        created_at TEXT NOT NULL,
        done_at TEXT
    );

    CREATE TABLE timelog (
        id INTEGER PRIMARY KEY,
        day TEXT NOT NULL,
        domain TEXT NOT NULL,
        minutes INTEGER NOT NULL,
        note TEXT
    );

    CREATE TABLE checkins (
        day TEXT PRIMARY KEY,
        energy INTEGER, mood INTEGER, sleep_hours REAL,
        exercised INTEGER DEFAULT 0,
        love_minutes INTEGER,
        note TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE items (
        id INTEGER PRIMARY KEY,
        code TEXT UNIQUE,
        model TEXT NOT NULL,
        serial TEXT,
        condition TEXT,
        defects TEXT DEFAULT '[]',
        buy_price REAL,
        buy_platform TEXT,
        bought_at TEXT,
        extra_costs REAL DEFAULT 0,
        status TEXT DEFAULT '待检测',  -- 待检测 / 待拍照 / 在售 / 已售 / 已发货 / 完结
        est_price REAL,
        list_price REAL,
        listed_at TEXT,
        sell_price REAL,
        sell_platform TEXT,
        sold_at TEXT,
        hours_spent REAL DEFAULT 0,
        notes TEXT
    );

    CREATE TABLE wishes (
        id INTEGER PRIMARY KEY,
        person TEXT DEFAULT '她',
        content TEXT NOT NULL,
        category TEXT,                 -- travel / project / health / gift / experience / other
        status TEXT DEFAULT '想法',    -- 想法 / 规划中 / 进行中 / 已实现
        mentioned_at TEXT NOT NULL,
        project TEXT,
        notes TEXT
    );

    CREATE TABLE important_dates (
        id INTEGER PRIMARY KEY,
        person TEXT DEFAULT '她',
        name TEXT NOT NULL,
        month INTEGER NOT NULL,
        day INTEGER NOT NULL,
        remind_days TEXT DEFAULT '[30, 7, 1]'
    );

    CREATE TABLE suggestions (
        id INTEGER PRIMARY KEY,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        rationale TEXT,
        level INTEGER,
        status TEXT DEFAULT 'pending', -- pending / accepted / rejected / modified / auto
        feedback TEXT,
        severe INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        resolved_at TEXT
    );

    CREATE TABLE autonomy (
        category TEXT PRIMARY KEY,
        level INTEGER NOT NULL,
        changed_at TEXT
    );

    CREATE TABLE decisions (
        id INTEGER PRIMARY KEY,
        category TEXT,
        question TEXT NOT NULL,
        suggestion TEXT,
        choice TEXT,
        prediction TEXT,
        confidence REAL,
        outcome TEXT,
        correct INTEGER,
        lesson TEXT,
        decided_at TEXT NOT NULL,
        review_on TEXT,
        reviewed_at TEXT
    );

    CREATE TABLE experiments (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        hypothesis TEXT,
        metric TEXT NOT NULL,          -- checkins 中的列：mood / energy / sleep_hours
        start TEXT NOT NULL,
        end TEXT NOT NULL,
        status TEXT DEFAULT 'running',
        result TEXT,
        decision TEXT
    );

    CREATE TABLE cards (
        id INTEGER PRIMARY KEY,
        deck TEXT DEFAULT 'Part3',
        front TEXT NOT NULL,
        back TEXT NOT NULL,
        ease REAL DEFAULT 2.5,
        interval INTEGER DEFAULT 0,
        reps INTEGER DEFAULT 0,
        due TEXT NOT NULL,
        lapses INTEGER DEFAULT 0
    );

    CREATE TABLE insights (
        id INTEGER PRIMARY KEY,
        content TEXT NOT NULL,
        kind TEXT,                     -- conflict / synergy / pattern / autonomy / reminder
        status TEXT DEFAULT 'new',     -- new / seen / accepted / rejected
        created_at TEXT NOT NULL
    );

    CREATE INDEX idx_mem_time ON memories(occurred_at);
    CREATE INDEX idx_tasks_status ON tasks(status);
    CREATE INDEX idx_sugg_cat ON suggestions(category, status);
    """,
]


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().date().isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript(script)
        conn.execute(f"PRAGMA user_version = {i}")
    conn.commit()


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def get_meta(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_meta(conn, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, json.dumps(value, ensure_ascii=False)),
    )
    conn.commit()


def entity(conn, kind: str, name: str, attributes: dict | None = None) -> int:
    row = conn.execute("SELECT id FROM entities WHERE kind = ? AND name = ?", (kind, name)).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO entities(kind, name, attributes, created_at) VALUES(?, ?, ?, ?)",
        (kind, name, json.dumps(attributes or {}, ensure_ascii=False), now()),
    )
    return cur.lastrowid


def relate(conn, a: int, b: int, kind: str, note: str = "", status: str = "hypothesis", bump: float = 0) -> None:
    """建立或加强两个实体之间的关系。bump>0 时累加强度（共现证据）。"""
    if a == b:
        return
    if kind == "related" and a > b:
        a, b = b, a
    row = conn.execute(
        "SELECT id, strength FROM relations WHERE source_id = ? AND target_id = ? AND kind = ?", (a, b, kind)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE relations SET strength = strength + ?, updated_at = ? WHERE id = ?", (bump, now(), row[0])
        )
    else:
        conn.execute(
            "INSERT INTO relations(source_id, target_id, kind, strength, status, note, updated_at) VALUES(?,?,?,?,?,?,?)",
            (a, b, kind, max(bump, 1), status, note, now()),
        )
