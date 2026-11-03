"""人生局势：把散落各处的数据合成一个判断——现在的局面是什么，主要矛盾在哪里，下一着落在哪里。

几种看法放在一起，各管一段，互相校正：
- 科学：只用你真实记下的数据（时间、感受、签到、任务、钱），区分相关和因果，看基准率和你自己的判断校准
- 逻辑推演：反演（怎样一定会失败）、二阶后果（然后呢）、事前验尸、可逆性、最坏情况
- 哲学：斯多葛的"能控制 / 能影响 / 控制不了"；君子之道（人生导则、北极星）
- 矛盾论：许多矛盾里找出主要矛盾，以及矛盾的主要方面；抓住它，其他的跟着动；主要矛盾会转化，所以每周重算
- 实践论：判断要回到实践里检验——每个重要选择都记下预测和把握，到期回看
- 论持久战：长期目标分阶段（防御、相持、反攻），每个阶段该做的事不一样；积小胜为大胜
- 量变质变：哪些积累快到临界点了
- 周易：时（时令之卦、今日之卦）、位（你在一件事里的位置）、势（各领域的顺逆）
- 命理：只作文化的镜子，不进入任何计算

它只给判断和角度，不替你做决定。
"""

import json
import re
from collections import Counter
from datetime import date, datetime, timedelta

from . import business, config, db, decisions, llm, mingli, relationship, shi, tasks, tianshi, yi

# ------------------------------------------------------------------ 自评：你自己怎么看（主观），和数据（客观）对照

def rate(conn, ratings: dict, note: str = "") -> None:
    clean = {k: max(1, min(10, int(v))) for k, v in ratings.items() if k in config.domains() and str(v).strip()}
    conn.execute("INSERT INTO situations(at, kind, data) VALUES(?,?,?)",
                 (db.now(), "rating", json.dumps({"ratings": clean, "note": note}, ensure_ascii=False)))
    conn.commit()


def latest_rating(conn) -> dict:
    row = conn.execute("SELECT at, data FROM situations WHERE kind = 'rating' ORDER BY id DESC LIMIT 1").fetchone()
    return {"at": row[0], **json.loads(row[1])} if row else {"at": None, "ratings": {}, "note": ""}


# ------------------------------------------------------------------ 全局：每个领域的投入、势、状态

def wheel(conn, on: date, days: int = 28) -> list[dict]:
    since = (on - timedelta(days=days)).isoformat()
    hours = {d: m / 60 for d, m in conn.execute("SELECT domain, SUM(minutes) FROM timelog WHERE day > ? GROUP BY domain", (since,))}
    open_ = Counter(r[0] for r in conn.execute("SELECT domain FROM tasks WHERE status = 'todo'"))
    skips = Counter()
    for d, s in conn.execute("SELECT domain, skips FROM tasks WHERE status = 'todo' AND skips > 0"):
        skips[d] += s
    done = Counter(r[0] for r in conn.execute("SELECT domain FROM tasks WHERE status = 'done' AND done_at > ?", (since,)))
    mentions = Counter(r[0] for r in conn.execute(
        "SELECT domain FROM memories WHERE occurred_at > ? AND type NOT IN ('summary', 'reflection')", (since,)))
    mom = shi.momentum(conn)
    rating = latest_rating(conn)["ratings"]
    logged_any = bool(hours)
    out = []
    for name, d in config.domains().items():
        budget = d.get("budget", 0) * days / 7
        h = round(hours.get(name, 0), 1)
        ratio = round(h / budget, 2) if budget and logged_any else None
        out.append({"domain": name, "role": d.get("role", "side"), "hours": h, "budget": round(budget, 1), "ratio": ratio,
                    "momentum": mom.get(name, 0), "open": open_.get(name, 0), "skips": skips.get(name, 0),
                    "done": done.get(name, 0), "mentions": mentions.get(name, 0), "self": rating.get(name)})
    return out


# ------------------------------------------------------------------ 矛盾论：找出主要矛盾

def _competitions(conn) -> list[tuple[str, str, str]]:
    return [(r[0], r[1], r[2] or "") for r in conn.execute(
        """SELECT a.name, b.name, r.note FROM relations r JOIN entities a ON a.id = r.source_id JOIN entities b ON b.id = r.target_id
           WHERE r.kind = 'competition' AND r.status != 'rejected' AND a.kind = 'domain' AND b.kind = 'domain'""")]


def _feelings(conn, on: date, days: int = 14) -> Counter:
    since = (on - timedelta(days=days)).isoformat()
    return Counter(r[0] for r in conn.execute("SELECT feeling FROM states WHERE at > ?", (since,)))


def contradictions(conn, on: date, w: list[dict]) -> list[dict]:
    """每条矛盾：两个方面、证据、分量、主要方面、一着。分量越大越可能是主要矛盾。"""
    by = {x["domain"]: x for x in w}
    weight = {"main": 1.5, "side": 1.0, "frozen": 0.3}
    out = []

    def add(title, a, b, score, aspect, evidence, move, kind):
        out.append({"title": title, "a": a, "b": b, "score": round(score, 2), "aspect": aspect,
                    "evidence": [e for e in evidence if e], "move": move, "kind": kind})

    # 1. 时间之争：互相竞争的两个领域，一个投入不足、一个超出
    for a, b, note in _competitions(conn):
        if a not in by or b not in by or by[a]["ratio"] is None:
            continue
        xa, xb = by[a], by[b]
        da, db_ = max(0, 1 - xa["ratio"]) * weight[xa["role"]], max(0, 1 - xb["ratio"]) * weight[xb["role"]]
        oa, ob = max(0, xa["ratio"] - 1), max(0, xb["ratio"] - 1)
        score = max(da + ob, db_ + oa) * 2 + (xa["skips"] + xb["skips"]) / 10
        if score < 0.6:
            continue
        short, long_ = (xa, xb) if da + ob >= db_ + oa else (xb, xa)
        add(f"「{short['domain']}」与「{long_['domain']}」之争", short["domain"], long_["domain"], score,
            f"主要方面在「{short['domain']}」：只投入了预算的 {int(short['ratio'] * 100)}%",
            [note, f"近 4 周：{short['domain']} {short['hours']}h / 预算 {short['budget']}h；{long_['domain']} {long_['hours']}h / 预算 {long_['budget']}h",
             f"「{short['domain']}」的事被跳过 {short['skips']} 次" if short["skips"] else ""],
            f"把「{long_['domain']}」的一段固定时间让给「{short['domain']}」，先保证一周两次", "time")

    # 2. 工作与她：关系是主线，时间却不够
    rel, work = by.get("关系"), by.get("建筑工作")
    if rel and rel["ratio"] is not None and rel["ratio"] < 0.7:
        over = max(0, work["ratio"] - 1) if work and work["ratio"] is not None else 0
        add("工作与她", "关系", "建筑工作", (1 - rel["ratio"]) * 3 + over * 2,
            f"主要方面在「关系」：和她的时间只有预算的 {int(rel['ratio'] * 100)}%",
            [f"近 4 周和她 {rel['hours']}h / 预算 {rel['budget']}h", f"建筑工作 {work['hours']}h / 预算 {work['budget']}h" if work else ""],
            "先把「❤️ 和她在一起」的那两个晚上守住，其他再说", "her")

    # 3. 想做的事与精力
    feel = _feelings(conn, on)
    n = sum(feel.values())
    low = feel.get("疲惫", 0) + feel.get("低落", 0)
    open_total = sum(x["open"] for x in w)
    if n >= 4 and low / n >= 0.4:
        add("想做的事与精力", "精力", "负荷", low / n * 4 + min(open_total, 40) / 20,
            "主要方面在「精力」：近两周 {} 次里有 {} 次累或低落".format(n, low),
            [f"口袋里有 {open_total} 件事"], "这一周先恢复：睡够、减少新事，只做有期限的", "energy")

    # 4. 愿望与行动
    old = [x for x in relationship.wishes(conn) if x["status"] == "想法"
           and (on - date.fromisoformat(x["mentioned_at"][:10])).days >= 30]
    if old:
        add("她的愿望与行动", "愿望", "行动", len(old) * 0.8,
            f"主要方面在「行动」：{len(old)} 个愿望说出来一个月以上还没开始",
            [f"「{x['content']}」（{x['mentioned_at'][:10]}）" for x in old[:3]],
            f"挑一个（比如「{old[0]['content']}」），定一个日期放进盼头", "wish")

    # 5. 钱：资金占用与周转
    st = business.stats(conn)
    cap = config.rules().get("business", {}).get("max_inventory_value", 0)
    if cap and st["stock_value"] > cap * 0.8 or len(st["stale"]) >= 2:
        add("资金占用与周转", "库存", "现金", (st["stock_value"] / cap if cap else 0) * 2 + len(st["stale"]) * 0.5,
            "主要方面在「周转」：压着的货", [f"库存 {config.currency()}{st['stock_value']:.0f}（上限 {cap}）", f"滞销 {len(st['stale'])} 件"],
            "先把滞销的降价出掉，回笼资金后再收", "money")

    # 6. 你的投入与外面的势
    for x in w:
        if x["role"] == "main" and x["momentum"] <= -1.5:
            add(f"你在「{x['domain']}」的投入与外面的势", x["domain"], "外势", abs(x["momentum"]) * 0.6,
                f"主要方面在「外势」：「{x['domain']}」近来逆势 {abs(x['momentum'])}",
                [t["title"] for t in shi.trends(conn, 30) if t["domain"] == x["domain"] and t["direction"] < 0][:2],
                "逆势时不加码：守住基本盘，把精力放在顺势的那一面", "trend")

    # 7. 期望与现状：你看重它，却给它打了低分
    for x in w:
        if x["self"] is not None and x["self"] <= 4 and x["role"] == "main":
            add(f"对「{x['domain']}」的期望与现状", x["domain"], "期望", (5 - x["self"]) * 0.7 + 0.5,
                f"主要方面在「{x['domain']}」：它是主线，你只给了 {x['self']} 分",
                [f"近 4 周投入 {x['hours']}h / 预算 {x['budget']}h" if x["ratio"] is not None else "还没有记录时间"],
                f"问自己：「{x['domain']}」从 {x['self']} 分到 {x['self'] + 1} 分，最小的一步是什么？", "rating")

    out.sort(key=lambda c: -c["score"])
    # 同一个"主要方面"只留最重的一条：Part3 被器材挤、被自媒体挤，说的是同一件事
    seen, uniq = set(), []
    for c in out:
        k = c["a"] if c["kind"] in ("time", "her", "rating") else c["title"]
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def gaps(w: list[dict]) -> list[str]:
    """实践论：你的认识（自评）和你的实践（数据）对不上的地方。"""
    out = []
    for x in w:
        if x["self"] is None or x["ratio"] is None:
            continue
        if x["self"] >= 7 and x["ratio"] < 0.5:
            out.append(f"「{x['domain']}」你给了 {x['self']} 分，但近 4 周的投入只有预算的 {int(x['ratio'] * 100)}%："
                       "也许是质量高、不需要很多时间，也许是感觉还停在过去")
        elif x["self"] <= 4 and x["ratio"] >= 1:
            out.append(f"「{x['domain']}」投入已经够了（预算的 {int(x['ratio'] * 100)}%），你却只给了 {x['self']} 分："
                       "问题可能不在时间，而在方法或方向")
    return out


# ------------------------------------------------------------------ 论持久战：长期目标的阶段

STAGES = [
    (0.34, "战略防御", "打基础、保存力量，不求速胜，也不轻易决战"),
    (0.67, "战略相持", "最长也最难熬的阶段：靠坚持，积小胜为大胜"),
    (1.01, "战略反攻", "条件成熟了：集中力量，一鼓作气完成"),
]


def _stage(p: float) -> tuple[str, str]:
    return next((name, text) for limit, name, text in STAGES if p < limit)


def campaigns(conn, on: date) -> list[dict]:
    out = []
    for f in business.funds(conn):
        if f["progress"] is not None:
            out.append({"name": f["name"], "progress": min(1.0, f["progress"]), "detail": f"{config.currency()}{f['saved']:.0f} / {config.currency()}{f['target']}"})
    since = (on - timedelta(days=28)).isoformat()
    for w in relationship.wishes(conn):
        if not w["project"]:
            continue
        rows = conn.execute("SELECT status, done_at FROM tasks WHERE project = ? AND status IN ('todo', 'done')", (w["project"],)).fetchall()
        if rows:
            done = sum(1 for r in rows if r[0] == "done")
            recent = sum(1 for r in rows if r[0] == "done" and (r[1] or "") > since)
            out.append({"name": w["project"], "progress": done / len(rows), "detail": f"{done}/{len(rows)} 步，近 4 周完成 {recent} 步",
                        "recent": recent})
    target = config.rules().get("jushi", {}).get("part3_cards", 120)
    cards = conn.execute("SELECT COUNT(*) FROM cards WHERE deck = 'Part3'").fetchone()[0]
    if target:
        out.append({"name": "Part 3 卡片", "progress": min(1.0, cards / target), "detail": f"{cards} / {target} 张"})
    for c in out:
        c["stage"], c["stage_text"] = _stage(c["progress"])
        c["pct"] = int(c["progress"] * 100)
    return out


def thresholds(camps: list[dict]) -> list[str]:
    """量变质变：快到临界点的积累。"""
    out = []
    for c in camps:
        if 0.8 <= c["progress"] < 1:
            out.append(f"「{c['name']}」到了 {c['pct']}%：量变快到质变了，这时候最值得再推一把")
        elif c["progress"] >= 1:
            out.append(f"「{c['name']}」已经完成：一个阶段结束，新的矛盾会出现")
    return out


# ------------------------------------------------------------------ 斯多葛：能控制 / 能影响 / 控制不了

def control(conn, main: dict | None) -> dict:
    can, influence, cannot = [], [], []
    if main:
        can.append(f"你的时间怎么分：{main['move']}")
    can += ["今晚几点睡", "下一件事先做什么"]
    for t in tasks.list_open(conn)[:3]:
        can.append(t["title"])
    influence += ["她的感受（你能做的是在场、倾听）", "甲方和同事的看法（你能做的是把事做好、把话说清）", "买家愿不愿意出价（成色、照片、描述）"]
    cannot += [t["title"] for t in shi.trends(conn, 20) if t["direction"]][:3]
    cannot += ["天气、利率、市场行情", "别人怎么想"]
    return {"can": can[:6], "influence": influence, "cannot": cannot[:5]}


# ------------------------------------------------------------------ 实践论：判断回到实践里检验

def practice(conn) -> dict:
    due = decisions.due_reviews(conn)
    cal = decisions.calibration(conn)
    running = db.rows(conn.execute("SELECT name, hypothesis, end FROM experiments WHERE status = 'running'"))
    pending = db.rows(conn.execute("SELECT id, question, at FROM choices WHERE decision_id IS NULL ORDER BY id DESC LIMIT 3"))
    return {"due": due, "calibration": cal, "experiments": running, "undecided": pending}


# ------------------------------------------------------------------ 天时

def tian(conn, on: date) -> dict:
    sea = tianshi.season(on)
    cast = yi.today_cast(conn, on.isoformat())
    mom = shi.momentum(conn)
    return {"season": f"{sea['hex']['symbol']} {sea['hex']['name']}卦当令（{sea['term']}）：{sea['text']}",
            "season_stance": sea["hex"]["stance"],
            "cast": f"{cast['primary']['symbol']} {cast['primary']['full']}，{cast['primary']['stance_desc']}" if cast else None,
            "cast_stance": cast["primary"]["stance"] if cast else None,
            "momentum": sorted(mom.items(), key=lambda x: -abs(x[1]))[:4]}


# ------------------------------------------------------------------ 汇总

def report(conn, on: date | None = None, save: bool = False) -> dict:
    on = on or date.today()
    w = wheel(conn, on)
    cons = contradictions(conn, on, w)
    main = cons[0] if cons else None
    camps = campaigns(conn, on)
    r = {
        "date": on.isoformat(), "wheel": w, "contradictions": cons, "main": main,
        "campaigns": camps, "thresholds": thresholds(camps), "control": control(conn, main),
        "practice": practice(conn), "tian": tian(conn, on), "rating": latest_rating(conn),
        "logged": any(x["ratio"] is not None for x in w),
    }
    r["gaps"] = gaps(w)
    last = conn.execute("SELECT at, data FROM situations WHERE kind = 'report' ORDER BY id DESC LIMIT 1").fetchone()
    prev = json.loads(last[1]).get("main") if last else None
    if prev and main and prev["title"] != main["title"]:
        r["shift"] = f"主要矛盾转化了：上一次是「{prev['title']}」，现在是「{main['title']}」"
    save = save or not last or last[0] < (datetime.now() - timedelta(days=6)).isoformat(timespec="seconds")
    mc = mingli.mine(conn, on)
    if mc:
        r["mingli"] = {"lines": mingli.describe(mc), "note": mc["note"], "year_god": mc["flow"]["year_god"]}
    r["summary"] = _summary(r)
    r["markdown"] = render(r)
    if save:
        conn.execute("INSERT INTO situations(at, kind, data) VALUES(?,?,?)",
                     (db.now(), "report", json.dumps({"main": main, "summary": r["summary"]}, ensure_ascii=False)))
        conn.commit()
    return r


def _summary(r: dict) -> list[str]:
    out = []
    if r["main"]:
        m = r["main"]
        out.append(f"主要矛盾：{m['title']}。{m['aspect']}。")
        out.append(f"下一着：{m['move']}。")
    elif not r["logged"]:
        out.append("数据还少：记两周时间（晚安时说说和她在一起多久、命令行 lifeos t 领域 分钟），再给每个领域打个分，局势会清楚起来。")
    else:
        out.append("没有突出的矛盾：局面平稳。守住节律，把精力放在最想推进的那件事上。")
    if r.get("shift"):
        out.append(r["shift"] + "。")
    t = r["tian"]
    out.append(f"天时：{t['season']}" + (f" 今日之卦 {t['cast']}。" if t["cast"] else ""))
    hot = [c for c in r["campaigns"] if c["stage"] == "战略反攻"]
    if hot:
        out.append(f"「{hot[0]['name']}」进入反攻阶段（{hot[0]['pct']}%），可以集中力量。")
    return out


def render(r: dict) -> str:
    L = [f"# 🧭 人生局势（{r['date']}）", ""] + [f"- {s}" for s in r["summary"]] + [""]
    L += ["## 全局", "", "领域 | 角色 | 近4周投入/预算 | 势 | 未完成 | 自评", "---|---|---|---|---|---"]
    for x in r["wheel"]:
        L.append(f"{x['domain']} | {x['role']} | " + (f"{x['hours']}/{x['budget']}h" if x["ratio"] is not None else "—")
                 + f" | {x['momentum']:+} | {x['open']} | {x['self'] or '—'}")
    L.append("")
    if r["contradictions"]:
        L += ["## 矛盾（第一条是主要矛盾）", ""]
        for i, c in enumerate(r["contradictions"][:5]):
            L.append(f"{'**主要**' if i == 0 else '次要'}：{c['title']}（分量 {c['score']}）——{c['aspect']}。一着：{c['move']}")
            L += [f"  - {e}" for e in c["evidence"]]
        L.append("")
    if r.get("gaps"):
        L += ["## 认识与实践", ""] + [f"- {x}" for x in r["gaps"]] + [""]
    if r["campaigns"]:
        L += ["## 持久战", ""] + [f"- {c['name']}：{c['detail']}，{c['stage']}——{c['stage_text']}" for c in r["campaigns"]] + [""]
    if r["thresholds"]:
        L += ["## 量变与质变", ""] + [f"- {x}" for x in r["thresholds"]] + [""]
    c = r["control"]
    L += ["## 能控制 / 能影响 / 控制不了", "", "能控制：" + "；".join(c["can"]), "能影响：" + "；".join(c["influence"]),
          "控制不了：" + "；".join(c["cannot"]), ""]
    if r.get("mingli"):
        L += ["## 命理（文化的镜子，不进入计算）", ""] + [f"- {x}" for x in r["mingli"]["lines"]] + [""]
    return "\n".join(L)


# ------------------------------------------------------------------ 选择分析：一件事、几个选项，从各个角度看

EXPAND_RE = re.compile(r"扩大|做大|加码|投资|投入|买|收|辞职|换工作|跳槽|创业|搬|签|开|报名|贷款|全职")
HOLD_RE = re.compile(r"等|暂缓|不|放下|保持|维持|休息|推迟|先不")

LENSES = [
    ("反演", "怎样做，能保证这件事一定失败？把这些避开。"),
    ("事前验尸", "假设一年后回看，这个选择失败了。最可能的原因是什么？"),
    ("二阶后果", "选了之后，然后呢？再然后呢？谁会因此改变？"),
    ("基准率", "像这样的事，一般人做的结果如何？你凭什么会不一样？"),
    ("10/10/10", "10 分钟后、10 个月后、10 年后，你会怎么看这个选择？"),
    ("君子", "哪个选项更像你想成为的那个人？"),
]


def choose(conn, question: str, options: list[dict], save: bool = True) -> dict:
    """options：[{name, reversible, contra(-1/0/1 对主要矛盾), her(-1/0/1), worst_ok, ten_years, cost}]"""
    on = date.today()
    r = report(conn, on)
    main, t = r["main"], r["tian"]
    camps = r["campaigns"]
    hit = [b for b in r["practice"]["calibration"] if b["n"] >= 3]
    rows = []
    for o in options:
        name = (o.get("name") or "").strip()
        if not name:
            continue
        score, notes, flags = 0.0, [], []
        contra = int(o.get("contra") or 0)
        if main and contra:
            score += 2 * contra
            notes.append(("矛盾论", f"它{'缓解' if contra > 0 else '加剧'}了主要矛盾「{main['title']}」"))
        her = int(o.get("her") or 0)
        if her:
            score += 1.5 * her
            notes.append(("人和", "对她" + ("好" if her > 0 else "不好")))
        if o.get("reversible") is False:
            flags.append("单向门：做了很难回头。慢一点，多要一些证据，睡一晚再定")
            score -= 0.3
        elif o.get("reversible"):
            score += 0.5
            notes.append(("可逆", "双向门：可以先小规模试，不行再退"))
        if o.get("worst_ok") is False:
            score -= 3
            flags.append("最坏的情况你承受不了：要么不做，要么先买保险（杠铃：大部分稳，一小部分冒险）")
        elif o.get("worst_ok"):
            notes.append(("安全边际", "最坏的情况你承受得起"))
        if o.get("ten_years"):
            score += 1
            notes.append(("10/10/10", "十年后你还会在意它"))
        expand = bool(EXPAND_RE.search(name)) and not HOLD_RE.match(name)
        if expand and t["season_stance"] in ("守", "养") :
            notes.append(("天时", f"时令{t['season'].split('：')[0]}，宜收不宜张；扩张的事放慢一点"))
            score -= 0.3
        related_camp = next((c for c in camps if any(tok in name for tok in re.findall(r"[\u4e00-\u9fff]{2}|[A-Za-z0-9]{2,}", c["name"]))), None)
        if related_camp:
            notes.append(("持久战", f"「{related_camp['name']}」在{related_camp['stage']}阶段（{related_camp['pct']}%）：{related_camp['stage_text']}"))
        if t["cast_stance"] in ("进", "断") and expand:
            notes.append(("今日之卦", f"今日之卦{yi.STANCES[t['cast_stance']]['desc']}"))
        rows.append({"name": name, "score": round(score, 2), "notes": notes, "flags": flags, "cost": o.get("cost") or ""})
    rows.sort(key=lambda x: -x["score"])
    analysis = {
        "question": question, "options": rows, "main": main["title"] if main else None,
        "lenses": [{"name": n, "q": q} for n, q in LENSES],
        "calibration": (f"你过去说有 {hit[-1]['confidence']} 把握的判断，实际命中 {int(hit[-1]['hit_rate'] * 100)}%"
                        if hit else "还没有足够的判断记录来校准你的把握；这次记下预测，到期回看"),
        "practice": "实践论：能先做一个小实验吗？把预测和把握记进决策日志，到期回来检验。",
        "tian": t["season"], "note": "这是帮你想清楚的工具，不替你决定。分数只是把你自己的判断加起来。",
    }
    if r.get("mingli"):
        analysis["mingli"] = f"（文化的镜子）流年{r['mingli']['year_god']}：{mingli.TEN_GODS[r['mingli']['year_god']][0]}"
    if save:
        cid = conn.execute("INSERT INTO choices(at, question, options, analysis) VALUES(?,?,?,?)",
                           (db.now(), question, json.dumps(options, ensure_ascii=False), json.dumps(analysis, ensure_ascii=False))).lastrowid
        conn.commit()
        analysis["id"] = cid
    return analysis


def decide(conn, choice_id: int, chosen: str, prediction: str, confidence: float, review_in_days: int = 30) -> int:
    """做出选择：记进决策日志，到期回看（实践检验认识）。"""
    q = conn.execute("SELECT question FROM choices WHERE id = ?", (choice_id,)).fetchone()[0]
    did = decisions.log_decision(conn, q, chosen, prediction, confidence, category="life", review_in_days=review_in_days)
    conn.execute("UPDATE choices SET chosen = ?, decision_id = ? WHERE id = ?", (chosen, did, choice_id))
    conn.commit()
    return did


def ai_reading(conn, r: dict) -> str | None:
    """有 Claude 时（API 或本机 claude-code）：把局势写成一段推演。"""
    return llm.complete_text(
        "你是一位冷静的朋友，熟悉矛盾论、实践论、论持久战、斯多葛哲学、决策科学和《周易》，但你诚实：不迷信、不说吉凶。"
        "根据下面的局势数据，用中文 300 字以内：1) 一句话说清现在的局面；2) 主要矛盾和它的主要方面，为什么是它；"
        "3) 下一着，以及为什么这一着能带动其他矛盾；4) 一个需要回到实践里检验的判断。不给长清单，不评判他。",
        r["markdown"], effort="medium", slow_ok=True,
    )
