"""Periyodik durum raporu maili: bakiye, acik pozisyon, son islemler, toplam PnL."""
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

import notify
import storage
from btcturk_client import BtcTurkClient

load_dotenv()

REPORT_DAYS = int(os.getenv("REPORT_DAYS", "2"))


def main() -> None:
    client = BtcTurkClient(os.getenv("BTCTURK_API_KEY", ""), os.getenv("BTCTURK_API_SECRET", ""))
    positions = storage.load_positions()
    trade_log = storage.load_trade_log()

    lines = [f"Trade Agent durum raporu — son {REPORT_DAYS} gun", ""]

    try:
        balances = client.get_balances()
        try_balance = next((float(b["free"]) for b in balances if b["asset"] == "TRY"), 0.0)
        lines.append(f"Bosta nakit (TRY): {try_balance:.2f}")
    except Exception as exc:
        try_balance = None
        lines.append(f"Bakiye okunamadi: {exc!r}")

    lines.append("")

    try:
        ticker_data = client.get_ticker_all()
    except Exception:
        ticker_data = []

    if positions:
        lines.append(f"ACIK POZISYONLAR ({len(positions)} adet)")
        for pos in positions:
            ticker = next(
                (t for t in ticker_data if t["pairNormalized"] == pos["symbol"]), None
            )
            last = ticker["last"] if ticker else None
            lines.append(f"  Coin      : {pos['symbol']}")
            lines.append(f"  Giris     : {pos['entry_price']} TRY")
            if last is not None:
                fark_pct = (last - pos["entry_price"]) / pos["entry_price"] * 100
                anlik_pnl = (last - pos["entry_price"]) * pos["quantity"]
                lines.append(f"  Guncel    : {last} TRY  ({fark_pct:+.2f}%)")
                lines.append(f"  Anlik K/Z : {anlik_pnl:+.2f} TRY (henuz gerceklesmedi)")
            lines.append(f"  Stop-loss : {pos['stop_loss_price']} TRY")
            lines.append(f"  Hedef     : {pos['take_profit_price']} TRY")
            lines.append("")
    else:
        lines.append("ACIK POZISYON: yok — bot yeni firsat ariyor.")

    lines.append("")

    cutoff = datetime.now(timezone.utc) - timedelta(days=REPORT_DAYS)
    recent = [
        t for t in trade_log
        if t.get("timestamp", "") and datetime.fromisoformat(t["timestamp"]) >= cutoff
    ]

    lines.append(f"SON {REPORT_DAYS} GUNDEKI ISLEMLER ({len(recent)} adet)")
    if recent:
        for t in recent:
            zaman = t["timestamp"][:16].replace("T", " ")
            if t["side"] == "buy":
                lines.append(f"  {zaman}  ALIM  {t['symbol']} @ {t['price']}")
            else:
                lines.append(
                    f"  {zaman}  SATIS {t['symbol']} @ {t['price']}  "
                    f"({t.get('pnl_try', 0):+.2f} TRY, {t.get('reason', '')})"
                )
    else:
        lines.append("  (bu donemde islem yok)")

    lines.append("")

    kapanan = [t for t in trade_log if t.get("side") == "sell"]
    toplam_pnl = sum(t.get("pnl_try", 0.0) for t in kapanan)
    karli = len([t for t in kapanan if t.get("pnl_try", 0) > 0])
    lines.append("TUM ZAMANLAR")
    lines.append(f"  Kapanan islem : {len(kapanan)}")
    lines.append(f"  Karli / Zararli: {karli} / {len(kapanan) - karli}")
    lines.append(f"  Toplam K/Z    : {toplam_pnl:+.2f} TRY")

    notify.send_mail(
        f"Trade Agent — Durum Raporu ({datetime.now(timezone.utc).strftime('%d.%m.%Y')})",
        "\n".join(lines),
    )


if __name__ == "__main__":
    main()
