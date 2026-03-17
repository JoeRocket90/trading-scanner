"""
Trading Signal Scanner v4 - Auto-Derivate-Suche
Neu: Automatische KO-Schein + Optionsschein Suche via finanzen.net bei jedem Signal
"""

import os
import re
import json
import requests
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import anthropic

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# ── Konfiguration ──────────────────────────────────────────────────────────────

MIN_SCORE       = 6
TOP_N           = 5
ANTI_SPAM_HOURS = 6
TSL_TRIGGER_PCT = 0.035
TP_TOLERANCE    = 0.005

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ── Kern-Watchlist ─────────────────────────────────────────────────────────────

WATCHLIST = {
    "NVDA":   {"name": "NVIDIA",           "wkn": "918422",  "isin": "US67066G1040", "slug": "nvidia",           "megatrend": "AI & Halbleiter", "market": "US"},
    "ASML":   {"name": "ASML Holding",     "wkn": "A1J4U4",  "isin": "NL0010273215", "slug": "asml-holding",     "megatrend": "AI & Halbleiter", "market": "US"},
    "AVGO":   {"name": "Broadcom",         "wkn": "A2JG9Z",  "isin": "US11135F1012", "slug": "broadcom",         "megatrend": "AI & Halbleiter", "market": "US"},
    "AMD":    {"name": "AMD",              "wkn": "A2N6GH",  "isin": "US0079031078", "slug": "advanced-micro-devices", "megatrend": "AI & Halbleiter", "market": "US"},
    "MSFT":   {"name": "Microsoft",        "wkn": "870747",  "isin": "US5949181045", "slug": "microsoft",        "megatrend": "AI & Halbleiter", "market": "US"},
    "XOM":    {"name": "ExxonMobil",       "wkn": "852549",  "isin": "US30231G1022", "slug": "exxon-mobil",      "megatrend": "Energie",         "market": "US"},
    "SLB":    {"name": "SLB",              "wkn": "853390",  "isin": "AN8068571086", "slug": "schlumberger",     "megatrend": "Energie",         "market": "US"},
    "NEE":    {"name": "NextEra Energy",   "wkn": "A0NH8V",  "isin": "US65339F1012", "slug": "nextera-energy",   "megatrend": "Energie",         "market": "US"},
    "NVO":    {"name": "Novo Nordisk",     "wkn": "A1XA8R",  "isin": "US6701002056", "slug": "novo-nordisk",     "megatrend": "Healthcare GLP-1","market": "US"},
    "LLY":    {"name": "Eli Lilly",        "wkn": "858560",  "isin": "US5324571083", "slug": "eli-lilly",        "megatrend": "Healthcare GLP-1","market": "US"},
    "PM":     {"name": "Philip Morris",    "wkn": "A14TQH",  "isin": "US7181721090", "slug": "philip-morris-international", "megatrend": "Defensiv", "market": "US"},
    "GD":     {"name": "General Dynamics", "wkn": "851143",  "isin": "US3695501086", "slug": "general-dynamics", "megatrend": "Ruestung",        "market": "US"},
    "GLD":    {"name": "Gold ETF",         "wkn": "A0LP78",  "isin": "US78463V1070", "slug": "spdr-gold-shares", "megatrend": "Gold Hedge",      "market": "ETF"},
    "GDX":    {"name": "Gold Miner ETF",   "wkn": "A0Q8NB",  "isin": "US92189F1066", "slug": "vaneck-vectors-gold-miners", "megatrend": "Gold Hedge", "market": "ETF"},
    "RHM.DE": {"name": "Rheinmetall",      "wkn": "703000",  "isin": "DE0007030009", "slug": "rheinmetall",      "megatrend": "Ruestung Europa", "market": "DAX"},
    "SIE.DE": {"name": "Siemens",          "wkn": "723610",  "isin": "DE0007236101", "slug": "siemens",          "megatrend": "Infrastruktur",   "market": "DAX"},
    "ZAL.DE": {"name": "Zalando",          "wkn": "ZAL111",  "isin": "DE000ZAL1111", "slug": "zalando",          "megatrend": "E-Commerce",      "market": "DAX"},
    "SAP.DE": {"name": "SAP",              "wkn": "716460",  "isin": "DE0007164600", "slug": "sap",              "megatrend": "AI & Halbleiter", "market": "DAX"},
    "SPY":    {"name": "S&P 500 ETF",      "wkn": "A0AET0",  "isin": "US78462F1030", "slug": "spdr-sp-500",      "megatrend": "Index",           "market": "ETF"},
    "QQQ":    {"name": "Nasdaq 100 ETF",   "wkn": "A0AET7",  "isin": "US46090E1038", "slug": "invesco-qqq-trust","megatrend": "Index",           "market": "ETF"},
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

# ── AUTO-DERIVATE-SUCHE v4.2 (onvista JSON-API) ──────────────────────────────
#
# Strategie: onvista JSON-API (stabiles JSON, kein JS-Rendering noetig)
# Finanzen.Zero / gettex Emittenten: HSBC, Goldman, Morgan Stanley, Vontobel, UBS, HVB
#
# System-Parameter nach unserem Trading-System:
#   KO Long : Hebel 3-6x | KO-Schwelle mind. 8% unter Entry-Kurs
#   OS Call : Hebel 3-8x | Restlaufzeit mind. 90 Tage

ONVISTA_HEADS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0",
    "Accept":     "application/json",
    "Referer":    "https://www.onvista.de/",
}

# Nur diese Emittenten sind auf gettex / Finanzen.Zero handelbar
GETTEX_EMITTENTEN = {
    "hsbc", "goldman", "gs bank", "morgan stanley",
    "vontobel", "ubs", "hvb", "unicredit", "hypo"
}
EMITTENT_KURZ = {
    "hsbc":           "HSBC",
    "goldman":        "Goldman",
    "gs bank":        "Goldman",
    "morgan stanley": "Morgan S.",
    "vontobel":       "Vontobel",
    "ubs":            "UBS",
    "hvb":            "HVB",
    "unicredit":      "HVB",
    "hypo":           "HVB",
}


def fetch_derivate(ticker, info, entry_price):
    """
    Hauptfunktion: holt KO-Scheine + OS via onvista JSON-API.
    Filtert auf gettex-Emittenten + System-Parameter.
    """
    isin = info.get("isin", "")
    slug = info.get("slug", ticker.lower().replace(".de", ""))

    if not isin:
        return _derivate_fallback(slug)

    # Schritt 1: onvista Entity-ID via ISIN ermitteln
    entity = _get_onvista_entity(isin)

    ko_results = []
    os_result  = None

    if entity:
        ko_results = _fetch_ko_onvista(entity, entry_price)
        os_result  = _fetch_os_onvista(entity, entry_price)

    lines = []

    if ko_results:
        lines.append("🔴 <b>KO Long (gettex):</b>")
        for ko in ko_results[:2]:
            lines.append(
                "  • WKN <code>" + ko["wkn"] + "</code>"
                + " | " + ko.get("emittent", "—")
                + " | Hebel " + ko.get("hebel", "?") + "x"
                + " | KO " + ko.get("barrier", "?")
            )
    else:
        lines.append(
            "🔴 KO Long: <a href=\"https://www.hsbc-zertifikate.de/home/alle-produkte/hebel/turbo-bull-bear.html\">HSBC</a>"
            + " | ISIN: " + isin
        )

    if os_result:
        lines.append("🟡 <b>OS Call (gettex):</b>")
        lines.append(
            "  • WKN <code>" + os_result["wkn"] + "</code>"
            + " | " + os_result.get("emittent", "—")
            + " | Hebel " + os_result.get("hebel", "?") + "x"
            + " | Laufzeit " + os_result.get("laufzeit", "?")
        )
    else:
        lines.append(
            "🟡 OS Call: finanzen.net → " + slug + " → Optionsscheine"
        )

    return "\n".join(lines)


def _get_onvista_entity(isin):
    """Sucht onvista Entity-ID via ISIN. Gibt dict {type, id} zurueck oder None."""
    try:
        url  = "https://api.onvista.de/api/v1/instruments/search/query"
        resp = requests.get(url, params={"query": isin, "limit": 5},
                            headers=ONVISTA_HEADS, timeout=10)
        if resp.status_code != 200:
            print("  onvista Entity: HTTP " + str(resp.status_code))
            return None

        data  = resp.json()
        items = data.get("items", data if isinstance(data, list) else [])

        for item in items:
            isin_check = str(item.get("isin", ""))
            if isin_check.upper() == isin.upper():
                etype = str(item.get("entityType", "STOCK"))
                eid   = str(item.get("entityValue", item.get("id", "")))
                if eid:
                    print("  onvista Entity OK: " + etype + "/" + eid)
                    return {"type": etype, "id": eid}

        # Fallback: erstes Ergebnis nehmen
        if items:
            first = items[0]
            etype = str(first.get("entityType", "STOCK"))
            eid   = str(first.get("entityValue", first.get("id", "")))
            if eid:
                print("  onvista Entity (Fallback): " + etype + "/" + eid)
                return {"type": etype, "id": eid}

    except Exception as e:
        print("  onvista Entity Fehler: " + str(e))
    return None


def _fetch_ko_onvista(entity, entry_price):
    """Holt KO-Calls via onvista Derivate-API, filtert nach System-Parametern."""
    results        = []
    ko_max_barrier = entry_price * 0.92   # mind. 8% Abstand (System-Regel)
    ko_min_barrier = entry_price * 0.60   # max 40% Abstand (sinnvoller Hebel)

    url = ("https://api.onvista.de/api/v1/instruments/"
           + entity["type"] + "/" + entity["id"]
           + "/derivatives/list")

    params = {
        "derivativeCategory": "KNOCK_OUT",
        "derivativeType":     "CALL",
        "sortType":           "LEVERAGE_ASC",
        "limit":              "50",
        "offset":             "0",
    }

    try:
        resp = requests.get(url, params=params, headers=ONVISTA_HEADS, timeout=12)
        if resp.status_code != 200:
            print("  KO onvista: HTTP " + str(resp.status_code))
            return []

        data  = resp.json()
        items = data.get("list", data.get("items", data if isinstance(data, list) else []))
        print("  KO onvista: " + str(len(items)) + " Treffer")

        for item in items:
            try:
                wkn          = str(item.get("wkn", "")).strip().upper()
                emittent_raw = str(item.get("issuer", item.get("emittent", ""))).lower()
                barrier      = _sf(item.get("knockOutBarrier",
                                   item.get("barrier",
                                   item.get("knockoutLevel",
                                   item.get("strikePrice", 0)))))
                hebel        = _sf(item.get("leverage",
                                   item.get("leverageFactor",
                                   item.get("gearing", 0))))

                # gettex-Filter: nur erlaubte Emittenten
                if not _is_gettex_emittent(emittent_raw):
                    continue
                if not wkn or len(wkn) < 4:
                    continue
                # KO-Abstand: mind. 8%, max. 40% unter Entry
                if barrier <= 0:
                    continue
                if barrier >= ko_max_barrier or barrier < ko_min_barrier:
                    continue
                # Hebel-Filter 3-6x
                if not (3.0 <= hebel <= 6.0):
                    continue

                results.append({
                    "wkn":      wkn,
                    "hebel":    str(round(hebel, 1)),
                    "barrier":  str(round(barrier, 2)),
                    "emittent": _map_emittent(emittent_raw),
                })

                if len(results) >= 2:
                    break

            except Exception:
                continue

    except Exception as e:
        print("  KO onvista Fehler: " + str(e))

    return results


def _fetch_os_onvista(entity, entry_price):
    """Holt OS-Calls via onvista Derivate-API, filtert nach System-Parametern."""
    from datetime import datetime, timedelta
    min_expiry = datetime.now() + timedelta(days=90)  # mind. 3 Monate Laufzeit

    url = ("https://api.onvista.de/api/v1/instruments/"
           + entity["type"] + "/" + entity["id"]
           + "/derivatives/list")

    params = {
        "derivativeCategory": "WARRANT",
        "derivativeType":     "CALL",
        "sortType":           "LEVERAGE_ASC",
        "limit":              "50",
        "offset":             "0",
    }

    try:
        resp = requests.get(url, params=params, headers=ONVISTA_HEADS, timeout=12)
        if resp.status_code != 200:
            return None

        data  = resp.json()
        items = data.get("list", data.get("items", data if isinstance(data, list) else []))
        print("  OS onvista: " + str(len(items)) + " Treffer")

        for item in items:
            try:
                wkn          = str(item.get("wkn", "")).strip().upper()
                emittent_raw = str(item.get("issuer", item.get("emittent", ""))).lower()
                hebel        = _sf(item.get("leverage",
                                   item.get("leverageFactor",
                                   item.get("gearing", 0))))
                expiry_str   = str(item.get("expiryDate",
                                   item.get("maturityDate",
                                   item.get("laufzeit", ""))))

                if not _is_gettex_emittent(emittent_raw):
                    continue
                if not wkn or len(wkn) < 4:
                    continue
                if not (3.0 <= hebel <= 8.0):
                    continue

                # Laufzeit-Check: mind. 90 Tage
                try:
                    exp_date = datetime.fromisoformat(expiry_str[:10])
                    if exp_date < min_expiry:
                        continue
                except Exception:
                    pass  # Datum nicht parsebar, trotzdem nehmen

                return {
                    "wkn":      wkn,
                    "hebel":    str(round(hebel, 1)),
                    "laufzeit": _format_expiry(expiry_str),
                    "emittent": _map_emittent(emittent_raw),
                }

            except Exception:
                continue

    except Exception as e:
        print("  OS onvista Fehler: " + str(e))

    return None


def _is_gettex_emittent(raw):
    """Prueft ob Emittent auf gettex / Finanzen.Zero handelbar ist."""
    raw = raw.lower()
    return any(e in raw for e in GETTEX_EMITTENTEN)


def _map_emittent(raw):
    """Kuerzt Emittenten-Namen auf Kurzform."""
    raw = raw.lower()
    for key, short in EMITTENT_KURZ.items():
        if key in raw:
            return short
    return raw[:12].title() if raw else "—"


def _sf(val):
    """Safe float — gibt 0.0 bei None/ungueltigem Wert."""
    try:
        if val is None:
            return 0.0
        return float(str(val).replace(",", ".").strip())
    except Exception:
        return 0.0


def _format_expiry(expiry_str):
    """ISO-Datum → lesbares Kurzformat: '2026-09-18' → 'Sep 26'"""
    months = ["Jan","Feb","Mar","Apr","Mai","Jun",
              "Jul","Aug","Sep","Okt","Nov","Dez"]
    try:
        parts = str(expiry_str)[:10].split("-")
        if len(parts) == 3:
            return months[int(parts[1]) - 1] + " " + parts[2][-2:]
    except Exception:
        pass
    return str(expiry_str)[:10] if len(str(expiry_str)) >= 10 else str(expiry_str)


def _derivate_fallback(slug):
    """Fallback wenn ISIN fehlt oder API komplett nicht erreichbar."""
    return (
        "🔴 KO Long: hsbc-zertifikate.de → Turbo Long suchen\n"
        "🟡 OS Call: finanzen.net → " + slug + " → Optionsscheine"
    )


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

            if c <= stop:
                loss = round(((c - entry) / entry) * 100, 1)
                msg = (
                    "⛔ <b>STOP-LOSS - " + ticker + "</b>\n"
                    "Kurs: " + str(round(c,2)) + " | Stop: " + str(stop) + "\n"
                    "Verlust: " + str(loss) + "%\n"
                    "────────────────────\n"
                    "🚨 <b>Sofortmassnahme Finanzen.Zero:</b>\n"
                    "1. Depot oeffnen → " + ticker + "\n"
                    "2. KO/OS → Verkaufen → Market Order\n"
                    "3. Aktie (falls gehalten) → Stop-Loss hat ausgeloest\n"
                    "────────────────────\n"
                    "⚠️ Kein Anlageberater!"
                )
                exit_messages.append(msg)
                to_close.append((ticker, "Stop-Loss"))

            elif c >= tp2 * (1 - TP_TOLERANCE):
                msg = (
                    "🎯 <b>TP2 ERREICHT - " + ticker + "</b>\n"
                    "Kurs: " + str(round(c,2)) + " | TP2: " + str(tp2) + "\n"
                    "Gewinn: +" + str(pnl_pct) + "%\n"
                    "────────────────────\n"
                    "✅ <b>Aktion Finanzen.Zero:</b>\n"
                    "1. Restposition KO/OS vollstaendig verkaufen\n"
                    "2. Limit-Order bei " + str(tp2) + " oder Market\n"
                    "3. Maximales Ziel erreicht — Trade abgeschlossen!\n"
                    "────────────────────\n"
                    "⚠️ Kein Anlageberater!"
                )
                exit_messages.append(msg)
                to_close.append((ticker, "TP2"))

            elif c >= tp1 * (1 - TP_TOLERANCE) and not tp1_hit:
                state["positions"][ticker]["tp1_hit"] = True
                new_tsl_level = round(entry * (1 - tsl_pct), 2)
                msg = (
                    "✅ <b>TP1 ERREICHT - " + ticker + "</b>\n"
                    "Kurs: " + str(round(c,2)) + " | TP1: " + str(tp1) + "\n"
                    "Gewinn: +" + str(pnl_pct) + "%\n"
                    "────────────────────\n"
                    "📋 <b>Aktion Finanzen.Zero:</b>\n"
                    "1. 50% des KO/OS verkaufen → Limit " + str(tp1) + "\n"
                    "2. TSL anpassen auf Break-Even:\n"
                    "   Order → TSL aendern → neuer Abstand\n"
                    "   sodass Stop bei Entry <b>" + str(entry) + "</b> liegt\n"
                    "3. Rest laeuft bis TP2: " + str(tp2) + "\n"
                    "────────────────────\n"
                    "⚠️ Kein Anlageberater!"
                )
                exit_messages.append(msg)

            elif c <= tsl_lvl and c >= entry:
                profit = round(((c - entry) / entry) * 100, 1)
                msg = (
                    "🔒 <b>TSL MIT GEWINN - " + ticker + "</b>\n"
                    "Kurs: " + str(round(c,2)) + " | TSL-Level: " + str(tsl_lvl) + "\n"
                    "Gewinn gesichert: +" + str(profit) + "%\n"
                    "────────────────────\n"
                    "📋 <b>Aktion Finanzen.Zero:</b>\n"
                    "1. Trailing Stop hat automatisch ausgeloest\n"
                    "2. Position sollte bereits geschlossen sein\n"
                    "3. Falls nicht: KO/OS manuell verkaufen\n"
                    "────────────────────\n"
                    "⚠️ Kein Anlageberater!"
                )
                exit_messages.append(msg)
                to_close.append((ticker, "TSL mit Gewinn"))

            elif c <= tsl_lvl and c < entry:
                msg = (
                    "⚠️ <b>TSL AUSGELOEST - " + ticker + "</b>\n"
                    "Kurs: " + str(round(c,2)) + " | TSL-Level: " + str(tsl_lvl) + "\n"
                    "PnL: " + str(pnl_pct) + "%\n"
                    "────────────────────\n"
                    "📋 <b>Aktion Finanzen.Zero:</b>\n"
                    "1. Trailing Stop hat ausgeloest\n"
                    "2. KO/OS sollte verkauft sein — pruefen!\n"
                    "3. Falls nicht: sofort Market verkaufen\n"
                    "────────────────────\n"
                    "⚠️ Kein Anlageberater!"
                )
                exit_messages.append(msg)
                to_close.append((ticker, "TSL Verlust"))

            else:
                e10  = float(close.ewm(span=10, adjust=False).mean().iloc[-1])
                e20  = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
                mf   = close.ewm(span=12, adjust=False).mean()
                ms_s = close.ewm(span=26, adjust=False).mean()
                mh   = float((mf - ms_s).iloc[-1])
                mh_p = float((mf - ms_s).iloc[-2])
                if e10 < e20 and mh < 0 and mh < mh_p:
                    msg = (
                        "📉 <b>TECH. AUSSTIEG - " + ticker + "</b>\n"
                        "Kurs: " + str(round(c,2)) + " | Entry: " + str(entry) + "\n"
                        "PnL: " + str(pnl_pct) + "%\n"
                        "────────────────────\n"
                        "EMA10 < EMA20 + MACD negativ\n"
                        "📋 <b>Empfehlung Finanzen.Zero:</b>\n"
                        "1. Chart pruefen — Trendbruch bestaetigt?\n"
                        "2. Wenn ja: KO/OS verkaufen\n"
                        "3. TSL enger setzen als Absicherung\n"
                        "────────────────────\n"
                        "⚠️ Kein Anlageberater!"
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
                    "name": ticker, "wkn": "suchen", "isin": "",
                    "slug": ticker.lower().replace(".de",""),
                    "megatrend": sektor, "market": "US",
                })
                results.append({"ticker": ticker, "info": info,
                                 "analysis": a, "sektor": sektor})
    results.sort(key=lambda x: x["analysis"]["score"], reverse=True)
    print("  -> " + str(len(results)) + " Long-Kandidaten")
    return results

# ── Claude Analyse ─────────────────────────────────────────────────────────────

def get_claude_signal(ticker, analysis, info):
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
    # Retry-Logik: 2 Versuche mit je 25s Timeout
    for attempt in range(2):
        try:
            client = anthropic.Anthropic(
                api_key=os.environ["ANTHROPIC_API_KEY"],
                timeout=25.0,
            )
            r = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            return r.content[0].text
        except Exception as e:
            print("  Claude-Signal Versuch " + str(attempt+1) + " Fehler: " + str(e))
            if attempt == 0:
                import time; time.sleep(3)
    # Fallback: kompakte Analyse ohne Claude
    return (
        "📊 <b>Setup:</b> " + ticker + " Score " + str(analysis["score"]) + "/8\n"
        + "📈 Trend: EMA-Faecher "
        + ("✅" if "OK" in analysis["checks"].get("EMA-Faecher","") else "❌")
        + " | RSI " + str(round(analysis["rsi"],1))
        + " | MACD "
        + ("✅" if "OK" in analysis["checks"].get("MACD","") else "❌") + "\n"
        + "💡 Megatrend: " + info.get("megatrend", "-")
    )

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

# ── Signal-Nachricht bauen (NEU in v4) ─────────────────────────────────────────

def build_signal_msg(ticker, info, analysis, sektor, claude_text, now, derivate_text):
    stars     = "*" * (1 if analysis["score"] == 6 else 2 if analysis["score"] == 7 else 3)
    entry     = round(analysis["price"], 2)
    sl        = analysis["stop_loss"]
    tp1       = analysis["tp1"]
    tp2       = analysis["tp2"]
    tsl_pct   = analysis["tsl_pct"]
    tsl_level = round(entry * (1 - tsl_pct / 100), 2)

    msg = (
        "📊 <b>SIGNAL - " + ticker + "</b> " + stars + "\n"
        + "<b>" + info.get("name", ticker) + "</b>"
        + " | Score <b>" + str(analysis["score"]) + "/8</b> | " + now + "\n"
        + "<b>MEGATREND: " + sektor + "</b>\n"
        + "────────────────────────\n"
        + claude_text + "\n"
        + "────────────────────────\n"
        + "📋 <b>Aktie WKN:</b> <code>" + info.get("wkn","suchen") + "</code>\n"
        + derivate_text + "\n"
        + "────────────────────────\n"
        + "📌 <b>TRADE-PLAN:</b>\n"
        + "  Entry:  <b>" + str(entry) + "</b>\n"
        + "  Stop:   <b>" + str(sl) + "</b>  ← sofort setzen\n"
        + "  TP1:    <b>" + str(tp1) + "</b>  ← 50% schliessen\n"
        + "  TP2:    <b>" + str(tp2) + "</b>  ← Rest schliessen\n"
        + "  R:R:    1:" + str(analysis["rr"]) + "\n"
        + "────────────────────────\n"
        + "🔁 <b>TSL bei Finanzen.Zero:</b>\n"
        + "  Ordertyp → TSL → Abstand <b>" + str(tsl_pct) + "%</b>\n"
        + "  (= Kurs " + str(tsl_level) + " bei Entry)\n"
        + "  Bei TP1: TSL auf Break-Even <b>" + str(entry) + "</b> nachziehen\n"
        + "────────────────────────\n"
        + "🚪 <b>AUSSTIEGS-PLAN Derivat:</b>\n"
        + "  TP1 → 50% des KO/OS verkaufen\n"
        + "  TP2 → Rest verkaufen\n"
        + "  TSL ausgeloest → sofort schliessen\n"
        + "  Kurs unter Stop → sofort schliessen\n"
        + "⚠️ Kein Anlageberater!"
    )
    return msg

# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram(message):
    token   = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url     = "https://api.telegram.org/bot" + token + "/sendMessage"
    payload = {
        "chat_id":    chat_id,
        "text":       message,
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
    print("Trading Scanner v4 - " + now)
    mode = "MORGEN" if is_morning else "NACHMITTAG" if is_afternoon else "INTRADAY"
    print("Modus: " + mode + " | Offene Positionen: " + str(len(positions)))
    print("BS4 verfuegbar: " + str(BS4_AVAILABLE))
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
                    pos_lines.append(
                        pticker + ": Entry " + str(pos["entry"])
                        + " → " + str(round(c,2))
                        + " (" + sign + str(pnl) + "%)"
                        + " | SL: " + str(pos["stop"])
                        + " | TP1: " + str(pos["tp1"])
                    )
                except:
                    pos_lines.append(pticker + ": Daten nicht verfuegbar")

            pos_msg = (
                "📂 <b>OFFENE POSITIONEN (" + str(len(positions)) + ")</b>\n"
                + "\n".join(pos_lines)
                + "\n\n⚠️ Kein Anlageberater!"
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

        msg = (
            "📈 <b>" + label + " - " + now + "</b>\n"
            + markt_info + "\n"
            + "────────────────────────\n"
            + bericht + "\n"
            + "────────────────────────\n"
            + "<b>Top-" + str(TOP_N) + " Setups:</b>\n"
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

        msg += "\n⚠️ Kein Anlageberater!"

        if len(msg) > 4000:
            msg = msg[:3950] + "\n...\n⚠️ Kein Anlageberater!"

        send_telegram(msg)
        print("\n" + label + " gesendet")

        # Echte Signale einzeln mit Derivaten senden
        for r in top5:
            a = r["analysis"]
            if a["score"] >= MIN_SCORE and not recently_sent(r["ticker"], signals):
                print("\nEinzel-Signal: " + r["ticker"] + " " + str(a["score"]) + "/8")
                print("  Suche Derivate fuer " + r["ticker"] + "...")
                derivate_text = fetch_derivate(r["ticker"], r["info"], a["price"])
                try:
                    sig = get_claude_signal(r["ticker"], a, r["info"])
                    sig_msg = build_signal_msg(
                        r["ticker"], r["info"], a, r["sektor"], sig, now, derivate_text
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
                    intraday[t] = {
                        "name": t, "wkn": "suchen", "isin": "",
                        "slug": t.lower().replace(".de",""),
                        "megatrend": sektor, "market": "US",
                    }

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
                print("  SIGNAL! Suche Derivate...")
                derivate_text = fetch_derivate(ticker, info, a["price"])
                try:
                    sig = get_claude_signal(ticker, a, info)
                except Exception as e:
                    sig = "Analyse nicht verfuegbar."

                sig_msg = build_signal_msg(
                    ticker, info, a, info["megatrend"], sig, now, derivate_text
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
