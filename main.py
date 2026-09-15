"""Tek 'tick': acik pozisyonlarin stop/target kontrolu, sonra bosta nakit varsa
yeni firsat tarama+karar. Ayni anda birden fazla coin'de pozisyon tutulabilir -
her pozisyon acilista cuzdandaki bosta nakdin bir kismini kullanir, boylece
sermaye tek coine kilitlenmez.
GitHub Actions'ta / cron'da periyodik calistirilmasi icin tasarlandi.
"""
import math
import os

from dotenv import load_dotenv

import market_data
import notify
import risk
import storage
import strategy
from btcturk_client import BtcTurkClient
from decision import decide

load_dotenv()

DRY_RUN = os.getenv("DRY_RUN", "true").lower() != "false"
MAX_CAPITAL_TRY = float(os.getenv("MAX_CAPITAL_TRY", "500"))
# Gunluk zarar durdurma kurali MAX_CAPITAL_TRY buyutulse bile sabit bir tabana
# gore hesaplanir - yoksa pozisyon limiti kaldirilinca guvenlik agi da etkisiz kalir.
DAILY_LOSS_BASE_TRY = float(os.getenv("DAILY_LOSS_BASE_TRY", "500"))
# BtcTurk pariteleri icin tipik minExchangeValue ~100 TRY civarinda - bunun
# altinda bir tutarla alim denemek API'nin reddetmesine yol acar.
MIN_TRADE_TRY = float(os.getenv("MIN_TRADE_TRY", "150"))
# BtcTurk spot tipik oran: %0.2 islem ucreti + %0.04 BSMV (gider vergisi) = %0.24
# toplam, her iki yonde de (al/sat) ayri ayri kesiliyor. Gercek fill verisi yoksa
# (DRY_RUN, ya da LIVE'da fill sorgusu basarisiz olursa) bu oranla tahmin edilir.
BTCTURK_COMMISSION_RATE = float(os.getenv("BTCTURK_COMMISSION_RATE", "0.0024"))


def log(msg: str) -> None:
    prefix = "[DRY_RUN]" if DRY_RUN else "[LIVE]"
    print(f"{prefix} {msg}")


def settlement_try(fills: list[dict], side: str) -> float:
    """Fill listesinden gercek TRY tutarini hesaplar. fee ve tax BtcTurk'ta
    TRY (denominator) cinsinden kesiliyor - numeratorSymbol'den bagimsiz
    (VPS'teki canli hesap verisiyle dogrulandi: fee, islem tutarinin sabit
    %0.2'sine esit cikiyor, coin cinsinden olsaydi oranlar tutmazdi).
    side='buy'  -> cuzdandan cikan net TRY (komisyon+vergi ustune eklenir).
    side='sell' -> cuzdana giren net TRY (komisyon+vergi dusulur)."""
    gross = sum(abs(float(f["amount"])) * float(f["price"]) for f in fills)
    fee_tax = sum(float(f["fee"]) + float(f["tax"]) for f in fills)  # ikisi de negatif
    return round(gross - fee_tax, 2) if side == "buy" else round(gross + fee_tax, 2)


def estimate_settlement_try(gross_try: float, side: str) -> float:
    """settlement_try'in gercek fill verisi olmadan (DRY_RUN, ya da LIVE'da fill
    sorgusu bos donerse) BTCTURK_COMMISSION_RATE'e gore tahmini karsiligi.
    Simulasyon ve canli modun ayni metrigi (net_pnl_try) uretmesi icin var."""
    if side == "buy":
        return round(gross_try * (1 + BTCTURK_COMMISSION_RATE), 2)
    return round(gross_try * (1 - BTCTURK_COMMISSION_RATE), 2)


def handle_position(client: BtcTurkClient, position: dict, ticker_data: list[dict]) -> bool:
    """Acik bir pozisyonun stop/target kontrolunu yapar. Kapandiysa True doner."""
    ticker = next(
        (t for t in ticker_data if t["pairNormalized"] == position["symbol"]), None
    )
    if ticker is None:
        log(f"UYARI: {position['symbol']} icin ticker bulunamadi, bu tick atlaniyor.")
        return False

    last = ticker["last"]
    hit_stop = last <= position["stop_loss_price"]
    hit_target = last >= position["take_profit_price"]

    if not (hit_stop or hit_target):
        log(
            f"Pozisyon acik: {position['symbol']} @ {position['entry_price']}, "
            f"guncel {last}. Bekleniyor."
        )
        return False

    reason = "stop_loss" if hit_stop else "take_profit"
    quantity = position["quantity"]

    if not DRY_RUN:
        # Kayitli "quantity" tahminidir (spend_try/entry_price); gercek cuzdan
        # bakiyesi slipaj/komisyon yuzunden bundan az ya da (nadiren) fazla
        # olabilir. Her durumda cuzdanda o coin'den ne varsa onu sat - kayitli
        # tahmini ust sinir olarak kullanmak (eski min(quantity, wallet_balance)
        # mantigi) tahmin gercek bakiyeden yuksek CIKINCA calisiyordu ama tersi
        # olursa cuzdanda kalici artik biriktirirdi.
        asset = position["symbol"].split("_")[0]
        wallet_balance = next(
            (float(b["free"]) for b in client.get_balances() if b["asset"] == asset), 0.0
        )
        scale = client.get_quantity_scale(position["pair"])
        quantity = math.floor(wallet_balance * 10**scale) / 10**scale

    pnl_try = round((last - position["entry_price"]) * quantity, 2)

    exit_proceeds_try = None
    exit_estimated = True
    if not DRY_RUN:
        order = client.submit_market_order(position["pair"], "sell", quantity)
        fills = client.get_trade_fills(order["id"])
        if fills:
            exit_proceeds_try = settlement_try(fills, "sell")
            exit_estimated = False
    if exit_proceeds_try is None:
        exit_proceeds_try = estimate_settlement_try(quantity * last, "sell")

    entry_cost_try = position.get("entry_cost_try")
    entry_estimated = position.get("entry_cost_estimated", True)
    if entry_cost_try is None:
        entry_cost_try = estimate_settlement_try(quantity * position["entry_price"], "buy")
        entry_estimated = True

    net_pnl_try = round(exit_proceeds_try - entry_cost_try, 2)
    pnl_estimated = entry_estimated or exit_estimated

    log(
        f"{reason.upper()} tetiklendi: {position['symbol']} @ {last}, PnL: {pnl_try} TRY, "
        f"net PnL (komisyon dahil{', TAHMINI' if pnl_estimated else ''}): {net_pnl_try} TRY"
    )

    storage.append_trade(
        {
            "side": "sell",
            "symbol": position["symbol"],
            "price": last,
            "quantity": quantity,
            "pnl_try": pnl_try,
            "exit_proceeds_try": exit_proceeds_try,
            "entry_cost_try": entry_cost_try,
            "net_pnl_try": net_pnl_try,
            "pnl_estimated": pnl_estimated,
            "reason": reason,
        }
    )

    kazanc_kayip = "KAZANC" if pnl_try > 0 else "KAYIP"
    storage.append_lesson(
        "trade_outcome",
        f"{position['symbol']}: {reason} ile kapandi, {pnl_try:+.2f} TRY {kazanc_kayip} "
        f"(giris {position['entry_price']}, cikis {last}). "
        f"{'Bu tarz aday/giris noktasi ise yaradi.' if pnl_try > 0 else 'Bu tarz aday/giris noktasinda dikkatli ol.'}",
    )

    baslik = "KAR ALINDI" if reason == "take_profit" else "ZARAR KESILDI"
    notify.send_mail(
        f"Trade Agent — SATIS: {position['symbol']} ({baslik}) {pnl_try:+.2f} TRY",
        f"Pozisyon kapatildi.\n\n"
        f"Coin      : {position['symbol']}\n"
        f"Sebep     : {baslik}\n"
        f"Giris     : {position['entry_price']} TRY\n"
        f"Cikis     : {last} TRY\n"
        f"Miktar    : {quantity}\n"
        f"Kar/Zarar : {pnl_try:+.2f} TRY\n\n"
        f"Bot simdi bosta kalan nakit icin yeni firsat aramaya devam ediyor.\n"
        f"{'(DRY_RUN - gercek islem degil)' if DRY_RUN else ''}",
    )
    return True


def portfolio_value_try(available_try: float, positions: list[dict], ticker_data: list[dict]) -> float:
    """Bosta TRY + acik pozisyonlarin guncel (ticker'daki 'last' fiyatla
    hesaplanan) TRY karsiligi. Ticker bulunamazsa (nadir) giris fiyatina
    duser - portfoy degerini hafifce yanlis ama makul tutar."""
    positions_value = 0.0
    for p in positions:
        ticker = next((t for t in ticker_data if t["pairNormalized"] == p["symbol"]), None)
        last = ticker["last"] if ticker else p["entry_price"]
        positions_value += p["quantity"] * last
    return round(available_try + positions_value, 2)


def look_for_entry(
    client: BtcTurkClient,
    trade_log: list[dict],
    ticker_data: list[dict],
    held_symbols: set[str],
    positions: list[dict],
) -> dict | None:
    if risk.daily_limit_hit(trade_log, DAILY_LOSS_BASE_TRY):
        log("Gunluk zarar limiti asildi, bugun yeni islem YOK.")
        return None

    available_try = MAX_CAPITAL_TRY if DRY_RUN else client.get_try_balance()
    portfolio_try = portfolio_value_try(available_try, positions, ticker_data)
    spend_try = risk.calculate_spend_try(available_try, portfolio_try)
    if spend_try < MIN_TRADE_TRY:
        log(
            f"Bosta nakit yetersiz/pozisyon+tampon limiti nedeniyle bekleniyor "
            f"(spend={spend_try} TRY, bosta={available_try} TRY, portfoy={portfolio_try} TRY)."
        )
        return None

    candidates = [c for c in strategy.find_candidates(ticker_data) if c["symbol"] not in held_symbols]
    if not candidates:
        log("Kriterlere uyan (ve zaten elde olmayan) aday yok, bekleniyor.")
        return None

    fear_greed = market_data.get_fear_greed()
    news = market_data.get_news_headlines(os.getenv("CRYPTOPANIC_API_KEY"))
    lessons = storage.load_recent_lessons()

    result = decide(candidates, fear_greed, news, lessons, os.getenv("GROQ_API_KEY"))
    storage.append_decision({"candidates": candidates, "fear_greed": fear_greed, "result": result})
    log(f"LLM karari: {result}")

    if result.get("action") != "buy":
        return None

    symbol = result["symbol"]
    candidate = next(c for c in candidates if c["symbol"] == symbol)
    entry_price = candidate["last"]

    pair = next(t["pair"] for t in ticker_data if t["pairNormalized"] == symbol)

    scale = client.get_quantity_scale(pair)
    quantity = round(spend_try / entry_price, scale)

    exits = risk.compute_exit_prices(
        entry_price, result.get("stop_loss_pct", 8), result.get("take_profit_pct", 15)
    )

    log(
        f"ALIM: {symbol} miktar={quantity} fiyat={entry_price} "
        f"stop={exits['stop_loss_price']} hedef={exits['take_profit_price']} "
        f"gerekce: {result.get('reasoning')}"
    )

    entry_cost_try = None
    entry_cost_estimated = True
    if not DRY_RUN:
        # BtcTurk market BUY emri "quantity"yi coin miktari degil, harcanacak TRY
        # tutari olarak bekliyor (SELL'de coin miktari dogru) - API'nin dokumante
        # edilmemis ama yaygin bilinen bir davranisi (FAILED_INVALID_QUANTITY_SCALE).
        order = client.submit_market_order(pair, "buy", spend_try)
        fills = client.get_trade_fills(order["id"])
        if fills:
            entry_cost_try = settlement_try(fills, "buy")
            entry_cost_estimated = False
    if entry_cost_try is None:
        entry_cost_try = estimate_settlement_try(quantity * entry_price, "buy")

    storage.append_trade(
        {
            "side": "buy",
            "symbol": symbol,
            "price": entry_price,
            "quantity": quantity,
            "entry_cost_try": entry_cost_try,
            "entry_cost_estimated": entry_cost_estimated,
        }
    )

    notify.send_mail(
        f"Trade Agent — ALIM: {symbol} @ {entry_price} TRY",
        f"Yeni pozisyon acildi.\n\n"
        f"Coin        : {symbol}\n"
        f"Giris fiyati: {entry_price} TRY\n"
        f"Miktar      : {quantity}\n"
        f"Harcanan    : ~{spend_try} TRY\n"
        f"Stop-loss   : {exits['stop_loss_price']} TRY (%{exits['stop_loss_pct']})\n"
        f"Hedef       : {exits['take_profit_price']} TRY (%{exits['take_profit_pct']})\n\n"
        f"Gerekce: {result.get('reasoning')}\n\n"
        f"{'(DRY_RUN - gercek islem degil)' if DRY_RUN else ''}",
    )

    return {
        "symbol": symbol,
        "pair": pair,
        "entry_price": entry_price,
        "quantity": quantity,
        "entry_cost_try": entry_cost_try,
        "entry_cost_estimated": entry_cost_estimated,
        **exits,
    }


def main() -> None:
    client = BtcTurkClient(os.getenv("BTCTURK_API_KEY", ""), os.getenv("BTCTURK_API_SECRET", ""))
    positions = storage.load_positions()
    trade_log = storage.load_trade_log()
    ticker_data = client.get_ticker_all()

    remaining = []
    for position in positions:
        if not handle_position(client, position, ticker_data):
            remaining.append(position)
    positions = remaining

    held_symbols = {p["symbol"] for p in positions}
    new_position = look_for_entry(client, trade_log, ticker_data, held_symbols, positions)
    if new_position:
        positions.append(new_position)

    storage.save_positions(positions)


if __name__ == "__main__":
    main()
