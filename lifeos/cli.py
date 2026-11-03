"""命令行入口：python -m lifeos <命令>。所有命令都设计成 10 秒内可完成。"""

import argparse
import json
import sys
from datetime import date

from . import (__version__, business, cards, config, db, decisions, daily, experiments, family, letter, photos, llm, meals, memory, mind, now,
               planner, relationship, review, seed, shi, tasks, tianshi, yi, jushi, mingli, moments)


def out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2) if not isinstance(obj, str) else obj)


def ask(prompt: str, default: str = "") -> str:
    """交互式提问；在定时任务、管道里（没有终端）直接用默认值，而不是报错。"""
    if not sys.stdin.isatty():
        return default
    try:
        return input(prompt)
    except EOFError:
        return default


def cmd_init(a, conn):
    r = seed.run(conn)
    out(f"✅ LifeOS 已初始化：{config.db_path()}\n" + json.dumps(r, ensure_ascii=False))
    out(f"AI：{llm.describe()}")
    out("下一步：python -m lifeos today")


def cmd_add(a, conn):
    r = memory.capture(" ".join(a.text), source="cli", conn=conn)
    out(memory.describe(r) + f"（{r['engine']}）")


def cmd_now(a, conn):
    feeling = a.feeling
    if not feeling:
        # 不用先回答问题：先按天时、地利、人和给一个"此刻宜"
        her = True if a.her else None
        out(now.render_right_now(now.right_now(conn, place=a.place, her=her)))
        opts = list(now.FEELINGS)
        ans = ask("\n想说说现在的感受吗？ " + "  ".join(f"{i + 1}.{now.FEELINGS[f]['icon']}{f}" for i, f in enumerate(opts))
                  + "（回车跳过）> ").strip()
        if not ans:
            return
        feeling = opts[int(ans) - 1] if ans.isdigit() and 0 < int(ans) <= len(opts) else (ans if ans in opts else "平静")
    now.log_state(conn, feeling, a.minutes)
    seen = []
    while True:
        sug = now.suggest(conn, feeling, a.minutes, seen, decide=a.decide, place=a.place)
        out("\n" + now.render_suggestion(sug))
        if sug["kind"] == "none":
            return
        ans = ask("\n[回车] 好  [n] 换一个  [d] 做完了  [s] 跳过  [q] 算了 > ", "q").strip().lower()
        if ans == "n":
            seen.append(sug["key"])
            continue
        if ans == "d" and sug["kind"] == "task":
            tasks.done(conn, sug["task_id"])
            out("✓ 好的。")
        elif ans == "s" and sug["kind"] == "task":
            r = now.skip(conn, sug["task_id"])
            if r["ask_let_go"] and ask("这件事你跳过好几次了，要放下吗？(y/n) ").strip().lower() == "y":
                now.let_go(conn, sug["task_id"])
                out("🍃 放下了。")
        return


def cmd_jushi(a, conn):
    if a.action == "rate":
        ratings = dict(x.split("=", 1) for x in a.args if "=" in x)
        jushi.rate(conn, ratings)
        out("记下了。")
        return
    r = jushi.report(conn)
    out(r["markdown"])
    if a.ai:
        out("\n" + (jushi.ai_reading(conn, r) or "（没有可用的 Claude）"))


def cmd_choose(a, conn):
    opts = [{"name": o} for o in a.option]
    r = jushi.choose(conn, a.question, opts)
    out(f"🧩 {a.question}")
    for o in r["options"]:
        out(f"\n· {o['name']}")
        for k, t in o["notes"]:
            out(f"  {k}：{t}")
        for t in o["flags"]:
            out(f"  ⚠️ {t}")
    out("\n再问自己：")
    for x in r["lenses"]:
        out(f"  {x['name']}：{x['q']}")
    out(f"\n{r['calibration']}。{r['practice']}\n天时：{r['tian']}\n{r['note']}")
    out("（在网页「更多 → 人生局势」里可以对每个选项标注可逆性、对主要矛盾、对她、最坏情况，并记进决策日志）")


def cmd_mingli(a, conn):
    if a.birth:
        mingli.set_birth(conn, a.birth)
    c = mingli.mine(conn)
    if not c:
        out("先告诉我出生时间：python3 -m lifeos mingli --birth \"1997-05-01 08:30\"（只存在你的电脑上）")
        return
    out("\n".join(mingli.describe(c)) + "\n\n" + c["note"])


def cmd_moments(a, conn):
    if a.action == "add":
        out("加进去了：" + moments.add(conn, " ".join(a.args), a.need, a.minutes))
        return
    if a.action in ("on", "off"):
        for k in a.args:
            moments.set_active(conn, k, a.action == "on")
        out("好。")
        return
    for m in moments.listing(conn):
        out(f"{'  ' if m['active'] else '× '}[{m['cat']}] {m['title']}（{tianshi.NEED_LABEL.get(m['need'], m['need'])}，{m['minutes']} 分钟）"
            + (f" 好{m['yes']}/换{m['no']}" if m["yes"] or m["no"] else "") + f"  key={m['key']}")


def cmd_tian(a, conn):
    t = tianshi.now(conn)
    sea = t["season"]
    out(f"🧭 {tianshi.line(t)}")
    out(f"🌗 时令之卦 {sea['hex']['symbol']} {sea['hex']['full']}（{sea['month']}，阳 {sea['yang']} 阴 {6 - sea['yang']}）："
        f"{sea['text']}\n   《象》曰：{sea['hex']['xiang']}\n   {sea['next_hex']['from']}起转为 {sea['next_hex']['symbol']}{sea['next_hex']['name']}")
    out(f"🌾 {sea['term']}三候：" + " · ".join(("【" + h + "】") if i + 1 == sea["hou"]["n"] else h for i, h in enumerate(sea["hou"]["all"])))
    if t["sun"]:
        sn = t["sun"]
        out(f"☀️ 日出 {sn['rise']} · 黄金时刻 {sn['golden']} · 日落 {sn['set']} · 白昼 {sn['length']}（比昨天{'长' if sn['change'] >= 0 else '短'} {abs(sn['change'])} 分钟）")


def cmd_pocket(a, conn):
    p = now.pocket(conn)
    lines = [f"🫧 口袋里有 {p['count']} 件事，它们会等你。"]
    if p["dated"]:
        lines.append("\n⏳ 有日期的")
        lines += [f"  #{t['id']} {t['title']}（{t['due']}）" for t in p["dated"]]
    for g, items in p["groups"].items():
        lines.append(f"\n{g}")
        lines += [f"  #{t['id']} {t['title']}" for t in items]
    lines.append("\n做完：lifeos task done ID ；放下：lifeos letgo ID")
    out("\n".join(lines))


def cmd_letgo(a, conn):
    for tid in a.ids:
        now.let_go(conn, tid)
    out("🍃 放下了。放下也是一种选择。")


def cmd_morning(a, conn):
    out(now.morning(conn))


def cmd_letter(a, conn):
    out(letter.write(conn)["markdown"])


def _print_reading(rd: dict) -> None:
    z = rd["zhuxi"]
    out(f"\n☯ {rd['title']}\n{rd['guaci']}\n《象》曰：{rd['xiang']}\n{rd['plain']}\n\n{z['rule']}")
    for m in z["main"] + z["aux"]:
        out(f"  {m['text']}" + (f"\n    （底本：{m['wuying']}）" if m.get("wuying") else ""))
    out(f"\n姿态：{rd['stance_text']}\n{rd['change']}")
    if rd.get("trend"):
        out(rd["trend"])
    st = rd.get("structure")
    if st:
        out(f"\n卦象：{st['summary']}{st['balance']}")
        out(f"{st['lines_title']}：")
        for ln in st["lines"]:
            out(f"  {ln['name']}　{ln['text']}")
        out("看看另外三面：")
        for k in ("hu", "zong", "cuo"):
            x = st["related"][k]
            out(f"  {x['label']} {x['symbol']}{x['full']}（{x['meaning']}）：" + ("就是本卦自己——从这个角度看都一样" if x["same"] else x["plain"]))
        out("落在各处：" + "；".join(f"{k}：{v}" for k, v in st["areas"].items()))
    if rd.get("ai"):
        out("\n" + rd["ai"])
    out("\n自问：\n" + "\n".join(f"  · {q}" for q in rd["questions"]) + f"\n\n{rd['note']}")


def cmd_yi(a, conn):
    if a.action == "stats":
        out(yi.stats(conn))
        return
    if a.action == "history":
        for c in yi.history(conn):
            out(f"#{c['id']} {c['day']} {c['question'] or '今日'}：{c['title']}" + (f" ｜后来：{c['outcome']}" if c["outcome"] else ""))
        return
    if a.action == "outcome":
        yi.note_outcome(conn, a.id, " ".join(a.text))
        out("记下了。")
        return
    if a.ask:
        ask(f"心里想着：「{a.ask}」。准备好了按回车，掷六次铜钱…")
        from . import web

        r = web.ask_yi(conn, a.ask)
    else:
        intention = ask("心里想着什么？（可以不写，直接回车）").strip()
        r = yi.cast_today(conn, intention or None)
    lines = r["lines"]
    for i in range(5, -1, -1):
        v = lines[i]
        bar = "━━━━━━━" if v in (7, 9) else "━━━ ━━━"
        out(f"  {bar} {'○' if v == 9 else '×' if v == 6 else ''}")
    _print_reading(r["reading"])


def cmd_ai(a, conn):
    if a.action == "prepare":
        b = daily.backup()
        r = daily.prepare(conn, fetch_news=not a.no_news)
        out(f"💾 已备份：{b}")
        out(f"📦 工作包：{r['inbox']}\n   新输入 {r['inputs']} 条，新记忆 {r['memories']} 条，新闻标题 {r['headlines']} 条"
            + ("\n   ✉️ 今天是周日，请写信" if r["write_letter"] else ""))
        out(f"📐 结果格式：{r['schema']}\n✍️ 结果写到：{r['outbox']}\n然后运行：python3 -m lifeos ai apply {r['outbox']}")
    elif a.action == "apply":
        r = daily.apply(conn, a.file)
        out(f"✅ 第 {r['run']} 次梳理已应用（{r['changes']} 处）\n{r['summary']}\n报告：{r['report']}\n不满意：python3 -m lifeos ai undo")
    elif a.action == "undo":
        r = daily.undo(conn, a.id)
        out(f"↩️ 已撤销第 {r.get('run')} 次梳理的 {r['undone']} 处改动" if r["undone"] else "没有可撤销的梳理。")
    elif a.action == "improvements":
        for i in daily.improvements(conn, None if a.all else "open"):
            out(f"#{i['id']} [{i['status']}] {i['title']}（{i['effort'] or '?'}）\n   为什么：{i['why']}\n   怎么做：{i['how']}")
    elif a.action == "mark":
        daily.mark_improvement(conn, a.id, a.status)
        out("好。")
    else:
        s = daily.status(conn)
        out(json.dumps(s, ensure_ascii=False, indent=2))


def cmd_backup(a, conn):
    out(f"💾 {daily.backup()}")


def cmd_mind(a, conn):
    text = " ".join(a.text)
    if a.action == "recall":
        out(mind.context(conn, text) or "想不起和这件事相关的记忆。")
    elif a.action == "about":
        out("\n".join(mind.about_lines(conn, text)) or f"系统还不认识「{text}」。")
        for m in mind.about(conn, text)["memories"][:10]:
            out(f"  {m['occurred_at'][:10]} {m['content']}")
    elif a.action == "reflect":
        made = mind.reflect(conn, use_ai=a.ai or None)
        out("\n".join(f"🧠 {x}" for x in made) or "暂时没有新的领悟。")
    elif a.action == "wrong":
        memory.confirm(a.id, keep=False, conn=conn)
        out("好，这条领悟不再提。")
    elif a.action == "reindex":
        out(mind.reindex(conn))
    else:
        for r in mind.reflections(conn):
            out(f"#{r['id']} {r['content']}")


def cmd_shi(a, conn):
    if a.action == "add":
        tid = shi.add(conn, " ".join(a.text), a.domain, a.direction, a.strength)
        out(f"🌏 记下第 {tid} 条势")
    elif a.action == "fetch":
        out(shi.fetch(conn))
    elif a.action == "retire":
        shi.retire(conn, int(a.text[0]))
        out("✓")
    else:
        term = shi.solar_term()
        out(f"🌿 {term['name']}：{term['tip']}（距{term['next']} {term['days_to_next']} 天）")
        w = shi.weather(conn)
        if w:
            out(f"{w['icon']} {w['city']} {w['label']} {w['tmin']}–{w['tmax']}°C")
        mom = shi.momentum(conn)
        if mom:
            out("各领域之势：" + "，".join(f"{k} {'顺' if v > 0 else '逆'}{abs(v)}" for k, v in sorted(mom.items(), key=lambda x: -abs(x[1]))))
        for t in shi.trends(conn):
            d = {1: "顺", -1: "逆", 0: "观"}[t["direction"]]
            out(f"#{t['id']} [{d}{t['strength']}] [{t['domain'] or '—'}] {t['title']}")


def cmd_horizon(a, conn):
    if a.action == "add":
        out(f"✨ 盼头 #{family.add_horizon(conn, ' '.join(a.text), a.date, not a.alone)} 放上地平线了")
    elif a.action == "live":
        family.live_horizon(conn, int(a.text[0]), " ".join(a.text[1:]))
        out("记下了。下一个盼头是什么？")
    else:
        h = family.horizons(conn)
        for x in h["ahead"]:
            out(f"#{x['id']} {x['title']}  {x['date']}（还有 {x['days_left']} 天）")
        for x in h["to_reflect"]:
            out(f"#{x['id']} {x['title']} 已经过了——怎么样？ lifeos horizon live {x['id']} 一句话")
        if h["empty_soon"]:
            out("✨ 一个月内没有盼头了。可以是：" + "；".join(h["ideas"]))


def cmd_ritual(a, conn):
    if a.action == "log":
        family.log_ritual(conn, int(a.text[0]), " ".join(a.text[1:]))
        out("🕯")
    elif a.action == "add":
        out(f"🕯 仪式 #{family.add_ritual(conn, ' '.join(a.text), a.cadence, a.weekday, a.month, a.day)}")
    else:
        for r in family.rituals(conn):
            done = f"（这一期已经做了：{r['done_this_period']['day']}）" if r["done_this_period"] else ""
            out(f"#{r['id']} {r['when']} · {r['name']} {done}")


def cmd_northstar(a, conn):
    if a.text:
        family.set_north_star(conn, " ".join(a.text))
    ns = family.north_star(conn)
    out(f"⭐ {ns['text'] or '（还没有写。和她一起，一句话就够）'}")
    for h in ns["history"][:3]:
        out(f"   过去（至 {h['until']}）：{h['text']}")


def cmd_place(a, conn):
    if a.action == "add":
        p = family.add_place(conn, " ".join(a.text), a.date)
        out(f"📍 {p['name']}" + (f"（{p['lat']:.2f}, {p['lon']:.2f}）" if p["lat"] else "（没找到坐标，地图上暂时不显示）"))
    else:
        for p in family.places(conn):
            out(f"📍 {p['visited_on'] or ''} {p['name']}")


def cmd_photos(a, conn):
    out(photos.scan(conn))


def cmd_junzi(a, conn):
    c = yi.junzi_card()
    out(f"\n{c['symbol']}  {c['image']}\n\n    {c['act']}\n\n—— {c['plain']}\n")


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
    r = mind.nightly(conn, a.day)
    out(r["summary"] or "这一天没有记忆")
    for x in r["reflections"]:
        out(f"🧠 {x}")


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

    s = sub.add_parser("now", help="此刻：你现在感觉怎么样？给你一个可能性")
    s.add_argument("--feeling", "-f", choices=list(now.FEELINGS))
    s.add_argument("--minutes", "-m", type=int, help="此刻有多少分钟")
    s.add_argument("--decide", action="store_true", help="帮我决定：不随机，直接给最合适的")
    s.add_argument("--place", "-p", choices=list(tianshi.PLACES), help="地利：你现在在哪里")
    s.add_argument("--her", action="store_true", help="她在身边")
    s.set_defaults(fn=cmd_now)

    sub.add_parser("tian", help="天时：此刻的时辰、天光、天气、节气与候、时令之卦").set_defaults(fn=cmd_tian)

    s = sub.add_parser("jushi", help="人生局势：主要矛盾、持久战、能控制的事 / rate 关系=8 Part3=4（自评）")
    s.add_argument("action", nargs="?", choices=["report", "rate"], default="report")
    s.add_argument("args", nargs="*")
    s.add_argument("--ai", action="store_true", help="请 Claude 推演一下（需要 API 或 claude-code 模式）")
    s.set_defaults(fn=cmd_jushi)

    s = sub.add_parser("choose", help="选择分析：lifeos choose \"要不要做大器材生意\" -o 加码 -o 维持")
    s.add_argument("question")
    s.add_argument("-o", "--option", action="append", required=True)
    s.set_defaults(fn=cmd_choose)

    s = sub.add_parser("mingli", help="命理（文化的镜子）：--birth \"1997-05-01 08:30\"")
    s.add_argument("--birth")
    s.set_defaults(fn=cmd_mingli)

    s = sub.add_parser("moments", help="此刻宜的选择库：list / add 标题 --need home --minutes 15 / off key / on key")
    s.add_argument("action", nargs="?", choices=["list", "add", "on", "off"], default="list")
    s.add_argument("args", nargs="*")
    s.add_argument("--need", default="any", choices=list(tianshi.NEED_LABEL))
    s.add_argument("--minutes", type=int, default=15)
    s.set_defaults(fn=cmd_moments)

    sub.add_parser("pocket", help="口袋：装着的杂事，不追你").set_defaults(fn=cmd_pocket)

    s = sub.add_parser("letgo", help="放下一件事")
    s.add_argument("ids", nargs="+", type=int)
    s.set_defaults(fn=cmd_letgo)

    s = sub.add_parser("yi", help="起卦：今日之卦 / --ask 问一事 / history / outcome")
    s.add_argument("action", nargs="?", choices=["today", "history", "outcome", "stats"], default="today")
    s.add_argument("--ask", help="心里犹豫的一件事")
    s.add_argument("--id", type=int)
    s.add_argument("text", nargs="*")
    s.set_defaults(fn=cmd_yi)

    s = sub.add_parser("ai", help="每日梳理（Claude Code 定时任务用）：prepare / apply 文件 / undo / status / improvements / mark")
    s.add_argument("action", nargs="?", choices=["prepare", "apply", "undo", "status", "improvements", "mark"], default="status")
    s.add_argument("file", nargs="?")
    s.add_argument("--id", type=int)
    s.add_argument("--status", choices=["open", "accepted", "declined", "done"], default="accepted")
    s.add_argument("--all", action="store_true")
    s.add_argument("--no-news", action="store_true", help="prepare 时不抓新闻")
    s.set_defaults(fn=cmd_ai)

    sub.add_parser("backup", help="备份数据库到 data/backups/").set_defaults(fn=cmd_backup)

    s = sub.add_parser("mind", help="记忆中枢：list 领悟 / recall 回忆 / about 一件事 / reflect / wrong --id / reindex")
    s.add_argument("action", nargs="?", choices=["list", "recall", "about", "reflect", "wrong", "reindex"], default="list")
    s.add_argument("--id", type=int)
    s.add_argument("--ai", action="store_true", help="reflect 时让 Claude 也想一想")
    s.add_argument("text", nargs="*")
    s.set_defaults(fn=cmd_mind)

    s = sub.add_parser("shi", help="势：天下大势 list / add / fetch / retire")
    s.add_argument("action", nargs="?", choices=["list", "add", "fetch", "retire"], default="list")
    s.add_argument("text", nargs="*")
    s.add_argument("--domain", "-d")
    s.add_argument("--direction", type=int, default=0, choices=[-1, 0, 1], help="1 顺势 / -1 逆势 / 0 观察")
    s.add_argument("--strength", type=int, default=2, choices=range(1, 6))
    s.set_defaults(fn=cmd_shi)

    s = sub.add_parser("horizon", help="盼头：add 标题 --date YYYY-MM-DD / list / live ID 一句话")
    s.add_argument("action", nargs="?", choices=["list", "add", "live"], default="list")
    s.add_argument("text", nargs="*")
    s.add_argument("--date")
    s.add_argument("--alone", action="store_true", help="不是和她一起的")
    s.set_defaults(fn=cmd_horizon)

    s = sub.add_parser("ritual", help="仪式：list / log ID 一句话 / add 名称 --cadence weekly --weekday 7")
    s.add_argument("action", nargs="?", choices=["list", "log", "add"], default="list")
    s.add_argument("text", nargs="*")
    s.add_argument("--cadence", choices=["weekly", "monthly", "yearly"], default="weekly")
    s.add_argument("--weekday", type=int)
    s.add_argument("--month", type=int)
    s.add_argument("--day", type=int)
    s.set_defaults(fn=cmd_ritual)

    s = sub.add_parser("northstar", help="我们的北极星：查看，或写下新的一句")
    s.add_argument("text", nargs="*")
    s.set_defaults(fn=cmd_northstar)

    s = sub.add_parser("place", help="我们去过的地方：add 地名 --date / list")
    s.add_argument("action", nargs="?", choices=["list", "add"], default="list")
    s.add_argument("text", nargs="*")
    s.add_argument("--date")
    s.set_defaults(fn=cmd_place)

    s = sub.add_parser("photos", help="索引照片文件夹（rules.toml [photos]），用于那年今日")
    s.add_argument("action", nargs="?", choices=["scan"], default="scan")
    s.set_defaults(fn=cmd_photos)

    sub.add_parser("junzi", help="君子卡：卡住的时候抽一张").set_defaults(fn=cmd_junzi)

    sub.add_parser("morning", help="早安：今天的节律、有期限的事、一个回响").set_defaults(fn=cmd_morning)
    sub.add_parser("letter", help="一封信：写给这一周的你").set_defaults(fn=cmd_letter)

    s = sub.add_parser("today", help="今天我需要一点结构：展开时间表")
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
    family.seed(conn)
    args.fn(args, conn)
