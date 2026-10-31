"""命令行入口：python -m lifeos <命令>。所有命令都设计成 10 秒内可完成。"""

import argparse
import json
import sys
from datetime import date

from . import (__version__, business, cards, config, db, decisions, experiments, llm, meals, memory, planner,
               relationship, review, seed, tasks)


def out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2) if not isinstance(obj, str) else obj)


def cmd_init(a, conn):
    r = seed.run(conn)
    out(f"✅ LifeOS 已初始化：{config.db_path()}\n" + json.dumps(r, ensure_ascii=False))
    out(f"AI 引擎：{'Claude（' + llm.MODEL + '）' if llm.available() else '规则引擎（设置 ANTHROPIC_API_KEY 后启用 Claude）'}")
    out("下一步：python -m lifeos today")


def cmd_add(a, conn):
    r = memory.capture(" ".join(a.text), source="cli", conn=conn)
    out(memory.describe(r) + f"（{r['engine']}）")


def cmd_today(a, conn):
    on = date.fromisoformat(a.date) if a.date else date.today()
    p = planner.plan(on, conn)
    out(p if a.json else planner.render(p))


def cmd_checkin(a, conn):
    vals = {"energy": a.energy, "mood": a.mood, "sleep": a.sleep, "exercised": a.exercised,
            "love_minutes": a.love, "note": a.note}
    if all(v is None for v in vals.values()):
        for key, q in review.CHECKIN_QUESTIONS:
            ans = input(f"{q} ").strip()
            if not ans:
                continue
            if key == "exercised":
                vals[key] = 1 if ans.lower().startswith(("y", "是", "1")) else 0
            elif key == "note":
                vals[key] = ans
            else:
                try:
                    vals[key] = float(ans) if key == "sleep" else int(ans)
                except ValueError:
                    pass
    r = review.checkin(conn, energy=vals["energy"], mood=vals["mood"], sleep=vals["sleep"],
                       exercised=vals["exercised"], love_minutes=vals["love_minutes"], note=vals["note"])
    if vals["note"]:
        memory.capture(vals["note"], source="checkin", conn=conn)
    if vals["love_minutes"]:
        review.log_time(conn, "关系", int(vals["love_minutes"]), "签到")
    s = memory.consolidate(conn=conn)
    out("✅ 签到完成，晚安。" + (f"\n📝 今日摘要：{s['summary']}" if s else ""))
    del r


def cmd_t(a, conn):
    if a.domain not in config.domains():
        sys.exit(f"未知领域：{a.domain}。可选：{'、'.join(config.domains())}")
    review.log_time(conn, a.domain, a.minutes, " ".join(a.note))
    out(f"⏱ 记录 {a.domain} {a.minutes} 分钟")


def cmd_task(a, conn):
    if a.action == "add":
        tid = tasks.add(conn, " ".join(a.rest), a.domain, a.priority, a.energy, a.minutes, a.due, a.project)
        out(f"☐ 任务 #{tid} 已添加")
    elif a.action in ("done", "drop"):
        for tid in a.rest:
            (tasks.done if a.action == "done" else tasks.drop)(conn, int(tid))
        out("✓")
    else:
        for t in tasks.list_open(conn, a.domain, a.project):
            due = f" ⏰{t['due']}" if t["due"] else ""
            out(f"#{t['id']:<4} P{t['priority']} [{t['domain']}] {t['title']}{due}")


def cmd_search(a, conn):
    for m in memory.search(" ".join(a.query), a.limit, a.domain, conn):
        out(f"#{m['id']} {m['occurred_at'][:10]} [{m['domain']}] {m['content']}  (score {m['score']})")


def cmd_confirm(a, conn):
    for m in memory.pending_confirm(conn):
        ans = input(f"#{m['id']} [{m['domain']}] {m['content']}\n  理解对吗？(y=对 / n=删掉 / 回车跳过) ").strip().lower()
        if ans in ("y", "n"):
            memory.confirm(m["id"], ans == "y", conn)
    out("✓")


def cmd_fb(a, conn):
    out(decisions.feedback(conn, a.id, a.verdict, " ".join(a.reason), a.severe))


def cmd_autonomy(a, conn):
    if a.action == "set":
        cur = decisions.level(conn, a.category)
        new = cur + int(a.value) if a.value.startswith(("+", "-")) else int(a.value)
        out(f"{a.category}: {decisions.LEVEL_NAMES[decisions.set_level(conn, a.category, new)]}")
        return
    for o in decisions.overview(conn):
        rate = f"{o['rate']:.0%}" if o["rate"] is not None else "—"
        out(f"{o['desc']:<14} {o['level']:<10} 上限 {o['cap']:<10} 采纳率 {rate}（{o['n']} 次）  [{o['category']}]")
    for p in decisions.promotion_candidates(conn):
        out(f"⬆️ 建议升级 {p['category']}：{p['from']} → {p['to']}")


def cmd_item(a, conn):
    cur = config.currency()
    if a.action == "add":
        it = business.add_item(conn, a.model, a.price, a.platform, a.defects or [], a.condition, a.serial, a.est)
        out(f"📷 {it['code']} {it['model']} 收价 {cur}{it['buy_price']}" + (f"，预估售价 {cur}{it['est_price']}" if it["est_price"] else ""))
    elif a.action == "set":
        it = business.update_item(conn, a.code, status=a.status, list_price=a.list_price, extra_costs=a.extra,
                                  hours_spent=a.hours, notes=a.notes)
        out(it)
        if a.status == "在售":
            decisions.suggest(conn, "listing_price", f"{it['code']} 定价 {it['list_price']}", "上架")
            out("\n— 上架描述草稿 —\n" + business.listing_draft(it))
    elif a.action == "sell":
        it = business.sell(conn, a.code, a.price, a.platform, a.hours)
        out(f"✅ {it['code']} 售出 {cur}{it['sell_price']}，净利润 {cur}{business.profit_of(it)}")
    elif a.action == "stats":
        out(business.stats(conn))
        out(business.funds(conn))
    else:
        for it in db.rows(conn.execute("SELECT * FROM items ORDER BY id DESC")):
            profit = business.profit_of(it)
            out(f"{it['code']} [{it['status']}] {it['model']} 收{cur}{it['buy_price']}"
                + (f" 售{cur}{it['sell_price']} 利{cur}{profit}" if profit is not None else ""))


def cmd_deal(a, conn):
    r = business.evaluate_deal(conn, a.model, a.price, a.defects or [], a.platform, a.est)
    sid = decisions.suggest(conn, "deal_eval", f"{a.model} @ {a.price}: {r['verdict']}", "；".join(r["reasons"]))
    out(f"🔍 {r['verdict']}\n" + "\n".join(f"  · {x}" for x in r["reasons"]) + f"\n👍/👎 lifeos fb {sid} accept|reject \"原因\"")


def cmd_her(a, conn):
    lines = ["❤️ 她的愿望清单"]
    for w in relationship.wishes(conn, include_done=True):
        lines.append(f"  #{w['id']} [{w['status']}] {w['content']}" + (f"  → 项目：{w['project']}" if w["project"] else ""))
    up = relationship.upcoming_dates(conn, horizon=366)
    lines.append("\n🎁 重要日期" + ("" if up else "：还没有，lifeos date add 生日 5 20"))
    lines += [f"  {d['name']} {d['date']}（还有 {d['days_left']} 天）" for d in up]
    lines.append(f"\n⏱ 本周高质量相处：{relationship.love_minutes_week(conn) / 60:.1f}h")
    lines.append("\n💡 惊喜建议（微 / 中 / 大）")
    ai = relationship.ai_ideas(conn) if a.ai else None
    if ai:
        lines.append(ai)
    else:
        for i in relationship.ideas(conn):
            lines.append(f"  [{i['scale']}] {i['idea']}  ——「{i['wish']}」")
    sid = decisions.suggest(conn, "surprise", "\n".join(lines[-3:]), "惊喜引擎")
    lines.append(f"\n做了哪个？她的反应？ lifeos fb {sid} accept \"她很开心，因为……\"")
    out("\n".join(lines))


def cmd_wish(a, conn):
    if a.action == "add":
        out(f"❤️ 愿望 #{relationship.add_wish(conn, ' '.join(a.rest), a.category)} 已记下")
    elif a.action == "status":
        relationship.set_wish_status(conn, int(a.rest[0]), a.rest[1])
        out("✓")


def cmd_date(a, conn):
    out(f"🎁 已添加 #{relationship.add_date(conn, a.name, a.month, a.day)}")


def cmd_menu(a, conn):
    m = meals.plan_week(conn, regenerate=a.regenerate)
    if not a.regenerate:
        key = f"menu_sugg:{m['week']}"
        if db.get_meta(conn, key) is None:
            db.set_meta(conn, key, decisions.suggest(conn, "meal_plan", json.dumps(m["days"], ensure_ascii=False)))
    lines = [f"🍳 本周菜单（{m['week']} 起，轻食 = 🥗）"]
    lines += [f"  {d['day']} {d['dish']}{' 🥗' if d['light'] else ''}" for d in m["days"]]
    lines.append("\n🛒 购物清单：" + "、".join(m["shopping"]))
    lines.append(f"\n不满意？python -m lifeos menu --regenerate ；好用就 lifeos fb {db.get_meta(conn, 'menu_sugg:' + m['week'])} accept")
    out("\n".join(lines))


def cmd_card(a, conn):
    if a.action == "add":
        out(f"📚 卡片 #{cards.add(conn, a.front, a.back, a.deck)}")
    elif a.action == "review":
        due = cards.due(conn, deck=a.deck)
        if not due:
            out("🎉 今天没有到期卡片")
        for c in due:
            input(f"\n❓ {c['front']}\n   （回车看答案）")
            print(f"💡 {c['back']}")
            g = input("   记得怎么样？0=忘了 3=费劲 4=还行 5=秒答：").strip()
            r = cards.review(conn, c["id"], int(g) if g.isdigit() else 3)
            print(f"   下次：{r['next_due']}")
    else:
        out(cards.stats(conn))


def cmd_exp(a, conn):
    if a.action == "add":
        out(f"🔬 实验 #{experiments.add(conn, a.name, a.metric, a.start, a.end, a.hypothesis or '')}")
    elif a.action == "analyze":
        out(experiments.analyze(conn, a.id))
    else:
        for e in experiments.list_all(conn):
            out(f"#{e['id']} [{e['status']}] {e['name']}（{e['metric']}，{e['start']}→{e['end']}）{e['result'] or ''}")


def cmd_decide(a, conn):
    if a.action == "log":
        did = decisions.log_decision(conn, a.question, a.choice, a.prediction, a.confidence, a.category or "")
        out(f"📝 决策 #{did} 已记录，{14} 天后提醒你复盘")
    elif a.action == "review":
        for d in decisions.due_reviews(conn):
            print(f"\n#{d['id']} {d['question']}\n  选择：{d['choice']}  预测：{d['prediction']}（信心 {d['confidence']:.0%}）")
            outcome = input("  实际结果：").strip()
            if not outcome:
                continue
            correct = input("  预测对了吗？(y/n) ").strip().lower() == "y"
            lesson = input("  教训：").strip()
            decisions.review_decision(conn, d["id"], outcome, correct, lesson)
        out(decisions.calibration(conn))


def cmd_review(a, conn):
    r = review.weekly(conn)
    out(r["markdown"])
    out(f"\n已保存：{r['path']}")


def cmd_manual(a, conn):
    out(review.user_manual(conn))


def cmd_consolidate(a, conn):
    out(memory.consolidate(a.day, conn) or "这一天没有记忆")


def cmd_serve(a, conn):
    from . import web

    web.serve(a.host, a.port)


def cmd_phone(a, conn):
    from . import phone

    phone.run(a.port)


def cmd_bot(a, conn):
    from . import bot

    bot.run()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lifeos", description=f"LifeOS v{__version__} —— AI 人生管理系统")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化数据库与种子数据").set_defaults(fn=cmd_init)

    s = sub.add_parser("add", aliases=["a"], help="随手记一句话（AI 自动拆解成记忆/任务/愿望/交易）")
    s.add_argument("text", nargs="+")
    s.set_defaults(fn=cmd_add)

    s = sub.add_parser("today", help="今日驾驶舱：日程 + 3 件事 + 提醒")
    s.add_argument("--date")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_today)

    s = sub.add_parser("checkin", help="晚间签到（不带参数则交互式提问）")
    s.add_argument("--energy", type=int)
    s.add_argument("--mood", type=int)
    s.add_argument("--sleep", type=float)
    s.add_argument("--exercised", type=int, choices=[0, 1])
    s.add_argument("--love", type=int, help="和她高质量相处的分钟数")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_checkin)

    s = sub.add_parser("t", help="记录时间：lifeos t 器材事业 90 拍照")
    s.add_argument("domain")
    s.add_argument("minutes", type=int)
    s.add_argument("note", nargs="*")
    s.set_defaults(fn=cmd_t)

    s = sub.add_parser("task", help="任务：add / list / done / drop")
    s.add_argument("action", choices=["add", "list", "done", "drop"])
    s.add_argument("rest", nargs="*")
    s.add_argument("--domain", "-d")
    s.add_argument("--priority", "-p", type=int, default=3)
    s.add_argument("--energy", "-e", default="medium", choices=["high", "medium", "low"])
    s.add_argument("--minutes", "-m", type=int, default=30)
    s.add_argument("--due")
    s.add_argument("--project")
    s.set_defaults(fn=cmd_task)

    s = sub.add_parser("search", aliases=["s"], help="检索记忆")
    s.add_argument("query", nargs="+")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--domain")
    s.set_defaults(fn=cmd_search)

    sub.add_parser("confirm", help="确认 AI 不确定的记忆").set_defaults(fn=cmd_confirm)

    s = sub.add_parser("fb", help="对系统建议反馈：lifeos fb 12 reject \"原因\" [--severe]")
    s.add_argument("id", type=int)
    s.add_argument("verdict", choices=["accept", "reject", "modify"])
    s.add_argument("reason", nargs="*")
    s.add_argument("--severe", action="store_true", help="错得离谱，立即降一级自主权")
    s.set_defaults(fn=cmd_fb)

    s = sub.add_parser("autonomy", help="查看/调整决策自主等级")
    s.add_argument("action", nargs="?", choices=["list", "set"], default="list")
    s.add_argument("category", nargs="?")
    s.add_argument("value", nargs="?", default="+1")
    s.set_defaults(fn=cmd_autonomy)

    s = sub.add_parser("item", help="器材库存：add / set / sell / list / stats")
    s.add_argument("action", choices=["add", "set", "sell", "list", "stats"])
    s.add_argument("--model")
    s.add_argument("--code")
    s.add_argument("--price", type=float)
    s.add_argument("--platform")
    s.add_argument("--defects", nargs="*")
    s.add_argument("--condition")
    s.add_argument("--serial")
    s.add_argument("--est", type=float)
    s.add_argument("--status", choices=business.STATUSES)
    s.add_argument("--list-price", type=float)
    s.add_argument("--extra", type=float, help="清洁/维修等额外成本")
    s.add_argument("--hours", type=float)
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_item)

    s = sub.add_parser("deal", help="捡漏评估：lifeos deal --model \"50/1.4\" --price 180 --defects 雾")
    s.add_argument("--model", required=True)
    s.add_argument("--price", type=float, required=True)
    s.add_argument("--defects", nargs="*")
    s.add_argument("--platform")
    s.add_argument("--est", type=float, help="没有历史数据时手动给预估售价")
    s.set_defaults(fn=cmd_deal)

    s = sub.add_parser("her", help="她的愿望、重要日期、惊喜建议")
    s.add_argument("--ai", action="store_true", help="用 Claude 生成个性化惊喜方案")
    s.set_defaults(fn=cmd_her)

    s = sub.add_parser("wish", help="愿望：add 内容 / status ID 状态")
    s.add_argument("action", choices=["add", "status"])
    s.add_argument("rest", nargs="+")
    s.add_argument("--category", default="other", choices=["travel", "project", "health", "gift", "experience", "other"])
    s.set_defaults(fn=cmd_wish)

    s = sub.add_parser("date", help="重要日期：lifeos date add 生日 5 20")
    s.add_argument("action", choices=["add"])
    s.add_argument("name")
    s.add_argument("month", type=int)
    s.add_argument("day", type=int)
    s.set_defaults(fn=cmd_date)

    s = sub.add_parser("menu", help="本周菜单 + 购物清单")
    s.add_argument("--regenerate", action="store_true")
    s.set_defaults(fn=cmd_menu)

    s = sub.add_parser("card", help="Part 3 卡片：add / review / stats")
    s.add_argument("action", choices=["add", "review", "stats"])
    s.add_argument("front", nargs="?")
    s.add_argument("back", nargs="?")
    s.add_argument("--deck", default="Part3")
    s.set_defaults(fn=cmd_card)

    s = sub.add_parser("exp", help="个人实验：add / list / analyze")
    s.add_argument("action", choices=["add", "list", "analyze"])
    s.add_argument("--name")
    s.add_argument("--metric", choices=experiments.METRICS)
    s.add_argument("--start")
    s.add_argument("--end")
    s.add_argument("--hypothesis")
    s.add_argument("--id", type=int)
    s.set_defaults(fn=cmd_exp)

    s = sub.add_parser("decide", help="决策日志：log / review（校准你的判断力）")
    s.add_argument("action", choices=["log", "review"])
    s.add_argument("--question")
    s.add_argument("--choice")
    s.add_argument("--prediction")
    s.add_argument("--confidence", type=float, default=0.7)
    s.add_argument("--category")
    s.set_defaults(fn=cmd_decide)

    sub.add_parser("review", help="生成本周复盘").set_defaults(fn=cmd_review)
    sub.add_parser("manual", help="生成《我的说明书》").set_defaults(fn=cmd_manual)

    s = sub.add_parser("consolidate", help="把某天的记忆巩固成日摘要")
    s.add_argument("--day")
    s.set_defaults(fn=cmd_consolidate)

    s = sub.add_parser("serve", help="启动可视化仪表盘")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("phone", help="让 iPhone 能访问：生成口令、显示手机链接、启动服务")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_phone)

    sub.add_parser("bot", help="启动 Telegram 机器人（手机随手记）").set_defaults(fn=cmd_bot)
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    conn = db.connect()
    if args.cmd != "init" and not db.get_meta(conn, "seeded"):
        seed.run(conn)
    args.fn(args, conn)
