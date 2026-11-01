"""把一句随手输入拆解成结构化记忆、任务、愿望、交易。

优先用 Claude 抽取；没有 API 时用规则引擎（关键词 + 正则）兜底。
两者输出同一结构，下游不关心来源。
"""

import re
from datetime import date, timedelta

from . import config, llm

MEMORY_TYPES = ["episodic", "semantic", "procedural", "prospective", "normative"]
WISH_CATEGORIES = ["travel", "project", "health", "gift", "experience", "other"]

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["memories", "tasks", "wishes", "items"],
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["content", "type", "domain", "importance", "confidence", "people", "mood", "occurred_on", "topics"],
                "properties": {
                    "content": {"type": "string"},
                    "type": {"type": "string", "enum": MEMORY_TYPES},
                    "domain": {"type": "string"},
                    "importance": {"type": "integer"},
                    "confidence": {"type": "number"},
                    "people": {"type": "array", "items": {"type": "string"}},
                    "mood": {"type": "integer"},
                    "occurred_on": {"type": "string"},
                    "topics": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "domain", "due", "energy", "est_minutes", "priority"],
                "properties": {
                    "title": {"type": "string"},
                    "domain": {"type": "string"},
                    "due": {"type": "string"},
                    "energy": {"type": "string", "enum": ["high", "medium", "low"]},
                    "est_minutes": {"type": "integer"},
                    "priority": {"type": "integer"},
                },
            },
        },
        "wishes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["person", "content", "category"],
                "properties": {
                    "person": {"type": "string"},
                    "content": {"type": "string"},
                    "category": {"type": "string", "enum": WISH_CATEGORIES},
                },
            },
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["action", "model", "price", "platform", "defects"],
                "properties": {
                    "action": {"type": "string", "enum": ["buy", "sell"]},
                    "model": {"type": "string"},
                    "price": {"type": "number"},
                    "platform": {"type": "string"},
                    "defects": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}


def _system_prompt() -> str:
    domains = "、".join(config.domains().keys())
    defects = "、".join(config.rules().get("business", {}).get("defect_discount", {}).keys())
    return f"""你是用户个人人生管理系统 LifeOS 的"记忆官"。用户是一位建筑师，同时在准备 RIBA Part 3，
经营二手相机镜头转卖，研究 AI 自媒体，非常重视和女友的感情。你的工作是把用户随手记下的一段话拆成结构化数据。

规则：
- 一段话里可能有多件互不相关的事，每件事拆成一条 memory，content 用简洁中文复述原意，保留数字和专有名词。
- domain 只能从这些里选：{domains}。
- type：发生过的事=episodic；关于人/世界的稳定事实或偏好=semantic；做事方法=procedural；将来要做的事=prospective；价值观/原则=normative。
- importance 1-10：涉及女友、重大金钱、健康、截止日期的更高；日常琐事低。
- confidence 0-1：你对理解是否正确的把握，含糊时给低分，系统会请用户确认。
- people：提到的人，女友统一写"她"。mood：文字里能看出用户心情时给 1-10，否则 0。
- occurred_on：事情实际发生的日期 YYYY-MM-DD（"昨天""上周六"要换算成日期）；就是今天或看不出来就留空字符串。
- topics：这件事涉及的具体事物，1-3 个简短名词（地点、项目、器材型号、爱好、作品），如"冰岛""陶艺""50/1.4"；没有就给空数组。
- 只有用户明确要做/要记得做的事才放进 tasks；due 用 YYYY-MM-DD，没有就留空字符串；今天是 {date.today().isoformat()}。
- 女友（或其他人）说想要/想做/希望的事放进 wishes，这是惊喜引擎的燃料，不要漏。
- 买入(收)或卖出(出)相机器材放进 items；platform 不确定就留空字符串；defects 尽量用这些词：{defects}。
- 不要编造原文没有的信息。"""


def extract(text: str) -> dict:
    result = llm.complete_json(_system_prompt(), text, SCHEMA)
    if result is not None:
        result["engine"] = "claude"
        return result
    result = extract_rules(text)
    result["engine"] = "rules"
    return result


# ------------------------------------------------------------------ 规则引擎

PERSON_RE = re.compile(r"(她|女友|女朋友|宝贝)")
WISH_RE = re.compile(r"(想要|想去|想学|想吃|想买|想做|想和|想一起|想|希望|好想|一直想)")
TASK_RE = re.compile(r"^(记得|别忘了|提醒我|待办|todo|要去|要做|需要|得去|明天|后天|下周|这周|周[一二三四五六日天])", re.I)
TASK_PREFIX_RE = re.compile(r"^(记得|别忘了|提醒我|待办|todo|明天|后天|下周|这周|今天|今晚)?(要|得|需要|去)?", re.I)
BUY_RE = re.compile(r"(收了|收到|买了|入了|拿下|收)")
SELL_RE = re.compile(r"(出了|卖了|售出|成交|出掉)")
MODEL_RE = re.compile(
    r"((?:[A-Za-z]+\s?)?\d{2,3}(?:-\d{2,3})?\s?(?:mm)?\s?(?:f/?|/)\s?\d(?:\.\d)?(?:\s?[A-Za-z]+)?"
    r"|(?:[A-Za-z]{1,10}[\s-]?)?[A-Za-z]{1,4}\d{1,4}[A-Za-z]*(?:\s?(?:II|III|IV|Mark\s?\d))?)",
    re.I,
)
PRICE_RE = re.compile(r"(?<![\d./])(\d{2,6}(?:\.\d{1,2})?)(?![\d./]|mm)")
PLATFORMS = ["闲鱼", "eBay", "ebay", "MPB", "mpb", "小红书", "转转", "Facebook", "Gumtree"]
PAST_RE = re.compile(r"[了过](?![解])|刚才|刚刚")
REMIND_RE = re.compile(r"^(记得|别忘了|提醒我|待办|todo)", re.I)
GEAR_RE = re.compile(r"\d{2,3}\s?mm|\d{2,3}\s?/\s?\d(?:\.\d)?\b|\b[A-Z]{1,3}\d{1,2}[A-Z]{0,2}\d?\b|镜头|机身")
FACT_RE = re.compile(r"(喜欢|不喜欢|讨厌|爱吃|不吃|过敏|习惯|总是|从不|最爱|不爱|不再|开始喜欢|怕)")
EVENT_RE = re.compile(r"(今天|昨天|前天|今晚|昨晚|刚才|刚刚|上周|那天|这次)")
TRAVEL_WORDS = ["去", "旅行", "旅游", "玩", "看极光", "冰岛", "海边"]
HEALTH_WORDS = ["减肥", "瘦", "健身", "锻炼", "跑步", "体重"]
PROJECT_WORDS = ["开发", "做一个", "平台", "一起做", "创业", "店"]


def _domain_of(text: str) -> str:
    lower = text.lower()
    best, best_hits = "生活维持", 0
    for name, d in config.domains().items():
        hits = sum(1 for k in d.get("keywords", []) if k.lower() in lower)
        if hits > best_hits:
            best, best_hits = name, hits
    return best


def _segments(text: str) -> list[str]:
    segs = []
    for sentence in re.split(r"[。！？!?；;\n]+", text):
        current = ""
        for clause in re.split(r"[，,]", sentence):
            clause = clause.strip()
            if not clause:
                continue
            starts_new = PERSON_RE.search(clause) or TASK_RE.search(clause)
            if current and starts_new:
                segs.append(current)
                current = clause
            else:
                current = f"{current}，{clause}" if current else clause
        if current:
            segs.append(current)
    return segs


def _due_of(seg: str) -> str:
    today = date.today()
    if "明天" in seg:
        return (today + timedelta(days=1)).isoformat()
    if "后天" in seg:
        return (today + timedelta(days=2)).isoformat()
    if "今天" in seg or "今晚" in seg:
        return today.isoformat()
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", seg)
    if m:
        try:
            d = date(today.year, int(m.group(1)), int(m.group(2)))
            if d < today:
                d = d.replace(year=today.year + 1)
            return d.isoformat()
        except ValueError:
            pass
    return ""


def _wish_category(seg: str) -> str:
    if any(w in seg for w in HEALTH_WORDS):
        return "health"
    if any(w in seg for w in PROJECT_WORDS):
        return "project"
    if any(w in seg for w in TRAVEL_WORDS):
        return "travel"
    if "买" in seg or "礼物" in seg:
        return "gift"
    return "experience"


def _item_of(seg: str) -> dict | None:
    action = "sell" if SELL_RE.search(seg) else "buy" if BUY_RE.search(seg) else None
    if not action:
        return None
    model_match = MODEL_RE.search(seg)
    if not model_match:
        return None
    model = model_match.group(0).strip()
    rest = seg.replace(model, " ")
    price = next((float(p) for p in PRICE_RE.findall(rest) if float(p) >= 10), None)
    if price is None:
        return None
    defect_keys = config.rules().get("business", {}).get("defect_discount", {}).keys()
    platform = next((p for p in PLATFORMS if p in seg), "")
    return {
        "action": action,
        "model": model,
        "price": price,
        "platform": {"ebay": "eBay", "mpb": "MPB"}.get(platform, platform),
        "defects": [d for d in defect_keys if d in seg],
    }


def extract_rules(text: str) -> dict:
    out = {"memories": [], "tasks": [], "wishes": [], "items": []}
    for seg in _segments(text):
        domain = _domain_of(seg)
        has_person = bool(PERSON_RE.search(seg))
        people = ["她"] if has_person else []
        if has_person:
            domain = "关系"
        # "周日一起做了饭"是发生过的事，不是待办；"记得……"永远是待办
        is_task = bool(TASK_RE.search(seg)) and not has_person and (
            not PAST_RE.search(seg) or bool(REMIND_RE.search(seg)))
        if not has_person and GEAR_RE.search(seg):
            domain = "器材事业"
        mem_type = "prospective" if is_task else "episodic"
        if not is_task and FACT_RE.search(seg) and not EVENT_RE.search(seg) and not WISH_RE.search(seg):
            mem_type = "semantic"  # "她不吃香菜""我习惯早上画图"是关于人的稳定事实
        importance = 4 + (3 if domain == "关系" else 0) + (2 if PRICE_RE.search(seg) else 0)

        if has_person and WISH_RE.search(seg):
            # "她笑得很开心，说想学陶艺" → 只取"说"之后的愿望本身
            said = seg.rfind("说")
            content = seg[said + 1:] if said >= 0 else PERSON_RE.sub("", seg, count=1)
            content = content.lstrip("说讲提到了过，, ")
            out["wishes"].append({"person": "她", "content": content or seg, "category": _wish_category(seg)})
            importance += 1
        if is_task:
            out["tasks"].append(
                {
                    "title": TASK_PREFIX_RE.sub("", seg, count=1).strip("，, ") or seg,
                    "domain": domain,
                    "due": _due_of(seg),
                    "energy": "medium",
                    "est_minutes": 30,
                    "priority": 3,
                }
            )
        item = _item_of(seg)
        if item:
            out["items"].append(item)
            domain = "器材事业"
        out["memories"].append(
            {
                "content": seg,
                "type": mem_type,
                "domain": domain,
                "importance": min(importance, 10),
                "confidence": 0.75,
                "people": people,
                "mood": 0,
                "occurred_on": "",
                "topics": [],
            }
        )
    return out
