#!/bin/bash
# macOS：把 LifeOS 装成"开机自动运行"的本地服务。
#
#   bash scripts/install-mac.sh            # 开机/登录后自动启动 LifeOS（iPhone 随时能用）
#   bash scripts/install-mac.sh --daily    # 另外每天 07:30 用 claude 命令行做每日梳理（不用 Desktop 时的备用方式）
#   bash scripts/install-mac.sh --uninstall
#
# 只装在你自己的用户下（~/Library/LaunchAgents），不需要管理员密码。
set -e
cd "$(dirname "$0")/.."
REPO="$(pwd)"
AGENTS="$HOME/Library/LaunchAgents"
SERVER="com.lifeos.server"
DAILY="com.lifeos.daily"
mkdir -p "$AGENTS" "$REPO/data/logs"

if [ "$1" = "--uninstall" ]; then
  for name in $SERVER $DAILY; do
    launchctl bootout "gui/$(id -u)/$name" 2>/dev/null || true
    rm -f "$AGENTS/$name.plist"
  done
  echo "已移除开机启动。数据还在 $REPO/data/，没有动。"
  exit 0
fi

# 找一个 3.11 以上的 python3（macOS 自带的 /usr/bin/python3 常常太旧）
PY=""
for p in "$(command -v python3)" /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if [ -x "$p" ] && "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$p"; break
  fi
done
if [ -z "$PY" ]; then
  echo "❌ 没找到 Python 3.11 以上。请先到 https://www.python.org/downloads/ 安装，然后重新运行。"
  exit 1
fi
echo "✓ Python：$PY（$("$PY" --version)）"

"$PY" -m lifeos init >/dev/null 2>&1 || true
TOKEN=$("$PY" -c 'from lifeos import phone; print(phone.token())')

cat > "$AGENTS/$SERVER.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$SERVER</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string><string>-m</string><string>lifeos</string><string>phone</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict><key>LIFEOS_AUTORELOAD</key><string>1</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$REPO/data/logs/server.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/logs/server.log</string>
</dict></plist>
PLIST
launchctl bootout "gui/$(id -u)/$SERVER" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENTS/$SERVER.plist"
echo "✓ LifeOS 已在后台运行，以后开机登录会自动启动"

if [ "$1" = "--daily" ]; then
  cat > "$AGENTS/$DAILY.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$DAILY</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$REPO/scripts/daily-claude.sh</string>
  </array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(dirname "$PY"):/usr/bin:/bin</string></dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>$REPO/data/logs/daily-launchd.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/logs/daily-launchd.log</string>
</dict></plist>
PLIST
  launchctl bootout "gui/$(id -u)/$DAILY" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$DAILY.plist"
  echo "✓ 每天 07:30 自动做每日梳理（电脑睡着时会在醒来后补一次）。日志：data/logs/"
fi

IP=$("$PY" -c 'from lifeos import phone; print(phone.lan_ip() or "")')
echo
echo "📱 iPhone（同一个 Wi-Fi）打开：http://$IP:8765/?token=$TOKEN"
echo "   然后 分享 → 添加到主屏幕。在外面用 Tailscale（见 docs/iPhone使用指南.md）。"
echo "   查看运行日志：tail -f $REPO/data/logs/server.log"
