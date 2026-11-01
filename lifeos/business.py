"""器材事业：库存流水线、捡漏评估、利润与周转、瑕疵折价自学习。"""

import json
import re
import statistics
from datetime import date

from . import config, db, shi, yi

STATUSES = ["待检测", "待拍照", "在售", "已售", "已发货", "完结"]
SOLD = ("已售", "已发货", "完结")


def _cfg() -> dict:
    return config.rules().get("business", {})


def normalize_model(model: str) -> str:
    m = model.lower().replace("mm", "").replace("f/", "/").replace("f", "/")
    return re.sub(r"[\s\-_]", "", m)


def fee_rate(platform: str | None) -> float:
    fees = _cfg().get("platform_fee", {})
    return fees.get(platform or "其他", fees.get("其他", 0.05))


def defect_discounts(conn) -> dict:
    """配置中的初始折价 + 用真实成交校准后的值（存于 meta）。"""
    base = dict(_cfg().get("defect_discount", {}))
    base.update(db.get_meta(conn, "defect_discount", {}))
    return base


def _discount(conn, defects: list[str]) -> float:
    table = defect_discounts(conn)
    keep = 1.0
    for d in defects:
        keep *= 1 - table.get(d, 0.05)
    return 1 - keep


def estimate_price(conn, model: str, defects: list[str] | None = None) -> tuple[float | None, int]:
    """用你自己的历史成交估价：同型号成交价先还原成"无瑕疵价"，取中位数，再按当前瑕疵折价。"""
    key = normalize_model(model)
    sold = db.rows(conn.execute(f"SELECT * FROM items WHERE status IN {SOLD} AND sell_price IS NOT NULL"))
    clean = []
    for it in sold:
        if normalize_model(it["model"]) == key:
            d = _discount(conn, json.loads(it["defects"] or "[]"))
            clean.append(it["sell_price"] / max(1 - d, 0.1))
    if not clean:
        return None, 0
    return round(statistics.median(clean) * (1 - _discount(conn, defects or [])), 2), len(clean)


def _next_code(conn) -> str:
    year = date.today().year
    n = conn.execute("SELECT COUNT(*) FROM items WHERE code LIKE ?", (f"L-{year}-%",)).fetchone()[0]
    return f"L-{year}-{n + 1:03d}"


def add_item(conn, model, buy_price, platform=None, defects=None, condition=None, serial=None, est_price=None) -> dict:
    defects = defects or []
    if est_price is None:
        est_price, _ = estimate_price(conn, model, defects)
    code = _next_code(conn)
    row_id = conn.execute(
        """INSERT INTO items(code, model, serial, condition, defects, buy_price, buy_platform, bought_at, est_price)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (code, model, serial, condition, json.dumps(defects, ensure_ascii=False), buy_price, platform, db.today(), est_price),
    ).lastrowid
    from . import mind

    mind.link_item(conn, row_id, model)
    item_id = db.entity(conn, "item", code, {"model": model})
    db.relate(conn, item_id, db.entity(conn, "domain", "器材事业"), "related", bump=0.5)
    conn.commit()
    return get_item(conn, code)


def get_item(conn, code: str) -> dict | None:
    row = conn.execute("SELECT * FROM items WHERE code = ?", (code,)).fetchone()
    return dict(row) if row else None


def update_item(conn, code: str, **fields) -> dict | None:
    allowed = {"status", "list_price", "extra_costs", "hours_spent", "notes", "condition", "serial", "est_price"}
    fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if fields.get("status") == "在售":
        fields.setdefault("listed_at", db.today())
    if not fields:
        return get_item(conn, code)
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE items SET {sets} WHERE code = ?", (*fields.values(), code))
    conn.commit()
    return get_item(conn, code)


def sell(conn, code: str, price: float, platform: str | None = None, hours: float | None = None) -> dict | None:
    item = get_item(conn, code)
    if not item:
        return None
    conn.execute(
        "UPDATE items SET status = '已售', sell_price = ?, sell_platform = ?, sold_at = ?, hours_spent = COALESCE(?, hours_spent) WHERE code = ?",
        (price, platform, db.today(), hours, code),
    )
    conn.commit()
    calibrate_defects(conn)
    return get_item(conn, code)


def sell_by_model(conn, model: str, price: float, platform: str | None = None) -> dict | None:
    key = normalize_model(model)
    for it in db.rows(conn.execute(f"SELECT * FROM items WHERE status NOT IN {SOLD} ORDER BY bought_at")):
        if normalize_model(it["model"]) == key:
            return sell(conn, it["code"], price, platform)
    return None


def profit_of(item: dict) -> float | None:
    if item.get("sell_price") is None:
        return None
    fee = item["sell_price"] * fee_rate(item.get("sell_platform"))
    return round(item["sell_price"] - (item["buy_price"] or 0) - (item["extra_costs"] or 0) - fee, 2)


def evaluate_deal(conn, model: str, price: float, defects=None, platform=None, est=None) -> dict:
    """捡漏收购决策：期望利润 = 预估售价 − 收购价 − 平台费 − 清洁维修 − 时间成本。"""
    cfg = _cfg()
    defects = defects or []
    samples = 0
    if est is None:
        est, samples = estimate_price(conn, model, defects)
    if est is None:
        return {"verdict": "数据不足", "reasons": [f"你还没有卖过 {model}，请用 --est 手动给出预估售价，系统会记住这次判断。"]}
    fee = est * fee_rate(platform)
    time_cost = cfg.get("default_hours_per_item", 1.5) * cfg.get("hour_value", 15)
    profit = round(est - price - fee - time_cost, 2)
    ratio = profit / price if price else 0
    reasons = [
        f"预估售价 {est:.0f}（{'基于你 ' + str(samples) + ' 次同型号成交' if samples else '手动输入'}，已按瑕疵 {defects or '无'} 折价）",
        f"平台费 {fee:.0f}，时间成本 {time_cost:.0f}",
        f"期望利润 {profit:.0f}（利润率 {ratio:.0%}）",
    ]
    inv_value = conn.execute(f"SELECT COALESCE(SUM(buy_price), 0) FROM items WHERE status NOT IN {SOLD}").fetchone()[0]
    over_cap = inv_value + price > cfg.get("max_inventory_value", 1e9)
    if over_cap:
        reasons.append(f"⚠️ 库存占用将达 {inv_value + price:.0f}，超过上限 {cfg.get('max_inventory_value')}")
    good = profit >= cfg.get("min_profit_abs", 0) and ratio >= cfg.get("min_profit_ratio", 0)
    if good and not over_cap:
        verdict = "建议收"
    elif profit > 0:
        # 反推满足两条门槛的最高收购价：利润 ≥ 绝对下限 且 利润/收购价 ≥ 比例下限
        net = est - fee - time_cost
        target = min(net - cfg.get("min_profit_abs", 0), net / (1 + cfg.get("min_profit_ratio", 0)))
        verdict = f"还价到 {max(target, 0):.0f} 以下再收"
    else:
        verdict = "跳过"
    stance = yi.today_stance(conn)
    if stance and yi.STANCES[stance].get("deal") and verdict != "跳过":
        reasons.append(f"☯ 今日卦象{yi.STANCES[stance]['desc']}：数据之外，问问自己是不是有点急。结论仍以数据为准。")
    from . import mind

    # 记忆：你以前对这个型号说过什么（只提醒，不改变结论）
    seen = [m for m in mind.about(conn, normalize_model(model))["memories"] if m["type"] != "reflection"][:2]
    for m in seen:
        reasons.append(f"🧠 你记过（{m['occurred_at'][:10]}）：{m['content']}")
    mom = shi.momentum(conn).get("器材事业", 0)
    if mom <= -1.5:
        reasons.append("🌏 器材市场近期逆势：宜快进快出，少压库存。")
    elif mom >= 1.5:
        reasons.append("🌏 器材市场近期顺势。")
    return {"verdict": verdict, "expected_profit": profit, "est_price": est, "ratio": round(ratio, 3), "reasons": reasons}


def calibrate_defects(conn, alpha: float = 0.3) -> dict:
    """自学习：用"实际成交价 / 收购时预估价"的偏差修正各瑕疵的折价率（指数滑动平均）。"""
    table = defect_discounts(conn)
    learned = db.get_meta(conn, "defect_discount", {})
    done = set(db.get_meta(conn, "calibrated_items", []))
    for it in db.rows(conn.execute(f"SELECT * FROM items WHERE status IN {SOLD} AND est_price IS NOT NULL")):
        defects = json.loads(it["defects"] or "[]")
        if it["code"] in done or not defects or not it["sell_price"]:
            continue
        err = it["sell_price"] / it["est_price"]  # >1 说明折价估多了
        per = err ** (1 / len(defects))
        for d in defects:
            old = table.get(d, 0.05)
            observed = min(max(1 - (1 - old) * per, 0), 0.6)
            learned[d] = round((1 - alpha) * old + alpha * observed, 4)
            table[d] = learned[d]
        done.add(it["code"])
    db.set_meta(conn, "defect_discount", learned)
    db.set_meta(conn, "calibrated_items", sorted(done))
    return learned


def stats(conn) -> dict:
    items = db.rows(conn.execute("SELECT * FROM items"))
    sold = [i for i in items if i["status"] in SOLD and i["sell_price"] is not None]
    stock = [i for i in items if i["status"] not in SOLD]
    cfg = _cfg()
    profit = sum(profit_of(i) for i in sold)
    hours = sum(i["hours_spent"] or cfg.get("default_hours_per_item", 1.5) for i in sold)
    turnover = [
        (date.fromisoformat(i["sold_at"]) - date.fromisoformat(i["bought_at"])).days
        for i in sold
        if i["sold_at"] and i["bought_at"]
    ]
    today = date.today()
    stale = [
        i for i in stock
        if i["status"] == "在售" and i["listed_at"]
        and (today - date.fromisoformat(i["listed_at"])).days > cfg.get("stale_days", 21)
    ]
    month = today.isoformat()[:7]
    by_platform: dict = {}
    for i in sold:
        p = by_platform.setdefault(i["sell_platform"] or "未知", {"count": 0, "profit": 0.0})
        p["count"] += 1
        p["profit"] = round(p["profit"] + profit_of(i), 2)
    return {
        "sold_count": len(sold),
        "profit_total": round(profit, 2),
        "profit_month": round(sum(profit_of(i) for i in sold if (i["sold_at"] or "").startswith(month)), 2),
        "hourly_rate": round(profit / hours, 2) if hours else None,
        "avg_turnover_days": round(statistics.mean(turnover), 1) if turnover else None,
        "stock_count": len(stock),
        "stock_value": round(sum(i["buy_price"] or 0 for i in stock), 2),
        "stale": [i["code"] for i in stale],
        "by_status": {s: sum(1 for i in items if i["status"] == s) for s in STATUSES},
        "by_platform": by_platform,
    }


def funds(conn) -> list[dict]:
    total = stats(conn)["profit_total"]
    out = []
    for name, f in config.rules().get("funds", {}).items():
        saved = round(max(total, 0) * f.get("share_of_profit", 0) + db.get_meta(conn, f"fund_extra:{name}", 0), 2)
        out.append({"name": name, "target": f.get("target"), "saved": saved,
                    "progress": round(saved / f["target"], 3) if f.get("target") else None})
    return out


def listing_draft(item: dict) -> str:
    """上架描述草稿（规则版；配置 API 后可在此调用 Claude 生成更好的文案）。"""
    defects = json.loads(item.get("defects") or "[]")
    lines = [
        f"【{item['model']}】{item.get('condition') or ''}".strip(),
        f"瑕疵如实说明：{'、'.join(defects) if defects else '无明显瑕疵'}",
        "已清洁检测，功能正常，实拍图无修饰。",
        "支持当面验货 / 走平台担保交易。",
    ]
    if item.get("list_price"):
        lines.append(f"价格：{config.currency()}{item['list_price']:.0f}")
    return "\n".join(lines)
