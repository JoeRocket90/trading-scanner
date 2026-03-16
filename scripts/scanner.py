"""
Trading Signal Scanner v3 - Exit-Signale + TSL-Tracking
Neu: TSL-Alarm, TP1/TP2-Alarm, Technischer Ausstieg, Positions-Tracking
"""

import os
import json
import requests
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import anthropic

# ── Konfiguration ──────────────────────────────────────────────────────────────

MIN_SCORE       = 6
TOP_N           = 5
ANTI_SPAM_HOURS = 6
TSL_TRIGGER_PCT = 0.035   # TSL-Alarm ab 3.5% Rückgang vom Hochpunkt
TP_TOLERANCE    = 0.005   # TP gilt als erreicht bei 0.5% Abstand

# ── Kern-Watchlist ─────────────────────────────────────────────────────────────

WATCHLIST = {
    "NVDA":   {"name": "NVIDIA",         "wkn": "918422",  "megatrend": "AI & Halbleiter", "market": "US"},
    "ASML":   {"name": "ASML Holding",   "wkn": "A1J4U4",  "megatrend": "AI & Halbleiter", "market": "US"},
    "AVGO":   {"name": "Broadcom",       "wkn": "A2JG9Z",  "megatrend": "AI & Halbleiter", "market": "US"},
    "AMD":    {"name": "AMD",            "wkn": "A2N6GH",  "megatrend": "AI & Halbleiter", "market": "US"},
    "MSFT":   {"name": "Microsoft",      "wkn": "870747",  "megatrend": "AI & Halbleiter", "market": "US"},
    "XOM":    {"name": "ExxonMobil",     "wkn": "852549",  "megatrend": "Energie",         "market": "US"},
    "SLB":    {"name": "SLB",            "wkn": "853390",  "megatrend": "Energie",         "market": "US"},
    "NEE":    {"name": "NextEra Energy", "wkn": "A0NH8V",  "megatrend": "Energie",         "market": "US"},
    "NVO":    {"name": "Novo Nordisk",   "wkn": "A1XA8R",  "megatrend": "Healthcare GLP-1","market": "US"},
    "LLY":    {"name": "Eli Lilly",      "wkn": "858560",  "megatrend": "Healthcare GLP-1","market": "US"},
    "PM":     {"name": "Philip Morris",  "wkn": "A14TQH",  "megatrend": "Defensiv",        "market": "US"},
    "GLD":    {"name": "Gold ETF",       "wkn": "A0LP78",  "megatrend": "Gold Hedge",      "market": "ETF"},
    "GDX":    {"name": "Gold Miner ETF", "wkn": "A0Q8NB",  "megatrend": "Gold Hedge",      "market": "ETF"},
    "RHM.DE": {"name": "Rheinmetall",    "wkn": "703000",  "megatrend": "Ruestung Europa", "market": "DAX"},
    "SIE.DE": {"name": "Siemens",        "wkn": "723610",  "megatrend": "Infrastruktur",   "market": "DAX"},
    "ZAL.DE": {"name": "Zalando",        "wkn": "ZAL111",  "megatrend": "E-Commerce",      "market": "DAX"},
    "SAP.DE": {"name": "SAP",            "wkn": "716460",  "megatrend": "AI & Halbleiter", "market": "DAX"},
    "SPY":    {"name": "S&P 500 ETF",    "wkn": "A0AET0",  "megatrend": "Index",           "market": "ETF"},
    "QQQ":    {"name": "Nasdaq 100 ETF", "wkn": "A0AET7",  "megatrend": "Index",           "market": "ETF"},
}

# ── Megatrend-Universen ────────────────────────────────────────────────────────

MEGATREND_UNIVERSE = {
    "AI & Halbleiter": [
        "NVDA","ASML","AVGO","AMD","TSM","LRCX","KLAC","AMAT","MRVL",
        "SMCI","ARM","INTC","QCOM","TXN","NXPI","ON","MPWR",
        "CDNS","SNPS","CRM","NOW","PLTR","AI",
    ],
    "Ruestung Europa": [
        "RHM.DE","BA","RTX","LMT","NOC","GD","HII","KTOS","AXON",
    ],
    "Energie & Power": [
        "XOM","CVX","COP","SLB","HAL","BKR","PSX","VLO","MPC",
        "NEE","CEG","VST","NRG","ETR","AEP","EXC","GEV","FSLR","ENPH",
    ],
    "Healthcare & GLP-1": [
        "NVO","LLY","MRNA","VRTX","REGN","ABBV","BMY","MRK","PFE",
        "JNJ","UNH","ABT","DHR","TMO","ISRG","SYK",
    ],
    "Gold & Rohstoffe": [
        "GLD","GDX","GDXJ","SLV","GOLD","NEM","AEM","WPM","FNV","FCX","MP",
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

        if e10 > e20 > e50:
            score += 2
            checks["EMA-Faecher"] = "OK: " + str(round(e10,2)) + ">" + str(round(e20,2)) + ">" + str(round(e50,2))
        else:
            checks["EMA-Faecher"] = "X: Nicht ausgerichtet"

        if c > e200:
            score += 1
            checks["EMA200"] = "OK: Kurs ueber EMA200"
        else:
            checks["EMA200"] = "X: Unter EMA200"

        if 45 <= r <= 70:
            score += 1
            checks["RSI"] = "OK: " + str(round(r,1)) + " (Bullish Zone)"
        elif r < 30:
            score += 1
            checks["RSI"] = "Ueberverkauft: " + str(round(r,1))
        else:
            checks["RSI"] = "X: " + str(round(r,1))

        if ml > ms and mh > mh_p:
            score += 1
            checks["MACD"] = "OK: Positiv und wachsend"
        else:
            checks["MACD"] = "X: Schwach"

        if vol_now > vol_avg * 1.2:
            score += 1
            checks["Volumen"] = "OK: +" + str(round(((vol_now/vol_avg)-1)*100)) + "% ueber Durchschnitt"
        else:
            checks["Volumen"] = "Normal"

        if fib["38.2"] >= c >= fib["61.8"]:
            score += 2
            checks["Fibonacci"] = "OK: Goldene Zone"
        elif fib["23.6"] >= c >= fib["78.6"]:
            score += 1
            checks["Fibonacci"] = "Nahe Fib-Level"
        else:
            checks["Fibonacci"] = "X: Kein Pullback"

        if e10 > e20 and c > e200:
            direction = "LONG"
        elif e10 < e20 and c < e200:
            direction = "SHORT/MEIDEN"
        else:
            direction = "NEUTRAL"

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
        print("  Fehler " + ticker_symbol + ": " + str(e))
        return None

# ── Positions-Tracking ─────────────────────────────────────────────────────────

def load_state():
    try:
        with open("sent_signals.json", "r") as f:
            data = json.load(f)
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
    state["positions"][ticker] = {
        "entry":     analysis["price"],
        "stop":      analysis["stop_loss"],
        "tp1":       analysis["tp1"],
        "tp2":       analysis["tp2"],
        "tsl_pct":   analysis["tsl_pct"],
        "high":      analysis["price"],
        "tp1_hit":   False,
        "opened_at": datetime.now().isoformat(),
    }
    print("  Position " + ticker + " wird getrackt")

def close_position(ticker, state, reason):
    if ticker in state["positions"]:
        del state["positions"][ticker]
        print("  Position " + ticker + " geschlossen: " + reason)

# ── Exit-Signale pruefen ───────────────────────────────────────────────────────

def check_exit_signals(state):
    exit_messages = []
    positions     = state.get("positions", {})
    to_close      = []

    for ticker, pos in list(positions.items()):
        try:
            df = yf.download(ticker, period="5d", interval="1d", progress=False)
            if df.empty:
                continue

            close  = df["Close"].squeeze()
            high_s = df["High"].squeeze()
            c      = float(close.iloc[-1])
            h_now  = float(high_s.iloc[-1])

            new_high = max(pos["high"], h_now, c)
            state["positions"][ticker]["high"] = new_high

            entry   = pos["entry"]
            stop    = pos["stop"]
            tp1     = pos["tp1"]
            tp2     = pos["tp2"]
            tsl_pct = pos["tsl_pct"] / 100
            tp1_hit = pos.get("tp1_hit", False)
            pnl_pct = round(((c - entry) / entry) * 100, 1)
            tsl_lvl = round(new_high * (1 - tsl_pct), 2)

            print("  " + ticker + ": Kurs " + str(round(c,2)) +
                  " | Entry " + str(entry) +
                  " | PnL " + str(pnl_pct) + "%" +
                  " | Hoch " + str(round(new_high,2)))

            # Stop-Loss getroffen
            if c <= stop:
                loss = round(((c - entry) / entry) * 100, 1)
                msg = (
                    "STOP-LOSS GETROFFEN - " + ticker + "\n"
                    "Kurs: " + str(round(c,2)) + " | Stop: " + str(stop) + "\n"
                    "Verlust: " + str(loss) + "%\n"
                    "--------------------------------\n"
                    "Aktion: Position SOFORT schliessen!\n"
                    "Stop-Loss wurde unterschritten."
                )
                exit_messages.append(msg)
                to_close.append((ticker, "Stop-Loss"))

            # TP2 erreicht
            elif c >= tp2 * (1 - TP_TOLERANCE):
                msg = (
                    "TP2 ERREICHT - " + ticker + "\n"
                    "Kurs: " + str(round(c,2)) + " | TP2: " + str(tp2) + "\n"
                    "Gesamtgewinn: +" + str(pnl_pct) + "%\n"
                    "--------------------------------\n"
                    "Aktion: Restposition vollstaendig schliessen!\n"
                    "Maximales Ziel erreicht."
                )
                exit_messages.append(msg)
                to_close.append((ticker, "TP2"))

            # TP1 erreicht (nur einmal)
            elif c >= tp1 * (1 - TP_TOLERANCE) and not tp1_hit:
                state["positions"][ticker]["tp1_hit"] = True
                msg = (
                    "TP1 ERREICHT - " + ticker + "\n"
                    "Kurs: " + str(round(c,2)) + " | TP1: " + str(tp1) + "\n"
                    "Gewinn: +" + str(pnl_pct) + "%\n"
                    "--------------------------------\n"
                    "Aktion: 50% der Position schliessen!\n"
                    "TSL auf Break-Even " + str(entry) + " nachziehen.\n"
                    "Rest laeuft weiter bis TP2: " + str(tp2)
                )
                exit_messages.append(msg)

            # TSL mit Gewinn
            elif c <= tsl_lvl and c >= entry:
                profit = round(((c - entry) / entry) * 100, 1)
                msg = (
                    "TSL MIT GEWINN - " + ticker + "\n"
                    "Kurs: " + str(round(c,2)) + " | TSL-Level: " + str(tsl_lvl) + "\n"
                    "Gewinn gesichert: +" + str(profit) + "%\n"
                    "--------------------------------\n"
                    "Aktion: Trailing Stop hat Gewinn gesichert.\n"
                    "Position schliessen."
                )
                exit_messages.append(msg)
                to_close.append((ticker, "TSL mit Gewinn"))

            # TSL mit Verlust
            elif c <= tsl_lvl and c < entry:
                msg = (
                    "TSL AUSGELOEST - " + ticker + "\n"
                    "Kurs: " + str(round(c,2)) + " | TSL-Level: " + str(tsl_lvl) + "\n"
                    "PnL: " + str(pnl_pct) + "%\n"
                    "--------------------------------\n"
                    "Aktion: Position schliessen!\n"
                    "Rueckgang von " + str(round(tsl_pct*100,1)) + "% vom Hochpunkt."
                )
                exit_messages.append(msg)
                to_close.append((ticker, "TSL Verlust"))

            # Technischer Ausstieg
            else:
                e10  = float(close.ewm(span=10, adjust=False).mean().iloc[-1])
                e20  = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
                mf   = close.ewm(span=12, adjust=False).mean()
                ms   = close.ewm(span=26, adjust=False).mean()
                mh   = float((mf - ms).iloc[-1])
                mh_p = float((mf - ms).iloc[-2])
                if e10 < e20 and mh < 0 and mh < mh_p:
                    msg = (
                        "TECHNISCHER AUSSTIEG - " + ticker + "\n"
                        "Kurs: " + str(round(c,2)) + " | Entry: " + str(entry) + "\n"
                        "PnL: " + str(pnl_pct) + "%\n"
                        "--------------------------------\n"
                        "EMA10 unter EMA20 + MACD negativ\n"
                        "Empfehlung: Ausstieg pruefen!"
                    )
                    exit_messages.append(msg)

        except Exception as e:
            print("  Exit-Check Fehler " + ticker + ": " + str(e))

    for ticker, reason in to_close:
        close_position(ticker, state, reason)

    return exit_messages

# ── Megatrend-Screening ────────────────────────────────────────────────────────

def scan_megatrend_universe():
    print("\nMegatrend-Screening...")
    results = []
    seen    = set()
    for sektor, tickers in MEGATREND_UNIVERSE.items():
        print("  " + sektor + " (" + str(len(tickers)) + " Titel)...")
        for ticker in tickers:
            if ticker in seen:
                continue
            seen.add(ticker)
            a = analyze_ticker(ticker)
            if a and a["direction"] == "LONG":
                info = WATCHLIST.get(ticker, {
                    "name": ticker, "wkn": "suchen",
                    "megatrend": sektor, "market": "US",
                })
                results.append({"ticker": ticker, "info": info,
                                 "analysis": a, "sektor": sektor})
    results.sort(key=lambda x: x["analysis"]["score"], reverse=True)
    print("  -> " + str(len(results)) + " Long-Kandidaten")
    return results

# ── Claude Analyse ─────────────────────────────────────────────────────────────

def get_claude_signal(ticker, analysis, info):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    checks = " | ".join([k + ": " + v for k, v in analysis["checks"].items()])
    prompt = (
        "Erfahrener Trading-Analyst. Kurzes Signal fuer Telegram (max 180 Woerter):\n\n"
        + ticker + " - " + info.get("name", ticker)
        + " | Score " + str(analysis["score"]) + "/8 | " + analysis["direction"] + "\n"
        + "Kurs: " + str(round(analysis["price"],2))
        + " | RSI: " + str(round(analysis["rsi"],1))
        + " | ATR: " + str(round(analysis["atr"],2)) + "\n"
        + "Checks: " + checks + "\n"
        + "Entry: " + str(round(analysis["price"],2))
        + " | SL: " + str(analysis["stop_loss"])
        + " | TP1: " + str(analysis["tp1"])
        + " | TP2: " + str(analysis["tp2"])
        + " | R:R 1:" + str(analysis["rr"]) + "\n"
        + "Megatrend: " + info.get("megatrend", "-") + "\n\n"
        + "Format: 1) Empfehlung 2) Begruendung (2 Saetze) 3) Levels 4) Megatrend. Emojis nutzen."
    )
    r = client.messages.create(model="claude-sonnet-4-6", max_tokens=400,
                                messages=[{"role": "user", "content": prompt}])
    return r.content[0].text

def get_claude_tagesbericht(top_results, markt_info):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    kandidaten = ""
    for i, r in enumerate(top_results[:5], 1):
        a = r["analysis"]
        kandidaten += (
            "\n" + str(i) + ". " + r["ticker"]
            + " (" + r["info"].get("name","") + ")"
            + " - Score " + str(a["score"]) + "/8"
            + " | RSI " + str(round(a["rsi"],1))
            + " | Kurs " + str(round(a["price"],2))
            + " | " + r["sektor"]
        )
    prompt = (
        "Trading-Analyst. Tagesbericht fuer Telegram (max 220 Woerter):\n\n"
        + "Markt: " + markt_info + "\n"
        + "Top-Kandidaten:" + kandidaten + "\n\n"
        + "Format: 1) Marktlage (2 Saetze) 2) Top-3 Kandidaten (je 1 Satz) "
        + "3) Tagesempfehlung. Emojis nutzen."
    )
    r = client.messages.create(model="claude-sonnet-4-6", max_tokens=500,
                                messages=[{"role": "user", "content": prompt}])
    return r.content[0].text

# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram(message):
    token   = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url     = "https://api.telegram.org/bot" + token + "/sendMessage"
    payload = {
        "chat_id":   chat_id,
        "text":      message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload)
    if r.status_code != 200:
        print("  Telegram Fehler: " + r.text)
    return r.status_code == 200

# ── Markt-Snapshot ─────────────────────────────────────────────────────────────

def get_markt_snapshot():
    snapshot = {}
    for ticker, name in {"SPY": "S&P500", "QQQ": "Nasdaq", "GLD": "Gold"}.items():
        try:
            df = yf.download(ticker, period="5d", interval="1d", progress=False)
            if not df.empty:
                c  = df["Close"].squeeze()
                ch = ((float(c.iloc[-1]) / float(c.iloc[-2])) - 1) * 100
                snapshot[name] = str(round(float(c.iloc[-1]))) + " (" + (("+" if ch>0 else "") + str(round(ch,1))) + "%)"
        except:
            pass
    return " | ".join([k + ": " + v for k, v in snapshot.items()])

# ── Haupt-Scanner ──────────────────────────────────────────────────────────────

def run_scan():
    now   = datetime.now().strftime("%d.%m.%Y %H:%M")
    hour  = datetime.now().hour
    state = load_state()
    signals   = state["signals"]
    positions = state["positions"]

    is_morning   = 7  <= hour <= 9
    is_afternoon = 14 <= hour <= 16

    print("\n" + "="*55)
    print("Trading Scanner v3 - " + now)
    mode = "MORGEN" if is_morning else "NACHMITTAG" if is_afternoon else "INTRADAY"
    print("Modus: " + mode + " | Offene Positionen: " + str(len(positions)))
    print("="*55)

    # EXIT-SIGNALE zuerst pruefen
    if positions:
        print("\nPruefe " + str(len(positions)) + " offene Position(en)...")
        exit_msgs = check_exit_signals(state)
        for msg in exit_msgs:
            send_telegram(msg)
            print("  -> Exit-Signal gesendet")
        if not exit_msgs:
            print("  -> Alle Positionen OK")

    # ── TAGESBERICHT ─────────────────────────────────────────────────────────
    if is_morning or is_afternoon:

        all_results = []
        seen        = set()

        # Kern-Watchlist
        print("\nKern-Watchlist...")
        for ticker, info in WATCHLIST.items():
            if ticker in seen:
                continue
            seen.add(ticker)
            a = analyze_ticker(ticker)
            if a:
                print("  " + ticker + ": " + str(a["score"]) + "/8 | " + a["direction"])
                if a["direction"] == "LONG":
                    all_results.append({"ticker": ticker, "info": info,
                                        "analysis": a, "sektor": info["megatrend"]})

        # Megatrend-Screening
        for r in scan_megatrend_universe():
            if r["ticker"] not in seen:
                seen.add(r["ticker"])
                all_results.append(r)

        all_results.sort(key=lambda x: x["analysis"]["score"], reverse=True)
        top5 = all_results[:TOP_N]

        print("\nTop-" + str(TOP_N) + ":")
        for i, r in enumerate(top5, 1):
            a = r["analysis"]
            print("  " + str(i) + ". " + r["ticker"]
                  + " Score " + str(a["score"]) + "/8"
                  + " | RSI " + str(round(a["rsi"],1))
                  + " | " + r["sektor"])

        # Offene Positionen im Morgen-Bericht
        if is_morning and positions:
            pos_lines = []
            for pticker, pos in positions.items():
                try:
                    df = yf.download(pticker, period="2d", interval="1d", progress=False)
                    c  = float(df["Close"].squeeze().iloc[-1]) if not df.empty else 0
                    pnl = round(((c - pos["entry"]) / pos["entry"]) * 100, 1) if pos["entry"] else 0
                    sign = "+" if pnl >= 0 else ""
                    emoji = "gruen" if pnl >= 0 else "rot"
                    pos_lines.append(
                        pticker + ": Entry " + str(pos["entry"])
                        + " -> " + str(round(c,2))
                        + " (" + sign + str(pnl) + "%)"
                        + " | SL: " + str(pos["stop"])
                        + " | TP1: " + str(pos["tp1"])
                    )
                except:
                    pos_lines.append(pticker + ": Daten nicht verfuegbar")

            pos_msg = (
                "<b>OFFENE POSITIONEN (" + str(len(positions)) + ")</b>\n"
                + "\n".join(pos_lines)
                + "\n\nKein Anlageberater - eigene Analyse!"
            )
            send_telegram(pos_msg)
            print("  -> " + str(len(positions)) + " Positionen gesendet")

        markt_info = get_markt_snapshot()

        print("\nClaude erstellt Tagesbericht...")
        try:
            bericht = get_claude_tagesbericht(top5, markt_info)
        except Exception as e:
            print("  Fehler: " + str(e))
            bericht = "Analyse nicht verfuegbar."

        label = "MORGEN-BERICHT" if is_morning else "NACHMITTAG-BERICHT"
        emoji = "Morgen" if is_morning else "Nachmittag"

        msg = (
            "<b>" + label + " - " + now + "</b>\n"
            + markt_info + "\n"
            + "--------------------------------\n"
            + bericht + "\n"
            + "--------------------------------\n"
            + "<b>Top-" + str(TOP_N) + " Setups (8-Punkte-System):</b>\n"
        )

        for i, r in enumerate(top5, 1):
            a     = r["analysis"]
            stars = "*" * (1 if a["score"] == 6 else 2 if a["score"] == 7 else 3)
            msg  += (
                "\n" + str(i) + ". <b>" + r["ticker"] + "</b> " + stars
                + " Score " + str(a["score"]) + "/8\n"
                + "   " + str(round(a["price"],2))
                + " | SL: " + str(a["stop_loss"])
                + " | TP1: " + str(a["tp1"])
                + " | R:R 1:" + str(a["rr"]) + "\n"
                + "   WKN: <code>" + r["info"].get("wkn","suchen") + "</code>"
                + " | TSL " + str(a["tsl_pct"]) + "%"
                + " | " + r["sektor"] + "\n"
            )

        msg += "\nKein Anlageberater - eigene Analyse erforderlich!"

        if len(msg) > 4000:
            msg = msg[:3950] + "\n...\nKein Anlageberater!"

        send_telegram(msg)
        print("\n" + label + " gesendet")

        # Echte Signale (Score >= MIN_SCORE) einzeln senden
        for r in top5:
            a = r["analysis"]
            if a["score"] >= MIN_SCORE and not recently_sent(r["ticker"], signals):
                print("\nEinzel-Signal: " + r["ticker"] + " " + str(a["score"]) + "/8")
                try:
                    sig = get_claude_signal(r["ticker"], a, r["info"])
                    stars = "*" * (1 if a["score"] == 6 else 2 if a["score"] == 7 else 3)
                    sig_msg = (
                        "<b>SIGNAL - " + r["ticker"] + "</b> " + stars + "\n"
                        + "<b>" + r["info"].get("name", r["ticker"]) + "</b>"
                        + " | Score <b>" + str(a["score"]) + "/8</b>\n"
                        + "<b>MEGATREND: " + r["sektor"] + "</b>\n"
                        + "--------------------------------\n"
                        + sig + "\n"
                        + "--------------------------------\n"
                        + "WKN: <code>" + r["info"].get("wkn","suchen") + "</code>\n"
                        + "KO: hsbc-zertifikate.de -> " + r["ticker"] + " -> Turbo Long\n"
                        + "TSL: " + str(a["tsl_pct"]) + "% | R:R 1:" + str(a["rr"]) + "\n"
                        + "Kein Anlageberater!"
                    )
                    if send_telegram(sig_msg):
                        signals[r["ticker"]] = datetime.now().isoformat()
                        open_position(r["ticker"], a, state)
                        print("  Gesendet + Position getrackt")
                except Exception as e:
                    print("  Fehler: " + str(e))

    # ── INTRADAY ──────────────────────────────────────────────────────────────
    else:
        print("\nIntraday-Scan...")
        intraday = dict(WATCHLIST)
        for sektor, tickers in MEGATREND_UNIVERSE.items():
            for t in tickers[:5]:
                if t not in intraday:
                    intraday[t] = {"name": t, "wkn": "suchen",
                                   "megatrend": sektor, "market": "US"}

        signals_found = []
        for ticker, info in intraday.items():
            a = analyze_ticker(ticker)
            if not a:
                continue
            print("  " + ticker + ": " + str(a["score"]) + "/8"
                  + " | " + a["direction"]
                  + " | RSI " + str(round(a["rsi"],1)))

            if a["score"] >= MIN_SCORE and a["direction"] == "LONG":
                if recently_sent(ticker, signals):
                    print("  -> Bereits gesendet")
                    continue
                print("  SIGNAL!")
                try:
                    sig = get_claude_signal(ticker, a, info)
                except Exception as e:
                    sig = "Analyse nicht verfuegbar."

                stars   = "*" * (1 if a["score"] == 6 else 2 if a["score"] == 7 else 3)
                sig_msg = (
                    "<b>SIGNAL - " + ticker + "</b> " + stars + "\n"
                    + "<b>" + info.get("name",ticker) + "</b>"
                    + " | Score <b>" + str(a["score"]) + "/8</b> | " + now + "\n"
                    + "<b>MEGATREND: " + info["megatrend"] + "</b>\n"
                    + "--------------------------------\n"
                    + sig + "\n"
                    + "--------------------------------\n"
                    + "WKN: <code>" + info.get("wkn","suchen") + "</code>\n"
                    + "KO: hsbc-zertifikate.de -> " + ticker + " -> Turbo Long\n"
                    + "TSL: " + str(a["tsl_pct"]) + "% | R:R 1:" + str(a["rr"]) + "\n"
                    + "Kein Anlageberater!"
                )
                if send_telegram(sig_msg):
                    signals[ticker] = datetime.now().isoformat()
                    open_position(ticker, a, state)
                    signals_found.append(ticker)
                    print("  Gesendet + Position getrackt")

        if not signals_found:
            print("\n-> Keine Signale.")
        else:
            print("\n" + str(len(signals_found)) + " Signal(e): " + ", ".join(signals_found))

    save_state(state)
    print("\nScan abgeschlossen.")


if __name__ == "__main__":
    run_scan()
