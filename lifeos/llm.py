"""AI 封装。三种方式（config/rules.toml 的 [ai] mode）：

- auto（默认）：设置了 ANTHROPIC_API_KEY 就实时调用 API；没有就不实时调用，
  由每天的 Claude Code 定时任务统一梳理（见 lifeos/daily.py）
- daily：不实时调用任何 AI，只靠每日梳理
- claude-code：在你主动点的地方（写信、问卦解读、惊喜方案、说明书）调用本机的 `claude` 命令，
  用你的 Claude 登录，不需要 API key；会慢一些（十几秒到一两分钟）

拿不到 AI 时返回 None，系统自动退回到规则引擎，保证离线也能用。
"""

import json
import os
import shutil
import subprocess
import sys

MODEL = os.environ.get("LIFEOS_MODEL", "claude-opus-5-5")
_client = None


def mode() -> str:
    m = os.environ.get("LIFEOS_AI_MODE")
    if not m:
        from . import config

        m = config.rules().get("ai", {}).get("mode", "auto")
    return m if m in ("auto", "daily", "api", "claude-code") else "auto"


def _api_ready() -> bool:
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def backend(slow_ok: bool = False) -> str | None:
    """这一次调用用哪种 AI：'api' / 'claude-code' / None（用规则引擎）。"""
    if os.environ.get("LIFEOS_LLM", "").lower() in ("0", "off", "false"):
        return None
    m = mode()
    if m in ("auto", "api") and _api_ready():
        return "api"
    if m == "claude-code" and slow_ok and shutil.which("claude"):
        return "claude-code"
    return None


def available(slow_ok: bool = False) -> bool:
    return backend(slow_ok) is not None


def describe() -> str:
    b = backend(slow_ok=True)
    if b == "api":
        return f"Claude API（{MODEL}）"
    if b == "claude-code":
        return "本机 Claude Code（只用于你主动点的地方）+ 每日梳理"
    return "规则引擎 + 每日梳理（Claude Code 定时任务）"


def _call_claude_code(system: str, user: str, output_format: dict | None):
    """用本机的 claude 命令（你的 Claude 登录）。不给它任何工具，只让它回答。"""
    from . import config

    cmd = ["claude", "-p", "--output-format", "json", "--system-prompt", system, "--permission-mode", "dontAsk"]
    if output_format:
        cmd += ["--json-schema", json.dumps(output_format["schema"], ensure_ascii=False)]
    try:
        proc = subprocess.run(cmd, input=user, capture_output=True, text=True, timeout=240, cwd=config.home())
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"[lifeos] 调用 Claude Code 失败：{e}", file=sys.stderr)
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(f"[lifeos] Claude Code 没有返回 JSON：{proc.stderr[:300]}", file=sys.stderr)
        return None
    if data.get("is_error"):
        print(f"[lifeos] Claude Code 出错：{str(data.get('result'))[:300]}", file=sys.stderr)
        return None
    if output_format:
        so = data.get("structured_output")
        return json.dumps(so, ensure_ascii=False) if so is not None else None
    return data.get("result")


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic()
    return _client


def _call(system: str, user: str, effort: str, output_format: dict | None):
    import anthropic

    output_config = {"effort": effort}
    if output_format:
        output_config["format"] = output_format
    try:
        # fallbacks="default"：若主模型因安全分类器拒绝，服务端自动换推荐模型重试
        response = _get_client().beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError:
        print("[lifeos] Claude API 凭据无效，已退回规则引擎", file=sys.stderr)
        return None
    except anthropic.RateLimitError:
        print("[lifeos] Claude API 限流，已退回规则引擎", file=sys.stderr)
        return None
    except anthropic.APIStatusError as e:
        print(f"[lifeos] Claude API 错误 {e.status_code}: {e.message}", file=sys.stderr)
        return None
    except anthropic.APIConnectionError:
        print("[lifeos] 无法连接 Claude API，已退回规则引擎", file=sys.stderr)
        return None
    if response.stop_reason in ("refusal", "max_tokens"):
        print(f"[lifeos] Claude 未完成回答（{response.stop_reason}）", file=sys.stderr)
        return None
    return "".join(b.text for b in response.content if b.type == "text")


def core_memory() -> str:
    """借鉴 Letta 的"核心记忆块"：人生导则和《我的说明书》常驻在每一次对话里，AI 才真正认识他。"""
    from . import config

    parts = []
    for path, limit in ((config.REPO_ROOT / "principles" / "人生导则.md", 3000), (config.home() / "我的说明书.md", 1500)):
        if path.exists():
            parts.append(path.read_text(encoding="utf-8")[:limit])
    try:  # 记忆中枢：它从你的记忆里领悟到的、确认过的事实
        from . import db, mind

        conn = db.connect()
        try:
            k = mind.known(conn)
        finally:
            conn.close()
        if k:
            parts.append("它从记忆里知道的（领悟与事实）：\n" + k)
    except Exception:  # noqa: BLE001 —— 核心记忆缺一块，不该让回应失败
        pass
    if not parts:
        return ""
    return "\n\n<core_memory>\n以下是他自己写下的人生导则和系统对他的了解，回应时与之保持一致：\n" + "\n---\n".join(parts) + "\n</core_memory>"


def complete_text(system: str, user: str, effort: str = "medium", slow_ok: bool = False) -> str | None:
    b = backend(slow_ok)
    if b == "claude-code":
        return _call_claude_code(system + core_memory(), user, None)
    if b != "api":
        return None
    return _call(system + core_memory(), user, effort, None)


def complete_json(system: str, user: str, schema: dict, effort: str = "low", slow_ok: bool = False) -> dict | None:
    b = backend(slow_ok)
    fmt = {"type": "json_schema", "schema": schema}
    if b == "claude-code":
        text = _call_claude_code(system, user, fmt)
    elif b == "api":
        text = _call(system, user, effort, fmt)
    else:
        return None
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print("[lifeos] Claude 返回的 JSON 无法解析，已退回规则引擎", file=sys.stderr)
        return None
