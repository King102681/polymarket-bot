# -*- coding: utf-8 -*-
"""門檻參數重掃：離線重放 signals.jsonl，回答「調到多鬆才有單」。

方法：
  1. 對每個策略，把原始訊號重新走一遍「離線可算」的過濾關卡：
     黑名單 → whale_filter → min_size → 類別 → 運動 → 價格(用 whale_price 代理) → min_follow
  2. 「離線不可算」的關卡（市場已關/距結算/訂單簿）用歷史存活率修正：
     從 rejected_*.jsonl 統計「到達市場查詢階段的訊號中，活過 時間+訂單簿 關卡的比例」，
     只用 2026-06-22（cron-job.org 修復排程）之後的資料，避開舊時代的延遲失真。
  3. 輸出：每組門檻的 預估通過數/週（上限值 × 存活率）。

已知偏差（讀報告前必看）：
  - 價格用 whale_price 當進場價代理。實際進場價是「輪詢時的 best ask +0.5%」，
    市場重定價快的單會比 whale_price 貴 → 本報告的通過數是「樂觀上限」。
  - 存活率是舊門檻下的歷史統計，門檻放寬後到達後段關卡的訊號組成會變，修正只是近似。

用法（repo 根目錄）： python -m scripts.run_threshold_sweep
輸出： data/backtest/threshold_sweep_report.md
"""
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from whale_copy.market_classifier import classify
from whale_copy.sport_classifier import sport_type
from whale_copy.strategies import STRATEGIES
from whale_copy.signal_generator import WHALE_BLACKLIST, MIN_BET_USDC

DATA = Path(__file__).resolve().parent.parent / "data"
RELIABLE_SINCE = 1782000000  # 2026-06-22 前後 cron-job.org 修復排程（見 memory/CLAUDE.md）
GLOBAL_FOLLOW_RATIO = 0.001  # config.WHALE_FOLLOW_RATIO（避免 import core.config 需要 .env）
GLOBAL_MAX_BET = 10.0

# 每策略的掃描網格
SIZE_GRID = [10, 25, 50, 100, 250, 500, 1000]
PRICE_GRID = {
    "political":   [(0.20, 0.87), (0.10, 0.90), (0.20, 0.95)],
    "sports_live": [(0.70, 0.97), (0.50, 0.97), (0.30, 0.97)],
    "soccer":      [(0.55, 0.80), (0.40, 0.80), (0.55, 0.90), (0.30, 0.95)],
    "open":        [(0.15, 0.95), (0.05, 0.99)],
}
# political 額外掃鯨魚名單：目前白名單 vs 全部鯨魚（後者僅看訊號量，edge 未驗證！）
POLITICAL_WHALE_VARIANTS = {"目前白名單(2隻)": True, "全部鯨魚(edge未驗證)": False}

# whales.json 裡 pseudonym -> wallet
def load_whale_map():
    with open(DATA / "whales.json", encoding="utf-8") as f:
        whales = json.load(f)
    return {w["pseudonym"]: w["proxy_wallet"] for w in whales}


def load_signals():
    seen, out = set(), []
    with open(DATA / "signals.jsonl", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            s = json.loads(line)
            tx = s.get("transaction_hash")
            if not tx or tx in seen or s.get("side") != "BUY":
                continue
            seen.add(tx)
            # 預先算好重複使用的欄位
            s["_usdc"] = float(s["whale_price"]) * float(s["whale_size"])
            s["_cat"] = classify(s.get("market_slug"), s.get("market_title"))
            s["_sport"] = sport_type(s.get("market_slug"), s.get("market_title"))
            out.append(s)
    return out


def offline_pass(sig, strat, whale_names, min_size, pmin, pmax, use_whale_filter=True):
    """重放離線可算的關卡，回傳 True=通過。"""
    if sig["whale_wallet"] in WHALE_BLACKLIST:
        return False
    if use_whale_filter and strat.whale_filter:
        if sig["whale_pseudonym"] not in whale_names:
            return False
    if sig["_usdc"] < min_size:
        return False
    if strat.allowed_categories and sig["_cat"] not in strat.allowed_categories:
        return False
    if strat.sport_filter and sig["_sport"] not in strat.sport_filter:
        return False
    p = float(sig["whale_price"])  # 進場價代理（樂觀）
    if not (pmin <= p <= pmax):
        return False
    # 最後一關：min_follow（隱藏門檻）
    ratio = strat.follow_ratio or GLOBAL_FOLLOW_RATIO
    max_bet = strat.max_bet_usdc or GLOBAL_MAX_BET
    min_follow = strat.min_follow_usdc or MIN_BET_USDC
    target = min(sig["_usdc"] * ratio, max_bet)
    if target < min_follow:
        return False
    return True


# 「時間+市場狀態+訂單簿」關卡的歷史存活率（只算排程修復後的資料）
TIME_STAGE = ("距結算", "市場已關閉", "訂單簿", "orderbook")
LATE_STAGE = ("entry", "建議金額", "進場時剩")  # 到達過時間關卡且活過的證據

def survival_factor(name, tx_ts):
    reached = died = 0
    p = DATA / f"rejected_{name}.jsonl"
    if not p.exists():
        return None, 0
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = tx_ts.get(r.get("signal_tx_hash"))
            if ts is None or ts < RELIABLE_SINCE:
                continue
            reason = r.get("reason", "")
            if any(k in reason for k in TIME_STAGE):
                reached += 1
                died += 1
            elif any(k in reason for k in LATE_STAGE):
                reached += 1
    if reached == 0:
        return None, 0
    return 1 - died / reached, reached


def main():
    t0 = time.time()
    signals = load_signals()
    whale_map = load_whale_map()
    ts_all = [s.get("trade_ts") or s["detected_at"] for s in signals]
    span_weeks = (max(ts_all) - min(ts_all)) / 86400 / 7
    tx_ts = {s["transaction_hash"]: (s.get("trade_ts") or s["detected_at"]) for s in signals}

    L = []
    add = L.append
    add("# 策略A 門檻參數重掃報告")
    add(f"- 資料：signals.jsonl 去重後 {len(signals):,} 筆 BUY 訊號，跨度 {span_weeks:.1f} 週")
    add(f"- 產生時間：{time.strftime('%Y-%m-%d %H:%M')}")
    add("- ⚠️ 通過數用 whale_price 當進場價代理 = **樂觀上限**；「修正後/週」已乘上")
    add("  排程修復後(2026-06-22+)的時間/訂單簿關卡歷史存活率，仍是近似值。")
    add("- ⚠️ 放寬 whale_filter 的變體只代表訊號量，**該鯨魚池的 edge 未經回測驗證**，不可直接採用。")
    add("")

    for name, strat in STRATEGIES.items():
        surv, n_reached = survival_factor(name, tx_ts)
        surv_txt = f"{surv:.0%}（樣本 {n_reached:,}）" if surv is not None else "無資料，未修正"
        add(f"## {name}（{strat.display_name}）")
        eff_min = (strat.min_follow_usdc or MIN_BET_USDC) / (strat.follow_ratio or GLOBAL_FOLLOW_RATIO)
        add(f"- 現行門檻：min_size ${strat.min_size_usdc:.0f}，price [{strat.min_price}, {strat.max_price}]，"
            f"whale_filter {strat.whale_filter or '全部'}")
        add(f"- **min_follow 隱藏門檻：鯨魚單需 ≥ ${eff_min:,.0f} 才過最後一關**"
            + ("　⚠️ 高於 min_size，實際卡點在這裡" if eff_min > strat.min_size_usdc else "（不構成額外限制）"))
        add(f"- 時間/訂單簿關卡存活率（排程修復後）：{surv_txt}")
        add("")

        variants = POLITICAL_WHALE_VARIANTS if name == "political" else {"現行鯨魚名單": True}
        for vname, use_wf in variants.items():
            add(f"### 鯨魚名單：{vname}")
            add("| min_size \\ price | " + " | ".join(f"[{a},{b}]" for a, b in PRICE_GRID[name]) + " |")
            add("|---|" + "---|" * len(PRICE_GRID[name]))
            for ms in SIZE_GRID:
                cells = []
                for (pmin, pmax) in PRICE_GRID[name]:
                    n = sum(1 for s in signals
                            if offline_pass(s, strat, set(strat.whale_filter), ms, pmin, pmax, use_wf))
                    per_wk = n / span_weeks
                    adj = per_wk * surv if surv is not None else per_wk
                    mark = " ←現行" if (ms == strat.min_size_usdc and (pmin, pmax) == (strat.min_price, strat.max_price)) else ""
                    cells.append(f"{n}（{adj:.1f}/週）{mark}")
                add(f"| ${ms} | " + " | ".join(cells) + " |")
            add("")

        # 目前門檻下，各鯨魚貢獻（看訊號集中度）
        contrib = Counter()
        for s in signals:
            if offline_pass(s, strat, set(strat.whale_filter), strat.min_size_usdc,
                            strat.min_price, strat.max_price):
                contrib[s["whale_pseudonym"]] += 1
        if contrib:
            add("現行門檻下通過訊號的鯨魚分佈：" +
                "、".join(f"{k} {v}" for k, v in contrib.most_common(8)))
        add("")

    out = DATA / "backtest" / "threshold_sweep_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"\n[完成 {time.time()-t0:.1f}s] 報告：{out}")


if __name__ == "__main__":
    main()
