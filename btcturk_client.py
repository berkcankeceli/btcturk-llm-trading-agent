"""BtcTurk Pro API istemcisi. Kaynak: https://github.com/BTCTrader/broker-api-docs (README-pro.md)"""
import base64
import hashlib
import hmac
import time

import requests

BASE_URL = "https://api.btcturk.com"


class BtcTurkClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def _auth_headers(self) -> dict:
        stamp = str(int(time.time()) * 1000)
        secret_decoded = base64.b64decode(self.api_secret)
        data = f"{self.api_key}{stamp}".encode("utf-8")
        signature = hmac.new(secret_decoded, data, hashlib.sha256).digest()
        return {
            "X-PCK": self.api_key,
            "X-Stamp": stamp,
            "X-Signature": base64.b64encode(signature).decode("utf-8"),
        }

    def get_ticker_all(self) -> list[dict]:
        """Kimlik doğrulama gerektirmeyen public uç nokta. Tüm paritelerin 24s verisini döner."""
        resp = requests.get(f"{BASE_URL}/api/v2/ticker", timeout=15)
        resp.raise_for_status()
        return resp.json()["data"]

    def get_quantity_scale(self, pair: str) -> int:
        """pair: 'BTCTRY' gibi (alt cizgisiz). Miktarin kac ondalikla verilmesi gerektigini doner."""
        resp = requests.get(f"{BASE_URL}/api/v2/server/exchangeinfo", timeout=15)
        resp.raise_for_status()
        for s in resp.json()["data"]["symbols"]:
            if s["name"] == pair:
                return s["numeratorScale"]
        return 6  # bulunamazsa guvenli varsayilan

    def get_balances(self) -> list[dict]:
        resp = requests.get(
            f"{BASE_URL}/api/v1/users/balances", headers=self._auth_headers(), timeout=15
        )
        resp.raise_for_status()
        return resp.json()["data"]

    def get_try_balance(self) -> float:
        for b in self.get_balances():
            if b["asset"] == "TRY":
                return float(b["free"])
        return 0.0

    def submit_market_order(self, pair_symbol: str, order_type: str, quantity: float) -> dict:
        """order_type: 'buy' veya 'sell'. Market emri, price parametresi yok sayılır.
        DIKKAT: bu cevaptaki 'price'/'quantity' gerceklesen tutari YANSITMAZ -
        submit edilen emrin parametreleridir. Gercek tutar icin get_trade_fills kullan."""
        body = {
            "quantity": quantity,
            "orderMethod": "market",
            "orderType": order_type,
            "pairSymbol": pair_symbol,
        }
        resp = requests.post(
            f"{BASE_URL}/api/v1/order",
            headers=self._auth_headers(),
            json=body,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["data"]

    def get_trade_fills(self, order_id: int) -> list[dict]:
        """Bir siparise (orderId) ait gerceklesen fill'leri doner. Market emri
        birden fazla fill'e bolunebilir; gercek TRY tutari bunlarin toplamindan
        hesaplanmali. Endpoint orderId ile filtrelenemiyor (BtcTurk API kisiti),
        bu yuzden son islemler cekilip client tarafinda filtreleniyor."""
        resp = requests.get(
            f"{BASE_URL}/api/v1/users/transactions/trade",
            headers=self._auth_headers(),
            timeout=15,
        )
        resp.raise_for_status()
        trades = resp.json()["data"]
        return [t for t in trades if t.get("orderId") == order_id]
