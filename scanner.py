"""
Trading Signal Scanner — GitHub Actions Bot
Prüft EMA/RSI/MACD nach unserem Kombinations-System
Schickt Signale per Telegram wenn ein Setup triggert
"""

import os
import json
import requests
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import anthropic

# ── Konfiguration ──────────────────────────────────────────────────────────────

WATCHLIST = {
    # US-Aktien
    "NVDA":  {"name": "NVIDIA",          "wkn": "918422",  "megatrend": "AI & Halbleiter", "market": "US"},
    "ASML":  {"name": "ASML Holding",    "wkn": "A1J4U4",  "megatrend": "AI & Halbleiter", "market": "US"},
    "AVGO":  {"name": "Broadcom",        "wkn": "A2JG9Z",  "megatrend": "AI & Halbleiter", "market": "US"},
    "XOM":   {"name": "ExxonMobil",      "wkn": "852549",  "megatrend": "Energie",         "market": "US"},
    "NVO":   {"name": "Novo Nordisk",    "wkn": "A1XA8R",  "megatrend": "Healthcare GLP-1","market": "US"},
    "LLY":   {"name": "Eli Lilly",       "wkn": "858560",  "megatrend": "Healthcare GLP-1","market": "US"},
    "PM":    {"name": "Philip Morris",   "wkn": "A14TQH",  "megatrend": "Defensiv",        "market": "US"},
    # DAX
    "RHM.DE": {"name": "Rheinmetall",   "wkn": "703000",  "megatrend": "Rüstung Europa",  "market": "DAX"},
    "ZAL.DE": {"name": "Zalando",       "wkn": "ZAL111",  "megatrend": "E-Commerce",      "market": "DAX"},
    "SIE.DE": {"name": "Siemens",       "wkn": "723610",  "megatrend": "Infrastruktur",   "market": "DAX"},
    # ETFs/Indizes
    "GLD":   {"name": "Gold ETF",        "wkn": "A0LP78",  "megatrend": "Gold Hedge",      "market": "ETF"},
    "SPY":   {"name": "S&P 500 ETF",     "wkn": "A0AET0",  "megatrend": "Index",           "market": "ETF"},
}

# Mindest-Score für Signal-Versand (von 8 Punkten)
MIN_SCORE = 6

# Timeframe für Analyse
PERIOD = "3mo"      # 3 Monate historische Daten
INTERVAL = "1d"     # Daily-Kerzen (für Swing-Trading)


# ── Indikatoren berechnen ──────────────────────────────────────────────────────

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

def calc_fibonacci(high, low):
    diff = high - low
    return {
        "23.6": high - 0.236 * diff,
        "38.2": high - 0.382 * diff,
        "50.0": high - 0.500 * diff,
        "61.8": high - 0.618 * diff,
        "78.6": high - 0.786 * diff,
    }

def analyze_ticker(ticker_symbol):
    """Analysiert einen Ticker und gibt Score + Details zurück"""
    try:
        df = yf.download(ticker_symbol, period=PERIOD, interval=INTERVAL, progress=False)
        if df.empty or len(df) < 50:
            return None

        close = df["Close"].squeeze()
        volume = df["Volume"].squeeze()
        high_series = df["High"].squeeze()
        low_series = df["Low"].squeeze()

        # EMAs berechnen
        ema10  = calc_ema(close, 10)
        ema20  = calc_ema(close, 20)
        ema50  = calc_ema(close, 50)
        ema200 = calc_ema(close, 200)

        # RSI
        rsi = calc_rsi(close)

        # MACD
        macd_line, macd_signal, macd_hist = calc_macd(close)

        # Aktuelle Werte (letzter Tag)
        c   = float(close.iloc[-1])
        e10 = float(ema10.iloc[-1])
        e20 = float(ema20.iloc[-1])
        e50 = float(ema50.iloc[-1])
        e200= float(ema200.iloc[-1])
        r   = float(rsi.iloc[-1])
        ml  = float(macd_line.iloc[-1])
        ms  = float(macd_signal.iloc[-1])
        mh  = float(macd_hist.iloc[-1])
        mh_prev = float(macd_hist.iloc[-2])
        vol_avg = float(volume.rolling(20).mean().iloc[-1])
        vol_now = float(volume.iloc[-1])

        # Fibonacci (letzte 60 Tage)
        period_high = float(high_series.iloc[-60:].max())
        period_low  = float(low_series.iloc[-60:].min())
        fib = calc_fibonacci(period_high, period_low)

        # ── Scoring nach unserem Kombinations-System ──────────────────────────
        score = 0
        checks = {}

        # 1. EMA-Fächer (EMA10 > EMA20 > EMA50) — Gewicht 2
        if e10 > e20 > e50:
            score += 2
            checks["EMA-Fächer"] = f"✅ EMA10({e10:.2f}) > EMA20({e20:.2f}) > EMA50({e50:.2f})"
        else:
            checks["EMA-Fächer"] = f"❌ Nicht ausgerichtet"

        # 2. Kurs über EMA200 — Gewicht 1
        if c > e200:
            score += 1
            checks["EMA200"] = f"✅ Kurs({c:.2f}) > EMA200({e200:.2f})"
        else:
            checks["EMA200"] = f"❌ Kurs unter EMA200"

        # 3. RSI Bullish Zone (45–70) — Gewicht 1
        if 45 <= r <= 70:
            score += 1
            checks["RSI"] = f"✅ RSI={r:.1f} (Bullish Zone)"
        elif r < 30:
            score += 1  # Überverkauft = Reversal-Chance
            checks["RSI"] = f"⚡ RSI={r:.1f} (Überverkauft — Reversal)"
        else:
            checks["RSI"] = f"❌ RSI={r:.1f} (außerhalb Zone)"

        # 4. MACD positiv und wachsend — Gewicht 1
        if ml > ms and mh > mh_prev:
            score += 1
            checks["MACD"] = f"✅ MACD über Signal, Histogramm wächst"
        elif ml > ms:
            score += 0
            checks["MACD"] = f"⚠️ MACD über Signal, aber Momentum schwächer"
        else:
            checks["MACD"] = f"❌ MACD unter Signal"

        # 5. Volumen über Durchschnitt — Gewicht 1
        if vol_now > vol_avg * 1.2:
            score += 1
            checks["Volumen"] = f"✅ Vol={vol_now:,.0f} (+{((vol_now/vol_avg)-1)*100:.0f}% über Ø)"
        else:
            checks["Volumen"] = f"⚠️ Volumen normal ({vol_now:,.0f} vs Ø {vol_avg:,.0f})"

        # 6. Fibonacci-Pullback auf 38.2–61.8% — Gewicht 2
        in_fib_zone = fib["38.2"] >= c >= fib["61.8"]
        near_fib    = fib["23.6"] >= c >= fib["78.6"]
        if in_fib_zone:
            score += 2
            checks["Fibonacci"] = f"✅ Kurs in Goldener Zone (38.2–61.8%)"
        elif near_fib:
            score += 1
            checks["Fibonacci"] = f"⚠️ Kurs nahe Fib-Level"
        else:
            checks["Fibonacci"] = f"❌ Kein Fib-Pullback erkennbar"

        # ── Richtungsbestimmung ──────────────────────────────────────────────
        direction = "LONG" if (e10 > e20 and c > e200) else "NEUTRAL"
        if e10 < e20 and c < e200:
            direction = "SHORT/MEIDEN"

        # ── Stop-Loss und Take-Profit berechnen ──────────────────────────────
        atr = float(close.diff().abs().rolling(14).mean().iloc[-1])  # ATR-Näherung
        stop_loss = round(c - (atr * 2.5), 2)
        tp1 = round(c + (atr * 3.75), 2)  # R:R 1:1.5
        tp2 = round(c + (atr * 6.25), 2)  # R:R 1:2.5
        tsl_pct = round((atr * 2.5 / c) * 100, 1)
        rr = round((tp1 - c) / (c - stop_loss), 1)

        return {
            "ticker": ticker_symbol,
            "score": score,
            "max_score": 8,
            "direction": direction,
            "price": c,
            "ema10": e10, "ema20": e20, "ema50": e50, "ema200": e200,
            "rsi": r,
            "macd_line": ml, "macd_signal": ms, "macd_hist": mh,
            "volume": vol_now, "vol_avg": vol_avg,
            "fib": fib,
            "stop_loss": stop_loss,
            "tp1": tp1, "tp2": tp2,
            "tsl_pct": tsl_pct,
            "rr": rr,
            "checks": checks,
            "atr": atr,
        }

    except Exception as e:
        print(f"Fehler bei {ticker_symbol}: {e}")
        return None


# ── Claude Analyse anfordern ──────────────────────────────────────────────────

def get_claude_signal(ticker_symbol, analysis, ticker_info):
    """Erstellt ein vollständiges Signal mit Claude"""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    checks_text = "\n".join([f"  {k}: {v}" for k, v in analysis["checks"].items()])

    prompt = f"""Du bist ein erfahrener Trading-Analyst. Erstelle ein präzises Signal für:

TICKER: {ticker_symbol} — {ticker_info['name']}
MEGATREND: {ticker_info['megatrend']}
SCORE: {analysis['score']}/8
RICHTUNG: {analysis['direction']}

TECHNISCHE DATEN:
- Kurs: {analysis['price']:.2f}
- EMA10/20/50/200: {analysis['ema10']:.2f} / {analysis['ema20']:.2f} / {analysis['ema50']:.2f} / {analysis['ema200']:.2f}
- RSI: {analysis['rsi']:.1f}
- MACD Histogramm: {analysis['macd_hist']:.3f} (vorher: wachsend/fallend erkennbar)
- ATR (14): {analysis['atr']:.2f}

SETUP-CHECK:
{checks_text}

BERECHNETE LEVELS:
- Entry: ~{analysis['price']:.2f}
- Stop-Loss: {analysis['stop_loss']:.2f} (ATR-basiert, 2.5x ATR)
- TP1 (50% bei): {analysis['tp1']:.2f}
- TP2 (Rest): {analysis['tp2']:.2f}
- R:R: 1:{analysis['rr']}
- TSL-Abstand: {analysis['tsl_pct']}%

WKN: {ticker_info['wkn']}

Erstelle eine knappe, präzise Signal-Nachricht (max 280 Wörter) für Telegram mit:
1. Klarer Handlungsempfehlung (Long/Abwarten/Meiden)
2. Konkreter Begründung (2-3 Sätze)
3. Entry/Stop/TP1/TP2 nochmals zusammengefasst
4. TSL-Einstellung für Finanzen.Zero
5. Megatrend-Kontext (1 Satz)
6. Wichtige Risiken (1 Satz)

Formatiere mit Emojis für Telegram. Sei direkt und präzise, kein Blabla."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


# ── Telegram senden ──────────────────────────────────────────────────────────

def send_telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload)
    if r.status_code != 200:
        print(f"Telegram Fehler: {r.text}")
    return r.status_code == 200





# ── Bereits gesendete Signale tracken (verhindert Spam) ──────────────────────

def load_sent_signals():
    try:
        with open("sent_signals.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_sent_signals(signals):
    with open("sent_signals.json", "w") as f:
        json.dump(signals, f)

def was_recently_sent(ticker, sent_signals, hours=6):
    """Prüft ob für diesen Ticker in den letzten X Stunden schon ein Signal gesendet wurde"""
    if ticker not in sent_signals:
        return False
    last = datetime.fromisoformat(sent_signals[ticker])
    return datetime.now() - last < timedelta(hours=hours)


# ── Haupt-Scanner ─────────────────────────────────────────────────────────────

def run_scan():
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    print(f"\n{'='*50}")
    print(f"Signal-Scan gestartet: {now}")
    print(f"Watchlist: {len(WATCHLIST)} Titel")
    print(f"{'='*50}")

    sent_signals = load_sent_signals()
    signals_found = []
    scan_summary = []

    for ticker, info in WATCHLIST.items():
        print(f"\nAnalysiere {ticker} ({info['name']})...")
        analysis = analyze_ticker(ticker)

        if analysis is None:
            print(f"  → Keine Daten")
            continue

        score = analysis["score"]
        direction = analysis["direction"]
        print(f"  Score: {score}/8 | Richtung: {direction} | RSI: {analysis['rsi']:.1f}")
        scan_summary.append(f"{ticker}: {score}/8 — {direction}")

        # Signal nur senden wenn Score erreicht und kein Spam
        if score >= MIN_SCORE and direction == "LONG":
            if was_recently_sent(ticker, sent_signals, hours=6):
                print(f"  → Signal vor <6h schon gesendet — übersprungen")
                continue

            print(f"  🚨 SIGNAL GEFUNDEN — Score {score}/8!")

            # Claude für vollständige Analyse anfragen
            try:
                claude_text = get_claude_signal(ticker, analysis, info)
            except Exception as e:
                print(f"  Claude-Fehler: {e}")
                claude_text = "Claude-Analyse nicht verfügbar."

            # Telegram-Nachricht formatieren
            stars = "⭐" * (1 if score == 6 else 2 if score == 7 else 3)
            megatrend_tag = f"🔥 <b>MEGATREND: {info['megatrend']}</b>\n" if info['megatrend'] != "Defensiv" else ""

            message = (
                f"📊 <b>TRADING SIGNAL — {ticker}</b> {stars}\n"
                f"<b>{info['name']}</b> | Score: <b>{score}/8</b> | {now}\n"
                f"{megatrend_tag}"
                f"{'─'*30}\n"
                f"{claude_text}\n"
                f"{'─'*30}\n"
                f"📌 <b>WKN (Aktie):</b> <code>{info['wkn']}</code>\n"
                f"🔧 <b>KO/OS:</b> HSBC: hsbc-zertifikate.de → {ticker} → Turbo Long\n"
                f"📱 <b>Finanzen.Zero TSL:</b> {analysis['tsl_pct']}% Abstand\n"
                f"⚠️ <i>Kein Anlageberater — eigene Analyse!</i>"
            )

            if send_telegram(message):
                sent_signals[ticker] = datetime.now().isoformat()
                signals_found.append(ticker)
                print(f"  ✅ Telegram gesendet")

            else:
                print(f"  ❌ Telegram-Versand fehlgeschlagen")

    save_sent_signals(sent_signals)

    # Scan-Zusammenfassung für Morgen/Nachmittag-Berichte
    hour = datetime.now().hour
    is_morning_report = 8 <= hour <= 10
    is_afternoon_report = 16 <= hour <= 17

    if is_morning_report or is_afternoon_report:
        report_type = "🌅 MORGEN-SCAN" if is_morning_report else "🌆 NACHMITTAG-SCAN"
        if not signals_found:
            summary_msg = (
                f"{report_type} — {now}\n\n"
                f"📋 Kein Signal hat unsere Kriterien erfüllt (Min. Score {MIN_SCORE}/8)\n\n"
                f"<b>Scan-Übersicht:</b>\n"
                + "\n".join(scan_summary) +
                f"\n\n💤 Markt abwarten — kein Einstieg erzwingen."
            )
            send_telegram(summary_msg)
            print(f"\n→ Kein Signal. Zusammenfassung gesendet.")
        else:
            print(f"\n✅ {len(signals_found)} Signal(e) gesendet: {', '.join(signals_found)}")
    else:
        if signals_found:
            print(f"\n✅ Intraday-Signal(e) gesendet: {', '.join(signals_found)}")
        else:
            print(f"\n→ Kein Signal bei diesem Scan.")


if __name__ == "__main__":
    run_scan()
