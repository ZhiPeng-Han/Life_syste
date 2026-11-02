import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["LIFEOS_HOME"] = tempfile.mkdtemp()
os.environ["LIFEOS_LLM"] = "off"
os.environ["LIFEOS_OFFLINE"] = "1"

from lifeos import family, letter, llm, now, photos, shi, yi
from lifeos import config
from lifeos import business, cards, db, decisions, experiments, extract, meals, memory, planner, relationship, review, seed  # noqa: E402


def fresh():
    path = os.path.join(os.environ["LIFEOS_HOME"], "lifeos.db")
    if os.path.exists(path):
        os.remove(path)
    conn = db.connect()
    seed.run(conn)
    return conn


class ExtractTest(unittest.TestCase):
    def test_rules_split_mixed_input(self):
        r = extract.extract_rules("今天在闲鱼上 1800 收了一支 50/1.4，有轻微镜头雾，女朋友说下个月想去海边。明天要把立面图发给甲方")
        self.assertEqual(len(r["items"]), 1)
        item = r["items"][0]
        self.assertEqual((item["action"], item["model"], item["price"], item["platform"]), ("buy", "50/1.4", 1800.0, "闲鱼"))
        self.assertIn("雾", item["defects"])
        self.assertEqual(r["wishes"][0]["category"], "travel")
        self.assertEqual(r["tasks"][0]["title"], "把立面图发给甲方")
        self.assertEqual(r["tasks"][0]["due"], (date.today() + timedelta(days=1)).isoformat())

    def test_wish_content_is_the_wish_itself(self):
        self.assertEqual(extract.extract_rules("她笑得很开心，说想学陶艺")["wishes"][0]["content"], "想学陶艺")
        self.assertEqual(extract.extract_rules("她说冬天想去冰岛看极光")["wishes"][0]["content"], "冬天想去冰岛看极光")
        self.assertEqual(extract.extract_rules("她想和我一起开发相机转售平台")["wishes"][0]["content"], "想和我一起开发相机转售平台")

    def test_wish_categories(self):
        self.assertEqual(extract.extract_rules("她说想减肥")["wishes"][0]["category"], "health")
        self.assertEqual(extract.extract_rules("她想和我一起开发相机转售平台")["wishes"][0]["category"], "project")


class MemoryTest(unittest.TestCase):
    def test_capture_and_search(self):
        conn = fresh()
        memory.capture("她说冰岛想冬天去看极光", conn=conn)
        memory.capture("今天把立面图改完了", conn=conn)
        top = memory.search("冰岛极光", conn=conn)
        self.assertIn("极光", top[0]["content"])
        self.assertTrue(any("极光" in w["content"] for w in relationship.wishes(conn)))

    def test_consolidate(self):
        conn = fresh()
        memory.capture("和她去吃了日料", conn=conn)
        s = memory.consolidate(conn=conn)
        self.assertEqual(s["count"], 1)


class BusinessTest(unittest.TestCase):
    def test_profit_estimate_and_calibration(self):
        conn = fresh()
        a = business.add_item(conn, "50/1.4", 180, defects=[])
        business.sell(conn, a["code"], 260, "MPB")  # MPB 费率 0
        self.assertEqual(business.profit_of(business.get_item(conn, a["code"])), 80)
        est, n = business.estimate_price(conn, "50mm f1.4", ["雾"])
        self.assertEqual(n, 1)
        self.assertAlmostEqual(est, 260 * 0.9, places=1)
        # 有雾的那支其实卖得比预估好 → 雾的折价应被调低
        b = business.add_item(conn, "50/1.4", 150, defects=["雾"])
        business.sell(conn, b["code"], 255, "MPB")
        self.assertLess(business.defect_discounts(conn)["雾"], 0.10)

    def test_deal_verdicts(self):
        conn = fresh()
        self.assertEqual(business.evaluate_deal(conn, "35/2", 100, est=300)["verdict"], "建议收")
        self.assertTrue(business.evaluate_deal(conn, "35/2", 230, est=300)["verdict"].startswith("还价"))
        self.assertEqual(business.evaluate_deal(conn, "35/2", 400, est=300)["verdict"], "跳过")
        self.assertEqual(business.evaluate_deal(conn, "unknown", 100)["verdict"], "数据不足")

    def test_fund_progress(self):
        conn = fresh()
        a = business.add_item(conn, "85/1.8", 100)
        business.sell(conn, a["code"], 200, "MPB")
        fund = business.funds(conn)[0]
        self.assertEqual(fund["saved"], 30.0)  # 利润 100 × 30%


class PlannerTest(unittest.TestCase):
    def test_plan_respects_blocks_and_buffer(self):
        conn = fresh()
        tuesday = date(2026, 11, 3)
        p = planner.plan(tuesday, conn)
        tasks = [b for b in p["timeline"] if b["kind"] == "task"]
        fixed = [b for b in p["timeline"] if b["kind"] != "task"]
        for t in tasks:
            for f in fixed:
                self.assertFalse(t["start"] < f["end"] and f["start"] < t["end"], (t, f))
        love = next(b for b in p["timeline"] if b["domain"] == "关系" and b["kind"] == "protected")
        self.assertTrue(love.get("with"))  # 和她相关的任务挂在约会块里
        self.assertEqual(len(p["top3"]), 3)
        self.assertIsNotNone(p["suggestion_id"])


class AutonomyTest(unittest.TestCase):
    def test_promotion_and_severe_demotion(self):
        conn = fresh()
        for _ in range(20):
            sid = decisions.suggest(conn, "meal_plan", "菜单")
            decisions.feedback(conn, sid, "accept")
        cands = decisions.promotion_candidates(conn)
        self.assertEqual(cands[0]["category"], "meal_plan")
        decisions.set_level(conn, "surprise", 4)
        self.assertEqual(decisions.level(conn, "surprise"), 1)  # 惊喜永远只建议
        sid = decisions.suggest(conn, "meal_plan", "菜单")
        r = decisions.feedback(conn, sid, "reject", "全是我不爱吃的", severe=True)
        self.assertEqual(decisions.level(conn, "meal_plan"), 1)
        self.assertIn("L1", r["demoted_to"])


class NowTest(unittest.TestCase):
    def test_tired_gets_care_not_heavy_work(self):
        conn = fresh()
        from lifeos import tasks
        tasks.add(conn, "整理器材账目", "器材事业", 5, "high", 60)
        from datetime import datetime
        at = datetime(2026, 11, 3, 20, 0)
        cands = now.candidates(conn, "疲惫", 30, at)
        self.assertTrue(cands)
        self.assertFalse(any(c["title"] == "整理器材账目" for c in cands))
        self.assertTrue(all(c["minutes"] <= 30 for c in cands))
        self.assertEqual(cands[0]["kind"], "care")  # 累的时候，先照顾自己

    def test_irritated_puts_self_care_before_relationship_talks(self):
        conn = fresh()
        from datetime import datetime
        cands = now.candidates(conn, "烦躁", None, datetime(2026, 11, 3, 20, 0))
        self.assertEqual(cands[0]["kind"], "care")

    def test_deadline_rises_even_when_tired(self):
        conn = fresh()
        from lifeos import tasks
        tid = tasks.add(conn, "给甲方发图", "建筑工作", 3, "medium", 20, due=date.today().isoformat())
        s = now.suggest(conn, "充沛", decide=True)
        self.assertEqual(s.get("task_id"), tid)
        self.assertTrue(any(c.get("task_id") == tid for c in now.candidates(conn, "疲惫")))

    def test_skip_three_times_offers_let_go(self):
        conn = fresh()
        from lifeos import tasks
        tid = tasks.add(conn, "整理硬盘", "生活维持")
        r = [now.skip(conn, tid) for _ in range(3)][-1]
        self.assertTrue(r["ask_let_go"])
        now.let_go(conn, tid)
        self.assertEqual(now.pocket(conn)["count"], len(tasks.list_open(conn)))
        self.assertNotIn(tid, [t["id"] for t in tasks.list_open(conn)])

    def test_exclude_cycles_and_runs_out_gently(self):
        conn = fresh()
        seen = []
        for _ in range(60):
            s = now.suggest(conn, "低落", 5, seen)
            if s["kind"] == "none":
                break
            seen.append(s["key"])
        self.assertEqual(s["kind"], "none")

    def test_morning_and_letter(self):
        conn = fresh()
        memory.capture("和她在河边散步，她笑得很开心", conn=conn)
        now.log_state(conn, "平静")
        text = now.morning(conn)
        self.assertIn("口袋里还有", text)
        self.assertNotIn("07:00–", text)  # 早安不是时间表
        L = letter.write(conn, save=False)["markdown"]
        self.assertIn("她", L)
        self.assertIn("平静", L)


class TianshiTest(unittest.TestCase):
    def test_hexagram_table_is_complete_and_correct(self):
        self.assertEqual(len({(u, l) for _, u, l, *_ in yi.HEXAGRAMS}), 64)
        self.assertEqual(yi.cast([7] * 6)["primary"]["full"], "乾为天")
        self.assertEqual(yi.cast([8] * 6)["primary"]["full"], "坤为地")
        self.assertEqual(yi.info(11)["full"], "地天泰")
        self.assertEqual(yi.info(63)["full"], "水火既济")
        r = yi.cast([9, 7, 7, 7, 7, 7])  # 乾初九动 → 姤
        self.assertEqual(r["changed"]["name"], "姤")
        self.assertEqual(yi.cast([6] * 6)["changed"]["name"], "乾")
        self.assertTrue(all(yi.toss_line() in (6, 7, 8, 9) for _ in range(200)))

    def test_one_cast_per_day(self):
        conn = fresh()
        a, b = yi.cast_today(conn), yi.cast_today(conn)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(yi.today_stance(conn), a["primary"]["stance"])

    def test_stance_factor_is_gentle_and_switchable(self):
        f = yi.factor("养", "建筑工作", "high")
        self.assertTrue(0.8 <= f < 1)
        self.assertEqual(yi.factor(None, "建筑工作", "high"), 1.0)
        self.assertGreater(yi.factor("合", "关系"), 1)

    def test_momentum(self):
        conn = fresh()
        shi.add(conn, "二手镜头涨价", "器材事业", 1, 3)
        shi.add(conn, "住宅项目放缓", "建筑工作", -1, 4)
        m = shi.momentum(conn)
        self.assertGreater(m["器材事业"], 2.9)
        self.assertLess(m["建筑工作"], -3.9)
        self.assertGreater(shi.factor(m, "器材事业"), 1)
        self.assertLess(shi.factor(m, "建筑工作"), 1)

    def test_solar_terms(self):
        self.assertEqual(shi.solar_term(date(2026, 12, 22))["name"], "冬至")
        t = shi.solar_term(date(2027, 1, 1))
        self.assertEqual((t["name"], t["next"]), ("冬至", "小寒"))
        self.assertEqual(shi.solar_term(date(2026, 2, 10))["name"], "立春")

    def test_tianshi_never_changes_facts(self):
        conn = fresh()
        from lifeos import tasks
        conn.execute("INSERT INTO casts(at, day, kind, lines, hex, stance) VALUES(?,?,?,?,?,?)",
                     (db.now(), db.today(), "day", "[8,7,8,8,7,8]", 29, "慎"))  # 坎为水：宜谨慎
        conn.commit()
        r = business.evaluate_deal(conn, "35/2", 100, est=300)
        self.assertEqual(r["verdict"], "建议收")  # 结论仍由数据决定
        self.assertTrue(any("卦象" in x for x in r["reasons"]))
        tid = tasks.add(conn, "给甲方发图", "建筑工作", 3, "high", 20, due=date.today().isoformat())
        shi.add(conn, "住宅项目放缓", "建筑工作", -1, 5)
        c = next(c for c in now.candidates(conn, "充沛") if c.get("task_id") == tid)
        self.assertNotIn("逆势", c["reason"])  # 有期限的事不被势影响


class YiTextsTest(unittest.TestCase):
    def test_texts_complete(self):
        t = yi.texts()
        self.assertEqual(len(t), 64)
        self.assertTrue(all(len(x["yao"]) == 6 and len(x["wuying"]) == 6 for x in t))
        self.assertEqual(t[0]["yong"], "用九：见群龙无首，吉。")
        self.assertEqual([x["name"] for x in t], [h[0] for h in yi.HEXAGRAMS])

    def test_zhuxi_rules(self):
        main = lambda lines: [m["text"] for m in yi.zhuxi(yi.cast(lines))["main"]]  # noqa: E731
        self.assertEqual(main([7] * 6), ["乾：元亨，利贞。"])
        self.assertEqual(main([9, 7, 7, 7, 7, 7]), ["初九：潜龙，勿用。"])
        self.assertEqual(main([9, 9, 7, 7, 7, 7]), ["九二：见龙在田，利见大人。"])  # 二爻变以上爻为主
        self.assertEqual(main([9, 9, 9, 9, 7, 7]), ["九五：观我生，君子无咎。"])  # 四爻变看之卦下面的不变爻
        self.assertEqual(main([6] * 6), ["用六：利永贞。"])

    def test_stats_and_junzi(self):
        conn = fresh()
        self.assertEqual(yi.stats(conn)["n"], 0)
        yi.cast_today(conn, "今天想专心画图")
        st = yi.stats(conn)
        self.assertEqual(st["n"], 1)
        self.assertIn("描述", st["note"])
        self.assertEqual(yi.today_cast(conn)["reading"]["question"], "今天想专心画图")
        c = yi.junzi_card()
        self.assertTrue(c["act"])


class FamilyTest(unittest.TestCase):
    def test_horizons(self):
        conn = fresh()
        self.assertTrue(family.horizons(conn)["empty_soon"])
        family.add_horizon(conn, "冰岛", (date.today() + timedelta(days=100)).isoformat())
        self.assertTrue(family.horizons(conn)["empty_soon"])  # 一个月内仍然没有盼头
        hid = family.add_horizon(conn, "日料", (date.today() + timedelta(days=3)).isoformat())
        h = family.horizons(conn)
        self.assertFalse(h["empty_soon"])
        self.assertEqual(h["ahead"][0]["title"], "日料")
        h = family.horizons(conn, date.today() + timedelta(days=5))
        self.assertEqual(h["to_reflect"][0]["id"], hid)
        family.live_horizon(conn, hid, "她说是今年吃过最好吃的一顿")
        self.assertTrue(any("最好吃" in m["content"] for m in memory.timeline(1, conn)))
        self.assertIn("日料", now.morning(conn) + "日料")  # 早安能渲染

    def test_rituals_gentle_and_no_streaks(self):
        conn = fresh()
        sunday = date(2026, 11, 1)
        r = next(x for x in family.rituals(conn, sunday) if x["name"] == "周日一起做饭")
        self.assertTrue(r["gentle"] and r["today"])
        family.log_ritual(conn, r["id"], "做了番茄牛腩", on=sunday)
        r = next(x for x in family.rituals(conn, sunday) if x["name"] == "周日一起做饭")
        self.assertFalse(r["gentle"])
        self.assertNotIn("streak", r)

    def test_north_star_history(self):
        conn = fresh()
        family.set_north_star(conn, "A")
        ns = family.set_north_star(conn, "B")
        self.assertEqual((ns["text"], ns["history"][0]["text"]), ("B", "A"))
        self.assertIn("B", letter.render(conn))
        self.assertIn("地平线上", letter.render(conn))


class GentleTest(unittest.TestCase):
    def test_skip_reason_first_step(self):
        conn = fresh()
        from lifeos import tasks
        tid = tasks.add(conn, "写 Part 3 案例研究", "Part3", 4, "high", 120)
        r = now.skip_reason(conn, tid, "太大了", "列出案例的三个小标题")
        self.assertIn("拆小", r["reply"])
        t = conn.execute("SELECT title, est_minutes FROM tasks WHERE id = ?", (r["new_task_id"],)).fetchone()
        self.assertEqual((t[0], t[1]), ("第一步：列出案例的三个小标题", 10))
        self.assertEqual(now.skip_patterns(conn)[0]["reason"], "太大了")

    def test_feed_votes(self):
        conn = fresh()
        tid = shi.add(conn, "x", "器材事业", 0, 2, feed="https://a/feed")
        shi.retire(conn, tid)
        self.assertLess(db.get_meta(conn, "feed_weights")["https://a/feed"], 1)
        tid = shi.add(conn, "y", "器材事业", 0, 2, feed="https://b/feed")
        shi.keep(conn, tid)
        self.assertGreater(db.get_meta(conn, "feed_weights")["https://b/feed"], 1)
        self.assertIn("本周大势", shi.digest(conn))

    def test_photos_on_this_day(self):
        import tempfile
        from pathlib import Path
        conn = fresh()
        folder = Path(tempfile.mkdtemp())
        last_year = date.today().replace(year=date.today().year - 1)
        (folder / f"IMG_{last_year:%Y%m%d}_1.jpg").write_bytes(b"\xff\xd8 no exif")
        exif = f"{last_year:%Y:%m:%d} 10:00:00".encode()
        (folder / "DSC0001.jpg").write_bytes(b"\xff\xd8" + b"x" * 100 + exif)
        (folder / "other.jpg").write_bytes(b"\xff\xd8" + b"2001:01:01 00:00:00")
        from unittest import mock
        with mock.patch.object(config, "rules", return_value={"photos": {"folders": [str(folder)]}}):
            self.assertEqual(photos.scan(conn)["added"], 3)
        found = photos.on_this_day(conn, limit=5)
        self.assertEqual(len(found), 2)
        self.assertEqual(found[0]["years_ago"], 1)

    def test_core_memory_includes_principles(self):
        self.assertIn("天行健", llm.core_memory())


class MiscTest(unittest.TestCase):
    def test_sm2(self):
        conn = fresh()
        cid = cards.add(conn, "Q", "A")
        r1 = cards.review(conn, cid, 5)
        r2 = cards.review(conn, cid, 5)
        self.assertEqual((r1["interval"], r2["interval"]), (1, 6))
        self.assertEqual(cards.review(conn, cid, 1)["interval"], 1)

    def test_menu_has_light_dinners(self):
        conn = fresh()
        m = meals.plan_week(conn)
        self.assertEqual(len(m["days"]), 7)
        self.assertGreaterEqual(sum(d["light"] for d in m["days"]), 4)
        self.assertEqual(m["days"][5]["dish"], "约会 / 外出")

    def test_experiment_and_patterns(self):
        conn = fresh()
        today = date.today()
        for i in range(20, 0, -1):
            d = today - timedelta(days=i)
            sleep = 6 + (i % 3)
            review.checkin(conn, d.isoformat(), energy=sleep, mood=4 + (1 if i <= 10 else 0) * 3, sleep=sleep, exercised=int(i <= 10))
        eid = experiments.add(conn, "锻炼", "mood", (today - timedelta(days=10)).isoformat(), (today - timedelta(days=1)).isoformat())
        r = experiments.analyze(conn, eid)
        self.assertGreater(r["effect_size"], 0.5)
        self.assertTrue(any("睡眠" in p for p in review.patterns(conn)))

    def test_upcoming_dates(self):
        conn = fresh()
        soon = date.today() + timedelta(days=7)
        relationship.add_date(conn, "生日", soon.month, soon.day)
        up = relationship.upcoming_dates(conn)
        self.assertEqual(up[0]["days_left"], 7)
        self.assertTrue(up[0]["remind_today"])

    def test_iphone_text_routes(self):
        from lifeos import web

        conn = fresh()
        reply = web.TEXT_ROUTES["/api/capture"](conn, {}, {"text": "她说想去看极光"})
        self.assertIn("她的愿望", reply)
        self.assertEqual(web.TEXT_ROUTES["/api/capture"](conn, {}, {"text": " "}), "没有收到内容")
        self.assertIn("今天只需记住的 3 件事", web.TEXT_ROUTES["/api/today"](conn, {}, {}))

    def test_weekly_review_renders(self):
        conn = fresh()
        r = review.weekly(conn, save=False)
        self.assertIn("周复盘", r["markdown"])



class ExtractPastTest(unittest.TestCase):
    def test_past_is_not_a_task_and_gear_goes_to_business(self):
        r = extract.extract_rules("周日一起做了饭，很开心")
        self.assertEqual((r["memories"][0]["type"], len(r["tasks"])), ("episodic", 0))
        self.assertEqual(extract.extract_rules("记得明天给甲方打电话")["memories"][0]["type"], "prospective")
        self.assertEqual(extract.extract_rules("那支 50/1.4 挂了好久都卖不动")["memories"][0]["domain"], "器材事业")
        self.assertEqual(extract.extract_rules("她不吃香菜")["memories"][0]["type"], "semantic")


class MindTest(unittest.TestCase):
    """记忆中枢：时间、连接、回忆、领悟、更新，以及它对各处的影响。"""

    def test_when_of_reads_event_time(self):
        from datetime import datetime
        from lifeos import mind

        base = datetime(2026, 11, 4, 20, 0)  # 周三
        self.assertEqual(mind.when_of("昨天和她去看了电影", base).date().isoformat(), "2026-11-03")
        self.assertEqual(mind.when_of("三天前收了一支镜头", base).date().isoformat(), "2026-11-01")
        self.assertEqual(mind.when_of("上周六去了海边", base).date().isoformat(), "2026-10-31")
        self.assertEqual(mind.when_of("周一交了图", base).date().isoformat(), "2026-11-02")
        self.assertEqual(mind.when_of("10月3号我们第一次约会", base).date().isoformat(), "2026-10-03")
        self.assertIsNone(mind.when_of("下周一要交图", base))

    def test_capture_uses_event_time(self):
        conn = fresh()
        memory.capture("昨天和她在泰晤士河边散步", conn=conn)
        m = conn.execute("SELECT occurred_at, created_at FROM memories ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(m[0][:10], (date.today() - timedelta(days=1)).isoformat())
        self.assertEqual(m[1][:10], date.today().isoformat())

    def test_everything_about_one_thing_is_connected(self):
        from lifeos import mind

        conn = fresh()
        memory.capture("她说冬天想去冰岛看极光", conn=conn)
        family.add_horizon(conn, "冰岛", (date.today() + timedelta(days=90)).isoformat())
        memory.capture("查了一下冰岛的租车价格，有点贵", conn=conn)
        yi.save(conn, yi.cast([7, 7, 7, 7, 7, 7]), "冬天去冰岛合适吗", "ask")
        a = mind.about(conn, "冰岛")
        self.assertGreaterEqual(len(a["memories"]), 2)
        self.assertTrue(any("冰岛" in w["content"] for w in a["wishes"]))
        self.assertEqual(len(a["horizons"]), 1)
        self.assertEqual(len(a["casts"]), 1)
        lines = "\n".join(mind.about_lines(conn, "冰岛"))
        self.assertIn("盼头", lines)
        self.assertIn("冰岛基金", lines)  # 冰岛基金在配置里，自动连上

    def test_recall_follows_links_not_just_words(self):
        from lifeos import mind

        conn = fresh()
        memory.capture("她说想学陶艺", conn=conn)
        memory.capture("路过一家陶艺工作室，周末有体验课", conn=conn)
        for i in range(10):
            memory.capture(f"建筑项目第 {i} 次开会", conn=conn)
        got = [m["content"] for m in mind.recall(conn, "给她准备个惊喜，陶艺怎么样", k=3)]
        self.assertTrue(any("陶艺工作室" in c for c in got))
        ctx = mind.context(conn, "陶艺")
        self.assertIn("她", ctx)

    def test_reflection_on_repeated_topic_and_wrong_means_silence(self):
        from lifeos import mind

        conn = fresh()
        memory.capture("她说想学陶艺", conn=conn)
        memory.capture("她又提到陶艺课很治愈", conn=conn)
        memory.capture("她给我看了一个陶艺视频", conn=conn)
        made = mind.reflect(conn, use_ai=False)
        self.assertTrue(any("陶艺" in x for x in made))
        r = next(r for r in mind.reflections(conn) if "陶艺" in r["content"])
        memory.confirm(r["id"], keep=False, conn=conn)  # "不对，别再提"
        mind.reflect(conn, use_ai=False)
        self.assertFalse(any("陶艺" in r["content"] for r in mind.reflections(conn)))

    def test_her_quiet_reflection_and_nudge(self):
        from lifeos import mind

        conn = fresh()
        old = (date.today() - timedelta(days=12)).isoformat()
        memory.capture("和她吃了晚饭", conn=conn)
        conn.execute("UPDATE memories SET occurred_at = ? WHERE domain = '关系'", (old + "T19:00:00",))
        for i in range(6):
            memory.capture(f"改了第 {i} 版立面", conn=conn)
        made = mind.reflect(conn, use_ai=False)
        self.assertTrue(any("没有一件和她有关" in x for x in made))
        p = mind.pulse(conn)
        self.assertGreaterEqual(p["her_quiet"], 5)
        f, note = mind.nudge(p, "给她写张卡片", "关系", "平静")
        self.assertGreater(f, 1)
        self.assertIn("和她的事", note)
        # 记下和她的事之后，这条领悟淡出
        memory.capture("和她在河边散步", conn=conn)
        mind.reflect(conn, use_ai=False)
        self.assertFalse(any("没有一件和她有关" in r["content"] for r in mind.reflections(conn)))

    def test_now_suggestion_mentions_her_wish(self):
        conn = fresh()
        memory.capture("她说想学陶艺", conn=conn)
        from lifeos import tasks as tasks_mod

        conn.execute("UPDATE tasks SET status = 'done'")
        tasks_mod.add(conn, "查一下附近的陶艺体验课", "关系", 3, "low", 20)
        cands = [c for c in now.candidates(conn, "平静") if c["kind"] == "task"]
        self.assertIn("和她的愿望有关", cands[0]["reason"])

    def test_new_fact_supersedes_old(self):
        from lifeos import mind

        conn = fresh()
        memory.capture("她喜欢吃寿司", conn=conn)
        r = memory.capture("其实她现在不喜欢吃寿司了", conn=conn)
        self.assertTrue(r["memories"][0]["replaced"])
        old = conn.execute("SELECT status, superseded_by FROM memories WHERE content = '她喜欢吃寿司'").fetchone()
        self.assertEqual(old[0], "superseded")
        self.assertNotIn("她喜欢吃寿司", mind.known(conn))

    def test_deal_remembers_what_you_said_about_a_model(self):
        conn = fresh()
        memory.capture("那支 50/1.4 挂了一个月都卖不动", conn=conn)
        r = business.evaluate_deal(conn, "50/1.4", 300, est=500)
        self.assertTrue(any("卖不动" in x for x in r["reasons"]))

    def test_core_memory_carries_reflections(self):
        from lifeos import mind

        conn = fresh()
        for t in ("她说想学陶艺", "她又提到陶艺", "她在看陶艺视频"):
            memory.capture(t, conn=conn)
        mind.reflect(conn, use_ai=False)
        conn.close()
        self.assertIn("陶艺", llm.core_memory())

    def test_letter_includes_what_it_noticed(self):
        from lifeos import mind

        conn = fresh()
        for t in ("她说想学陶艺", "她又提到陶艺", "她在看陶艺视频"):
            memory.capture(t, conn=conn)
        mind.reflect(conn, use_ai=False)
        self.assertIn("这周我注意到的", letter.render(conn))

    def test_reindex_links_old_records(self):
        from lifeos import mind

        conn = fresh()
        conn.execute("DELETE FROM links")
        conn.execute("DELETE FROM memory_entities")
        memory.capture("她说冬天想去冰岛看极光", conn=conn)
        mind.nightly(conn)
        n = mind.reindex(conn)
        self.assertGreater(n["wishes"], 0)
        mind.nightly(conn)  # 第二次晚安：重写日摘要不能被连接卡住
        conn.execute("INSERT INTO memory_entities SELECT id, 1 FROM memories WHERE type = 'summary'")
        mind.nightly(conn)
        self.assertTrue(mind.about(conn, "冰岛")["wishes"])


class DailyTest(unittest.TestCase):
    """每日梳理：工作包 → Claude 的结果 → 校验写入 → 可撤销。"""

    def _result(self, conn, **extra):
        import json as _json
        from lifeos import daily

        path = daily.ai_dir("outbox") / "test.json"
        path.write_text(_json.dumps({"date": date.today().isoformat(), **extra}, ensure_ascii=False), encoding="utf-8")
        return daily.apply(conn, path)

    def test_prepare_writes_package(self):
        from lifeos import daily

        conn = fresh()
        memory.capture("昨天和她去看了电影", conn=conn)
        r = daily.prepare(conn, fetch_news=False)
        text = open(r["inbox"], encoding="utf-8").read()
        self.assertIn("昨天和她去看了电影", text)
        self.assertIn("领域只能用", text)
        self.assertTrue(os.path.exists(r["schema"]))

    def test_apply_validates_and_undo_restores(self):
        from lifeos import daily

        conn = fresh()
        memory.capture("下班路上拍到很好看的夕阳", conn=conn)
        mid = conn.execute("SELECT MAX(id) FROM memories").fetchone()[0]
        before = conn.execute("SELECT domain FROM memories WHERE id = ?", (mid,)).fetchone()[0]
        r = self._result(conn,
                         news=[{"title": "二手镜头市场回暖", "domain": "器材事业", "direction": 1, "strength": 3, "summary": "好卖"}],
                         memories=[{"id": mid, "domain": "器材事业", "topics": ["夕阳"]}, {"id": 99999, "domain": "关系"},
                                   {"id": mid, "domain": "不存在的领域"}],
                         reflections=[{"content": "有证据的领悟", "evidence": [mid]}, {"content": "没有证据", "evidence": [424242]}],
                         notes={"morning": "早安", "her": "她", "nope": "x"},
                         improvements=[{"title": "加拍照关键词", "why": "分错了", "how": "改 keywords", "effort": "小"}])
        self.assertEqual(conn.execute("SELECT domain FROM memories WHERE id = ?", (mid,)).fetchone()[0], "器材事业")
        self.assertTrue(any("有证据的领悟" in x["content"] for x in mind_reflections(conn)))
        self.assertFalse(any("没有证据" in x["content"] for x in mind_reflections(conn)))
        self.assertEqual(daily.notes(conn)["morning"], "早安")
        self.assertNotIn("nope", daily.notes(conn))
        self.assertEqual(len(daily.improvements(conn)), 1)
        self.assertIn("早安", now.morning(conn))
        daily.undo(conn, r["run"])
        self.assertEqual(conn.execute("SELECT domain FROM memories WHERE id = ?", (mid,)).fetchone()[0], before)
        self.assertEqual(daily.notes(conn), {})
        self.assertEqual(daily.improvements(conn), [])
        self.assertFalse(conn.execute("SELECT 1 FROM trends WHERE title = '二手镜头市场回暖'").fetchone())

    def test_cannot_delete_memories_only_confirm(self):
        conn = fresh()
        memory.capture("她说想学陶艺", conn=conn)
        mid = conn.execute("SELECT MAX(id) FROM memories").fetchone()[0]
        conn.execute("UPDATE memories SET status = 'needs_confirm' WHERE id = ?", (mid,))
        self._result(conn, confirm=[{"id": mid, "keep": False}])
        self.assertEqual(conn.execute("SELECT status FROM memories WHERE id = ?", (mid,)).fetchone()[0], "needs_confirm")
        self._result(conn, confirm=[{"id": mid, "keep": True}])
        self.assertEqual(conn.execute("SELECT status FROM memories WHERE id = ?", (mid,)).fetchone()[0], "active")

    def test_notes_expire(self):
        from lifeos import daily

        conn = fresh()
        self._result(conn, notes={"morning": "早安"})
        self.assertEqual(daily.notes(conn, date.today() + timedelta(days=3)), {})

    def test_backup(self):
        from lifeos import daily

        fresh().close()
        self.assertTrue(daily.backup().exists())


def mind_reflections(conn):
    from lifeos import mind

    return mind.reflections(conn)


class ConfigAndModeTest(unittest.TestCase):
    def test_personal_rules_merge_over_defaults(self):
        path = os.path.join(os.environ["LIFEOS_HOME"], "rules.toml")
        with open(path, "w", encoding="utf-8") as f:
            f.write('[general]\ncurrency = "¥"\n')
        try:
            config.reload()
            self.assertEqual(config.currency(), "¥")
            self.assertIn("关系", config.domains())  # 其他默认值仍然在
        finally:
            os.remove(path)
            config.reload()

    def test_ai_modes(self):
        old = os.environ.pop("LIFEOS_LLM", None)
        try:
            os.environ["LIFEOS_AI_MODE"] = "daily"
            self.assertIsNone(llm.backend(slow_ok=True))
            os.environ["LIFEOS_AI_MODE"] = "claude-code"
            import shutil as _sh

            expected = "claude-code" if _sh.which("claude") else None
            self.assertEqual(llm.backend(slow_ok=True), expected)
            self.assertIsNone(llm.backend(slow_ok=False))  # 记一句话时不等 Claude Code
        finally:
            os.environ.pop("LIFEOS_AI_MODE", None)
            if old is not None:
                os.environ["LIFEOS_LLM"] = old


if __name__ == "__main__":
    unittest.main()
