"""Basit momentum + geri çekilme (pullback) filtresi.

Amac: son 24 saatte yukselen ama tam tepe noktasinda olmayan (biraz sogumus,
retest bekleyen) coinleri kisa listeye almak. Ciplak "en cok yukseleni al"
tuzagina dusmemek icin.
"""

MIN_DAILY_PERCENT = 5.0
MIN_PULLBACK_RATIO = 0.15   # gunun tepesinden en az bu kadar geri cekilmis olmali
MAX_PULLBACK_RATIO = 0.75   # ama gunun dibine kadar da cokmemis olmali
TOP_N = 5


def find_candidates(ticker_data: list[dict]) -> list[dict]:
    candidates = []
    for t in ticker_data:
        if t.get("denominatorSymbol") != "TRY":
            continue
        high, low, last = t.get("high", 0), t.get("low", 0), t.get("last", 0)
        daily_percent = t.get("dailyPercent", 0)
        if high <= 0 or high == low or daily_percent < MIN_DAILY_PERCENT:
            continue
        pullback_ratio = (high - last) / (high - low)
        if not (MIN_PULLBACK_RATIO <= pullback_ratio <= MAX_PULLBACK_RATIO):
            continue
        candidates.append(
            {
                "symbol": t["pairNormalized"],
                "last": last,
                "daily_percent": daily_percent,
                "pullback_ratio": round(pullback_ratio, 3),
                "volume": t.get("volume", 0),
            }
        )
    candidates.sort(key=lambda c: c["daily_percent"], reverse=True)
    return candidates[:TOP_N]
