"""首次初始化：领域、初始关系假设网络、她的三个愿望及对应的起步任务、示例 Part 3 卡片。"""

from . import cards, config, db, relationship, tasks

# 方案第 6 章的初始假设网络，之后由真实数据验证或否定
RELATIONS = [
    ("器材事业", "自媒体", "synergy", "交易故事、器材评测都是素材"),
    ("旅行", "关系", "synergy", "一起旅行是最好的关系投资"),
    ("旅行", "器材事业", "synergy", "旅行中测试库存镜头、拍样张"),
    ("旅行", "自媒体", "synergy", "旅行内容素材"),
    ("器材事业", "关系", "synergy", "她想和你一起做转售平台：生意变成共同项目"),
    ("健康", "关系", "synergy", "一起锻炼、一起吃得健康，支持她减肥"),
    ("健康", "旅行", "synergy", "冰岛徒步需要体能"),
    ("生活维持", "关系", "synergy", "一起做饭"),
    ("建筑工作", "Part3", "synergy", "工作中的合同/管理问题就是 Part 3 素材"),
    ("器材事业", "关系", "competition", "周末晚上的上架、沟通会挤占约会时间"),
    ("器材事业", "Part3", "competition", "都抢下班后的时间"),
    ("自媒体", "Part3", "competition", "都抢下班后的时间"),
    ("器材事业", "旅行", "influence", "器材利润的 30% 进入冰岛基金"),
    ("健康", "建筑工作", "influence", "睡眠和运动影响设计效率（待验证）"),
    ("阅读思考", "关系", "influence", "人生导则约束一切取舍"),
]

PROJECTS = {
    "冰岛之旅": ("旅行", "她想去冰岛旅游"),
    "器材转售平台（和她一起）": ("器材事业", "她想和你一起开发相机设备转售平台"),
    "一起变健康": ("健康", "她想减肥——她主导，你支持"),
}

WISHES = [
    ("想去冰岛旅游", "travel", "冰岛之旅"),
    ("想和我一起开发相机设备转售平台", "project", "器材转售平台（和她一起）"),
    ("想减肥", "health", "一起变健康"),
]

TASKS = [
    # 冰岛
    ("和她一起决定冰岛出行季节：冬季看极光 vs 夏季自驾/徒步", "关系", 4, "low", 45, "冰岛之旅"),
    ("粗估冰岛预算（机票+租车+住宿+餐饮），修改 rules.toml 里冰岛基金 target", "旅行", 3, "medium", 45, "冰岛之旅"),
    ("建一个共享的冰岛灵感清单，发第一张图给她", "关系", 3, "low", 15, "冰岛之旅"),
    ("确认两人护照有效期与签证要求", "旅行", 3, "low", 20, "冰岛之旅"),
    ("列出冰岛拍摄器材清单：广角、三脚架、ND、防水（可顺便测库存镜头）", "器材事业", 2, "medium", 30, "冰岛之旅"),
    # 平台
    ("第一次「合伙人会议」：愿景、分工、边界（30 分钟，会后去吃饭）", "关系", 5, "medium", 60, "器材转售平台（和她一起）"),
    ("写下现在转售流程的痛点清单，问她最想负责哪一块", "器材事业", 4, "high", 45, "器材转售平台（和她一起）"),
    ("把现有库存录入 LifeOS（「器材」页 → 收入器材），让橱窗页有内容给她看", "器材事业", 4, "low", 60, "器材转售平台（和她一起）"),
    # 健康
    ("问她：你希望我怎么支持你？（只支持，不评价）", "关系", 5, "low", 20, "一起变健康"),
    ("看一眼本周菜单，按轻食晚餐采购", "生活维持", 3, "low", 45, "一起变健康"),
    ("约她每周一次一起徒步/长距离散步（也是冰岛体能准备）", "健康", 3, "low", 15, "一起变健康"),
    # 系统本身
    ("写人生导则 v0.1（principles/人生导则.md）", "阅读思考", 4, "high", 45, None),
    ("添加她的重要日期（「她」页最下方）", "关系", 5, "low", 10, None),
    ("把本周项目中遇到的一个合同/管理问题写成 Part 3 卡片", "Part3", 3, "high", 30, None),
]

CARDS = [
    ("（示例，请核对）小型、简单的建筑工程常用 JCT 哪一种合同？", "JCT Minor Works Building Contract (MW)"),
    ("（示例，请核对）CDM 2015 下，有多个承包商的项目由谁书面任命 Principal Designer？", "Client（委托方）"),
    ("（示例，请核对）ARB Code 要求建筑师持有哪类保险？", "足够且合适的职业责任保险（PII）"),
]


def run(conn=None) -> dict:
    conn = conn or db.connect()
    if db.get_meta(conn, "seeded"):
        return {"seeded": False, "reason": "已经初始化过"}
    ids = {name: db.entity(conn, "domain", name) for name in config.domains()}
    her = db.entity(conn, "person", "她", {"note": "最重要的人"})
    db.relate(conn, her, ids["关系"], "related", note="她", bump=3)
    for a, b, kind, note in RELATIONS:
        if a in ids and b in ids:
            db.relate(conn, ids[a], ids[b], kind, note=note)
    for name, (domain, note) in PROJECTS.items():
        pid = db.entity(conn, "project", name, {"note": note})
        db.relate(conn, pid, her, "related", note=note, bump=2)
        db.relate(conn, pid, ids[domain], "related", bump=2)
    for content, cat, project in WISHES:
        relationship.add_wish(conn, content, cat, project=project, notes="2026-10 告诉我的")
    for title, domain, pri, energy, minutes, project in TASKS:
        tasks.add(conn, title, domain, pri, energy, minutes, project=project, source="seed")
    for front, back in CARDS:
        cards.add(conn, front, back)
    db.set_meta(conn, "seeded", db.now())
    conn.commit()
    return {"seeded": True, "wishes": len(WISHES), "tasks": len(TASKS), "cards": len(CARDS)}
