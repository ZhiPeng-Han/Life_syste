"""可视化仪表盘：零依赖 HTTP 服务 + 单页前端。

默认只监听 127.0.0.1。在 iPhone 上使用：python -m lifeos phone（见 docs/iPhone使用指南.md）。

给 iPhone 快捷指令用的纯文本接口（请求头 X-LifeOS-Token 带上口令）：
    POST /api/capture?format=text   body: {"text": "..."}   → 中文回执
    GET  /api/today?format=text                              → 今日安排
"""

import html
import json
import os
from datetime import date, datetime
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import (business, config, daily, db, decisions, family, letter, meals, memory, mind, now, photos, planner, relationship, review,
               shi, tasks, yi)

STATIC = Path(__file__).parent / "static"
TOKEN = os.environ.get("LIFEOS_TOKEN")


def api_get(path: str, q: dict, conn):
    one = lambda k, d=None: q.get(k, [d])[0]  # noqa: E731
    if path == "/api/home":
        t = datetime.now()
        part = "清晨" if t.hour < 9 else "上午" if t.hour < 12 else "下午" if t.hour < 18 else "晚上" if t.hour < 23 else "深夜"
        p = now.pocket(conn)
        return {"greeting": f"周{'一二三四五六日'[t.weekday()]}的{part}。", "hour": t.hour,
                "feelings": {k: v["icon"] for k, v in now.FEELINGS.items()},
                "anchors": now.anchors(t.date(), t.hour * 60 + t.minute), "echo": now.echo(conn),
                "dated": [x for x in p["dated"] if x["days_left"] <= 2], "pocket_count": p["count"],
                "dates": relationship.upcoming_dates(conn, horizon=14),
                "term": shi.solar_term(), "weather": shi.weather(conn), "cast": _cast_brief(conn),
                "horizons": family.horizons(conn), "rituals": [r for r in family.rituals(conn) if r["gentle"]],
                "photos": photos.on_this_day(conn), "skip_reasons": list(now.SKIP_REASONS),
                "notes": daily.notes(conn)}
    if path == "/api/now":
        exclude = [x for x in one("exclude", "").split(",") if x]
        minutes = int(one("minutes")) if one("minutes") else None
        if one("log"):
            now.log_state(conn, one("feeling", "平静"), minutes, one("note"))
        sug = now.suggest(conn, one("feeling", "平静"), minutes, exclude, decide=bool(one("decide")))
        if one("note"):
            sug["ai"] = now.ai_note(conn, one("feeling"), one("note"), sug)
        return sug
    if path == "/api/family":
        return {"horizons": family.horizons(conn), "rituals": family.rituals(conn), "north_star": family.north_star(conn),
                "places": family.places(conn), "wishes": relationship.wishes(conn)}
    if path == "/api/junzi":
        return yi.junzi_card()
    if path == "/api/tianshi":
        return {"term": shi.solar_term(), "weather": shi.weather(conn), "today": yi.today_cast(conn),
                "almanac": shi.almanac(), "stats": yi.stats(conn),
                "history": yi.history(conn), "trends": shi.trends(conn), "momentum": shi.momentum(conn),
                "stances": {k: v["desc"] + "：" + v["detail"] for k, v in yi.STANCES.items()}}
    if path == "/api/pocket":
        return now.pocket(conn)
    if path == "/api/letter":
        # 预览用模板（不调用 AI）；点"写信"时 POST 才调用 Claude 并保存
        return {"markdown": letter.render(conn)}
    if path == "/api/today":
        on = date.fromisoformat(one("date")) if one("date") else date.today()
        return planner.plan(on, conn)
    if path == "/api/memories":
        if one("q"):
            return memory.search(one("q"), int(one("limit", 30)), one("domain"), conn)
        return memory.timeline(int(one("days", 30)), conn)
    if path == "/api/ai":
        return {**daily.status(conn), "improvements": daily.improvements(conn)}
    if path == "/api/reflections":
        return mind.reflections(conn)
    if path == "/api/about":
        return {**mind.about(conn, one("name", "")), "lines": mind.about_lines(conn, one("name", ""))}
    if path == "/api/graph":
        return memory.graph(conn)
    if path == "/api/items":
        items = db.rows(conn.execute("SELECT * FROM items ORDER BY id DESC"))
        for it in items:
            it["profit"] = business.profit_of(it)
            it["defects"] = json.loads(it["defects"] or "[]")
        return {"items": items, "stats": business.stats(conn), "funds": business.funds(conn),
                "statuses": business.STATUSES, "currency": config.currency()}
    if path == "/api/her":
        return {"wishes": relationship.wishes(conn, include_done=True), "dates": relationship.upcoming_dates(conn, horizon=366),
                "ideas": relationship.ideas(conn), "love_hours": round(relationship.love_minutes_week(conn) / 60, 1),
                "projects": {w["project"]: tasks.list_open(conn, project=w["project"]) for w in relationship.wishes(conn) if w["project"]}}
    if path == "/api/review":
        r = review.weekly(conn, save=False, coach=False)
        return {k: v for k, v in r.items() if k != "markdown"} | {"markdown": r["markdown"]}
    if path == "/api/autonomy":
        return {"overview": decisions.overview(conn), "pending": decisions.pending(conn),
                "promotions": decisions.promotion_candidates(conn)}
    if path == "/api/menu":
        return meals.plan_week(conn)
    if path == "/api/tasks":
        return tasks.list_open(conn, one("domain"), one("project"))
    if path == "/api/meta":
        return {"domains": list(config.domains()), "currency": config.currency(),
                "llm": __import__("lifeos.llm", fromlist=["available"]).available(),
                "ai_mode": __import__("lifeos.llm", fromlist=["backend"]).backend(slow_ok=True) or "daily"}
    return None


def api_post(path: str, body: dict, conn):
    parts = path.strip("/").split("/")  # ["api", "items", "L-2026-001"]
    if path == "/api/capture":
        return memory.capture(body["text"], source="web", conn=conn)
    if path == "/api/yi/today":
        return yi.cast_today(conn, body.get("intention"))
    if path == "/api/horizons":
        return {"id": family.add_horizon(conn, body["title"], body["date"], bool(body.get("with_her", True)),
                                         int(body["wish_id"]) if body.get("wish_id") else None)}
    if parts[:2] == ["api", "horizons"] and len(parts) == 4 and parts[3] == "live":
        family.live_horizon(conn, int(parts[2]), body.get("reflection", ""))
        return {"ok": True}
    if path == "/api/rituals":
        return {"id": family.add_ritual(conn, body["name"], body["cadence"], _int(body.get("weekday")),
                                        _int(body.get("month")), _int(body.get("day")), body.get("note"))}
    if parts[:2] == ["api", "rituals"] and len(parts) == 4 and parts[3] == "log":
        family.log_ritual(conn, int(parts[2]), body.get("note", ""))
        return {"ok": True}
    if parts[:2] == ["api", "rituals"] and len(parts) == 4 and parts[3] == "pause":
        conn.execute("UPDATE rituals SET active = 0 WHERE id = ?", (int(parts[2]),))
        conn.commit()
        return {"ok": True}
    if path == "/api/northstar":
        return family.set_north_star(conn, body["text"])
    if path == "/api/places":
        return family.add_place(conn, body["name"], body.get("visited_on") or None, note=body.get("note"))
    if path == "/api/photos/scan":
        return photos.scan(conn)
    if path == "/api/now/skip_reason":
        return now.skip_reason(conn, int(body["task_id"]), body["reason"], body.get("first_step"))
    if path == "/api/yi/ask":
        return ask_yi(conn, body["question"])
    if path == "/api/yi/outcome":
        yi.note_outcome(conn, int(body["id"]), body["outcome"])
        return {"ok": True}
    if path == "/api/trends":
        return {"id": shi.add(conn, body["title"], body.get("domain") or None, int(body.get("direction", 0)),
                              int(body.get("strength", 2)), body.get("summary"))}
    if path == "/api/trends/fetch":
        return shi.fetch(conn)
    if parts[:2] == ["api", "trends"] and len(parts) == 4 and parts[3] in ("retire", "keep"):
        (shi.retire if parts[3] == "retire" else shi.keep)(conn, int(parts[2]))
        return {"ok": True}
    if parts[:2] == ["api", "improvements"] and len(parts) == 4:
        daily.mark_improvement(conn, int(parts[2]), parts[3])
        return {"ok": True}
    if path == "/api/now/skip":
        return now.skip(conn, int(body["task_id"]))
    if path == "/api/now/letgo":
        now.let_go(conn, int(body["task_id"]))
        return {"ok": True}
    if path == "/api/goodnight":
        f = now.FEELINGS.get(body.get("feeling") or "", None)
        if f:
            now.log_state(conn, body["feeling"], None, "晚安")
        review.checkin(conn, energy=f and f["energy"], mood=f and f["mood"], sleep=body.get("sleep"),
                       love_minutes=body.get("love_minutes"), note=body.get("moment"))
        moment, her = (body.get("moment") or "").strip(), (body.get("her") or "").strip()
        if moment:
            memory.capture(moment, source="goodnight", conn=conn)
        if her:
            memory.capture(her if "她" in her else f"她{her}", source="goodnight", conn=conn)
        if body.get("love_minutes"):
            review.log_time(conn, "关系", int(body["love_minutes"]), "晚安")
        mind.nightly(conn)
        return {"ok": True}
    if path == "/api/letter":
        return letter.write(conn)
    if path == "/api/feedback":
        return decisions.feedback(conn, int(body["id"]), body["verdict"], body.get("reason", ""), bool(body.get("severe")))
    if path == "/api/checkin":
        r = review.checkin(conn, energy=body.get("energy"), mood=body.get("mood"), sleep=body.get("sleep"),
                           exercised=body.get("exercised"), love_minutes=body.get("love_minutes"), note=body.get("note"))
        if body.get("note"):
            memory.capture(body["note"], source="checkin", conn=conn)
        if body.get("love_minutes"):
            review.log_time(conn, "关系", int(body["love_minutes"]), "签到")
        mind.nightly(conn)
        return r
    if path == "/api/timelog":
        review.log_time(conn, body["domain"], int(body["minutes"]), body.get("note", ""))
        return {"ok": True}
    if path == "/api/tasks":
        return {"id": tasks.add(conn, body["title"], body.get("domain") or "生活维持", int(body.get("priority", 3)),
                                body.get("energy", "medium"), int(body.get("minutes", 30)), body.get("due") or None,
                                body.get("project"))}
    if parts[:2] == ["api", "tasks"] and len(parts) == 4:
        (tasks.done if parts[3] == "done" else tasks.drop)(conn, int(parts[2]))
        return {"ok": True}
    if path == "/api/items":
        return business.add_item(conn, body["model"], float(body["price"]), body.get("platform") or None,
                                 body.get("defects") or [], body.get("condition"), est_price=body.get("est") or None)
    if parts[:2] == ["api", "items"] and len(parts) == 3:
        if body.get("sell_price"):
            return business.sell(conn, parts[2], float(body["sell_price"]), body.get("platform"), body.get("hours"))
        return business.update_item(conn, parts[2], **body)
    if path == "/api/deal":
        r = business.evaluate_deal(conn, body["model"], float(body["price"]), body.get("defects") or [],
                                   body.get("platform"), float(body["est"]) if body.get("est") else None)
        r["suggestion_id"] = decisions.suggest(conn, "deal_eval", f"{body['model']} @ {body['price']}: {r['verdict']}", "；".join(r["reasons"]))
        return r
    if path == "/api/wishes":
        return {"id": relationship.add_wish(conn, body["content"], body.get("category", "other"))}
    if parts[:2] == ["api", "wishes"] and len(parts) == 3:
        relationship.set_wish_status(conn, int(parts[2]), body["status"])
        return {"ok": True}
    if path == "/api/dates":
        return {"id": relationship.add_date(conn, body["name"], int(body["month"]), int(body["day"]))}
    if path == "/api/review":
        return {"markdown": review.weekly(conn)["markdown"]}
    if path == "/api/confirm":
        memory.confirm(int(body["id"]), bool(body.get("keep", True)), conn)
        return {"ok": True}
    return None


def shop_page(conn) -> str:
    """器材橱窗：在售库存的只读展示页——也是和她一起开发的转售平台的第一个原型。"""
    cur = config.currency()
    items = db.rows(conn.execute("SELECT * FROM items WHERE status = '在售' ORDER BY listed_at DESC"))
    cards = "".join(
        f"""<article><h3>{html.escape(i['model'])}</h3><p class="price">{cur}{(i['list_price'] or 0):.0f}</p>
        <p>{html.escape(i['condition'] or '')}</p>
        <p class="muted">瑕疵：{html.escape('、'.join(json.loads(i['defects'] or '[]')) or '无明显瑕疵')}</p>
        <p class="muted">编号 {i['code']}</p></article>"""
        for i in items
    ) or "<p>暂时没有在售器材。</p>"
    return f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>器材橱窗</title><style>
:root{{--bg:#faf8f5;--fg:#1d1d1f;--muted:#6e6e73;--card:#fff;--line:#e5e2dc;--accent:#b4532a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--muted:#9a9a9a;--card:#1f1f1f;--line:#2e2e2e;--accent:#e2885c}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,"PingFang SC","Noto Sans SC",sans-serif}}
main{{max-width:960px;margin:0 auto;padding:24px 16px}} h1{{font-weight:600}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}}
article{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}}
h3{{margin:0 0 4px}} .price{{color:var(--accent);font-size:22px;font-weight:600;margin:0}} .muted{{color:var(--muted);font-size:14px;margin:4px 0}}
</style></head><body><main><p><a href="/" style="color:var(--muted)">← LifeOS</a></p><h1>📷 器材橱窗</h1><p class="muted">每一件都经过清洁、检测、实拍。共 {len(items)} 件在售。</p>
<div class="grid">{cards}</div></main></body></html>"""


def _int(v) -> int | None:
    return int(v) if v not in (None, "") else None


def _cast_brief(conn) -> dict | None:
    t = yi.today_cast(conn)
    if not t:
        return None
    p = t["primary"]
    return {"symbol": p["symbol"], "full": p["full"], "stance": p["stance_desc"], "xiang": p["xiang"]}


def ask_yi(conn, question: str) -> dict:
    """问一事：起卦 → 解读（有 Claude 时结合他的近况）→ 记录。"""
    r = yi.cast()
    reading = yi.interpret(r, question)
    feeling = conn.execute("SELECT feeling FROM states ORDER BY id DESC LIMIT 1").fetchone()
    context = "\n".join([f"- 最近的感受：{feeling[0] if feeling else '未知'}",
                         f"- 节气：{shi.solar_term()['name']}",
                         "- 各领域之势：" + ("，".join(f"{k} {v:+}" for k, v in shi.momentum(conn).items()) or "无记录"),
                         mind.context(conn, question, k=10)])
    reading["ai"] = yi.ai_reflect(conn, r, question, context)
    cid = yi.save(conn, r, question, "ask")
    conn.execute("UPDATE casts SET reading = ? WHERE id = ?", (json.dumps(reading, ensure_ascii=False), cid))
    conn.commit()
    return {"id": cid, **r, "reading": reading}


def _yi_text(conn) -> str:
    t = yi.cast_today(conn)
    rd = t["reading"]
    z = rd["zhuxi"]
    lines = [f"☯ 今日之卦：{rd['title']}", rd["guaci"], f"《象》曰：{rd['xiang']}", rd["plain"], "", z["rule"]]
    lines += [m["text"] for m in z["main"]] + [m["text"] for m in z["aux"]]
    lines += ["", f"姿态：{rd['stance_text']}"]
    if rd.get("trend"):
        lines.append(rd["trend"])
    lines += ["", "自问：" + " / ".join(rd["questions"]), "", rd["note"]]
    return "\n".join(lines)


def _now_text(conn, q) -> str:
    feeling = q.get("feeling", ["平静"])[0].strip() or "平静"
    minutes = q.get("minutes", [""])[0]
    minutes = int(minutes) if minutes.strip().isdigit() else None
    now.log_state(conn, feeling, minutes)
    return now.render_suggestion(now.suggest(conn, feeling, minutes, decide=True))


def _capture_text(conn, text: str) -> str:
    if not text.strip():
        return "没有收到内容"
    return memory.describe(memory.capture(text, source="iphone", conn=conn))


TEXT_ROUTES = {
    "/api/today": lambda conn, q, body: planner.render(planner.plan(conn=conn)),
    "/api/capture": lambda conn, q, body: _capture_text(conn, body.get("text") or q.get("text", [""])[0]),
    "/api/morning": lambda conn, q, body: now.morning(conn),
    "/api/yi": lambda conn, q, body: _yi_text(conn),
    "/api/junzi": lambda conn, q, body: (lambda c: f"{c['symbol']} {c['image']}\n{c['act']}\n——{c['plain']}")(yi.junzi_card()),
    "/api/shi": lambda conn, q, body: shi.digest(conn),
    "/api/now": lambda conn, q, body: _now_text(conn, q),
    "/api/her": lambda conn, q, body: "💡 今天的惊喜建议\n" + "\n".join(
        f"[{i['scale']}] {i['idea']}" for i in relationship.ideas(conn)),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 安静一点
        pass

    def _authorized(self, q) -> bool:
        if not TOKEN:
            return True
        if q.get("token", [None])[0] == TOKEN or self.headers.get("X-LifeOS-Token") == TOKEN:
            return True
        c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "lifeos_token" in c and c["lifeos_token"].value == TOKEN

    def _send(self, code: int, body: bytes, ctype: str, set_cookie: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if set_cookie and TOKEN:
            self.send_header("Set-Cookie", f"lifeos_token={TOKEN}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode(), "application/json; charset=utf-8")

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if not self._authorized(q):
            return self._send(401, "需要 token".encode(), "text/plain; charset=utf-8")
        conn = db.connect()
        try:
            if q.get("format", [""])[0] == "text" and url.path in TEXT_ROUTES:
                return self._send(200, TEXT_ROUTES[url.path](conn, q, {}).encode(), "text/plain; charset=utf-8")
            if url.path.startswith("/api/"):
                r = api_get(url.path, q, conn)
                return self._json(r) if r is not None else self._json({"error": "not found"}, 404)
            if url.path.startswith("/photo/"):
                f = photos.path_of(conn, int(url.path.rsplit("/", 1)[-1]))
                if not f:
                    return self._send(404, b"not found", "text/plain")
                ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
                         ".heic": "image/heic"}.get(f.suffix.lower(), "application/octet-stream")
                return self._send(200, f.read_bytes(), ctype)
            if url.path == "/shop":
                return self._send(200, shop_page(conn).encode(), "text/html; charset=utf-8")
            name = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
            f = (STATIC / name).resolve()
            if STATIC.resolve() not in f.parents or not f.is_file():
                return self._send(404, b"not found", "text/plain")
            ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                     ".css": "text/css; charset=utf-8", ".png": "image/png",
                     ".webmanifest": "application/manifest+json"}.get(f.suffix, "application/octet-stream")
            self._send(200, f.read_bytes(), ctype, set_cookie="token" in q)
        except Exception as e:  # 让前端看到错误，而不是空白
            self._json({"error": str(e)}, 500)
        finally:
            conn.close()

    def do_POST(self):
        url = urlparse(self.path)
        if not self._authorized(parse_qs(url.query)):
            return self._json({"error": "unauthorized"}, 401)
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "invalid json"}, 400)
        conn = db.connect()
        try:
            if parse_qs(url.query).get("format", [""])[0] == "text" and url.path in TEXT_ROUTES:
                return self._send(200, TEXT_ROUTES[url.path](conn, {}, body).encode(), "text/plain; charset=utf-8")
            r = api_post(url.path, body, conn)
            self._json(r) if r is not None else self._json({"error": "not found"}, 404)
        except (KeyError, ValueError) as e:
            self._json({"error": f"参数错误：{e}"}, 400)
        except Exception as e:
            self._json({"error": str(e)}, 500)
        finally:
            conn.close()


def serve(host: str = "127.0.0.1", port: int = 8765, token: str | None = None) -> None:
    global TOKEN
    TOKEN = token or TOKEN
    if host not in ("127.0.0.1", "localhost") and not TOKEN:
        raise SystemExit("监听外部地址时必须设置 LIFEOS_TOKEN 环境变量，保护你的私人数据。")
    conn = db.connect()
    family.seed(conn)
    conn.close()
    if host in ("127.0.0.1", "localhost"):
        print(f"🌐 LifeOS 仪表盘：http://{host}:{port}/    器材橱窗：http://{host}:{port}/shop")
    if os.environ.get("LIFEOS_AUTORELOAD"):
        _watch_for_updates()
    ThreadingHTTPServer((host, port), Handler).serve_forever()


def _code_stamp() -> float:
    root = Path(__file__).parent
    return max(p.stat().st_mtime for p in [*root.glob("*.py"), *root.glob("static/*")] if p.is_file())


def _watch_for_updates(every: int = 300) -> None:
    """在后台服务（launchd）里运行时：git pull 拿到新代码后，自己安静地退出，由 launchd 用新代码重启。"""
    import threading
    import time

    start = _code_stamp()

    def loop():
        while True:
            time.sleep(every)
            try:
                if _code_stamp() > start:
                    print("🔄 发现新版本，重启以加载…", flush=True)
                    os._exit(0)
            except OSError:
                pass

    threading.Thread(target=loop, daemon=True).start()
