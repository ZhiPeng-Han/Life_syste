"""可视化仪表盘：零依赖 HTTP 服务 + 单页前端。

默认只监听 127.0.0.1。在 iPhone 上使用：python -m lifeos phone（见 docs/iPhone使用指南.md）。

给 iPhone 快捷指令用的纯文本接口（请求头 X-LifeOS-Token 带上口令）：
    POST /api/capture?format=text   body: {"text": "..."}   → 中文回执
    GET  /api/today?format=text                              → 今日安排
"""

import html
import json
import os
from datetime import date
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import (business, config, db, decisions, meals, memory, planner, relationship, review, tasks)

STATIC = Path(__file__).parent / "static"
TOKEN = os.environ.get("LIFEOS_TOKEN")


def api_get(path: str, q: dict, conn):
    one = lambda k, d=None: q.get(k, [d])[0]  # noqa: E731
    if path == "/api/today":
        on = date.fromisoformat(one("date")) if one("date") else date.today()
        return planner.plan(on, conn)
    if path == "/api/memories":
        if one("q"):
            return memory.search(one("q"), int(one("limit", 30)), one("domain"), conn)
        return memory.timeline(int(one("days", 30)), conn)
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
                "llm": __import__("lifeos.llm", fromlist=["available"]).available()}
    return None


def api_post(path: str, body: dict, conn):
    parts = path.strip("/").split("/")  # ["api", "items", "L-2026-001"]
    if path == "/api/capture":
        return memory.capture(body["text"], source="web", conn=conn)
    if path == "/api/feedback":
        return decisions.feedback(conn, int(body["id"]), body["verdict"], body.get("reason", ""), bool(body.get("severe")))
    if path == "/api/checkin":
        r = review.checkin(conn, energy=body.get("energy"), mood=body.get("mood"), sleep=body.get("sleep"),
                           exercised=body.get("exercised"), love_minutes=body.get("love_minutes"), note=body.get("note"))
        if body.get("note"):
            memory.capture(body["note"], source="checkin", conn=conn)
        if body.get("love_minutes"):
            review.log_time(conn, "关系", int(body["love_minutes"]), "签到")
        memory.consolidate(conn=conn)
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


def _capture_text(conn, text: str) -> str:
    if not text.strip():
        return "没有收到内容"
    return memory.describe(memory.capture(text, source="iphone", conn=conn))


TEXT_ROUTES = {
    "/api/today": lambda conn, q, body: planner.render(planner.plan(conn=conn)),
    "/api/capture": lambda conn, q, body: _capture_text(conn, body.get("text") or q.get("text", [""])[0]),
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
    db.connect().close()
    if host in ("127.0.0.1", "localhost"):
        print(f"🌐 LifeOS 仪表盘：http://{host}:{port}/    器材橱窗：http://{host}:{port}/shop")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
