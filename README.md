# Life_syste · LifeOS v0.2

一个陪你生活的 AI 系统。它**替你记住**（杂事、她说过的话、发生过的美好），在你**需要时帮你做个小决定**；其余时候，它安静。

> 你是生活的主体，不是被管理的系统。 → [docs/主体性-设计反思.md](docs/主体性-设计反思.md)

- 🌿 v0.2 设计反思：[docs/主体性-设计反思.md](docs/主体性-设计反思.md)
- 📄 最初的设计方案：[docs/LifeOS-方案.md](docs/LifeOS-方案.md)
- ❤️ 她的三个愿望 · 行动计划：[docs/她的三个愿望-行动计划.md](docs/她的三个愿望-行动计划.md)
- 🔍 GitHub 参考项目调研：[docs/参考项目调研.md](docs/参考项目调研.md)
- 🔁 迭代机制与路线图：[docs/迭代机制.md](docs/迭代机制.md)
- 🧭 人生导则：[principles/人生导则.md](principles/人生导则.md)

## 5 分钟上手

需要 Python 3.11+，**不装任何依赖就能运行**（规则引擎模式）。

```bash
python -m lifeos init        # 初始化（会写入她的三个愿望和起步任务）
python -m lifeos now         # 此刻：你现在感觉怎么样？
python -m lifeos serve       # 打开 http://127.0.0.1:8765 可视化仪表盘
```

启用 Claude（抽取更准、复盘有 AI 教练点评、惊喜方案更个性化）：

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

## 怎么用

没有"必须"做的事，只有几个入口：

| 什么时候 | 做什么 | 命令 |
|---|---|---|
| 想到什么 | 记下一句：瞬间、她说的话、杂事、器材交易 | `python -m lifeos add "她说想学陶艺"` |
| 累了、犹豫、不想想 | 说出感受，得到一个可能性（可以换、可以不做） | `python -m lifeos now` |
| 想处理杂事 | 看口袋，拿一件，或者放下一件 | `python -m lifeos pocket` / `letgo ID` |
| 遇到捡漏 | 收不收？ | `python -m lifeos deal --model "50/1.4" --price 180 --defects 雾` |
| 早上 | 一段问候，不是时间表 | `python -m lifeos morning` |
| 周末 | 一封写给这一周的你的信 | `python -m lifeos letter` |
| 交图、考试前 | 这时才需要时间表 | `python -m lifeos today` |

<details>
<summary>全部命令</summary>

```
init / phone / add / now / pocket / letgo / morning / letter / today / checkin / t（记录时间）/ task / search / confirm / fb / autonomy
item（库存：add/set/sell/list/stats）/ deal（捡漏评估）/ her / wish / date / menu
card（Part 3 卡片）/ exp（个人实验）/ decide（决策日志）/ review / manual / consolidate / serve / bot
```

`python -m lifeos <命令> -h` 查看参数。
</details>

## 在 iPhone 上用

👉 **一步一步的图文说明：[docs/iPhone使用指南.md](docs/iPhone使用指南.md)**

简单说：电脑上双击 `start-lifeos.command`（Windows 用 `start-lifeos.bat`）→ iPhone Safari 打开窗口里的链接 → 添加到主屏幕。
在外面用 Tailscale 连接；「嘿 Siri，记一下」通过快捷指令随手记录。

## 结构

```
config/rules.toml      你的生活规则（时间块、预算、主线支线、自主等级、捡漏门槛、冰岛基金）← 每周改它
config/recipes.toml    菜谱库
lifeos/                代码：memory 记忆 · extract 抽取 · planner 规划 · decisions 放权
                       business 器材 · relationship 她 · meals 菜单 · cards Part3 · review 复盘
data/                  个人数据（SQLite、复盘、说明书），已 .gitignore
tests/                 python -m unittest discover -s tests
```

> 仓库是私有的，但个人数据（`data/`）仍默认不进 git：数据库和代码分开，备份请单独做（复制 `data/` 目录即可）。
