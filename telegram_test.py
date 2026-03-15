"""
Telegram Verbindungstest
Sendet eine Test-Nachricht um zu prüfen ob Bot + Chat-ID korrekt sind
"""
import os
import requests

token = os.environ["TELEGRAM_BOT_TOKEN"]
chat_id = os.environ["TELEGRAM_CHAT_ID"]

print(f"Token (erste 10 Zeichen): {token[:10]}...")
print(f"Chat-ID: {chat_id}")

url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = {
    "chat_id": chat_id,
    "text": (
        "✅ <b>Verbindungstest erfolgreich!</b>\n\n"
        "📈 Dein Trading Signal Bot ist aktiv.\n"
        "Signale werden gesendet sobald Score ≥ 6/8 erreicht wird.\n\n"
        "🕐 Scan-Zeiten: 09:00 · 10:00 · 12:00 · 14:00 · 16:30 · 20:00 Uhr"
    ),
    "parse_mode": "HTML"
}

r = requests.post(url, json=payload)
print(f"\nHTTP Status: {r.status_code}")
print(f"Antwort: {r.text}")

if r.status_code == 200:
    print("\n✅ Telegram funktioniert!")
else:
    data = r.json()
    print(f"\n❌ Fehler: {data.get('description', 'Unbekannt')}")
    if "chat not found" in str(data).lower():
        print("→ Chat-ID falsch ODER du hast dem Bot noch keine Nachricht geschickt")
        print("→ Lösung: Öffne Telegram → suche deinen Bot → schicke ihm /start")
    if "unauthorized" in str(data).lower():
        print("→ Bot-Token falsch — prüfe das Secret TELEGRAM_BOT_TOKEN")
