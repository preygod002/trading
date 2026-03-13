"""
Swing Scanner — Flask Web App
==============================
Runs the F&O swing scanner as a background service with a REST API.
Mobile UI at  /
API endpoints at  /api/*

Deploy free on Railway:
  railway init → railway up
"""

from flask import Flask, jsonify, render_template, request
import yfinance as yf
import pandas as pd
import numpy as np
import requests as req
import threading
import schedule
import time
import json
import os
import csv
from datetime import datetime, date
from zoneinfo import ZoneInfo

# ══════════════════════════════════════════════════════════════════
# CONFIG  — set via Railway environment variables or edit here
# ══════════════════════════════════════════════════════════════════
TELEGRAM_ENABLED  = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
BOT_TOKEN         = os.getenv("BOT_TOKEN", "")
TELEGRAM_CHAT_ID  = os.getenv("TELEGRAM_CHAT_ID", "")

EMA_PROXIMITY     = 0.005
MAX_CANDLE_RNG    = 0.01
MAX_SL_PCT        = 0.05
LOOKBACK_DAYS     = 30

DATA_DIR          = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

IST = ZoneInfo("Asia/Kolkata")

# ══════════════════════════════════════════════════════════════════
# F&O TICKERS
# ══════════════════════════════════════════════════════════════════
TICKERS = [
    "AARTIIND.NS","ABB.NS","ABBOTINDIA.NS","ABCAPITAL.NS","ABFRL.NS",
    "ACC.NS","ADANIENT.NS","ADANIPORTS.NS","ALKEM.NS","AMBUJACEM.NS",
    "APOLLOHOSP.NS","APOLLOTYRE.NS","ASHOKLEY.NS","ASIANPAINT.NS",
    "ASTRAL.NS","ATGL.NS","AUROPHARMA.NS","AXISBANK.NS","BAJAJ-AUTO.NS",
    "BAJAJFINSV.NS","BAJFINANCE.NS","BALKRISIND.NS","BANDHANBNK.NS",
    "BANKBARODA.NS","BATAINDIA.NS","BEL.NS","BERGEPAINT.NS",
    "BHARATFORG.NS","BHARTIARTL.NS","BHEL.NS","BIOCON.NS","BPCL.NS",
    "BRITANNIA.NS","BSOFT.NS","CANBK.NS","CANFINHOME.NS","CDSL.NS",
    "CESC.NS","CHOLAFIN.NS","CIPLA.NS","COALINDIA.NS","COFORGE.NS",
    "COLPAL.NS","CONCOR.NS","COROMANDEL.NS","CROMPTON.NS","CUB.NS",
    "CUMMINSIND.NS","DABUR.NS","DALBHARAT.NS","DEEPAKNTR.NS","DELTACORP.NS",
    "DIVISLAB.NS","DIXON.NS","DLF.NS","DRREDDY.NS","EICHERMOT.NS",
    "ESCORTS.NS","EXIDEIND.NS","FEDERALBNK.NS","GAIL.NS",
    "GLENMARK.NS","GMRINFRA.NS","GNFC.NS","GODREJCP.NS","GODREJPROP.NS",
    "GRANULES.NS","GRASIM.NS","GUJGASLTD.NS","HAL.NS","HAVELLS.NS",
    "HCLTECH.NS","HDFCBANK.NS","HDFCLIFE.NS","HEROMOTOCO.NS","HINDALCO.NS",
    "HINDCOPPER.NS","HINDPETRO.NS","HINDUNILVR.NS","ICICIBANK.NS",
    "ICICIGI.NS","ICICIPRULI.NS","IDFCFIRSTB.NS","IEX.NS",
    "IGL.NS","INDHOTEL.NS","INDIAMART.NS","INDUSINDBK.NS",
    "INDUSTOWER.NS","INFY.NS","INTELLECT.NS","IOC.NS","IPCALAB.NS",
    "IRCTC.NS","ITC.NS","JINDALSTEL.NS","JIOFIN.NS","JKCEMENT.NS",
    "JSL.NS","JSWSTEEL.NS","JUBLFOOD.NS","KALYANKJIL.NS","KOTAKBANK.NS",
    "LALPATHLAB.NS","LAURUSLABS.NS","LICHSGFIN.NS","LT.NS",
    "LTIM.NS","LTTS.NS","LUPIN.NS","M&M.NS","M&MFIN.NS","MANAPPURAM.NS",
    "MARICO.NS","MARUTI.NS","MAXHEALTH.NS","MCX.NS","METROPOLIS.NS",
    "MFSL.NS","MGL.NS","MOTHERSON.NS","MPHASIS.NS","MRF.NS","MUTHOOTFIN.NS",
    "NATIONALUM.NS","NAVINFLUOR.NS","NESTLEIND.NS",
    "NMDC.NS","NTPC.NS","OBEROIRLTY.NS","OFSS.NS","ONGC.NS","PAGEIND.NS",
    "PERSISTENT.NS","PETRONET.NS","PFC.NS","PIIND.NS","PNB.NS",
    "POLYCAB.NS","POWERGRID.NS","PVRINOX.NS","RAMCOCEM.NS",
    "RECLTD.NS","RELIANCE.NS","SAIL.NS","SBICARD.NS","SBILIFE.NS",
    "SBIN.NS","SHREECEM.NS","SHRIRAMFIN.NS","SIEMENS.NS","SRF.NS",
    "SUNPHARMA.NS","SUNTV.NS","SUPREMEIND.NS","SYNGENE.NS","TATACOMM.NS",
    "TATACONSUM.NS","TATAMOTORS.NS","TATAPOWER.NS","TATASTEEL.NS","TCS.NS",
    "TECHM.NS","TITAN.NS","TORNTPHARM.NS","TORNTPOWER.NS","TRENT.NS",
    "TRIDENT.NS","TVSMOTOR.NS","UBL.NS","ULTRACEMCO.NS",
    "UPL.NS","VEDL.NS","VOLTAS.NS","WIPRO.NS",
    "ZEEL.NS","ZYDUSLIFE.NS",
]

# ══════════════════════════════════════════════════════════════════
# SCANNER STATE  (thread-safe via lock)
# ══════════════════════════════════════════════════════════════════
_lock = threading.Lock()

state = {
    "status":          "idle",        # idle | scanning | stopped
    "scan_running":    False,
    "auto_schedule":   True,          # auto scans during market hours
    "current_ticker":  "",
    "scanned":         0,
    "total":           len(TICKERS),
    "signals_today":   {},            # ticker → signal dict
    "scan_log":        [],            # list of scan run summaries
    "scan_number":     0,
    "last_scan_time":  None,
    "next_scan_time":  None,
    "scan_start_ts":   None,
}

SCAN_TIMES = [
    "09:20","09:35","09:50","10:05","10:20","10:35","10:50",
    "11:05","11:20","11:35","11:50","12:05","12:20","12:35",
    "12:50","13:05","13:20","13:35","13:50","14:05","14:20",
    "14:35","14:50","15:00","15:15",
]


def ist_now():
    return datetime.now(IST)


def is_market_open():
    n = ist_now()
    if n.weekday() >= 5:
        return False
    open_t  = n.replace(hour=9,  minute=15, second=0, microsecond=0)
    close_t = n.replace(hour=15, minute=15, second=0, microsecond=0)
    return open_t <= n <= close_t


def _next_scan_str():
    now_t  = ist_now().strftime("%H:%M")
    future = [t for t in SCAN_TIMES if t > now_t]
    return future[0] if future else "—"


# ══════════════════════════════════════════════════════════════════
# SCANNER CORE
# ══════════════════════════════════════════════════════════════════

def fetch_and_check(ticker: str) -> dict | None:
    short = ticker.replace(".NS","").replace(".BO","")
    if short in state["signals_today"]:
        return None
    try:
        hist = yf.download(ticker, period=f"{LOOKBACK_DAYS}d",
                           interval="1d", auto_adjust=True, progress=False)
        if hist.empty or len(hist) < 10:
            return None
        hist.dropna(inplace=True)
        hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]

        live_raw = yf.download(ticker, period="1d", interval="1m",
                               auto_adjust=True, progress=False)
        if live_raw.empty:
            return None
        live_raw.columns = [c[0] if isinstance(c, tuple) else c for c in live_raw.columns]

        today_row = pd.DataFrame([{
            "Open":   float(live_raw["Open"].iloc[0]),
            "High":   float(live_raw["High"].max()),
            "Low":    float(live_raw["Low"].min()),
            "Close":  float(live_raw["Close"].iloc[-1]),
            "Volume": float(live_raw["Volume"].sum()),
        }], index=[pd.Timestamp(date.today())])

        if hist.index[-1].date() == date.today():
            hist = hist.iloc[:-1]

        df = pd.concat([hist, today_row]).copy()
        df["EMA9"]       = df["Close"].ewm(span=9,  adjust=False).mean()
        df["EMA20"]      = df["Close"].ewm(span=20, adjust=False).mean()
        df["CandleRng"]  = (df["High"] - df["Low"]) / df["Low"]
        df["MaxRng3"]    = df["CandleRng"].shift(1).rolling(3).max()
        df["Range3Hi"]   = df["High"].shift(1).rolling(3).max()
        above            = (df["Close"] > df["EMA20"]).astype(int)
        df["Above20_3d"] = above.shift(1).rolling(3).min()

        row = df.iloc[-1]
        ema9, ema20 = float(row["EMA9"]), float(row["EMA20"])

        if ema9 <= ema20:                                              return None
        if row["Above20_3d"] < 1:                                     return None
        if row["MaxRng3"] > MAX_CANDLE_RNG:                           return None
        today_low = float(row["Low"])
        if abs(today_low - ema20) / ema20 > EMA_PROXIMITY:            return None

        range3_hi   = float(row["Range3Hi"])
        live_price  = float(row["Close"])
        entry_price = round(range3_hi, 2)
        if live_price <= range3_hi:                                    return None

        stop_loss     = round(today_low, 2)
        risk_per_unit = entry_price - stop_loss
        if risk_per_unit <= 0:                                         return None
        if risk_per_unit / entry_price > MAX_SL_PCT:                  return None

        sl_pct = round(risk_per_unit / entry_price * 100, 2)
        return {
            "ticker":      short,
            "timestamp":   ist_now().strftime("%Y-%m-%d %H:%M:%S"),
            "live_price":  round(live_price, 2),
            "entry":       entry_price,
            "stop_loss":   stop_loss,
            "sl_pct":      sl_pct,
            "target_2r":   round(entry_price + 2 * risk_per_unit, 2),
            "target_3r":   round(entry_price + 3 * risk_per_unit, 2),
            "ema9":        round(ema9, 2),
            "ema20":       round(ema20, 2),
        }
    except Exception:
        return None


def run_scan(manual=False):
    """Full scan loop — runs in a background thread."""
    with _lock:
        if state["scan_running"]:
            return   # already running
        state["scan_running"]   = True
        state["status"]         = "scanning"
        state["scanned"]        = 0
        state["current_ticker"] = ""
        state["scan_number"]   += 1
        state["scan_start_ts"]  = ist_now().strftime("%Y-%m-%d %H:%M:%S")

    total         = len(TICKERS)
    found_this    = []
    scan_num      = state["scan_number"]
    started       = time.time()

    print(f"\n[{ist_now().strftime('%H:%M:%S')}] Scan #{scan_num} started "
          f"({'manual' if manual else 'auto'}) — {total} stocks")

    for i, ticker in enumerate(TICKERS, 1):
        short = ticker.replace(".NS","")
        with _lock:
            state["scanned"]        = i
            state["current_ticker"] = short

        sig = fetch_and_check(ticker)
        if sig:
            found_this.append(sig)
            with _lock:
                state["signals_today"][short] = sig
            _persist_signal(sig)
            _send_telegram_signal(sig)
            print(f"  🚨 SIGNAL: {short}  entry=₹{sig['entry']}  sl=₹{sig['stop_loss']}")

        time.sleep(0.15)

    elapsed = round(time.time() - started, 1)
    summary = {
        "scan_number":   scan_num,
        "time":          ist_now().strftime("%H:%M:%S"),
        "date":          ist_now().strftime("%Y-%m-%d"),
        "type":          "manual" if manual else "auto",
        "total_stocks":  total,
        "signals_found": len(found_this),
        "elapsed_sec":   elapsed,
        "tickers_found": [s["ticker"] for s in found_this],
    }

    with _lock:
        state["scan_running"]   = False
        state["status"]         = "idle"
        state["last_scan_time"] = ist_now().strftime("%H:%M:%S")
        state["next_scan_time"] = _next_scan_str()
        state["scan_log"].insert(0, summary)
        state["scan_log"]       = state["scan_log"][:50]   # keep last 50

    _persist_scan_log(summary)
    print(f"[{ist_now().strftime('%H:%M:%S')}] Scan #{scan_num} done in "
          f"{elapsed}s — {len(found_this)} signal(s)")

    if TELEGRAM_ENABLED and len(found_this) > 1:
        _send_telegram(
            f"📋 <b>Scan #{scan_num} Summary</b> — {ist_now().strftime('%H:%M')} IST\n"
            f"<b>{len(found_this)}</b> signals found across {total} F&O stocks."
        )


def _bg_scan(manual=False):
    t = threading.Thread(target=run_scan, args=(manual,), daemon=True)
    t.start()


# ══════════════════════════════════════════════════════════════════
# EOD SUMMARY
# ══════════════════════════════════════════════════════════════════

def send_eod_summary():
    sigs  = list(state["signals_today"].values())
    today = ist_now().strftime("%d %b %Y")
    if not sigs:
        msg = (f"📋 <b>EOD Summary — {today}</b>\n\n"
               f"No signals today across {len(TICKERS)} F&O stocks.")
    else:
        lines = [f"📋 <b>EOD Summary — {today}</b>",
                 f"<b>{len(sigs)} signal(s) today</b>\n",
                 "<code>Stock        Entry      SL      2R      3R</code>",
                 "<code>" + "─"*46 + "</code>"]
        for s in sigs:
            lines.append(
                f"<code>{s['ticker']:<12} "
                f"₹{s['entry']:>7.2f}  "
                f"₹{s['stop_loss']:>7.2f}  "
                f"₹{s['target_2r']:>7.2f}  "
                f"₹{s['target_3r']:>7.2f}</code>"
            )
        lines.append("\n<i>Strategy: 20 EMA Support + Consolidation Breakout</i>")
        msg = "\n".join(lines)

    _send_telegram(msg)
    print(f"[{ist_now().strftime('%H:%M:%S')}] EOD summary sent — {len(sigs)} signal(s)")


# ══════════════════════════════════════════════════════════════════
# PERSISTENCE  (JSON files in /data)
# ══════════════════════════════════════════════════════════════════

def _persist_signal(sig: dict):
    today_file = os.path.join(DATA_DIR, f"signals_{date.today()}.json")
    existing   = []
    if os.path.exists(today_file):
        try:
            with open(today_file) as f:
                existing = json.load(f)
        except Exception:
            existing = []
    # upsert by ticker
    existing = [s for s in existing if s.get("ticker") != sig["ticker"]]
    existing.append(sig)
    with open(today_file, "w") as f:
        json.dump(existing, f, indent=2)


def _persist_scan_log(summary: dict):
    log_file = os.path.join(DATA_DIR, "scan_log.json")
    existing = []
    if os.path.exists(log_file):
        try:
            with open(log_file) as f:
                existing = json.load(f)
        except Exception:
            existing = []
    existing.insert(0, summary)
    existing = existing[:200]
    with open(log_file, "w") as f:
        json.dump(existing, f, indent=2)


def _load_history():
    """Load all past signal JSON files into a list of (date_str, [sigs]) tuples."""
    history = []
    for fname in sorted(os.listdir(DATA_DIR), reverse=True):
        if fname.startswith("signals_") and fname.endswith(".json"):
            date_str = fname.replace("signals_","").replace(".json","")
            try:
                with open(os.path.join(DATA_DIR, fname)) as f:
                    sigs = json.load(f)
                history.append({"date": date_str, "signals": sigs, "count": len(sigs)})
            except Exception:
                pass
    return history


def _load_today_signals():
    """Load today's signals from file (survives restarts)."""
    today_file = os.path.join(DATA_DIR, f"signals_{date.today()}.json")
    if os.path.exists(today_file):
        try:
            with open(today_file) as f:
                sigs = json.load(f)
            for s in sigs:
                state["signals_today"][s["ticker"]] = s
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════

def _send_telegram(msg: str):
    if not TELEGRAM_ENABLED or not BOT_TOKEN:
        return
    try:
        req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def _send_telegram_signal(sig: dict):
    _send_telegram(
        f"🚨 <b>SIGNAL — {sig['ticker']}</b>\n"
        f"📅 {sig['timestamp']}\n\n"
        f"🟢 <b>Entry    :</b> ₹{sig['entry']}\n"
        f"🔴 <b>Stop Loss:</b> ₹{sig['stop_loss']} ({sig['sl_pct']}%)\n"
        f"🎯 <b>Target 2R:</b> ₹{sig['target_2r']}\n"
        f"🏆 <b>Target 3R:</b> ₹{sig['target_3r']}\n"
        f"💹 <b>Live     :</b> ₹{sig['live_price']}\n\n"
        f"<i>EMA9: {sig['ema9']} | EMA20: {sig['ema20']}</i>"
    )


# ══════════════════════════════════════════════════════════════════
# AUTO SCHEDULER  (background thread)
# ══════════════════════════════════════════════════════════════════

def _reset_cache():
    with _lock:
        state["signals_today"].clear()
    _load_today_signals()
    print(f"[{ist_now().strftime('%H:%M:%S')}] Daily cache reset")


def _start_scheduler():
    schedule.every().day.at("09:15").do(_reset_cache)
    schedule.every().day.at("15:30").do(send_eod_summary)
    for t in SCAN_TIMES:
        schedule.every().day.at(t).do(
            lambda: _bg_scan(manual=False) if state["auto_schedule"] else None
        )
    with _lock:
        state["next_scan_time"] = _next_scan_str()

    def _loop():
        while True:
            schedule.run_pending()
            time.sleep(10)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print("Scheduler started — auto scans every 15 min (09:20–15:15 IST)")


# ══════════════════════════════════════════════════════════════════
# FLASK APP
# ══════════════════════════════════════════════════════════════════

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


# ── Status ────────────────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    with _lock:
        s = dict(state)
        s.pop("signals_today", None)
        s.pop("scan_log", None)
    s["market_open"]    = is_market_open()
    s["ist_time"]       = ist_now().strftime("%H:%M:%S")
    s["ist_date"]       = ist_now().strftime("%d %b %Y")
    s["total_tickers"]  = len(TICKERS)
    s["signals_count"]  = len(state["signals_today"])
    return jsonify(s)


# ── Manual scan trigger ────────────────────────────────────────────
@app.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    if state["scan_running"]:
        return jsonify({"ok": False, "msg": "Scan already running"})
    _bg_scan(manual=True)
    return jsonify({"ok": True, "msg": "Scan started"})


@app.route("/api/scan/stop", methods=["POST"])
def api_scan_stop():
    # Graceful stop — set flag, loop will exit after current ticker
    with _lock:
        state["status"] = "stopping"
    return jsonify({"ok": True, "msg": "Stop requested"})


# ── Auto-schedule toggle ───────────────────────────────────────────
@app.route("/api/schedule/toggle", methods=["POST"])
def api_schedule_toggle():
    with _lock:
        state["auto_schedule"] = not state["auto_schedule"]
        val = state["auto_schedule"]
    return jsonify({"ok": True, "auto_schedule": val})


# ── Today's signals ────────────────────────────────────────────────
@app.route("/api/signals/today")
def api_signals_today():
    sigs = list(state["signals_today"].values())
    sigs.sort(key=lambda x: x["timestamp"], reverse=True)
    return jsonify({"date": ist_now().strftime("%d %b %Y"), "signals": sigs})


# ── Signal history (past days) ─────────────────────────────────────
@app.route("/api/signals/history")
def api_signals_history():
    return jsonify(_load_history())


# ── Scan log ──────────────────────────────────────────────────────
@app.route("/api/scan/log")
def api_scan_log():
    with _lock:
        logs = list(state["scan_log"])
    return jsonify(logs)


# ── Progress (poll every second while scan running) ────────────────
@app.route("/api/scan/progress")
def api_scan_progress():
    with _lock:
        return jsonify({
            "running":         state["scan_running"],
            "scanned":         state["scanned"],
            "total":           state["total"],
            "current_ticker":  state["current_ticker"],
            "signals_so_far":  len(state["signals_today"]),
            "pct":             round(state["scanned"] / state["total"] * 100, 1)
                               if state["total"] else 0,
        })


# ══════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════

_load_today_signals()   # restore signals from disk on restart
_start_scheduler()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
