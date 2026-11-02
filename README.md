# Life_syste · LifeOS v0.7

一个陪你生活的 AI 系统。它**替你记住**（杂事、她说过的话、发生过的美好），在你**需要时帮你做个小决定**；其余时候，它安静。

> 你是生活的主体，不是被管理的系统。 → [docs/主体性-设计反思.md](docs/主体性-设计反思.md)
>
> 天行健，君子以自强不息；地势坤，君子以厚德载物。 → [docs/天行健地势坤.md](docs/天行健地势坤.md)

- 🧭 **此刻宜：天时 · 地利 · 人和**（时令之卦、七十二候、日出日落、卦象解读）：[docs/天时与此刻宜.md](docs/天时与此刻宜.md)
- 🖥 **本地部署 · GitHub 同步 · 每日 AI 梳理（不用 API）**：[docs/本地部署与每日梳理.md](docs/本地部署与每日梳理.md)
- 🧠 记忆系统（v0.5 记忆中枢）：[docs/记忆系统.md](docs/记忆系统.md)
- ☯ 天行健，地势坤（家庭、天道与命）：[docs/天行健地势坤.md](docs/天行健地势坤.md)
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
python -m lifeos now         # 此刻宜：按天时、地利、人和，此刻去做什么
python -m lifeos tian        # 天时：时辰、天光、天气、节气与候、时令之卦
python -m lifeos serve       # 打开 http://127.0.0.1:8765 可视化仪表盘
```

可选：精确节气与农历 `pip install lunar_python`；照片回响在 `config/rules.toml` 的 `[photos]` 填文件夹后运行 `python -m lifeos photos`。

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
| 早上 | 一段问候：节气、天气、今日之卦、大势 | `python -m lifeos morning` |
| 想起一卦 | 今日之卦，或问一件犹豫的事 | `python -m lifeos yi` / `yi --ask "…"` |
| 有一件期待的事 | 放上地平线，倒计时 | `python -m lifeos horizon add 冰岛 --date 2027-02-14` |
| 做了一个仪式 | 记一句（不打卡） | `python -m lifeos ritual log 1 做了番茄牛腩` |
| 和她一起 | 写下 / 重写你们的北极星 | `python -m lifeos northstar 一句话` |
| 卡住了 | 抽一张君子卡 | `python -m lifeos junzi` |
| 观察到某种趋势 | 记下天下大势（顺 / 逆 / 观） | `python -m lifeos shi add 二手镜头涨价 -d 器材事业 --direction 1` |
| 周末 | 一封写给这一周的你的信 | `python -m lifeos letter` |
| 交图、考试前 | 这时才需要时间表 | `python -m lifeos today` |

<details>
<summary>全部命令</summary>

```
init / phone / add / now / pocket / letgo / morning / letter / yi / shi / horizon / ritual / northstar / place / photos / junzi / today / checkin / t（记录时间）/ task / search / confirm / fb / autonomy
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
scripts/               install-mac.sh 开机自启 · update.sh 更新 · lifeos-daily.md 每日梳理说明（给 Claude Code）
lifeos/                代码：memory 记忆 · mind 记忆中枢 · daily 每日梳理 · extract 抽取 · planner 规划 · decisions 放权
                       business 器材 · relationship 她 · meals 菜单 · cards Part3 · review 复盘
data/                  个人数据（SQLite、复盘、说明书），已 .gitignore
tests/                 python -m unittest discover -s tests
```

> 仓库是私有的，但个人数据（`data/`）仍默认不进 git：数据库和代码分开，备份请单独做（复制 `data/` 目录即可）。
