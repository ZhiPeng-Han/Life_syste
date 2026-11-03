#!/bin/bash
# 每日梳理（备用方式）：不用 Claude Desktop 时，用 claude 命令行在后台跑一次。
# 用你的 Claude 登录（先在终端里运行一次 claude 并登录），不需要 API key。
# 由 scripts/install-mac.sh --daily 安排每天自动运行；也可以手动运行：bash scripts/daily-claude.sh
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/bin:$HOME/.claude/local:/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p data/logs
log="data/logs/daily-$(date +%F).log"
if ! command -v claude >/dev/null; then
  echo "找不到 claude 命令。安装：https://code.claude.com/docs/en/setup" | tee -a "$log"
  exit 1
fi
{
  echo "=== $(date) ==="
  claude -p "按照 scripts/lifeos-daily.md 里的说明，做今天的 LifeOS 每日梳理。" \
    --permission-mode dontAsk \
    --allowedTools "Read" "Bash(python3 -m lifeos ai *)" "Bash(python3 -m lifeos mind *)" \
      "Bash(python3 -m lifeos backup)" "Bash(git pull --ff-only)" "Edit(./data/ai/**)" "Write(./data/ai/**)" \
      "WebSearch" "WebFetch(domain:*.bbc.co.uk)" "WebFetch(domain:*.bbc.com)" "WebFetch(domain:www.theguardian.com)" \
      "WebFetch(domain:www.reuters.com)" "WebFetch(domain:www.dezeen.com)" "WebFetch(domain:petapixel.com)" \
      "WebFetch(domain:www.theverge.com)" "WebFetch(domain:www.ons.gov.uk)"
  echo "=== 结束 $(date) ==="
} >>"$log" 2>&1
