"""集中封裝 LLM 呼叫（強制 JSON 輸出），支援兩個供應商：

  gemini     Google Gemini（免費額度，預設）—— 需 GEMINI_API_KEY
  anthropic  Claude（品質較高，計費）—— 需 ANTHROPIC_API_KEY

選擇邏輯（TREND_LLM_PROVIDER=auto）：有 GEMINI_API_KEY 用 Gemini，否則有
ANTHROPIC_API_KEY 用 Claude；兩者皆無 → call_json 回 None（管線優雅降級成 0 單）。

Gemini 走 REST（用 requests，不加新依賴），responseMimeType=application/json
強制 JSON；schema 不靠 API 強制（不同 API 版本欄位形狀不穩），改放進 prompt，
且呼叫端（signal_evaluator）本來就對每個欄位做防禦式驗證。
免費額度有 RPM 限制 → 內建呼叫最小間隔與 429 重試。
"""
from __future__ import annotations

import json
import time
from functools import lru_cache
from typing import Any

import requests

from core import config

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_GEMINI_MIN_INTERVAL = 4.5  # 秒；免費額度約 15 RPM（flash-lite），保守留空隙
_last_gemini_call = 0.0

# call_json() 失敗時設定具體原因，供呼叫端（signal_evaluator）寫精確的拒絕記錄。
# 不改 call_json 的回傳型別（仍是 dict|None），呼叫端在收到 None 後立刻呼叫
# last_failure_reason() 取得這次失敗的真正原因，避免「安全過濾」和「API錯誤」混在一起記錄。
_last_failure_reason: str = ""


def last_failure_reason() -> str:
    """回傳上一次 call_json() 失敗的具體原因：safety_block:* / rate_limited / api_error:* / no_key。"""
    return _last_failure_reason


def _provider() -> str | None:
    p = (config.TREND_LLM_PROVIDER or "auto").lower()
    if p == "gemini":
        return "gemini" if config.GEMINI_API_KEY else None
    if p == "anthropic":
        return "anthropic" if config.ANTHROPIC_API_KEY else None
    # auto：免費的 Gemini 優先
    if config.GEMINI_API_KEY:
        return "gemini"
    if config.ANTHROPIC_API_KEY:
        return "anthropic"
    return None


def call_json(
    *,
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    max_tokens: int = 1024,
) -> dict[str, Any] | None:
    """呼叫 LLM，強制回傳符合 schema 的 JSON，解析後回傳 dict。失敗回 None。

    `model` 只在 anthropic 路徑使用；gemini 路徑用 config.TREND_GEMINI_MODEL。
    """
    global _last_failure_reason
    _last_failure_reason = ""
    prov = _provider()
    if prov == "gemini":
        result = _call_gemini(system=system, user=user, schema=schema, max_tokens=max_tokens)
        # Gemini 免費額度常 429/503；若有備用的 ANTHROPIC_API_KEY，立刻切換重試，
        # 不要白白丟掉這次評估機會（safety_block 是刻意跳過，不重試）。
        if result is None and _last_failure_reason.startswith("api_error:") and config.ANTHROPIC_API_KEY:
            print("   🔁 Gemini 失敗，改用 Anthropic 重試")
            result = _call_anthropic(
                model=model, system=system, user=user, schema=schema, max_tokens=max_tokens
            )
        return result
    if prov == "anthropic":
        return _call_anthropic(
            model=model, system=system, user=user, schema=schema, max_tokens=max_tokens
        )
    print("   ⚠️ 無可用 LLM 金鑰（GEMINI_API_KEY / ANTHROPIC_API_KEY 皆未設定）")
    _last_failure_reason = "no_key"
    return None


# ── Gemini（免費）────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict[str, Any] | None:
    """解析 LLM 回傳的 JSON；容忍 markdown 圍欄或前後雜訊。"""
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else None
    except Exception:
        pass
    s, e = text.find("{"), text.rfind("}")
    if 0 <= s < e:
        try:
            v = json.loads(text[s : e + 1])
            return v if isinstance(v, dict) else None
        except Exception:
            pass
    global _last_failure_reason
    print(f"   ⚠️ LLM 回傳非合法 JSON: {text[:120]}")
    _last_failure_reason = "api_error:invalid_json"
    return None


def _call_gemini(
    *, system: str, user: str, schema: dict[str, Any], max_tokens: int
) -> dict[str, Any] | None:
    global _last_gemini_call, _last_failure_reason

    schema_hint = json.dumps(schema, ensure_ascii=False)
    body = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{
            "role": "user",
            "parts": [{
                "text": f"{user}\n\n輸出必須是符合此 JSON Schema 的單一 JSON 物件"
                        f"（不要 markdown 圍欄）：{schema_hint}"
            }],
        }],
        "generationConfig": {
            "responseMimeType": "application/json",
            # 2.5 系列的 thinking token 也算在輸出額度內，給足空間避免空回應
            "maxOutputTokens": max(max_tokens, 2048),
        },
        # 關閉安全過濾器：地緣政治/軍事/經濟新聞是本策略核心輸入，
        # 預設 BLOCK_MEDIUM_AND_ABOVE 會把 Iran/Israel 等合法財經分析擋掉。
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT",        "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH",       "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ],
    }
    url = _GEMINI_URL.format(model=config.TREND_GEMINI_MODEL)
    # key 走 header，不放 URL（避免進日誌）
    headers = {"x-goog-api-key": config.GEMINI_API_KEY, "Content-Type": "application/json"}

    last_err = ""
    for attempt in (1, 2):
        # 免費額度 RPM 限制：與上一次呼叫保持最小間隔
        wait = _GEMINI_MIN_INTERVAL - (time.time() - _last_gemini_call)
        if wait > 0:
            time.sleep(wait)
        _last_gemini_call = time.time()

        try:
            r = requests.post(url, headers=headers, json=body, timeout=60)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue

        if r.status_code == 429:
            last_err = "429 rate limited"
            if config.ANTHROPIC_API_KEY:
                # 有 Claude 備援：不等 30 秒賭限流解除，立刻失敗讓 call_json 切換供應商。
                # 429 多半是每日配額耗盡（等 30 秒也沒用），且每條趨勢等 30 秒 ×
                # 每輪最多 20 條 = 10 分鐘，會撞上 GHA workflow 的 timeout 被砍。
                break
            if attempt == 1:
                print("   ⏳ Gemini 限流（429），30 秒後重試")
                time.sleep(30)
            continue
        if r.status_code != 200:
            last_err = f"HTTP {r.status_code}: {r.text[:160]}"
            if attempt == 1 and r.status_code == 400 and "response" in r.text.lower():
                # 罕見：該版本不吃 responseMimeType → 退回純文字模式再試一次
                body["generationConfig"].pop("responseMimeType", None)
                continue
            break

        try:
            data = r.json()
            candidates = data.get("candidates", [])
            if not candidates:
                # Gemini 偶爾在 prompt-level 過濾時直接回空 candidates（無 finishReason 可查）
                fb = data.get("promptFeedback", {}).get("blockReason", "")
                last_err = f"回傳無候選（promptFeedback={fb or '無'}）: {r.text[:160]}"
                _last_failure_reason = f"safety_block:prompt_feedback:{fb}" if fb else f"api_error:empty_candidates"
                break
            cand = candidates[0]
            finish = cand.get("finishReason", "")
            if finish in ("SAFETY", "RECITATION", "PROHIBITED_CONTENT"):
                # Gemini 安全過濾器觸發（地緣政治/軍事新聞常見）→ 優雅降級
                print(f"   ⚠️ Gemini 安全過濾（{finish}），此趨勢跳過")
                _last_failure_reason = f"safety_block:{finish}"
                return None
            text = cand["content"]["parts"][0]["text"]
        except Exception:
            # 可能被 safety 擋下或回傳結構異常
            last_err = f"回傳結構異常: {r.text[:160]}"
            _last_failure_reason = "api_error:malformed_response"
            break
        return _extract_json(text)

    print(f"   ⚠️ Gemini 呼叫失敗（{config.TREND_GEMINI_MODEL}）: {last_err}")
    if not _last_failure_reason:
        _last_failure_reason = f"api_error:{last_err}"
    return None


# ── Anthropic（計費，品質較高）───────────────────────────────────────────────

@lru_cache(maxsize=1)
def _client():
    import anthropic

    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _call_anthropic(
    *, model: str, system: str, user: str, schema: dict[str, Any], max_tokens: int
) -> dict[str, Any] | None:
    global _last_failure_reason
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
        _last_failure_reason = f"api_error:{type(e).__name__}"
        return None

    text = next(
        (b.text for b in resp.content if getattr(b, "type", None) == "text"), None
    )
    if not text:
        _last_failure_reason = "api_error:empty_response"
        return None
    return _extract_json(text)
