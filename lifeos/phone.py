"""一条命令让 iPhone 能用：生成并保存访问口令、找到电脑地址、防止电脑睡眠、启动服务。"""

import os
import secrets
import shutil
import socket
import subprocess
import sys

from . import config, web


def token() -> str:
    if os.environ.get("LIFEOS_TOKEN"):
        return os.environ["LIFEOS_TOKEN"]
    path = config.home() / "token.txt"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(16))
        path.chmod(0o600)
    return path.read_text().strip()


def lan_ip() -> str | None:
    # 不会真的发包，只是让系统选出用来上网的那块网卡的地址
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def tailscale_ip() -> str | None:
    exe = shutil.which("tailscale") or (
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
        if os.path.exists("/Applications/Tailscale.app/Contents/MacOS/Tailscale") else None
    )
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.strip()
        return out.splitlines()[0] if out else None
    except (OSError, subprocess.SubprocessError):
        return None


def keep_awake() -> bool:
    """macOS：服务运行期间阻止电脑睡眠（合盖仍会睡，需接电源和外接显示器或保持开盖）。"""
    if sys.platform == "darwin" and shutil.which("caffeinate"):
        subprocess.Popen(["caffeinate", "-ims", "-w", str(os.getpid())])
        return True
    return False


def run(port: int = 8765) -> None:
    tok = token()
    lan, ts = lan_ip(), tailscale_ip()
    print("📱 LifeOS · iPhone 模式\n")
    if lan:
        print(f"  在家（同一个 Wi-Fi）：  http://{lan}:{port}/?token={tok}")
    if ts:
        print(f"  在外面（Tailscale）：  http://{ts}:{port}/?token={tok}")
    else:
        print("  在外面也想用？装 Tailscale（见 docs/iPhone使用指南.md 第 4 步）")
    print(f"\n  快捷指令里用的口令（请求头 X-LifeOS-Token）：{tok}")
    print("  ⚠️ 这个链接 = 你人生数据的钥匙，不要发给别人。换口令：删除 data/token.txt 后重启。")
    if keep_awake():
        print("\n  ☕ 已阻止电脑睡眠（关掉这个窗口就恢复）")
    print("\n  按 Ctrl+C 停止\n")
    web.serve("0.0.0.0", port, tok)
