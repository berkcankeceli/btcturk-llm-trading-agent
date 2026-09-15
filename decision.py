"""LLM karar katmani (Groq, ucretsiz tier). Sadece giris (buy) kararini verir -
cikis (stop-loss/take-profit) risk.py'de sabit kurallarla, LLM'e birakilmadan yapilir.
"""
import json

import requests

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-120b"

SYSTEM_PROMPT = """Sen temkinli bir kripto spot trading analistisin. Kaldirac yok, kucuk sermaye var.
Sana teknik olarak on-filtrelenmis (yukselen ama tepe noktasinda olmayan) coin adaylari,
genel piyasa duyarliligi (Fear&Greed), genel haber basliklari ve gecmis islemlerden
cikarilan dersler verilecek.
Gorevin: bu adaylardan EN FAZLA BIRINI almaya deger mi karar vermek, yoksa beklemek mi.
Belirli bir kisinin/kurumun anlik tweetine dayanma - sana verilen veriyle sinirli kal.
Emin degilsen "hold" de - sermaye kucuk, gereksiz islem ucret kaybi demek.
Eger 'gecmis_dersler' listesinde bir hata veya kayip paterni varsa, onu tekrarlamamaya
ozellikle dikkat et; kazandiran paternler varsa onlara benzer firsatlari daha olumlu degerlendir.

SADECE gecerli JSON dondur, baska hicbir metin yazma:
{"action": "buy" veya "hold", "symbol": "ADAY_SYMBOL veya null", "stop_loss_pct": 6-10 arasi sayi, "take_profit_pct": 10-20 arasi sayi, "reasoning": "kisa gerekce (max 2 cumle, Turkce)"}
"""


def decide(
    candidates: list[dict], fear_greed: dict, news: list[str], lessons: list[dict], api_key: str
) -> dict:
    user_content = json.dumps(
        {
            "adaylar": candidates,
            "fear_greed_index": fear_greed,
            "genel_haber_basliklari": news,
            "gecmis_dersler": [
                {"baglam": l["context"], "ne_oldu": l["what_happened"]} for l in lessons
            ],
        },
        ensure_ascii=False,
    )

    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        },
        timeout=30,
    )
    resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    parsed = json.loads(raw)

    # Guvenlik: LLM'in uydurdugu sembolu degil, sadece bize verilen adaylar listesindeki
    # bir sembolu kabul ediyoruz.
    valid_symbols = {c["symbol"] for c in candidates}
    if parsed.get("action") == "buy" and parsed.get("symbol") not in valid_symbols:
        parsed["action"] = "hold"
        parsed["reasoning"] = "LLM gecersiz sembol dondurdu, guvenlik icin hold'a cevrildi."
    return parsed
