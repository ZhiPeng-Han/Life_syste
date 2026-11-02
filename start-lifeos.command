#!/bin/bash
# macOS：双击这个文件启动 LifeOS（iPhone 模式）。关掉窗口即停止。
# 启动前会先从 GitHub 拿最新代码（拿不到就用现在的版本）。
cd "$(dirname "$0")"
git pull --ff-only -q 2>/dev/null && echo "🔄 已是最新版本" || echo "（这次没有更新，用现在的版本启动）"
python3 -m lifeos phone
