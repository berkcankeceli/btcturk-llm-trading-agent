"""Durum ve log yonetimi. SQLite yerine duz JSON/JSONL - git'e commit edilip
GitHub Actions calistirmalari arasinda kalici olmasi kolay olsun diye.

lessons.jsonl: 'hata hafizasi' + 'sonuc hafizasi' (alpaca-agent'taki ayni
mekanizma). main.py her pozisyon kapandiginda (kazandi/kaybetti farketmeksizin)
buraya bir not yazar, decision.py bir sonraki LLM promptuna bu derslerin
ozetini ekler. Amac: pahali bir modele gecmeden, ucretsiz modeli kendi
gercek sonuclarimizla 'egitmek'."""
import json
import os
from datetime import datetime, timezone

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(_BASE_DIR, "state.json")
TRADE_LOG_FILE = os.path.join(_BASE_DIR, "trade_log.jsonl")
DECISION_LOG_FILE = os.path.join(_BASE_DIR, "decision_log.jsonl")
LESSONS_FILE = os.path.join(_BASE_DIR, "lessons.jsonl")


def load_positions() -> list[dict]:
    """Acik pozisyonlar listesi. Eski format (tek dict) otomatik listeye gocuruluyor."""
    if not os.path.exists(STATE_FILE):
        return []
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and data:
        return [data]
    return []


def save_positions(positions: list[dict]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)


def _append_jsonl(path: str, entry: dict) -> None:
    entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_trade_log() -> list[dict]:
    if not os.path.exists(TRADE_LOG_FILE):
        return []
    with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_trade(entry: dict) -> None:
    _append_jsonl(TRADE_LOG_FILE, entry)


def append_decision(entry: dict) -> None:
    _append_jsonl(DECISION_LOG_FILE, entry)


def append_lesson(context: str, what_happened: str) -> None:
    """context: hangi asamada/tur (orn. 'trade_outcome', 'submit_market_order').
    what_happened: kisa aciklama, LLM'in okuyacagi sekilde Turkce."""
    _append_jsonl(LESSONS_FILE, {"context": context, "what_happened": what_happened})
    print(f"[LESSON] {context}: {what_happened}")


def load_recent_lessons(limit: int = 10) -> list[dict]:
    if not os.path.exists(LESSONS_FILE):
        return []
    with open(LESSONS_FILE, "r", encoding="utf-8") as f:
        lessons = [json.loads(line) for line in f if line.strip()]
    return lessons[-limit:]
