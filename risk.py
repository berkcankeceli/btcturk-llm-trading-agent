"""Risk kurallari - koda gomulu, LLM'e birakilmaz. LLM sadece 'hangi coin' der,
ne kadar alinacagini ve nerede cikilacagini burasi belirler."""
import os
from datetime import datetime, timezone

# Pozisyon buyuklugu bosta duran TRY'ye degil, TOPLAM PORTFOY degerine (bosta
# TRY + acik pozisyonlarin guncel TRY karsiligi) baglanir. Amac: her satistan
# sonra otomatik olarak sermayenin tamamiyla yeniden pozisyona girmemek.
POSITION_SIZE_PCT = float(os.getenv("POSITION_SIZE_PCT", "0.40"))
# Islem sonrasi kalan nakit portfoyun bu oranin altina dusecekse alim
# kisitlanir (hic yapilmaz degil - MIN_TRADE_TRY kontrolu main.py'de zaten
# cok kucuk tutarlari elemeye devam eder).
MIN_CASH_BUFFER_PCT = float(os.getenv("MIN_CASH_BUFFER_PCT", "0.15"))
MIN_STOP_LOSS_PCT = 4.0
MAX_STOP_LOSS_PCT = 15.0
MIN_TAKE_PROFIT_PCT = 8.0
MAX_TAKE_PROFIT_PCT = 30.0
DAILY_LOSS_LIMIT_PCT = 10.0  # gunluk bu orani asan net zararda bot durur


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def calculate_spend_try(available_try: float, portfolio_value_try: float) -> float:
    """Hedef: portfoy_degeri * POSITION_SIZE_PCT. Ama (a) elde o kadar bosta
    TRY yoksa available_try ile sinirlanir, (b) islem sonrasi kalan nakit
    portfoyun MIN_CASH_BUFFER_PCT'sinin altina dusecekse spend o kadar
    kisilir (tamponun altina asla inilmez)."""
    target = portfolio_value_try * POSITION_SIZE_PCT
    max_by_cash_buffer = available_try - portfolio_value_try * MIN_CASH_BUFFER_PCT
    spend = min(target, available_try, max(max_by_cash_buffer, 0.0))
    return round(spend, 2)


def compute_exit_prices(entry_price: float, stop_loss_pct: float, take_profit_pct: float) -> dict:
    stop_loss_pct = clamp(stop_loss_pct, MIN_STOP_LOSS_PCT, MAX_STOP_LOSS_PCT)
    take_profit_pct = clamp(take_profit_pct, MIN_TAKE_PROFIT_PCT, MAX_TAKE_PROFIT_PCT)
    return {
        "stop_loss_price": round(entry_price * (1 - stop_loss_pct / 100), 8),
        "take_profit_price": round(entry_price * (1 + take_profit_pct / 100), 8),
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
    }


def daily_realized_pnl_try(trade_log: list[dict]) -> float:
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(
        t.get("pnl_try", 0.0)
        for t in trade_log
        if t.get("timestamp", "").startswith(today) and t.get("side") == "sell"
    )


def daily_limit_hit(trade_log: list[dict], max_capital_try: float) -> bool:
    loss = -daily_realized_pnl_try(trade_log)
    return loss > max_capital_try * (DAILY_LOSS_LIMIT_PCT / 100)
