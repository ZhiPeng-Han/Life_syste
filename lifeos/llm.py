"""Claude API 封装。没有配置凭据时返回 None，系统自动退回到规则引擎，保证离线也能用。"""

import json
import os
import sys

MODEL = os.environ.get("LIFEOS_MODEL", "claude-opus-5-5")
_client = None


def available() -> bool:
    if os.environ.get("LIFEOS_LLM", "").lower() in ("0", "off", "false"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


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


def complete_text(system: str, user: str, effort: str = "medium") -> str | None:
    if not available():
        return None
    return _call(system, user, effort, None)


def complete_json(system: str, user: str, schema: dict, effort: str = "low") -> dict | None:
    if not available():
        return None
    text = _call(system, user, effort, {"type": "json_schema", "schema": schema})
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print("[lifeos] Claude 返回的 JSON 无法解析，已退回规则引擎", file=sys.stderr)
        return None
