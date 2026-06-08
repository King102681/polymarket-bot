"""足球專項回測：判斷鯨魚的足球下注是「真 alpha」還是「跟著賠率走」。

核心指標
  edge = 實際勝率 − 平均進場價（市場隱含勝率）
    > 0  鯨魚比市場聰明（選對被低估的隊）→ 跟單有意義
    ≈ 0  只是反映賠率（押熱門必中但 ROI 低）→ 跟單無意義
    < 0  高估自己 → 別跟

入場頻率（判斷「選擇性 vs 全押」）
  bets_per_match       每場下幾個盤口（1=單盤口；3+=勝負+大小+讓分全下）
  matches_per_matchday 每個比賽日下幾場（高=接近把當天整個聯賽全押）
  reload_ratio         加倉率（同一盤口多次 BUY 的比例，信念強度）
  big_match_ratio      大單($500+)覆蓋的場次比例（越低=越挑場次=越有選擇性）

執行：python -m scripts.run_soccer_backtest          （只跑 swisstony）
      python -m scripts.run_soccer_backtest WALLET   （加跑指定錢包）
"""
import sys, json, re, time, statistics
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import core  # noqa  DNS patch + UTF-8
sys.stdout.reconfigure(encoding="utf-8")

from backtest.pull_historical import fetch_all_trades, fetch_markets_for_conditions
from backtest.fees import DEFAULT_SLIPPAGE_RATIO as TAKER_FEE
from whale_copy.sport_classifier import sport_type, is_world_cup

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_BT_DIR   = _DATA_DIR / "backtest"
_OUT_PATH = _BT_DIR / "soccer_backtest.json"

LOOKBACK_DAYS = 90
FOLLOW_RATIO  = 0.001
MAX_BET_USDC  = 10.0
MIN_BET_USDC  = 1.0
BIG_BET_USDC  = 500.0

SWISSTONY = ("swisstony", "0x204f72f35326db932158cba6adff0b9a1da95e14")

_DATE_RE = re.compile(r"^(.+?-\d{4}-\d{2}-\d{2})")   # 抓到日期結尾＝一場比賽
_ONLY_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _base_match(slug: str) -> str:
    """fif-bul-mon-2026-06-01-bul → fif-bul-mon-2026-06-01（一場比賽）"""
    m = _DATE_RE.match(slug or "")
    return m.group(1) if m else (slug or "")


def _matchday(slug: str) -> str:
    """fif-bul-mon-2026-06-01-bul → fif|2026-06-01（一個比賽日×聯賽）"""
    s = slug or ""
    league = s.split("-", 1)[0] if s else "?"
    m = _ONLY_DATE_RE.search(s)
    return f"{league}|{m.group(1) if m else '?'}"


def _winning_outcome(market: dict) -> str | None:
    for tk in (market.get("tokens") or []):
        if tk.get("winner") is True or float(tk.get("price") or 0) >= 0.99:
            return tk.get("outcome")
    return None


def _won(trade: dict, market: dict) -> bool | None:
    """回傳 True/False（贏/輸），或 None（無法判定）。"""
    if not market.get("closed"):
        return None
    win_out = _winning_outcome(market)
    if not win_out:
        return None
    t_out = (trade.get("outcome") or trade.get("outcomeName") or "")
    if not t_out:
        return None
    return t_out.strip().lower() == win_out.strip().lower()


def _slug(t: dict) -> str:
    return t.get("slug") or t.get("market_slug") or t.get("eventSlug") or ""


def _title(t: dict) -> str:
    return t.get("title") or t.get("market_title") or ""


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "sum": 0.0, "mean": 0.0}
    return {"n": len(vals), "sum": round(sum(vals), 2), "mean": round(statistics.mean(vals), 4)}


def analyze(pseudonym: str, trades: list[dict], markets: dict[str, dict]) -> dict:
    """對一隻鯨魚的足球交易做完整分析。"""
    buys = [t for t in trades if (t.get("side") or "").upper() == "BUY"]
    soccer = [t for t in buys if sport_type(_slug(t), _title(t)) == "soccer"]

    def cost(t):
        return float(t.get("price", 0) or 0) * float(t.get("size", 0) or 0)

    # ── 規模/覆蓋 ──────────────────────────────────────────────────
    n_buys      = len(soccer)
    invested    = sum(cost(t) for t in soccer)
    markets_set = {t.get("conditionId") for t in soccer if t.get("conditionId")}
    match_set   = {_base_match(_slug(t)) for t in soccer if _slug(t)}
    mday_set    = {_matchday(_slug(t)) for t in soccer if _slug(t)}

    big = [t for t in soccer if cost(t) >= BIG_BET_USDC]
    big_match_set = {_base_match(_slug(t)) for t in big if _slug(t)}

    # ── edge（全部已結算 vs 大單已結算）─────────────────────────────
    def edge_block(subset: list[dict]) -> dict:
        rows = []
        for t in subset:
            cid = t.get("conditionId", "")
            m = markets.get(cid)
            if not m:
                continue
            w = _won(t, m)
            if w is None:
                continue
            rows.append((float(t.get("price", 0) or 0), w, cost(t)))
        if not rows:
            return {"n": 0}
        win_rate  = sum(1 for _, w, _ in rows if w) / len(rows)
        avg_entry = statistics.mean(p for p, _, _ in rows)
        # 投入加權勝率（大單押對更重要）
        tot_c = sum(c for _, _, c in rows) or 1
        w_win = sum(c for _, w, c in rows if w) / tot_c
        w_entry = sum(p * c for p, _, c in rows) / tot_c
        return {
            "n": len(rows),
            "win_rate": round(win_rate, 4),
            "avg_entry_price": round(avg_entry, 4),
            "edge": round(win_rate - avg_entry, 4),
            "weighted_win_rate": round(w_win, 4),
            "weighted_entry": round(w_entry, 4),
            "weighted_edge": round(w_win - w_entry, 4),
        }

    # ── 跟單模擬（只跟大單）────────────────────────────────────────
    follow_pnl = follow_cost = 0.0
    follow_n = follow_wins = 0
    for t in big:
        cid = t.get("conditionId", "")
        m = markets.get(cid)
        if not m:
            continue
        w = _won(t, m)
        if w is None:
            continue
        price = float(t.get("price", 0) or 0)
        if price <= 0:
            continue
        fc = min(cost(t) * FOLLOW_RATIO, MAX_BET_USDC)
        if fc < MIN_BET_USDC:
            continue
        shares = fc / price
        fee = fc * TAKER_FEE
        follow_pnl  += (shares - fc - fee) if w else (-fc - fee)
        follow_cost += fc
        follow_n    += 1
        follow_wins += 1 if w else 0

    # ── 世界盃專項 ─────────────────────────────────────────────────
    wc = [t for t in soccer if is_world_cup(_slug(t), _title(t))]

    n_matches = len(match_set) or 1
    n_mdays   = len(mday_set) or 1

    return {
        "pseudonym": pseudonym,
        "soccer_buys": n_buys,
        "invested_usdc": round(invested, 0),
        "avg_bet_usdc": round(invested / n_buys, 1) if n_buys else 0,
        "distinct_markets": len(markets_set),   # 不同盤口
        "distinct_matches": len(match_set),     # 不同場次
        "distinct_matchdays": len(mday_set),    # 不同比賽日
        # 入場頻率
        "bets_per_match": round(len(markets_set) / n_matches, 2),
        "matches_per_matchday": round(len(match_set) / n_mdays, 2),
        "reload_ratio": round(1 - len(markets_set) / n_buys, 3) if n_buys else 0,
        # 大單
        "big_bets": len(big),
        "big_matches": len(big_match_set),
        "big_match_ratio": round(len(big_match_set) / n_matches, 3),
        "big_invested": round(sum(cost(t) for t in big), 0),
        # edge
        "edge_all": edge_block(soccer),
        "edge_big": edge_block(big),
        # 跟單
        "follow": {
            "n": follow_n,
            "wins": follow_wins,
            "win_rate": round(follow_wins / follow_n, 3) if follow_n else 0,
            "pnl": round(follow_pnl, 2),
            "cost": round(follow_cost, 2),
            "roi": round(follow_pnl / follow_cost, 4) if follow_cost else 0,
        },
        # 世界盃
        "world_cup_buys": len(wc),
    }


def _print_report(reports: list[dict]) -> None:
    for r in reports:
        print(f"\n{'='*68}")
        print(f"  ⚽ {r['pseudonym']}  足球專項回測（過去 {LOOKBACK_DAYS} 天可拉範圍）")
        print(f"{'='*68}")
        print(f"  下注筆數      {r['soccer_buys']:>6d}    總投入  ${r['invested_usdc']:>12,.0f}")
        print(f"  平均單筆      ${r['avg_bet_usdc']:>5,.1f}    世界盃筆數  {r['world_cup_buys']:>6d}")
        print(f"  {'-'*64}")
        print(f"  不同盤口      {r['distinct_markets']:>6d}")
        print(f"  不同場次      {r['distinct_matches']:>6d}    不同比賽日  {r['distinct_matchdays']:>6d}")
        print(f"\n  📊 入場頻率（選擇性 vs 全押）")
        print(f"     每場下幾個盤口      {r['bets_per_match']:>5.2f}   (1=單盤口, 3+=勝負+大小+讓分全下)")
        print(f"     每比賽日下幾場      {r['matches_per_matchday']:>5.2f}   (越高越接近全押當天聯賽)")
        print(f"     加倉率              {r['reload_ratio']:>5.1%}   (同盤口重複下注比例=信念)")
        print(f"     大單覆蓋場次比      {r['big_match_ratio']:>5.1%}   (越低=越挑場次=越有選擇性)")
        print(f"     大單: {r['big_bets']} 筆 / {r['big_matches']} 場   投入 ${r['big_invested']:,.0f}")

        ea, eb = r["edge_all"], r["edge_big"]
        print(f"\n  🎯 EDGE（實際勝率 − 進場價；>0 才有跟單價值）")
        if ea.get("n"):
            print(f"     全部足球(n={ea['n']:>4d})  勝率={ea['win_rate']:>5.1%}  進場價={ea['avg_entry_price']:>5.1%}  "
                  f"edge={ea['edge']:>+6.1%}")
        else:
            print(f"     全部足球：無已結算樣本")
        if eb.get("n"):
            print(f"     大單足球(n={eb['n']:>4d})  勝率={eb['win_rate']:>5.1%}  進場價={eb['avg_entry_price']:>5.1%}  "
                  f"edge={eb['edge']:>+6.1%}")
            print(f"     大單(投入加權)    勝率={eb['weighted_win_rate']:>5.1%}  進場價={eb['weighted_entry']:>5.1%}  "
                  f"edge={eb['weighted_edge']:>+6.1%}")
        else:
            print(f"     大單足球：無已結算樣本")

        f = r["follow"]
        print(f"\n  💰 跟單模擬（只跟大單, ×{FOLLOW_RATIO}, cap ${MAX_BET_USDC:.0f}）")
        print(f"     n={f['n']}  勝率={f['win_rate']:.1%}  PnL=${f['pnl']:+.2f}  "
              f"成本=${f['cost']:.2f}  ROI={f['roi']:+.1%}")


def main():
    _BT_DIR.mkdir(parents=True, exist_ok=True)
    extra = [(f"wallet_{w[:6]}", w) for w in sys.argv[1:]]
    targets = [SWISSTONY] + extra
    since = int(time.time()) - LOOKBACK_DAYS * 86400

    # 拉所有目標的交易，集中查市場結算（共用快取）
    all_trades: dict[str, list] = {}
    all_cids: set[str] = set()
    for name, wallet in targets:
        print(f"📡 拉 {name} 交易...")
        trades = fetch_all_trades(wallet, since)
        all_trades[name] = trades
        for t in trades:
            if (t.get("side") or "").upper() == "BUY" and sport_type(_slug(t), _title(t)) == "soccer":
                cid = t.get("conditionId")
                if cid:
                    all_cids.add(cid)
        print(f"   {len(trades)} 筆，足球盤口 condition {len(all_cids)} 個（累計）")

    print(f"\n📡 查 {len(all_cids)} 個足球市場結算...")
    markets = fetch_markets_for_conditions(list(all_cids))
    closed = sum(1 for m in markets.values() if m.get("closed"))
    print(f"   {len(markets)} 個（已結算 {closed}）")

    reports = [analyze(name, all_trades[name], markets) for name, _ in targets]
    _print_report(reports)

    _OUT_PATH.write_text(json.dumps({
        "generated_at": int(time.time()),
        "lookback_days": LOOKBACK_DAYS,
        "reports": reports,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ 報告已存 → {_OUT_PATH}")


if __name__ == "__main__":
    main()
