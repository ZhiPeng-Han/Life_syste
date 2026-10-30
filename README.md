# Life_syste · LifeOS v0.1

一个基于 AI 的多维人生管理系统：以**记忆**为根基、以**关系网络**为骨架、以**减少决策**为目标、能**持续自我迭代**。

- 📄 设计方案：[docs/LifeOS-方案.md](docs/LifeOS-方案.md)
- ❤️ 她的三个愿望 · 行动计划：[docs/她的三个愿望-行动计划.md](docs/她的三个愿望-行动计划.md)
- 🔍 GitHub 参考项目调研：[docs/参考项目调研.md](docs/参考项目调研.md)
- 🔁 迭代机制与路线图：[docs/迭代机制.md](docs/迭代机制.md)
- 🧭 人生导则：[principles/人生导则.md](principles/人生导则.md)

## 5 分钟上手

需要 Python 3.11+，**不装任何依赖就能运行**（规则引擎模式）。

```bash
python -m lifeos init        # 初始化（会写入她的三个愿望和起步任务）
python -m lifeos today       # 今日驾驶舱
python -m lifeos serve       # 打开 http://127.0.0.1:8765 可视化仪表盘
```

启用 Claude（抽取更准、复盘有 AI 教练点评、惊喜方案更个性化）：

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
```

## 每天怎么用

| 时间 | 做什么 | 命令 |
|---|---|---|
| 早上 | 看今天的 3 件事和时间块 | `python -m lifeos today` |
| 随时 | 随手记一句（AI 自动拆成记忆/任务/她的愿望/器材交易） | `python -m lifeos add "1800 收了一支 50/1.4 有雾，她说想学陶艺"` |
| 遇到捡漏 | 评估要不要收 | `python -m lifeos deal --model "50/1.4" --price 180 --defects 雾` |
| 晚上 22:10 | 3 分钟签到 | `python -m lifeos checkin` |
| 周日 | 周复盘 → 修改 `config/rules.toml` | `python -m lifeos review` |

对系统的每条建议给反馈（`lifeos fb <编号> accept|reject|modify "原因"`），它会据此调整：采纳率连续达标就提议把这类决策交给系统自动做；一次"错得离谱"就立即收回权限。

<details>
<summary>全部命令</summary>

```
init / add / today / checkin / t（记录时间）/ task / search / confirm / fb / autonomy
item（库存：add/set/sell/list/stats）/ deal（捡漏评估）/ her / wish / date / menu
card（Part 3 卡片）/ exp（个人实验）/ decide（决策日志）/ review / manual / consolidate / serve / bot
```

`python -m lifeos <命令> -h` 查看参数。
</details>

## 手机上用

- **仪表盘**：`LIFEOS_TOKEN=随机字符 python -m lifeos serve --host 0.0.0.0`，手机打开 `http://电脑IP:8765/?token=随机字符`
- **Telegram 随手记**：见 `lifeos/bot.py` 顶部说明，`python -m lifeos bot`
- **器材橱窗**（给她看的平台原型）：`/shop`

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
