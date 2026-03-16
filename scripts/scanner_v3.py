"""
Trading Signal Scanner v2 — Dynamisch + Megatrend-Screening
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Neu in v2:
  - Automatisches Megatrend-Screening (100+ Titel pro Sektor)
  - Täglich Top-5 beste Setups aus dem gesamten Universum
  - Morgen-Bericht mit Marktlage + besten Kandidaten
  - Nachmittag-Bericht mit US-Open Kandidaten
  - Intraday: nur echte Signale (Score >= MIN_SCORE)
"""

import os
import json
import requests
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import anthropic

# ── Konfiguration ──────────────────────────────────────────────────────────────

MIN_SCORE       = 6     # Mindest-Score für Einzel-Signal (von 8)
TOP_N           = 5     # Beste Setups im Tagesbericht
ANTI_SPAM_HOURS = 6     # Stunden bis gleicher Ticker wieder gesendet wird

# Exit-Signal Konfiguration
TSL_TRIGGER_PCT  = 0.035   # TSL-Alarm wenn Kurs 3.5% unter Hochpunkt fällt
TP_TOLERANCE     = 0.005   # TP gilt als erreicht wenn Kurs innerhalb 0.5% vom Ziel

# ── Feste Kern-Watchlist ───────────────────────────────────────────────────────

WATCHLIST = {
    "NVDA":   {"name": "NVIDIA",          "wkn": "918422",  "megatrend": "AI & Halbleiter", "market": "US"},
    "ASML":   {"name": "ASML Holding",    "wkn": "A1J4U4",  "megatrend": "AI & Halbleiter", "market": "US"},
    "AVGO":   {"name": "Broadcom",        "wkn": "A2JG9Z",  "megatrend": "AI & Halbleiter", "market": "US"},
    "AMD":    {"name": "AMD",             "wkn": "A2N6GH",  "megatrend": "AI & Halbleiter", "market": "US"},
    "MSFT":   {"name": "Microsoft",       "wkn": "870747",  "megatrend": "AI & Halbleiter", "market": "US"},
    "XOM":    {"name": "ExxonMobil",      "wkn": "852549",  "megatrend": "Energie",         "market": "US"},
    "SLB":    {"name": "SLB",             "wkn": "853390",  "megatrend": "Energie",         "market": "US"},
    "NEE":    {"name": "NextEra Energy",  "wkn": "A0NH8V",  "megatrend": "Energie",         "market": "US"},
    "NVO":    {"name": "Novo Nordisk",    "wkn": "A1XA8R",  "megatrend": "Healthcare GLP-1","market": "US"},
    "LLY":    {"name": "Eli Lilly",       "wkn": "858560",  "megatrend": "Healthcare GLP-1","market": "US"},
    "PM":     {"name": "Philip Morris",   "wkn": "A14TQH",  "megatrend": "Defensiv",        "market": "US"},
    "GLD":    {"name": "Gold ETF",        "wkn": "A0LP78",  "megatrend": "Gold Hedge",      "market": "ETF"},
    "GDX":    {"name": "Gold Miner ETF",  "wkn": "A0Q8NB",  "megatrend": "Gold Hedge",      "market": "ETF"},
    "RHM.DE": {"name": "Rheinmetall",     "wkn": "703000",  "megatrend": "Rüstung Europa",  "market": "DAX"},
    "SIE.DE": {"name": "Siemens",         "wkn": "723610",  "megatrend": "Infrastruktur",   "market": "DAX"},
    "ZAL.DE": {"name": "Zalando",         "wkn": "ZAL111",  "megatrend": "E-Commerce",      "market": "DAX"},
    "SAP.DE": {"name": "SAP",             "wkn": "716460",  "megatrend": "AI & Halbleiter", "market": "DAX"},
    "SPY":    {"name": "S&P 500 ETF",     "wkn": "A0AET0",  "megatrend": "Index",           "market": "ETF"},
    "QQQ":    {"name": "Nasdaq 100 ETF",  "wkn": "A0AET7",  "megatrend": "Index",           "market": "ETF"},
}

# ── Megatrend-Universen (dynamisch gescannt) ───────────────────────────────────

MEGATREND_UNIVERSE = {

    "AI & Halbleiter": [
        "NVDA","ASML","AVGO","AMD","TSM","LRCX","KLAC","AMAT","MRVL",
        "SMCI","ARM","INTC","QCOM","TXN","NXPI","ON","MPWR",
        "CDNS","SNPS","CRM","NOW","PLTR","AI",
    ],

    "Rüstung Europa": [
        "RHM.DE","BA","RTX","LMT","NOC","GD","HII","KTOS","AXON",
    ],

    "Energie & Power": [
        "XOM","CVX","COP","SLB","HAL","BKR","PSX","VLO","MPC",
        "NEE","CEG","VST","NRG","ETR","AEP","EXC","GEV",
        "FSLR","ENPH",
    ],

    "Healthcare & GLP-1": [
        "NVO","LLY","MRNA","VRTX","REGN","ABBV","BMY","MRK","PFE",
        "JNJ","UNH","ABT","DHR","TMO","ISRG","SYK",
    ],

    "Gold & Rohstoffe": [
        "GLD","GDX","GDXJ","SLV","GOLD","NEM","AEM","WPM","FNV",
        "FCX","BHP","MP",
    ],
}

# ── Indikatoren ────────────────────────────────────────────────────────────────

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_rsi(series, period=14):
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs       = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_macd(series, fast=12, slow=26, signal=9):
    ema_fast    = calc_ema(series, fast)
    ema_slow    = calc_ema(series, slow)
    macd_line   = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram   = macd_line - signal_line
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

# ── Ticker analysieren ─────────────────────────────────────────────────────────

def analyze_ticker(ticker_symbol):
    try:
        df = yf.download(ticker_symbol, period="3mo", interval="1d", progress=False)
        if df.empty or len(df) < 50:
            return None

        close  = df["Close"].squeeze()
        volume = df["Volume"].squeeze()
        high_s = df["High"].squeeze()
        low_s  = df["Low"].squeeze()

        ema10  = calc_ema(close, 10)
        ema20  = calc_ema(close, 20)
        ema50  = calc_ema(close, 50)
        ema200 = calc_ema(close, 200)
        rsi    = calc_rsi(close)
        macd_line, macd_signal, macd_hist = calc_macd(close)

        c    = float(close.iloc[-1])
        e10  = float(ema10.iloc[-1])
        e20  = float(ema20.iloc[-1])
        e50  = float(ema50.iloc[-1])
        e200 = float(ema200.iloc[-1])
        r    = float(rsi.iloc[-1])
        ml   = float(macd_line.iloc[-1])
        ms   = float(macd_signal.iloc[-1])
        mh   = float(macd_hist.iloc[-1])
        mh_p = float(macd_hist.iloc[-2])
        vol_avg = float(volume.rolling(20).mean().iloc[-1])
        vol_now = float(volume.iloc[-1])

        period_high = float(high_s.iloc[-60:].max())
        period_low  = float(low_s.iloc[-60:].min())
        fib = calc_fibonacci(period_high, period_low)

        score  = 0
        checks = {}

        # 1. EMA-Fächer — Gewicht 2
        if e10 > e20 > e50:
            score += 2
            checks["EMA-Fächer"] = f"✅ {e10:.2f}>{e20:.2f}>{e50:.2f}"
        else:
            checks["EMA-Fächer"] = "❌ Nicht ausgerichtet"

        # 2. Kurs über EMA200 — Gewicht 1
        if c > e200:
            score += 1
            checks["EMA200"] = f"✅ {c:.2f}>{e200:.2f}"
        else:
            checks["EMA200"] = f"❌ Unter EMA200"

        # 3. RSI — Gewicht 1
        if 45 <= r <= 70:
            score += 1
            checks["RSI"] = f"✅ {r:.1f} (Bullish Zone)"
        elif r < 30:
            score += 1
            checks["RSI"] = f"⚡ {r:.1f} (Überverkauft)"
        else:
            checks["RSI"] = f"❌ {r:.1f}"

        # 4. MACD — Gewicht 1
        if ml > ms and mh > mh_p:
            score += 1
            checks["MACD"] = "✅ Positiv & wachsend"
        else:
            checks["MACD"] = "❌ Schwach"

        # 5. Volumen — Gewicht 1
        if vol_now > vol_avg * 1.2:
            score += 1
            checks["Volumen"] = f"✅ +{((vol_now/vol_avg)-1)*100:.0f}% über Ø"
        else:
            checks["Volumen"] = "⚠️ Normal"

        # 6. Fibonacci — Gewicht 2
        if fib["38.2"] >= c >= fib["61.8"]:
            score += 2
            checks["Fibonacci"] = "✅ Goldene Zone"
        elif fib["23.6"] >= c >= fib["78.6"]:
            score += 1
            checks["Fibonacci"] = "⚠️ Nahe Fib-Level"
        else:
            checks["Fibonacci"] = "❌ Kein Pullback"

        # Richtung
        if e10 > e20 and c > e200:
            direction = "LONG"
        elif e10 < e20 and c < e200:
            direction = "SHORT/MEIDEN"
        else:
            direction = "NEUTRAL"

        # Levels
        atr       = float(close.diff().abs().rolling(14).mean().iloc[-1])
        stop_loss = round(c - (atr * 2.5), 2)
        tp1       = round(c + (atr * 3.75), 2)
        tp2       = round(c + (atr * 6.25), 2)
        tsl_pct   = round((atr * 2.5 / c) * 100, 1)
        rr        = round((tp1 - c) / max(c - stop_loss, 0.01), 1)

        return {
            "ticker": ticker_symbol, "score": score, "max_score": 8,
            "direction": direction, "price": c,
            "ema10": e10, "ema20": e20, "ema50": e50, "ema200": e200,
            "rsi": r, "macd_line": ml, "macd_signal": ms, "macd_hist": mh,
            "volume": vol_now, "vol_avg": vol_avg, "fib": fib,
            "stop_loss": stop_loss, "tp1": tp1, "tp2": tp2,
            "tsl_pct": tsl_pct, "rr": rr, "checks": checks, "atr": atr,
        }
    except Exception as e:
        print(f"  Fehler {ticker_symbol}: {e}")
        return None

# ── Megatrend-Universum scannen ────────────────────────────────────────────────

def scan_megatrend_universe():
    print("\n📡 Megatrend-Screening...")
    results = []
    seen    = set()

    for sektor, tickers in MEGATREND_UNIVERSE.items():
        print(f"  {sektor} ({len(tickers)} Titel)...")
        for ticker in tickers:
            if ticker in seen:
                continue
            seen.add(ticker)
            analysis = analyze_ticker(ticker)
            if analysis and analysis["direction"] == "LONG":
                info = WATCHLIST.get(ticker, {
                    "name": ticker, "wkn": "→ suchen",
                    "megatrend": sektor, "market": "US",
                })
                results.append({"ticker": ticker, "info": info,
                                 "analysis": analysis, "sektor": sektor})

    results.sort(key=lambda x: x["analysis"]["score"], reverse=True)
    print(f"  → {len(results)} Long-Kandidaten")
    return results

# ── Claude Analyse ─────────────────────────────────────────────────────────────

def get_claude_signal(ticker, analysis, info):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    checks_text = " | ".join([f"{k}: {v}" for k, v in analysis["checks"].items()])
    prompt = f"""Erfahrener Trading-Analyst. Kurzes Signal für Telegram (max 180 Wörter):

{ticker} — {info.get('name',ticker)} | Score {analysis['score']}/8 | {analysis['direction']}
Kurs: {analysis['price']:.2f} | RSI: {analysis['rsi']:.1f} | ATR: {analysis['atr']:.2f}
Checks: {checks_text}
Entry: {analysis['price']:.2f} | SL: {analysis['stop_loss']:.2f} | TP1: {analysis['tp1']:.2f} | TP2: {analysis['tp2']:.2f} | R:R 1:{analysis['rr']}
Megatrend: {info.get('megatrend','-')}

Format: 1) Empfehlung 2) Begründung (2 Sätze) 3) Levels 4) Megatrend-Kontext. Emojis nutzen."""

    r = client.messages.create(model="claude-sonnet-4-6", max_tokens=400,
                                messages=[{"role": "user", "content": prompt}])
    return r.content[0].text

def get_claude_tagesbericht(top_results, markt_info):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    kandidaten = ""
    for i, r in enumerate(top_results[:5], 1):
        a = r["analysis"]
        kandidaten += (f"\n{i}. {r['ticker']} ({r['info'].get('name','')}) — "
                       f"Score {a['score']}/8 | RSI {a['rsi']:.1f} | "
                       f"Kurs {a['price']:.2f} | {r['sektor']}")

    prompt = f"""Trading-Analyst. Tagesbericht für Telegram (max 220 Wörter):

Markt: {markt_info}
Top-Kandidaten:{kandidaten}

Format: 1) Marktlage (2 Sätze) 2) Top-3 Kandidaten (je 1 Satz Begründung) 3) Tagesempfehlung. Emojis nutzen."""

    r = client.messages.create(model="claude-sonnet-4-6", max_tokens=500,
                                messages=[{"role": "user", "content": prompt}])
    return r.content[0].text

# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram(message):
    token   = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url     = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message,
                "parse_mode": "HTML", "disable_web_page_preview": True}
    r = requests.post(url, json=payload)
    if r.status_code != 200:
        print(f"  Telegram Fehler: {r.text}")
    return r.status_code == 200

# ── Spam-Schutz ────────────────────────────────────────────────────────────────

def load_state():
    """Lädt Signale UND offene Positionen"""
    try:
        with open("sent_signals.json", "r") as f:
            data = json.load(f)
            # Rückwärtskompatibilität: altes Format hat keine 'positions' key
            if "signals" not in data:
                return {"signals": data, "positions": {}}
            return data
    except FileNotFoundError:
        return {"signals": {}, "positions": {}}

def save_state(state):
    with open("sent_signals.json", "w") as f:
        json.dump(state, f, indent=2)

def recently_sent(ticker, signals, hours=ANTI_SPAM_HOURS):
    if ticker not in signals:
        return False
    return datetime.now() - datetime.fromisoformat(signals[ticker]) < timedelta(hours=hours)

def open_position(ticker, analysis, state):
    """Speichert eine neue offene Position nach einem Entry-Signal"""
    state["positions"][ticker] = {
        "entry":     analysis["price"],
        "stop":      analysis["stop_loss"],
        "tp1":       analysis["tp1"],
        "tp2":       analysis["tp2"],
        "tsl_pct":   analysis["tsl_pct"],
        "high":      analysis["price"],   # Höchstkurs seit Entry — wird aktualisiert
        "tp1_hit":   False,
        "opened_at": datetime.now().isoformat(),
    }

def close_position(ticker, state, reason):
    """Entfernt eine Position aus dem Tracking"""
    if ticker in state["positions"]:
        del state["positions"][ticker]
        print(f"  Position {ticker} geschlossen: {reason}")

# ── Exit-Signal prüfen ─────────────────────────────────────────────────────────

def check_exit_signals(state):
    """
    Prüft alle offenen Positionen auf Exit-Bedingungen:
    1. TSL ausgelöst — Kurs fällt zu weit vom Hochpunkt
    2. TP1 erreicht — erste Gewinnmitnahme
    3. TP2 erreicht — voller Gewinn
    4. Technischer Ausstieg — EMA dreht, Setup ungültig
    Gibt Liste von Exit-Nachrichten zurück.
    """
    exit_messages = []
    positions     = state.get("positions", {})
    to_close      = []

    for ticker, pos in positions.items():
        try:
            df = yf.download(ticker, period="5d", interval="1d", progress=False)
            if df.empty:
                continue

            close  = df["Close"].squeeze()
            high_s = df["High"].squeeze()
            c      = float(close.iloc[-1])
            h_now  = float(high_s.iloc[-1])

            # Höchstkurs aktualisieren
            new_high = max(pos["high"], h_now, c)
            state["positions"][ticker]["high"] = new_high

            entry   = pos["entry"]
            stop    = pos["stop"]
            tp1     = pos["tp1"]
            tp2     = pos["tp2"]
            tsl_pct = pos["tsl_pct"] / 100
            tp1_hit = pos.get("tp1_hit", False)

            # Gewinn/Verlust berechnen
            pnl_pct = ((c - entry) / entry) * 100

            # ── 1. TSL ausgelöst ────────────────────────────────────────────
            tsl_level = new_high * (1 - tsl_pct)
            if c <= tsl_level and c < entry * 1.005:  # TSL unter Entry = Verlust
                msg = (
                    f"🔴 <b>TSL AUSGELÖST — {ticker}</b>\n"
                    f"Kurs: <b>{c:.2f}</b> | TSL-Level: {tsl_level:.2f}\n"
                    f"Hoch seit Entry: {new_high:.2f}\n"
                    f"P&L: <b>{pnl_pct:+.1f}%</b>\n"
                    f"{'─'*28}\n"
                    f"📌 <b>Aktion:</b> Position schliessen!\n"
                    f"TSL wurde durch Kursrückgang von {tsl_pct*100:.1f}% "
                    f"vom Hochpunkt ausgelöst."
                )
                exit_messages.append(msg)
                to_close.append((ticker, "TSL ausgelöst"))

            elif c <= tsl_level and c >= entry:  # TSL mit Gewinn
                profit_pct = ((c - entry) / entry) * 100
                msg = (
                    f"🟡 <b>TSL MIT GEWINN — {ticker}</b>\n"
                    f"Kurs: <b>{c:.2f}</b> | Entry: {entry:.2f}\n"
                    f"Gewinn gesichert: <b>+{profit_pct:.1f}%</b>\n"
                    f"{'─'*28}\n"
                    f"✅ <b>Aktion:</b> Trailing Stop hat Gewinn gesichert.\n"
                    f"Position kann geschlossen werden."
                )
                exit_messages.append(msg)
                to_close.append((ticker, "TSL mit Gewinn"))

            # ── 2. TP2 erreicht ─────────────────────────────────────────────
            elif c >= tp2 * (1 - TP_TOLERANCE):
                profit_pct = ((c - entry) / entry) * 100
                msg = (
                    f"🎯🎯 <b>TP2 ERREICHT — {ticker}</b>\n"
                    f"Kurs: <b>{c:.2f}</b> | TP2: {tp2:.2f}\n"
                    f"Gesamtgewinn: <b>+{profit_pct:.1f}%</b> 🚀\n"
                    f"{'─'*28}\n"
                    f"✅ <b>Aktion:</b> Restposition vollständig schliessen!\n"
                    f"Maximales Ziel erreicht — Gewinne realisieren."
                )
                exit_messages.append(msg)
                to_close.append((ticker, "TP2 erreicht"))

            # ── 3. TP1 erreicht (nur einmal senden) ─────────────────────────
            elif c >= tp1 * (1 - TP_TOLERANCE) and not tp1_hit:
                profit_pct = ((c - entry) / entry) * 100
                state["positions"][ticker]["tp1_hit"] = True
                msg = (
                    f"🎯 <b>TP1 ERREICHT — {ticker}</b>\n"
                    f"Kurs: <b>{c:.2f}</b> | TP1: {tp1:.2f}\n"
                    f"Gewinn: <b>+{profit_pct:.1f}%</b>\n"
                    f"{'─'*28}\n"
                    f"✅ <b>Aktion:</b> 50% der Position schliessen!\n"
                    f"TSL auf Break-Even ({entry:.2f}) nachziehen.\n"
                    f"Rest läuft weiter Richtung TP2: {tp2:.2f}"
                )
                exit_messages.append(msg)
                # Position bleibt offen bis TP2 oder TSL

            # ── 4. Stop-Loss unterschritten ──────────────────────────────────
            elif c <= stop:
                loss_pct = ((c - entry) / entry) * 100
                msg = (
                    f"🔴 <b>STOP-LOSS GETROFFEN — {ticker}</b>\n"
                    f"Kurs: <b>{c:.2f}</b> | Stop: {stop:.2f}\n"
                    f"Verlust: <b>{loss_pct:.1f}%</b>\n"
                    f"{'─'*28}\n"
                    f"📌 <b>Aktion:</b> Position sofort schliessen!\n"
                    f"Stop-Loss wurde unterschritten."
                )
                exit_messages.append(msg)
                to_close.append((ticker, "Stop-Loss getroffen"))

            # ── 5. Technischer Ausstieg ──────────────────────────────────────
            else:
                # Kurze technische Prüfung
                ema10  = float(close.ewm(span=10, adjust=False).mean().iloc[-1])
                ema20  = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
                macd_f = close.ewm(span=12, adjust=False).mean()
                macd_s = close.ewm(span=26, adjust=False).mean()
                macd_h = float((macd_f - macd_s).iloc[-1])
                macd_h_prev = float((macd_f - macd_s).iloc[-2])

                if ema10 < ema20 and macd_h < 0 and macd_h < macd_h_prev:
                    msg = (
                        f"⚠️ <b>TECHNISCHER AUSSTIEG — {ticker}</b>\n"
                        f"Kurs: {c:.2f} | Entry: {entry:.2f}\n"
                        f"P&L: {pnl_pct:+.1f}%\n"
                        f"{'─'*28}\n"
                        f"EMA10 ({ema10:.2f}) unter EMA20 ({ema20:.2f})\n"
                        f"MACD Histogramm negativ und fallend\n"
                        f"📌 <b>Empfehlung:</b> Setup ungültig — Ausstieg prüfen!"
                    )
                    exit_messages.append(msg)
                    # Kein automatisches Schliessen — nur Warnung

            print(f"  {ticker}: Kurs {c:.2f} | Entry {entry:.2f} | "
                  f"P&L {pnl_pct:+.1f}% | Hoch {new_high:.2f}")

        except Exception as e:
            print(f"  Exit-Check Fehler {ticker}: {e}")

    # Geschlossene Positionen entfernen
    for ticker, reason in to_close:
        close_position(ticker, state, reason)

    return exit_messages

# ── Markt-Snapshot ─────────────────────────────────────────────────────────────

def get_markt_snapshot():
    snapshot = {}
    for ticker, name in {"SPY": "S&P500", "QQQ": "Nasdaq", "GLD": "Gold"}.items():
        try:
            df = yf.download(ticker, period="5d", interval="1d", progress=False)
            if not df.empty:
                c  = df["Close"].squeeze()
                ch = ((float(c.iloc[-1]) / float(c.iloc[-2])) - 1) * 100
                snapshot[name] = f"{float(c.iloc[-1]):.0f} ({ch:+.1f}%)"
        except:
            pass
    return " | ".join([f"{k}: {v}" for k, v in snapshot.items()])

# ── Haupt-Scanner ──────────────────────────────────────────────────────────────

def run_scan():
    now  = datetime.now().strftime("%d.%m.%Y %H:%M")
    hour = datetime.now().hour
    state = load_state()
    signals   = state["signals"]
    positions = state["positions"]

    is_morning   = 7  <= hour <= 9
    is_afternoon = 14 <= hour <= 16

    print(f"\n{'='*55}")
    print(f"Trading Scanner v3 — {now}")
    mode = "MORGEN" if is_morning else "NACHMITTAG" if is_afternoon else "INTRADAY"
    print(f"Modus: {mode} | Offene Positionen: {len(positions)}")
    print(f"{'='*55}")

    # ── EXIT-SIGNALE ZUERST PRÜFEN (bei jedem Scan) ───────────────────────────
    if positions:
        print(f"\n🔍 Prüfe {len(positions)} offene Position(en)...")
        exit_msgs = check_exit_signals(state)
        for msg in exit_msgs:
            send_telegram(msg)
            print(f"  → Exit-Signal gesendet")
        if not exit_msgs:
            print(f"  → Alle Positionen im grünen Bereich")

    # ── TAGESBERICHT (Morgen / Nachmittag) ────────────────────────────────────
    if is_morning or is_afternoon:

        all_results = []
        seen        = set()

        # Kern-Watchlist
        print("\n📋 Kern-Watchlist...")
        for ticker, info in WATCHLIST.items():
            if ticker in seen:
                continue
            seen.add(ticker)
            a = analyze_ticker(ticker)
            if a:
                print(f"  {ticker}: {a['score']}/8 | {a['direction']}")
                if a["direction"] == "LONG":
                    all_results.append({"ticker": ticker, "info": info,
                                        "analysis": a, "sektor": info["megatrend"]})

        # Megatrend-Universum
        for r in scan_megatrend_universe():
            if r["ticker"] not in seen:
                seen.add(r["ticker"])
                all_results.append(r)

        # Top-5
        all_results.sort(key=lambda x: x["analysis"]["score"], reverse=True)
        top5 = all_results[:TOP_N]

        print(f"\n🏆 Top-{TOP_N}:")
        for i, r in enumerate(top5, 1):
            a = r["analysis"]
            print(f"  {i}. {r['ticker']} Score {a['score']}/8 | RSI {a['rsi']:.1f} | {r['sektor']}")

        markt_info = get_markt_snapshot()

        # Offene Positionen im Morgen-Bericht anzeigen
        if is_morning and positions:
            pos_lines = []
            for ticker, pos in positions.items():
                try:
                    df = yf.download(ticker, period="2d", interval="1d", progress=False)
                    c = float(df["Close"].squeeze().iloc[-1]) if not df.empty else 0
                    pnl = ((c - pos["entry"]) / pos["entry"]) * 100 if pos["entry"] else 0
                    emoji = "🟢" if pnl > 0 else "🔴"
                    pos_lines.append(
                        f"{emoji} <b>{ticker}</b>: Entry {pos['entry']:.2f} → "
                        f"Jetzt {c:.2f} ({pnl:+.1f}%) | SL: {pos['stop']:.2f} | "
                        f"TP1: {pos['tp1']:.2f}"
                    )
                except:
                    pos_lines.append(f"⚪ <b>{ticker}</b>: Daten nicht verfügbar")

            pos_msg = (
                f"📂 <b>OFFENE POSITIONEN ({len(positions)})</b>\n"
                + "\n".join(pos_lines)
                + "\n⚠️ <i>Kein Anlageberater!</i>"
            )
            send_telegram(pos_msg)
            print(f"  → {len(positions)} offene Positionen gesendet")

        print("\n📝 Claude erstellt Tagesbericht...")
        try:
            bericht = get_claude_tagesbericht(top5, markt_info)
        except Exception as e:
            print(f"  Fehler: {e}")
            bericht = "Analyse nicht verfügbar."

        emoji = "🌅" if is_morning else "🌆"
        label = "MORGEN-BERICHT" if is_morning else "NACHMITTAG-BERICHT"

        # Header + Claude-Bericht
        msg = (f"{emoji} <b>{label} — {now}</b>\n"
               f"📊 {markt_info}\n"
               f"{'─'*32}\n"
               f"{bericht}\n"
               f"{'─'*32}\n"
               f"🏆 <b>Top-{TOP_N} Setups (8-Punkte-System):</b>\n")

        # Top-5 Liste
        for i, r in enumerate(top5, 1):
            a     = r["analysis"]
            stars = "⭐" * (1 if a["score"] == 6 else 2 if a["score"] == 7 else 3)
            msg  += (f"\n{i}. <b>{r['ticker']}</b> {stars} Score {a['score']}/8\n"
                     f"   💰 {a['price']:.2f} | 🛑 {a['stop_loss']:.2f} | "
                     f"🎯 {a['tp1']:.2f} | R:R 1:{a['rr']}\n"
                     f"   📌 <code>{r['info'].get('wkn','→ suchen')}</code> | "
                     f"TSL {a['tsl_pct']}% | {r['sektor']}\n")

        msg += "\n⚠️ <i>Kein Anlageberater — eigene Analyse!</i>"

        if len(msg) > 4000:
            msg = msg[:3950] + "\n...\n⚠️ <i>Kein Anlageberater!</i>"

        send_telegram(msg)
        print(f"\n✅ {label} gesendet")

        # Echte Signale zusätzlich einzeln senden
        for r in top5:
            a = r["analysis"]
            if a["score"] >= MIN_SCORE and not recently_sent(r["ticker"], sent):
                print(f"\n🚨 Einzel-Signal: {r['ticker']} {a['score']}/8")
                try:
                    sig = get_claude_signal(r["ticker"], a, r["info"])
                    stars = "⭐" * (1 if a["score"] == 6 else 2 if a["score"] == 7 else 3)
                    sig_msg = (
                        f"🚨 <b>SIGNAL — {r['ticker']}</b> {stars}\n"
                        f"<b>{r['info'].get('name', r['ticker'])}</b> | Score <b>{a['score']}/8</b>\n"
                        f"🔥 <b>MEGATREND: {r['sektor']}</b>\n"
                        f"{'─'*32}\n{sig}\n{'─'*32}\n"
                        f"📌 WKN: <code>{r['info'].get('wkn','→ suchen')}</code>\n"
                        f"🔧 KO: hsbc-zertifikate.de → {r['ticker']} → Turbo Long\n"
                        f"📱 TSL: {a['tsl_pct']}% | R:R 1:{a['rr']}\n"
                        f"⚠️ <i>Kein Anlageberater!</i>"
                    )
                    if send_telegram(sig_msg):
                        signals[r["ticker"]] = datetime.now().isoformat()
                        open_position(r["ticker"], r["analysis"], state)
                        print(f"  ✅ Gesendet + Position getrackt")
                except Exception as e:
                    print(f"  Fehler: {e}")

    # ── INTRADAY: Nur echte Signale ───────────────────────────────────────────
    else:
        print("\n🔍 Intraday-Scan...")
        intraday = dict(WATCHLIST)
        # Pro Sektor zusätzlich Top-5 Titel
        for sektor, tickers in MEGATREND_UNIVERSE.items():
            for t in tickers[:5]:
                if t not in intraday:
                    intraday[t] = {"name": t, "wkn": "→ suchen",
                                   "megatrend": sektor, "market": "US"}

        signals_found = []
        for ticker, info in intraday.items():
            a = analyze_ticker(ticker)
            if not a:
                continue
            print(f"  {ticker}: {a['score']}/8 | {a['direction']} | RSI {a['rsi']:.1f}")

            if a["score"] >= MIN_SCORE and a["direction"] == "LONG":
                if recently_sent(ticker, signals):
                    print(f"  → Bereits gesendet")
                    continue
                print(f"  🚨 SIGNAL!")
                try:
                    sig = get_claude_signal(ticker, a, info)
                except Exception as e:
                    sig = "Analyse nicht verfügbar."

                stars   = "⭐" * (1 if a["score"] == 6 else 2 if a["score"] == 7 else 3)
                sig_msg = (
                    f"📊 <b>SIGNAL — {ticker}</b> {stars}\n"
                    f"<b>{info.get('name',ticker)}</b> | Score <b>{a['score']}/8</b> | {now}\n"
                    f"🔥 <b>MEGATREND: {info['megatrend']}</b>\n"
                    f"{'─'*32}\n{sig}\n{'─'*32}\n"
                    f"📌 WKN: <code>{info.get('wkn','→ suchen')}</code>\n"
                    f"🔧 KO: hsbc-zertifikate.de → {ticker} → Turbo Long\n"
                    f"📱 TSL: {a['tsl_pct']}% | R:R 1:{a['rr']}\n"
                    f"⚠️ <i>Kein Anlageberater!</i>"
                )
                if send_telegram(sig_msg):
                    signals[ticker] = datetime.now().isoformat()
                    open_position(ticker, a, state)
                    signals_found.append(ticker)
                    print(f"  ✅ Gesendet + Position getrackt")

        if not signals_found:
            print("\n→ Keine Signale.")
        else:
            print(f"\n✅ {len(signals_found)} Signal(e): {', '.join(signals_found)}")

    save_state(state)
    print("\nScan abgeschlossen.")


if __name__ == "__main__":
    run_scan()
