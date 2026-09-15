import os
from dotenv import load_dotenv
import requests

load_dotenv()
r = requests.get(
    "https://api.groq.com/openai/v1/models",
    headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}"},
)
for m in r.json()["data"]:
    print(m["id"], m.get("context_window"), m.get("supported_features"))
