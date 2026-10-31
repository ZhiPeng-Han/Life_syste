"""Telegram 机器人：手机上随手一句话就进入记忆系统（输入零摩擦）。

1. 在 Telegram 找 @BotFather 创建机器人，拿到 token
2. export LIFEOS_TELEGRAM_TOKEN=xxx
3. 先不设 LIFEOS_TELEGRAM_CHAT，运行 python -m lifeos bot，给机器人发一条消息，
   终端会打印你的 chat id；再 export LIFEOS_TELEGRAM_CHAT=那个id 后重启。只有这个 chat 能写入你的数据。

命令：/today 今日计划  /her 惊喜建议  /menu 本周菜单  /deal 型号 报价 [瑕疵…]
其他任何文字都会被当作"随手记"。
"""

import json
import os
import time
import urllib.parse
import urllib.request

from . import business, db, decisions, meals, memory, planner, relationship

API = "https://api.telegram.org/bot{token}/{method}"


def _call(token: str, method: str, **params) -> dict:
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(API.format(token=token, method=method), data=data, timeout=40) as r:
        return json.loads(r.read())


def handle(text: str, conn) -> str:
    text = text.strip()
    if text.startswith("/today"):
        return planner.render(planner.plan(conn=conn))
    if text.startswith("/her"):
        ideas = relationship.ideas(conn)
        return "💡 惊喜建议\n" + "\n".join(f"[{i['scale']}] {i['idea']}" for i in ideas) if ideas else "还没有记下她的愿望"
    if text.startswith("/menu"):
        m = meals.plan_week(conn)
        return "\n".join(f"{d['day']} {d['dish']}{' 🥗' if d['light'] else ''}" for d in m["days"]) + "\n🛒 " + "、".join(m["shopping"])
    if text.startswith("/deal"):
        parts = text.split()[1:]
        if len(parts) < 2:
            return "用法：/deal 型号 报价 [瑕疵…]"
        try:
            price = float(parts[1])
        except ValueError:
            return "报价需要是数字"
        r = business.evaluate_deal(conn, parts[0], price, parts[2:])
        sid = decisions.suggest(conn, "deal_eval", f"{parts[0]} @ {price}: {r['verdict']}", "；".join(r["reasons"]))
        return f"🔍 {r['verdict']}\n" + "\n".join(r["reasons"]) + f"\n（反馈：/fb {sid} accept|reject 原因）"
    if text.startswith("/fb"):
        parts = text.split(maxsplit=3)
        if len(parts) < 3 or parts[2] not in ("accept", "reject", "modify"):
            return "用法：/fb 编号 accept|reject|modify 原因"
        decisions.feedback(conn, int(parts[1]), parts[2], parts[3] if len(parts) > 3 else "")
        return "已记录反馈 🙏"
    return memory.describe(memory.capture(text, source="telegram", conn=conn))


def run() -> None:
    token = os.environ.get("LIFEOS_TELEGRAM_TOKEN")
    allowed = os.environ.get("LIFEOS_TELEGRAM_CHAT")
    if not token:
        raise SystemExit("请先设置 LIFEOS_TELEGRAM_TOKEN（见 lifeos/bot.py 顶部说明）")
    print("🤖 LifeOS 机器人运行中…（Ctrl+C 退出）")
    offset = 0
    while True:
        try:
            updates = _call(token, "getUpdates", offset=offset, timeout=30).get("result", [])
        except OSError as e:
            print(f"网络错误：{e}，5 秒后重试")
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            chat = str(msg.get("chat", {}).get("id", ""))
            if not msg.get("text"):
                continue
            if not allowed:
                print(f"收到来自 chat {chat} 的消息。确认是你本人后：export LIFEOS_TELEGRAM_CHAT={chat}")
                continue
            if chat != allowed:
                continue
            conn = db.connect()
            try:
                reply = handle(msg["text"], conn)
            except Exception as e:  # 机器人不能因为一条消息挂掉
                reply = f"出错了：{e}"
            finally:
                conn.close()
            _call(token, "sendMessage", chat_id=chat, text=reply[:4000])
