import os
import tempfile
import unittest
from datetime import date, timedelta

os.environ["LIFEOS_HOME"] = tempfile.mkdtemp()
os.environ["LIFEOS_LLM"] = "off"

from lifeos import letter, now
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


if __name__ == "__main__":
    unittest.main()
