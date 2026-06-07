"""集中封裝 Anthropic API 呼叫（強制結構化 JSON 輸出）。

只在此處 import anthropic，方便日後調整模型、加上重試或快取。
模型由 core.config 決定（可用環境變數覆寫）：
  TREND_MATCHER_MODEL   預設 claude-haiku-4-5（配對/翻譯，便宜）
  TREND_EVALUATOR_MODEL 預設 claude-opus-4-8（下注判斷，較強）

結構化輸出採 messages.create(output_config={"format": {"type":"json_schema",...}})，
此功能在 Haiku 4.5 / Sonnet 4.6 / Opus 4.8 皆支援。注意 json_schema 限制：
所有 object 需 additionalProperties:false，且不支援數值 min/max（在呼叫端 clamp）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from core import config


@lru_cache(maxsize=1)
def _client():
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("缺少 ANTHROPIC_API_KEY（請加到 ~/.polymarket/.env）")
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def call_json(
    *,
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int = 1024,
) -> dict[str, Any] | None:
    """呼叫 Claude，強制回傳符合 schema 的 JSON，解析後回傳 dict。失敗回 None。"""
    try:
        resp = _client().messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
    except Exception as e:
        print(f"   ⚠️ Claude 呼叫失敗（{model}）: {type(e).__name__}: {e}")
        return None

    text = next(
        (b.text for b in resp.content if getattr(b, "type", None) == "text"), None
    )
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        print(f"   ⚠️ Claude 回傳非合法 JSON: {text[:120]}")
        return None
