# 📈 Trading Signal Scanner

Automatischer Markt-Scanner der nach unserem EMA/RSI/MACD Kombinations-System
Signale erkennt und per Telegram schickt. Läuft 100% kostenlos auf GitHub Actions.

## Was der Bot macht

- Scannt täglich 6x: 09:00, 10:00, 12:00, 14:00, 16:30, 20:00 MEZ
- Prüft EMA-Fächer, RSI, MACD, Fibonacci, Volumen nach unserem 8-Punkte-System
- Sendet Signal nur wenn Score ≥ 6/8 — kein Spam
- Anti-Spam: Jeder Ticker max. 1x alle 6 Stunden
- Morgen/Nachmittag: Immer Bericht — auch wenn kein Signal

## Setup in 4 Schritten

### Schritt 1 — Repository erstellen
1. GitHub Account erstellen (kostenlos): github.com
2. Neues Repository anlegen: "trading-scanner" → Public oder Private (egal)
3. Diese Dateien hochladen (drag & drop im Browser)

### Schritt 2 — Telegram Bot erstellen (5 Minuten)
1. Telegram öffnen → @BotFather suchen
2. /newbot schreiben → Namen eingeben (z.B. "MeinTradingBot")
3. Bot-Token kopieren (sieht so aus: 123456789:ABCdef...)
4. Deinen Bot anschreiben → dann @userinfobot anschreiben → Chat-ID notieren

### Schritt 3 — Anthropic API Key
1. console.anthropic.com → Account erstellen
2. API Keys → New Key → kopieren
3. Kosten: ~0.01–0.05€ pro Scan (ca. 1–3€/Monat gesamt)

### Schritt 4 — Secrets in GitHub eintragen
Repository → Settings → Secrets and variables → Actions → New repository secret:

| Secret Name          | Wert                          |
|----------------------|-------------------------------|
| ANTHROPIC_API_KEY    | sk-ant-...                    |
| TELEGRAM_BOT_TOKEN   | 123456789:ABCdef...           |
| TELEGRAM_CHAT_ID     | Deine Chat-ID (z.B. 98765432) |
| GMAIL_USER           | optional: deine@gmail.com     |
| GMAIL_APP_PASSWORD   | optional: Gmail App-Passwort  |
| TO_EMAIL             | optional: empfaenger@mail.com |

Fertig — der Bot startet automatisch zum nächsten geplanten Zeitpunkt.

## Watchlist anpassen

In `scripts/scanner.py` die WATCHLIST bearbeiten:
```python
WATCHLIST = {
    "NVDA": {"name": "NVIDIA", "wkn": "918422", "megatrend": "AI", "market": "US"},
    # weitere Ticker hinzufügen...
}
```

## Scan-Zeitplan anpassen

In `.github/workflows/scanner.yml` die cron-Zeiten ändern:
- `0 7 * * 1-5` = 09:00 MEZ (Sommer) täglich Mo–Fr
- Alle Zeiten sind UTC — MEZ = UTC+1 (Winter), UTC+2 (Sommer)

## Manuell ausführen (zum Testen)
GitHub → Actions → Trading Signal Scanner → Run workflow

## Kosten
- GitHub Actions: 100% kostenlos (2000 Minuten/Monat, wir brauchen ~60)
- Anthropic API: ~0.003$ pro Signal-Analyse, ~1–3$/Monat
- Telegram: kostenlos
