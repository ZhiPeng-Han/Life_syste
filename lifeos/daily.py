"""每日梳理：不用 API，由你电脑上的 Claude Code 每天做一次 AI 梳理。

流程（三步，都在你自己的电脑上）：
1. prepare：系统把"自上次以来"的输入、相关上下文、新闻标题整理成一个工作包
   data/ai/inbox/<日期>.md（给 Claude 读）和 <日期>.json
2. Claude Code（定时任务里的 /lifeos-daily）读工作包，可以再上网看看今天的大事，
   然后按 SCHEMA 写出结果 data/ai/outbox/<日期>.json
3. apply：系统校验结果、写入数据库，每一处改动都记在 ai_changes 里，可以整次撤销（undo）

Claude 能做的事被限定在 SCHEMA 里：添加大势、修正记忆的领域/类型/时间/主题、
关联事物、写领悟、写日摘要、写给明天的几句话、在周日写信、提出系统提升建议。
它不能删除你的任何记忆（只能在"AI 不太确定"的记忆上帮你确认），也不改代码。
"""

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

from . import business, config, db, mind, relationship, shi, moments, tianshi

KINDS = ("synergy", "competition", "influence", "dependency", "related")
TYPES = ("episodic", "semantic", "procedural", "prospective", "normative")

SCHEMA = {
    "type": "object",
    "required": ["date"],
    "properties": {
        "date": {"type": "string", "description": "工作包的日期 YYYY-MM-DD"},
        "news": {"type": "array", "description": "天下大势：真正会影响他生活或事业的 0-5 个趋势，宁缺毋滥", "items": {
            "type": "object", "required": ["title", "domain", "direction", "strength", "summary"],
            "properties": {"title": {"type": "string"}, "domain": {"type": "string"},
                           "direction": {"type": "integer", "enum": [-1, 0, 1]},
                           "strength": {"type": "integer", "minimum": 1, "maximum": 5},
                           "summary": {"type": "string", "description": "一句话：为什么和他有关、顺势怎么做"},
                           "url": {"type": "string"}}}},
        "retire_trends": {"type": "array", "items": {"type": "integer"}, "description": "已经过时的大势 id"},
        "memories": {"type": "array", "description": "修正规则引擎的理解（只填需要改的字段）", "items": {
            "type": "object", "required": ["id"],
            "properties": {"id": {"type": "integer"}, "domain": {"type": "string"}, "type": {"type": "string", "enum": list(TYPES)},
                           "importance": {"type": "integer", "minimum": 1, "maximum": 10},
                           "occurred_on": {"type": "string"}, "mood": {"type": "integer", "minimum": 1, "maximum": 10},
                           "topics": {"type": "array", "items": {"type": "string"}}}}},
        "confirm": {"type": "array", "description": "只针对 needs_confirm 的记忆：理解得够清楚就 keep=true；看不懂就不要填", "items": {
            "type": "object", "required": ["id", "keep"],
            "properties": {"id": {"type": "integer"}, "keep": {"type": "boolean"}}}},
        "supersede": {"type": "array", "description": "新事实取代旧事实（都必须是 semantic）", "items": {
            "type": "object", "required": ["old", "new"], "properties": {"old": {"type": "integer"}, "new": {"type": "integer"}}}},
        "relations": {"type": "array", "description": "事物之间的关系（用名字）", "items": {
            "type": "object", "required": ["a", "b", "kind", "note"],
            "properties": {"a": {"type": "string"}, "b": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
                           "note": {"type": "string"}}}},
        "reflections": {"type": "array", "description": "最多 3 条更高一层的领悟，每条必须引用证据记忆 id", "items": {
            "type": "object", "required": ["content", "evidence"],
            "properties": {"content": {"type": "string"}, "domain": {"type": "string"},
                           "evidence": {"type": "array", "items": {"type": "integer"}},
                           "confidence": {"type": "number"}}}},
        "summary": {"type": "string", "description": "这段时间的 3-5 句总结：发生了什么、情绪、和她有关的、值得记住的"},
        "notes": {"type": "object", "description": "给明天的几句话，都不超过 80 字", "properties": {
            "morning": {"type": "string", "description": "明早的一句问候：具体、温和，不给待办"},
            "her": {"type": "string", "description": "一个和她有关的小提醒或惊喜点子，引用她说过的话"},
            "shi": {"type": "string", "description": "顺势而为：今天外面的势对他意味着什么"}}},
        "letter": {"type": "string", "description": "只在周日写：给这一周的信（Markdown，300 字内，最后留一个问题）"},
        "moments": {"type": "array", "description": "0-3 条新的「此刻宜」选择：结合他最近的生活、季节和天气，此刻可以做的小事（不是任务）", "items": {
            "type": "object", "required": ["title", "need", "minutes"],
            "properties": {"title": {"type": "string"}, "why": {"type": "string"}, "minutes": {"type": "integer"},
                           "need": {"type": "string", "enum": ["any", "home", "desk", "out", "leave", "camera", "phone", "work"]},
                           "cat": {"type": "string"}, "when": {"type": "string", "enum": ["any", "morning", "day", "noon", "evening", "night", "daylight", "golden", "dark", "weekend"]},
                           "her": {"type": "string", "enum": ["any", "with", "without"]},
                           "feel": {"type": "array", "items": {"type": "string", "enum": ["充沛", "平静", "疲惫", "烦躁", "低落"]}}}}},
        "improvements": {"type": "array", "description": "0-3 条系统提升建议：系统哪里不懂他、哪里多余、哪里可以更好", "items": {
            "type": "object", "required": ["title", "why", "how"],
            "properties": {"title": {"type": "string"}, "why": {"type": "string"}, "how": {"type": "string"},
                           "area": {"type": "string"}, "effort": {"type": "string", "enum": ["小", "中", "大"]}}}},
    },
}


def ai_dir(sub: str = "") -> Path:
    p = config.home() / "ai" / sub
    p.mkdir(parents=True, exist_ok=True)
    return p


# ------------------------------------------------------------------ 备份

def backup(keep: int = 30) -> Path:
    """用 SQLite 的在线备份复制一份数据库。梳理前自动做一次。"""
    folder = config.home() / "backups"
    folder.mkdir(exist_ok=True)
    dest = folder / f"lifeos-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(config.db_path())
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    for old in sorted(folder.glob("lifeos-*.db"))[:-keep]:
        old.unlink()
    return dest


# ------------------------------------------------------------------ 1. 准备工作包

def _since(conn) -> str:
    last = conn.execute("SELECT MAX(at) FROM ai_runs WHERE status = 'applied'").fetchone()[0]
    return last or (datetime.now() - timedelta(days=3)).isoformat(timespec="seconds")


def _headlines(conn) -> tuple[list[dict], list[str]]:
    feeds = config.rules().get("environment", {}).get("feeds", [])
    weights = db.get_meta(conn, "feed_weights", {})
    out, errors = [], []
    for f in feeds:
        w = weights.get(f["url"], 1.0)
        if w <= 0.2:
            continue
        try:
            for h in shi._fetch_feed(f["url"], limit=max(3, round(8 * w))):
                out.append({"title": h["title"], "url": h.get("url"), "domain": f.get("domain") or ""})
        except Exception as e:  # noqa: BLE001 —— 一个源坏了不影响其他
            errors.append(f"{f['url']}：{e}")
    return out, errors


def prepare(conn, fetch_news: bool = True) -> dict:
    since = _since(conn)
    today = date.today().isoformat()
    inputs = db.rows(conn.execute("SELECT id, text, source, created_at FROM raw_inputs WHERE created_at > ? ORDER BY id", (since,)))
    mems = db.rows(conn.execute(
        f"""SELECT id, raw_id, type, domain, content, substr(occurred_at, 1, 10) day, importance, confidence, mood, status
            FROM memories WHERE created_at > ? AND type NOT IN ('summary', 'reflection')
              AND status NOT IN {mind.INACTIVE_SQL} ORDER BY id""", (since,)))
    pending = db.rows(conn.execute("SELECT id, domain, content FROM memories WHERE status = 'needs_confirm' ORDER BY id"))
    facts = db.rows(conn.execute("SELECT id, domain, content FROM memories WHERE type = 'semantic' AND status = 'active' ORDER BY id DESC LIMIT 40"))
    context = db.rows(conn.execute(
        f"""SELECT id, type, domain, content, substr(occurred_at, 1, 10) day FROM memories
            WHERE created_at <= ? AND type NOT IN ('summary', 'reflection') AND status NOT IN {mind.INACTIVE_SQL}
            ORDER BY occurred_at DESC LIMIT 60""", (since,)))
    states = db.rows(conn.execute("SELECT substr(at, 1, 16) at, feeling, note FROM states WHERE at >= ? ORDER BY at",
                                  ((datetime.now() - timedelta(days=14)).isoformat(),)))
    trends = shi.trends(conn, 30)
    open_tasks = db.rows(conn.execute("SELECT id, title, domain, due, skips FROM tasks WHERE status = 'todo' ORDER BY priority DESC, id LIMIT 40"))
    done = db.rows(conn.execute("SELECT title, domain FROM tasks WHERE status IN ('done', 'let_go') AND done_at > ?", (since,)))
    casts = db.rows(conn.execute("SELECT id, day, kind, question, hex, outcome FROM casts WHERE at > ? ORDER BY id", (since,)))
    improvements = db.rows(conn.execute("SELECT id, title, status FROM improvements ORDER BY id DESC LIMIT 20"))
    domain_share = dict(conn.execute(
        "SELECT domain, COUNT(*) FROM memories WHERE created_at > ? AND type NOT IN ('summary','reflection') GROUP BY domain",
        ((datetime.now() - timedelta(days=30)).isoformat(),)).fetchall())
    headlines, errors = _headlines(conn) if fetch_news else ([], [])
    pkg = {
        "date": today, "since": since, "weekday": "一二三四五六日"[date.today().weekday()],
        "write_letter": date.today().weekday() == 6,
        "season": _season_line(),
        "jushi": _jushi_lines(conn),
        "moment_stats": _moment_stats(conn),
        "domains": list(config.domains()), "topics": [e["name"] for e in mind.dictionary(conn)],
        "inputs": inputs, "memories": mems, "needs_confirm": pending, "facts": facts, "context": context,
        "reflections": [{"id": r["id"], "content": r["content"]} for r in mind.reflections(conn)],
        "states": states, "wishes": relationship.wishes(conn, include_done=True),
        "trends": [{k: t[k] for k in ("id", "title", "domain", "direction", "strength", "weight", "observed_at")} for t in trends],
        "headlines": headlines, "feed_errors": errors,
        "tasks_open": open_tasks, "done_since": done, "casts": casts,
        "business": business.stats(conn), "funds": business.funds(conn),
        "skip_reasons": db.rows(conn.execute("SELECT reason, COUNT(*) n FROM skip_reasons GROUP BY reason")),
        "improvements": improvements, "domain_share_30d": domain_share,
        "health": {"inputs_since": len(inputs), "needs_confirm": len(pending),
                   "fallback_domain_share": round(domain_share.get("生活维持", 0) / max(sum(domain_share.values()), 1), 2)},
    }
    stem = ai_dir("inbox") / today
    stem.with_suffix(".json").write_text(json.dumps(pkg, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    stem.with_suffix(".md").write_text(_brief(pkg), encoding="utf-8")
    (ai_dir() / "schema.json").write_text(json.dumps(SCHEMA, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"inbox": str(stem.with_suffix(".md")), "outbox": str(ai_dir("outbox") / f"{today}.json"),
            "schema": str(ai_dir() / "schema.json"), "inputs": len(inputs), "memories": len(mems),
            "headlines": len(headlines), "write_letter": pkg["write_letter"]}


def _jushi_lines(conn) -> list[str]:
    from . import jushi

    try:
        r = jushi.report(conn)
    except Exception as e:  # noqa: BLE001 —— 局势出错不该挡住每日梳理
        return [f"（局势计算出错：{e}）"]
    return r["summary"] + [f"次要矛盾：{c['title']}——{c['aspect']}" for c in r["contradictions"][1:3]] + r.get("gaps", [])


def _moment_stats(conn) -> list[str]:
    since = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
    rows = conn.execute(
        """SELECT title, SUM(action IN ('ok', 'done')), SUM(action IN ('next', 'not_now')) FROM moment_log
           WHERE at >= ? AND title != '' GROUP BY title ORDER BY COUNT(*) DESC LIMIT 10""", (since,)).fetchall()
    return [f"{t}：好 {y} / 换 {n}" for t, y, n in rows]


def _season_line() -> str:
    from . import tianshi

    sea = tianshi.season()
    return (f"{sea['term']}·{sea['hou']['text']}；时令之卦 {sea['hex']['name']}（{sea['month']}，"
            f"{sea['hex']['stance_desc']}）：{sea['text']}")


def _brief(p: dict) -> str:
    cur = config.currency()
    L = [f"# LifeOS 每日工作包 · {p['date']}（周{p['weekday']}）", "",
         f"自上次梳理（{p['since'][:16]}）以来：{len(p['inputs'])} 条输入，{len(p['memories'])} 条新记忆。",
         f"领域只能用：{'、'.join(p['domains'])}", ""]
    if p["inputs"]:
        L += ["## 他的原话（raw_inputs）", ""] + [f"- #{i['id']} {i['created_at'][:16]} [{i['source']}] {i['text']}" for i in p["inputs"]] + [""]
    if p["memories"]:
        L += ["## 规则引擎拆出的新记忆（请检查并修正）", "", "id | 发生日 | 类型 | 领域 | 重要性 | 状态 | 内容"]
        L += [f"{m['id']} | {m['day']} | {m['type']} | {m['domain']} | {m['importance']:.0f} | {m['status']} | {m['content']}" for m in p["memories"]]
        L.append("")
    if p["needs_confirm"]:
        L += ["## AI 不太确定、等他确认的记忆", ""] + [f"- {m['id']} [{m['domain']}] {m['content']}" for m in p["needs_confirm"]] + [""]
    if p["states"]:
        L += ["## 近两周的感受", ""] + [f"- {s['at']} {s['feeling']}" + (f"：{s['note']}" if s["note"] else "") for s in p["states"]] + [""]
    if p["reflections"]:
        L += ["## 已有的领悟（不要重复）", ""] + [f"- {r['content']}" for r in p["reflections"]] + [""]
    if p["facts"]:
        L += ["## 关于他和她的稳定事实", ""] + [f"- {f['id']} [{f['domain']}] {f['content']}" for f in p["facts"]] + [""]
    if p["wishes"]:
        L += ["## 她的愿望", ""] + [f"- {w['content']}（{w['status']}，{w['mentioned_at']}）" for w in p["wishes"]] + [""]
    if p["context"]:
        L += ["## 更早的记忆（上下文，可作为领悟的证据）", ""] + [f"- {m['id']} {m['day']} [{m['domain']}] {m['content']}" for m in p["context"]] + [""]
    if p.get("jushi"):
        L += ["## 人生局势（系统按数据算的，供参考）", ""] + [f"- {x}" for x in p["jushi"]]
        L += ["- 写 notes 和领悟时可以参考主要矛盾，但不要说教；他的判断优先", ""]
    if p.get("moment_stats"):
        L += ["## 此刻宜：他最近点\"好\"和\"换一个\"的（30 天）", ""] + [f"- {x}" for x in p["moment_stats"]] + [""]
    if p.get("season"):
        L += ["## 天时", "", f"- {p['season']}", "- notes.morning / notes.shi 可以自然地借用时令（比如剥卦当令：宜收宜藏），但不要说吉凶", ""]
    L += ["## 现在的天下大势", ""] + ([f"- #{t['id']} {'顺' if t['direction'] > 0 else '逆' if t['direction'] < 0 else '观'}"
                                       f" [{t['domain'] or ''}] {t['title']}（{t['observed_at'][:10]}，当前权重 {t['weight']}）" for t in p["trends"]] or ["- 暂无"]) + [""]
    if p["headlines"]:
        L += ["## 今天的新闻标题（RSS）", ""] + [f"- [{h['domain']}] {h['title']} {h.get('url') or ''}" for h in p["headlines"]] + [""]
    if p["feed_errors"]:
        L += ["新闻源出错：" + "；".join(p["feed_errors"]), ""]
    b = p["business"]
    L += ["## 器材生意", "", f"- 在库 {b['stock_count']} 件（{cur}{b['stock_value']:.0f}），累计利润 {cur}{b['profit_total']:.0f}，"
          f"卖出 {b['sold_count']} 件" + (f"，压货：{'、'.join(b['stale'])}" if b["stale"] else "")]
    L += [f"- {f['name']}：{cur}{f['saved']:.0f} / {cur}{f['target']}" for f in p["funds"]] + [""]
    if p["tasks_open"]:
        L += ["## 口袋里的事（前 40）", ""] + [f"- {t['title']}（{t['domain']}" + (f"，{t['due']} 截止" if t["due"] else "")
                                             + (f"，跳过 {t['skips']} 次" if t["skips"] else "") + "）" for t in p["tasks_open"]] + [""]
    if p["done_since"]:
        L += ["## 这段时间做完或放下的", ""] + [f"- {t['title']}" for t in p["done_since"]] + [""]
    if p["casts"]:
        L += ["## 起过的卦", ""] + [f"- {c['day']} {c['question'] or '今日'}（第 {c['hex']} 卦）" for c in p["casts"]] + [""]
    if p["improvements"]:
        L += ["## 以前提过的系统建议（不要重复）", ""] + [f"- {i['title']}（{i['status']}）" for i in p["improvements"]] + [""]
    h = p["health"]
    skips = "、".join(f"{s['reason']}×{s['n']}" for s in p["skip_reasons"]) or "无"
    L += ["## 系统健康", "", f"- 等确认 {h['needs_confirm']} 条；近 30 天被归到「生活维持」（规则引擎兜底）的比例 {h['fallback_domain_share']:.0%}",
          f"- 跳过的原因：{skips}", ""]
    if p["write_letter"]:
        L += ["**今天是周日：请在 letter 里写这一周的信。**", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ 2. 应用结果

class Run:
    def __init__(self, conn, day: str, source: str):
        self.conn = conn
        self.id = conn.execute("INSERT INTO ai_runs(day, at, source, status) VALUES(?,?,?, 'applying')",
                               (day, db.now(), source)).lastrowid
        self.log: list[str] = []

    def inserted(self, tbl: str, row_id: int) -> None:
        self.conn.execute("INSERT INTO ai_changes(run_id, tbl, row_id, action) VALUES(?,?,?, 'insert')", (self.id, tbl, row_id))

    def updated(self, tbl: str, row_id: int, before: dict) -> None:
        self.conn.execute("INSERT INTO ai_changes(run_id, tbl, row_id, action, before) VALUES(?,?,?, 'update', ?)",
                          (self.id, tbl, row_id, json.dumps(before, ensure_ascii=False)))

    def meta(self, key: str, value) -> None:
        before = db.get_meta(self.conn, key)
        self.conn.execute("INSERT INTO ai_changes(run_id, tbl, row_id, action, before) VALUES(?, 'meta', 0, 'meta', ?)",
                          (self.id, json.dumps({"key": key, "value": before}, ensure_ascii=False)))
        db.set_meta(self.conn, key, value)


def _str(x, n: int = 600) -> str:
    return str(x or "").strip()[:n]


def apply(conn, path: str | Path, source: str = "claude-code") -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("date"):
        raise ValueError("结果文件缺少 date")
    day = _str(data["date"], 10)
    domains = set(config.domains())
    run = Run(conn, day, source)
    log = run.log
    mem_ids = {r[0] for r in conn.execute("SELECT id FROM memories")}

    # 天下大势
    seen = {r[0] for r in conn.execute("SELECT title FROM trends")}
    for t in data.get("news", [])[:5]:
        title = _str(t.get("title"), 200)
        if not title or title in seen:
            continue
        tid = shi.add(conn, title, t.get("domain") if t.get("domain") in domains else None,
                      max(-1, min(1, int(t.get("direction", 0)))), max(1, min(5, int(t.get("strength", 2)))),
                      _str(t.get("summary"), 300) or None, source="ai", url=_str(t.get("url"), 500) or None)
        run.inserted("trends", tid)
        log.append(f"🌏 大势：{title}")
    for tid in data.get("retire_trends", []):
        row = conn.execute("SELECT status FROM trends WHERE id = ?", (tid,)).fetchone()
        if row and row[0] == "active":
            run.updated("trends", int(tid), {"status": row[0]})
            conn.execute("UPDATE trends SET status = 'retired' WHERE id = ?", (tid,))
            log.append(f"🌏 大势 #{tid} 已过时")

    # 修正记忆
    for m in data.get("memories", []):
        mid = m.get("id")
        if mid not in mem_ids:
            continue
        row = dict(conn.execute("SELECT type, domain, importance, occurred_at, mood FROM memories WHERE id = ?", (mid,)).fetchone())
        new = {}
        if m.get("domain") in domains and m["domain"] != row["domain"]:
            new["domain"] = m["domain"]
        if m.get("type") in TYPES and m["type"] != row["type"]:
            new["type"] = m["type"]
        if isinstance(m.get("importance"), int) and 1 <= m["importance"] <= 10 and m["importance"] != row["importance"]:
            new["importance"] = m["importance"]
        if isinstance(m.get("mood"), int) and 1 <= m["mood"] <= 10:
            new["mood"] = m["mood"]
        on = _str(m.get("occurred_on"), 10)
        if len(on) == 10 and on <= date.today().isoformat() and on != row["occurred_at"][:10]:
            try:
                date.fromisoformat(on)
                new["occurred_at"] = on + "T12:00:00"
            except ValueError:
                pass
        if new:
            run.updated("memories", mid, {k: row[k] for k in new})
            conn.execute(f"UPDATE memories SET {', '.join(f'{k} = ?' for k in new)} WHERE id = ?", (*new.values(), mid))
            if "domain" in new:
                mind.attach(conn, "memories", mid, db.entity(conn, "domain", new["domain"]))
            log.append(f"🧠 记忆 #{mid}：" + "，".join(f"{k}→{v}" for k, v in new.items()))
        for name in (m.get("topics") or [])[:4]:
            name = _str(name, 20)
            if len(name) >= 2:
                mind.attach(conn, "memories", mid, db.entity(conn, "topic", name))
    for c in data.get("confirm", []):
        row = conn.execute("SELECT status FROM memories WHERE id = ?", (c.get("id"),)).fetchone()
        if row and row[0] == "needs_confirm" and c.get("keep") is True:
            run.updated("memories", c["id"], {"status": "needs_confirm"})
            conn.execute("UPDATE memories SET status = 'active' WHERE id = ?", (c["id"],))
            log.append(f"✓ 记忆 #{c['id']} 已确认")
    for s in data.get("supersede", []):
        old = conn.execute("SELECT type, status, superseded_by FROM memories WHERE id = ?", (s.get("old"),)).fetchone()
        new = conn.execute("SELECT type FROM memories WHERE id = ?", (s.get("new"),)).fetchone()
        if old and new and old["type"] == new["type"] == "semantic" and old["status"] == "active":
            run.updated("memories", s["old"], {"status": "active", "superseded_by": old["superseded_by"]})
            mind.supersede(conn, s["old"], s["new"])
            log.append(f"🔄 事实 #{s['old']} 被 #{s['new']} 取代")

    # 关系
    for r in data.get("relations", [])[:10]:
        a, b, kind = _str(r.get("a"), 30), _str(r.get("b"), 30), r.get("kind")
        if not a or not b or kind not in KINDS:
            continue
        ea = conn.execute("SELECT id FROM entities WHERE name = ? COLLATE NOCASE", (a,)).fetchone()
        eb = conn.execute("SELECT id FROM entities WHERE name = ? COLLATE NOCASE", (b,)).fetchone()
        ea = ea[0] if ea else db.entity(conn, "topic", a)
        eb = eb[0] if eb else db.entity(conn, "topic", b)
        existed = conn.execute("SELECT id FROM relations WHERE source_id = ? AND target_id = ? AND kind = ?",
                               (min(ea, eb) if kind == "related" else ea, max(ea, eb) if kind == "related" else eb, kind)).fetchone()
        db.relate(conn, ea, eb, kind, note=_str(r.get("note"), 200), bump=0.5)
        if not existed:
            rid = conn.execute("SELECT MAX(id) FROM relations").fetchone()[0]
            run.inserted("relations", rid)
            log.append(f"✨ 关系：{a} —{kind}→ {b}")

    # 领悟
    for ins in data.get("reflections", [])[:3]:
        ev = [i for i in ins.get("evidence", []) if i in mem_ids]
        content = _str(ins.get("content"), 400)
        if not ev or not content:
            continue
        import hashlib

        key = "ai:" + hashlib.sha1(content.encode()).hexdigest()[:10]
        existed = conn.execute("SELECT id FROM memories WHERE rkey = ?", (key,)).fetchone()
        rid = mind._save_reflection(conn, key, content, ins.get("domain") if ins.get("domain") in domains else None, ev,
                                    float(ins.get("confidence") or 0.6))
        if rid and not existed:
            run.inserted("memories", rid)
            log.append(f"🧠 领悟：{content}")

    # 日摘要（替换规则版）
    if _str(data.get("summary")):
        target = (date.today() - timedelta(days=1)).isoformat()
        old = conn.execute("SELECT id, content FROM memories WHERE type = 'summary' AND substr(occurred_at, 1, 10) = ?", (target,)).fetchone()
        if old:
            run.updated("memories", old["id"], {"content": old["content"]})
            conn.execute("UPDATE memories SET content = ? WHERE id = ?", (_str(data["summary"], 1500), old["id"]))
        else:
            sid = conn.execute("""INSERT INTO memories(type, domain, content, occurred_at, importance, tags, created_at)
                                  VALUES('summary', '日摘要', ?, ?, 6, '["daily","ai"]', ?)""",
                               (_str(data["summary"], 1500), f"{target}T23:59:00", db.now())).lastrowid
            run.inserted("memories", sid)
        log.append("📝 日摘要已更新")

    # 给明天的几句话
    notes = {k: _str(v, 200) for k, v in (data.get("notes") or {}).items() if k in ("morning", "her", "shi") and _str(v)}
    if notes:
        run.meta("ai_notes", {"date": day, **notes})
        log.append("💬 " + "、".join({"morning": "早安", "her": "关于她", "shi": "顺势"}[k] for k in notes))

    # 周日的信
    if _str(data.get("letter")):
        iso = date.fromisoformat(day).isocalendar()
        p = config.home() / "letters" / f"{iso.year}-W{iso.week:02d}.md"
        p.parent.mkdir(exist_ok=True)
        p.write_text(_str(data["letter"], 6000), encoding="utf-8")
        log.append(f"✉️ 这周的信：{p.name}")

    # 此刻宜的新选择
    for m in data.get("moments", [])[:3]:
        title = _str(m.get("title"), 80)
        if not title or conn.execute("SELECT 1 FROM moments WHERE title = ?", (title,)).fetchone():
            continue
        need = m.get("need") if m.get("need") in tianshi.NEED_LABEL else "any"
        whn = m.get("when") if m.get("when") in ("any", "morning", "day", "noon", "evening", "night", "daylight", "golden", "dark", "weekend") else "any"
        feels = [f for f in m.get("feel", []) if f in ("充沛", "平静", "疲惫", "烦躁", "低落")]
        key = moments.add(conn, title, need, max(0, min(240, int(m.get("minutes") or 15))), _str(m.get("cat"), 10) or "新的",
                          feels, whn, m.get("her") if m.get("her") in ("any", "with", "without") else "any", _str(m.get("why"), 120))
        conn.execute("UPDATE moments SET source = 'ai' WHERE key = ?", (key,))
        run.inserted("moments", conn.execute("SELECT id FROM moments WHERE key = ?", (key,)).fetchone()[0])
        log.append(f"🌿 此刻宜：{title}")

    # 系统提升建议
    for i in data.get("improvements", [])[:3]:
        title = _str(i.get("title"), 120)
        if not title or conn.execute("SELECT 1 FROM improvements WHERE title = ?", (title,)).fetchone():
            continue
        iid = conn.execute(
            "INSERT INTO improvements(run_id, day, title, why, how, area, effort, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (run.id, day, title, _str(i.get("why")), _str(i.get("how"), 1200), _str(i.get("area"), 40),
             i.get("effort") if i.get("effort") in ("小", "中", "大") else None, db.now())).lastrowid
        run.inserted("improvements", iid)
        log.append(f"🛠 建议：{title}")

    summary = "\n".join(log) or "这次没有需要改动的地方。"
    conn.execute("UPDATE ai_runs SET status = 'applied', summary = ? WHERE id = ?", (summary, run.id))
    conn.commit()
    report = ai_dir("reports") / f"{day}.md"
    report.write_text(f"# 每日梳理 · {day}（第 {run.id} 次）\n\n" + "\n".join(f"- {x}" for x in log) + "\n", encoding="utf-8")
    return {"run": run.id, "changes": len(log), "summary": summary, "report": str(report)}


# ------------------------------------------------------------------ 3. 撤销

def undo(conn, run_id: int | None = None) -> dict:
    run_id = run_id or conn.execute("SELECT MAX(id) FROM ai_runs WHERE status = 'applied'").fetchone()[0]
    if not run_id:
        return {"undone": 0}
    n = 0
    for c in db.rows(conn.execute("SELECT * FROM ai_changes WHERE run_id = ? ORDER BY id DESC", (run_id,))):
        before = json.loads(c["before"]) if c["before"] else {}
        if c["action"] == "insert":
            if c["tbl"] == "memories":
                conn.execute("DELETE FROM memory_entities WHERE memory_id = ?", (c["row_id"],))
            conn.execute(f"DELETE FROM {c['tbl']} WHERE id = ?", (c["row_id"],))
        elif c["action"] == "update":
            conn.execute(f"UPDATE {c['tbl']} SET {', '.join(f'{k} = ?' for k in before)} WHERE id = ?",
                         (*before.values(), c["row_id"]))
        elif c["action"] == "meta":
            if before["value"] is None:
                conn.execute("DELETE FROM meta WHERE key = ?", (before["key"],))
            else:
                db.set_meta(conn, before["key"], before["value"])
        n += 1
    conn.execute("UPDATE ai_runs SET status = 'undone' WHERE id = ?", (run_id,))
    conn.commit()
    return {"run": run_id, "undone": n}


# ------------------------------------------------------------------ 给页面用

def status(conn) -> dict:
    last = conn.execute("SELECT id, day, at, summary, status FROM ai_runs ORDER BY id DESC LIMIT 1").fetchone()
    return {"last": dict(last) if last else None, "notes": notes(conn)}


def notes(conn, on: date | None = None) -> dict:
    """最近一次梳理留下的话（两天内有效）。"""
    n = db.get_meta(conn, "ai_notes") or {}
    on = on or date.today()
    if not n.get("date") or (on - date.fromisoformat(n["date"])).days > 1:
        return {}
    return n


def improvements(conn, status_: str | None = "open") -> list[dict]:
    sql = "SELECT * FROM improvements" + (" WHERE status = ?" if status_ else "") + " ORDER BY id DESC LIMIT 30"
    return db.rows(conn.execute(sql, (status_,) if status_ else ()))


def mark_improvement(conn, iid: int, status_: str) -> None:
    if status_ not in ("open", "accepted", "declined", "done"):
        raise ValueError(status_)
    conn.execute("UPDATE improvements SET status = ? WHERE id = ?", (status_, iid))
    conn.commit()
