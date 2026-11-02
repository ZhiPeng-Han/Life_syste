#!/bin/bash
# 从 GitHub 拿最新的系统代码。你的个人数据在 data/（不进 git），不会被动到。
cd "$(dirname "$0")/.." || exit 1
branch=$(git rev-parse --abbrev-ref HEAD)
echo "🔄 更新 LifeOS（分支 $branch）…"
if git pull --ff-only; then
  python3 -c "import lifeos; print('✅ 现在是 v' + lifeos.__version__)"
  python3 -m lifeos backup >/dev/null && echo "💾 已顺手备份数据库"
  if launchctl print "gui/$(id -u)/com.lifeos.server" >/dev/null 2>&1; then
    launchctl kickstart -k "gui/$(id -u)/com.lifeos.server" && echo "♻️ 后台服务已用新版本重启"
  fi
else
  echo "⚠️ 没能自动更新。多半是你改过仓库里的文件。"
  echo "   个人设置请放到 data/rules.toml（只写想改的部分），然后运行：git status 看看改了什么"
fi
