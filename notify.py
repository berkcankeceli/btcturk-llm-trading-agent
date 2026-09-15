"""Mail bildirimi. Resend REST API uzerinden (DigitalOcean SMTP portlarini blokluyor)."""
import os

import requests


def send_mail(subject: str, body: str) -> None:
    """Bildirim gonderir. Mail hatasi trade akisini asla durdurmamali."""
    api_key = os.getenv("RESEND_API_KEY")
    to_addr = os.getenv("NOTIFY_EMAIL")

    if not (api_key and to_addr):
        print("[MAIL] Resend ayarlari eksik, bildirim atlandi.")
        return

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": "Trade Agent <onboarding@resend.dev>",
                "to": [to_addr],
                "subject": subject,
                "text": body,
            },
            timeout=20,
        )
        resp.raise_for_status()
        print(f"[MAIL] Gonderildi: {subject}")
    except Exception as exc:
        print(f"[MAIL] HATA (gormezden gelindi): {exc!r}")
