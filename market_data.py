"""Piyasa bağlamı: Fear&Greed endeksi ve (opsiyonel) genel haber akışı.

Not: burada tek bir kişinin/kurumun tweet'ini takip etmiyoruz - bu bütçe ve
kontrol sıklığıyla (30dk'da bir) o yarışa girmek anlamsız, haber zaten
fiyata yansımış oluyor. Amaç genel piyasa havasını LLM'e bağlam olarak vermek.
"""
import requests


def get_fear_greed() -> dict:
    try:
        resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        resp.raise_for_status()
        item = resp.json()["data"][0]
        return {"value": int(item["value"]), "label": item["value_classification"]}
    except Exception as e:
        return {"value": None, "label": f"alinamadi: {e}"}


def get_news_headlines(cryptopanic_api_key: str | None, limit: int = 8) -> list[str]:
    if not cryptopanic_api_key:
        return []
    try:
        resp = requests.get(
            "https://cryptopanic.com/api/v1/posts/",
            params={"auth_token": cryptopanic_api_key, "public": "true", "kind": "news"},
            timeout=10,
        )
        resp.raise_for_status()
        posts = resp.json().get("results", [])[:limit]
        return [p["title"] for p in posts]
    except Exception:
        return []
