

"""
Swing Scanner v3 — Box Breakout Strategy
==========================================
Setup:
  1. Stock makes a continuous move of >=15% (no single day down >3%) over >=3 days
  2. Then consolidates >=3 days in a tight box:
       - All candle Highs within box_tight% of each other
       - All candle Lows  within box_tight% of each other
  3. EMA9 > EMA20, consolidation box is above EMA20
  4. TWO alert types:
       A) Watchlist alert  -- valid box detected (still consolidating)
       B) Breakout alert   -- price closes above box High (breakout candle)

Backtest -- 2 Entry Types x 3 Exits = 6 combinations:
  Entry A: EOD buy on breakout day close (~3 PM)
  Entry B: Intraday buy when price is >1% above box High on breakout day
  Exit 1: 2R  |  Exit 2: 3R  |  Exit 3: EMA9-trail
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
import io
import os
import csv
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

# ======================================================
# CONFIG
# ======================================================
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

IST = ZoneInfo("Asia/Kolkata")

# ======================================================
# STRATEGY PARAMETERS (live-editable)
# ======================================================
PARAM_DEFAULTS = {
    "min_move_pct":    0.15,   # min rally before consolidation (15%)
    "max_down_day":    0.03,   # max single-day drop during rally (3%)
    "min_move_days":   3,      # min days in the rally leg
    "min_consol_days": 3,      # min consolidation candles
    "max_consol_days": 20,     # max consolidation candles
    "box_tight":       0.002,  # 0.2% -- high-band and low-band tightness
    "breakout_pct":    0.01,   # 1% above box high for Entry B
    "max_sl_pct":      0.06,   # max SL as % of entry
    "be_trigger_r":    1.0,
    "target_2r":       2.0,
    "target_3r":       3.0,
    "max_hold_days":   30,
    "risk_per_trade":  0.02,
    "initial_cash":    100000,
    "brokerage":       0.001,
    "lookback_days":   60,
}
params = dict(PARAM_DEFAULTS)

# ======================================================
# F&O TICKERS
# ======================================================
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

# ======================================================
# SCANNER STATE
# ======================================================
_lock = threading.Lock()

state = {
    "status": "idle", "scan_running": False, "auto_schedule": True,
    "current_ticker": "", "scanned": 0, "total": len(TICKERS),
    "watchlist_today": {},
    "breakouts_today": {},
    "scan_log": [], "scan_number": 0,
    "last_scan_time": None, "next_scan_time": None, "scan_start_ts": None,
}

bt_state = {
    "running": False, "progress": 0, "total": 7,
    "current": "", "result": None, "error": None,
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
    return (n.replace(hour=9, minute=15, second=0, microsecond=0) <= n <=
            n.replace(hour=15, minute=15, second=0, microsecond=0))


def _next_scan_str():
    now_t = ist_now().strftime("%H:%M")
    future = [t for t in SCAN_TIMES if t > now_t]
    return future[0] if future else "x"


# ======================================================
# CORE STRATEGY DETECTION
# ======================================================

def _compute_emas(df):
    df = df.copy()
    df["EMA9"]  = df["Close"].ewm(span=9,  adjust=False).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    return df


def _find_rally_ending_at(df, end_idx, p):
    """
    Walk backwards from end_idx to find start of continuous upward rally.
    Criteria: no single day drops more than max_down_day%.
    Returns (start_idx, move_pct) or None.
    """
    max_down = float(p["max_down_day"])
    min_move = float(p["min_move_pct"])
    min_days = int(p["min_move_days"])

    i = end_idx
    while i > 0:
        cur  = float(df.iloc[i]["Close"])
        prev = float(df.iloc[i - 1]["Close"])
        daily_ret = (cur - prev) / prev
        if daily_ret < -max_down:
            break
        i -= 1

    rally_start = i
    rally_len   = end_idx - rally_start
    if rally_len < min_days:
        return None

    start_close = float(df.iloc[rally_start]["Close"])
    end_close   = float(df.iloc[end_idx]["Close"])
    move_pct    = (end_close - start_close) / start_close
    if move_pct < min_move:
        return None

    return rally_start, round(move_pct * 100, 2)


def _check_consolidation(df, from_idx, p):
    """
    Starting from from_idx, check if candles form a tight box.
    High range <= box_tight AND Low range <= box_tight.
    Returns (end_idx, box_high, box_low) for the longest valid run, or None.
    """
    tight   = float(p["box_tight"])
    min_c   = int(p["min_consol_days"])
    max_c   = int(p["max_consol_days"])

    if from_idx >= len(df):
        return None

    highs = []
    lows  = []
    valid_end = None

    for j in range(from_idx, min(from_idx + max_c, len(df))):
        highs.append(float(df.iloc[j]["High"]))
        lows.append(float(df.iloc[j]["Low"]))

        bh = max(highs); bl_h = min(highs)
        bl = min(lows);  bh_l = max(lows)

        high_spread = (bh - bl_h) / bl_h if bl_h > 0 else 1
        low_spread  = (bh_l - bl)  / bl  if bl  > 0 else 1

        if high_spread <= tight and low_spread <= tight:
            if len(highs) >= min_c:
                valid_end = j
        else:
            # box broke -- stop here
            break

    if valid_end is None:
        return None

    bh = max(df.iloc[from_idx:valid_end + 1]["High"].tolist())
    bl = min(df.iloc[from_idx:valid_end + 1]["Low"].tolist())

    # Box must be above EMA20
    avg_ema20 = df["EMA20"].iloc[from_idx:valid_end + 1].mean()
    if float(bl) <= float(avg_ema20):
        return None

    return valid_end, round(float(bh), 2), round(float(bl), 2)


def detect_setups_all(df, p):
    """
    Find all valid box setups in df. Returns list of setup dicts.
    """
    df    = _compute_emas(df)
    found = []
    i     = int(p["min_move_days"])

    while i < len(df) - int(p["min_consol_days"]):
        rally = _find_rally_ending_at(df, i, p)
        if rally is None:
            i += 1
            continue

        rs, move_pct = rally

        # EMA9 > EMA20 at rally peak
        if float(df.iloc[i]["EMA9"]) <= float(df.iloc[i]["EMA20"]):
            i += 1
            continue

        consol = _check_consolidation(df, i + 1, p)
        if consol is None:
            i += 1
            continue

        ce, box_high, box_low = consol
        cs = i + 1

        setup = {
            "rally_start_idx":  rs,
            "rally_end_idx":    i,
            "consol_start_idx": cs,
            "consol_end_idx":   ce,
            "box_high":  box_high,
            "box_low":   box_low,
            "move_pct":  move_pct,
            "consol_days": ce - cs + 1,
            "ema9":  round(float(df.iloc[ce]["EMA9"]),  2),
            "ema20": round(float(df.iloc[ce]["EMA20"]), 2),
            "rally_start_date":  df.index[rs].strftime("%Y-%m-%d"),
            "rally_end_date":    df.index[i].strftime("%Y-%m-%d"),
            "consol_start_date": df.index[cs].strftime("%Y-%m-%d"),
            "consol_end_date":   df.index[ce].strftime("%Y-%m-%d"),
        }
        found.append(setup)
        i = ce + 1  # skip past this box

    return found


def detect_live_signal(df, p):
    """
    For live scanning: check last few candles for watchlist or breakout.
    Returns (alert_type, setup_dict) or (None, None).
    """
    setups = detect_setups_all(df, p)
    if not setups:
        return None, None

    # Look at most recent setup
    setup = setups[-1]
    ce    = setup["consol_end_idx"]
    last  = len(df) - 1

    if ce == last:
        # Still in box -- watchlist
        setup["alert_type"] = "watchlist"
        setup["live_price"] = round(float(df.iloc[last]["Close"]), 2)
        return "watchlist", setup

    elif ce == last - 1:
        # Box ended yesterday, check if today broke out
        today_close = float(df.iloc[last]["Close"])
        if today_close > setup["box_high"]:
            setup["alert_type"] = "breakout"
            setup["live_price"] = round(today_close, 2)
            setup["breakout_entry_eod"] = round(today_close, 2)
            sl  = setup["box_low"]
            rpu = today_close - sl
            if rpu > 0 and rpu / today_close <= float(p["max_sl_pct"]):
                setup["stop_loss"] = round(sl, 2)
                setup["sl_pct"]    = round(rpu / today_close * 100, 2)
                setup["target_2r"] = round(today_close + 2 * rpu, 2)
                setup["target_3r"] = round(today_close + 3 * rpu, 2)
            return "breakout", setup

    return None, None


# ======================================================
# CHART GENERATION
# ======================================================

def _make_setup_chart(df, setup, ticker, entry_price=None,
                      exit_price=None, exit_label=None, title_suffix=""):
    rs  = setup["rally_start_idx"]
    ce  = setup["consol_end_idx"]
    bh  = setup["box_high"]
    bl  = setup["box_low"]

    plot_start = max(0, rs - 3)
    plot_end   = min(len(df), ce + 10)
    plot_df    = df.iloc[plot_start:plot_end][["Open","High","Low","Close","Volume"]].copy()

    mc = mpf.make_marketcolors(
        up="#22c55e", down="#ef4444",
        wick={"up":"#22c55e","down":"#ef4444"},
        edge={"up":"#22c55e","down":"#ef4444"},
        volume={"up":"#22c55e55","down":"#ef444455"})
    s = mpf.make_mpf_style(
        marketcolors=mc, base_mpf_style="nightclouds",
        gridstyle="--", gridcolor="#334155",
        facecolor="#0f172a", figcolor="#0f172a",
        rc={"axes.labelcolor":"#94a3b8","xtick.color":"#94a3b8","ytick.color":"#94a3b8"})

    # EMA lines
    ema9_s  = pd.Series(
        [df.loc[d,"EMA9"]  if d in df.index else np.nan for d in plot_df.index],
        index=plot_df.index)
    ema20_s = pd.Series(
        [df.loc[d,"EMA20"] if d in df.index else np.nan for d in plot_df.index],
        index=plot_df.index)
    add = [
        mpf.make_addplot(ema9_s,  color="#38bdf8", width=1.2),
        mpf.make_addplot(ema20_s, color="#a855f7", width=1.2),
    ]

    hlines_p = [bh, bl]
    hlines_c = ["#f59e0b","#f59e0b"]
    hlines_ls= ["--","--"]
    hlines_lw= [1.5, 1.5]
    if entry_price:
        hlines_p.append(entry_price); hlines_c.append("#22c55e")
        hlines_ls.append("-");        hlines_lw.append(1.0)
    if exit_price:
        hlines_p.append(exit_price); hlines_c.append("#ef4444")
        hlines_ls.append("-");       hlines_lw.append(1.0)

    title = f"{ticker}  Box Breakout  {title_suffix}"
    fig, axes = mpf.plot(
        plot_df, type="candle", style=s, title=title,
        volume=True, addplot=add,
        hlines=dict(hlines=hlines_p, colors=hlines_c,
                    linestyle=hlines_ls, linewidths=hlines_lw),
        returnfig=True, figsize=(12, 7), tight_layout=True)

    ax = axes[0]
    cs_local = setup["consol_start_idx"] - plot_start
    ce_local = setup["consol_end_idx"]   - plot_start
    ax.axvspan(cs_local - 0.5, ce_local + 0.5,
               alpha=0.12, color="#f59e0b", zorder=0)
    ax.annotate(
        f"+{setup['move_pct']}%",
        xy=(setup["rally_end_idx"] - plot_start, bh * 1.005),
        color="#f59e0b", fontsize=9, fontweight="bold")

    if entry_price:
        ax.annotate(f"Entry {entry_price}",
                    xy=(ce_local + 1, entry_price),
                    color="#22c55e", fontsize=8)
    if exit_price and exit_label:
        ax.annotate(f"{exit_label} {exit_price}",
                    xy=(ce_local + 3, exit_price),
                    color="#ef4444", fontsize=8)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _make_equity_chart(results_by_key, ticker, start, end, init_cap):
    fig, ax = plt.subplots(figsize=(12, 5), facecolor="#0f172a")
    ax.set_facecolor("#0f172a")
    colors = {
        ("EOD",  "2R"):"#22c55e", ("EOD",  "3R"):"#16a34a", ("EOD",  "EMA9"):"#4ade80",
        ("BREAK","2R"):"#3b82f6", ("BREAK","3R"):"#2563eb", ("BREAK","EMA9"):"#60a5fa",
    }
    for key, trades in results_by_key.items():
        if not trades: continue
        caps = [init_cap] + [t["Capital"] for t in trades]
        et, em = key
        ax.plot(caps, label=f"{et}/{em}", color=colors.get(key,"#fff"), linewidth=1.5)

    ax.set_title(f"{ticker} -- Equity Curves ({start} to {end})",
                 color="#f1f5f9", fontsize=12)
    ax.set_xlabel("Trade #", color="#94a3b8")
    ax.set_ylabel("Capital", color="#94a3b8")
    ax.tick_params(colors="#94a3b8")
    ax.legend(facecolor="#1e293b", labelcolor="#f1f5f9", fontsize=9)
    ax.grid(True, color="#334155", linestyle="--", linewidth=0.5)
    for sp in ax.spines.values(): sp.set_edgecolor("#334155")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor="#0f172a")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ======================================================
# TELEGRAM
# ======================================================

def _send_telegram(msg):
    if not TELEGRAM_ENABLED or not BOT_TOKEN: return
    try:
        req.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                 json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
                 timeout=10)
    except Exception: pass


def _send_telegram_photo(png_bytes, caption=""):
    if not TELEGRAM_ENABLED or not BOT_TOKEN: return
    try:
        req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("chart.png", png_bytes, "image/png")},
            timeout=30)
    except Exception: pass


def _send_telegram_doc(file_bytes, filename, caption=""):
    if not TELEGRAM_ENABLED or not BOT_TOKEN: return
    try:
        req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
            data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption},
            files={"document": (filename, file_bytes, "text/csv")},
            timeout=30)
    except Exception: pass


def _send_watchlist_alert(ticker, sig, df):
    short = ticker.replace(".NS","")
    _send_telegram(
        f"👀 <b>WATCHLIST -- {short}</b>\n"
        f"Box forming since {sig['consol_start_date']} ({sig['consol_days']} days)\n\n"
        f"📈 Rally: +{sig['move_pct']}% from {sig['rally_start_date']}\n"
        f"📦 Box High: {sig['box_high']}  |  Box Low: {sig['box_low']}\n"
        f"💹 Live: {sig['live_price']}\n"
        f"<i>EMA9: {sig['ema9']}  EMA20: {sig['ema20']}</i>")
    try:
        chart = _make_setup_chart(df, sig, short)
        _send_telegram_photo(chart, caption=f"👀 {short} - Watchlist Box")
    except Exception: pass


def _send_breakout_alert(ticker, sig, df):
    short = ticker.replace(".NS","")
    sl_txt = ""
    if "stop_loss" in sig:
        sl_txt = (f"🔴 SL: {sig['stop_loss']} ({sig['sl_pct']}%)\n"
                  f"🎯 2R: {sig['target_2r']}  |  3R: {sig['target_3r']}\n")
    _send_telegram(
        f"🚨 <b>BREAKOUT -- {short}</b>\n"
        f"{ist_now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"📦 Box High: {sig['box_high']} (BROKEN)\n"
        f"🟢 EOD Entry: {sig.get('breakout_entry_eod','--')}\n"
        f"{sl_txt}"
        f"💹 Live: {sig['live_price']}\n"
        f"<i>EMA9: {sig['ema9']}  EMA20: {sig['ema20']}</i>")
    try:
        chart = _make_setup_chart(df, sig, short,
                                  entry_price=sig.get("breakout_entry_eod"),
                                  exit_price=sig.get("target_2r"), exit_label="2R")
        _send_telegram_photo(chart, caption=f"🚨 {short} - Breakout!")
    except Exception: pass


# ======================================================
# LIVE SCANNER
# ======================================================

def fetch_and_check(ticker):
    try:
        df = yf.download(ticker, period=f"{int(params['lookback_days'])}d",
                         interval="1d", auto_adjust=True, progress=False)
        if df.empty or len(df) < 15: return None, None
        df.dropna(inplace=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

        live_raw = yf.download(ticker, period="1d", interval="1m",
                               auto_adjust=True, progress=False)
        if not live_raw.empty:
            live_raw.columns = [c[0] if isinstance(c, tuple) else c for c in live_raw.columns]
            today_row = pd.DataFrame([{
                "Open":   float(live_raw["Open"].iloc[0]),
                "High":   float(live_raw["High"].max()),
                "Low":    float(live_raw["Low"].min()),
                "Close":  float(live_raw["Close"].iloc[-1]),
                "Volume": float(live_raw["Volume"].sum()),
            }], index=[pd.Timestamp(date.today())])
            if df.index[-1].date() == date.today():
                df = df.iloc[:-1]
            df = pd.concat([df, today_row])

        df = _compute_emas(df)
        alert_type, setup = detect_live_signal(df, params)
        if setup is None: return None, None
        setup["ticker"]    = ticker.replace(".NS","")
        setup["timestamp"] = ist_now().strftime("%Y-%m-%d %H:%M:%S")
        return setup, df
    except Exception:
        return None, None


def run_scan(manual=False):
    with _lock:
        if state["scan_running"]: return
        state.update({"scan_running": True, "status": "scanning",
                      "scanned": 0, "current_ticker": "",
                      "scan_start_ts": ist_now().strftime("%Y-%m-%d %H:%M:%S")})
        state["scan_number"] += 1

    total = len(TICKERS)
    new_watchlist = []; new_breakouts = []
    num = state["scan_number"]; t0 = time.time()

    for i, ticker in enumerate(TICKERS, 1):
        short = ticker.replace(".NS","")
        with _lock:
            state["scanned"] = i; state["current_ticker"] = short

        sig, df = fetch_and_check(ticker)
        if sig:
            atype = sig["alert_type"]
            if atype == "watchlist":
                already = short in state["watchlist_today"]
                with _lock: state["watchlist_today"][short] = sig
                if not already:
                    new_watchlist.append((ticker, sig, df))
                    _persist_signal(sig, "watchlist")
            elif atype == "breakout":
                already = short in state["breakouts_today"]
                with _lock: state["breakouts_today"][short] = sig
                if not already:
                    new_breakouts.append((ticker, sig, df))
                    _persist_signal(sig, "breakout")
        time.sleep(0.15)

    for ticker, sig, df in new_watchlist:
        _send_watchlist_alert(ticker, sig, df)
    for ticker, sig, df in new_breakouts:
        _send_breakout_alert(ticker, sig, df)

    elapsed = round(time.time() - t0, 1)
    summary = {
        "scan_number": num, "time": ist_now().strftime("%H:%M:%S"),
        "date": ist_now().strftime("%Y-%m-%d"),
        "type": "manual" if manual else "auto",
        "total_stocks": total,
        "watchlist_found": len(new_watchlist),
        "breakouts_found": len(new_breakouts),
        "elapsed_sec": elapsed,
    }
    with _lock:
        state.update({"scan_running": False, "status": "idle",
                      "last_scan_time": ist_now().strftime("%H:%M:%S"),
                      "next_scan_time": _next_scan_str()})
        state["scan_log"].insert(0, summary)
        state["scan_log"] = state["scan_log"][:50]
    _persist_scan_log(summary)


def _bg_scan(manual=False):
    threading.Thread(target=run_scan, args=(manual,), daemon=True).start()


# ======================================================
# BACKTEST ENGINE
# ======================================================

def _bt_fetch(ticker, start_date, end_date):
    warmup = (pd.Timestamp(start_date) - pd.Timedelta(days=120)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=warmup, end=end_date,
                     interval="1d", auto_adjust=True, progress=False)
    if df.empty or len(df) < 20: return None
    df.dropna(inplace=True)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return _compute_emas(df)


def _bt_simulate(setups, df, entry_type, exit_mode, p):
    """
    entry_type: EOD   -- entry = close of breakout day
                BREAK -- entry = box_high * (1 + breakout_pct) if hit same day
    exit_mode:  2R | 3R | EMA9
    """
    trades  = []
    capital = float(p["initial_cash"])
    used_til = -1

    for setup in setups:
        ce       = setup["consol_end_idx"]
        box_high = setup["box_high"]
        box_low  = setup["box_low"]

        # Find first breakout day after box
        breakout_idx = None
        for k in range(ce + 1, min(ce + 5, len(df))):
            if float(df.iloc[k]["Close"]) > box_high:
                breakout_idx = k; break

        if breakout_idx is None or breakout_idx <= used_til:
            continue

        brk_close = float(df.iloc[breakout_idx]["Close"])
        brk_high  = float(df.iloc[breakout_idx]["High"])

        if entry_type == "EOD":
            entry = round(brk_close, 2)
        else:
            trigger = round(box_high * (1.0 + float(p["breakout_pct"])), 2)
            if brk_high < trigger:
                continue
            entry = trigger

        sl0 = float(box_low)
        rps = entry - sl0
        if rps <= 0 or rps / entry > float(p["max_sl_pct"]):
            continue

        qty = int((capital * float(p["risk_per_trade"])) / rps)
        if qty <= 0: continue

        l1r = entry + float(p["be_trigger_r"]) * rps
        l2r = entry + float(p["target_2r"])    * rps
        l3r = entry + float(p["target_3r"])    * rps
        stop = sl0; be_hit = False; qty_rem = qty
        gross = cost = 0.0; exit_date = outcome = exit_px = None
        end_idx = min(breakout_idx + int(p["max_hold_days"]), len(df))

        for j in range(breakout_idx + 1, end_idx):
            c    = df.iloc[j]
            c_hi = float(c["High"]); c_lo = float(c["Low"])
            c_cl = float(c["Close"]); c_e9 = float(c["EMA9"])

            if c_lo <= stop:
                gross  += (stop - entry) * qty_rem
                cost   += (entry + stop) * qty_rem * float(p["brokerage"])
                exit_px = stop; exit_date = df.index[j]
                outcome = "BE_EXIT" if be_hit else "LOSS"
                qty_rem = 0; break

            if not be_hit and c_hi >= l1r:
                stop = entry; be_hit = True

            if exit_mode == "2R" and c_hi >= l2r:
                gross  += (l2r - entry) * qty_rem
                cost   += (entry + l2r) * qty_rem * float(p["brokerage"])
                exit_px = l2r; exit_date = df.index[j]
                outcome = "WIN_2R"; qty_rem = 0; break
            elif exit_mode == "3R" and c_hi >= l3r:
                gross  += (l3r - entry) * qty_rem
                cost   += (entry + l3r) * qty_rem * float(p["brokerage"])
                exit_px = l3r; exit_date = df.index[j]
                outcome = "WIN_3R"; qty_rem = 0; break
            elif exit_mode == "EMA9" and be_hit and c_cl < c_e9:
                gross  += (c_cl - entry) * qty_rem
                cost   += (entry + c_cl) * qty_rem * float(p["brokerage"])
                exit_px = c_cl; exit_date = df.index[j]
                outcome = "EMA9_TRAIL"; qty_rem = 0; break

        if qty_rem > 0:
            px     = float(df.iloc[end_idx - 1]["Close"])
            gross += (px - entry) * qty_rem
            cost  += (entry + px) * qty_rem * float(p["brokerage"])
            exit_px = round(px, 2); exit_date = df.index[end_idx - 1]
            outcome = "TIMEOUT"

        net = round(gross - cost, 2); capital += net
        used_til = breakout_idx + int(p["max_hold_days"])
        trades.append({
            "Entry_Type":     entry_type,
            "Exit_Mode":      exit_mode,
            "Setup_Date":     setup["consol_start_date"],
            "Breakout_Date":  df.index[breakout_idx].strftime("%Y-%m-%d"),
            "Exit_Date":      exit_date.strftime("%Y-%m-%d") if exit_date else "",
            "Box_High":       box_high,
            "Box_Low":        box_low,
            "Entry":          entry,
            "SL":             round(sl0, 2),
            "Exit_Price":     round(exit_px, 2) if exit_px else "",
            "Outcome":        outcome,
            "NetPnL":         net,
            "Capital":        round(capital, 2),
            "Move_Pct":       setup["move_pct"],
            "Consol_Days":    setup["consol_days"],
        })

    return trades, capital


def _bt_metrics(trades, init_cap, final_cap):
    if not trades: return {}
    wins   = [t for t in trades if t["NetPnL"] > 0]
    losses = [t for t in trades if t["NetPnL"] <= 0]
    caps   = [init_cap] + [t["Capital"] for t in trades]
    peak = init_cap; mdd = 0
    for c in caps:
        peak = max(peak, c); mdd = max(mdd, (peak - c) / peak * 100)
    ws = ls = mws = mls = 0
    for t in trades:
        if t["NetPnL"] > 0: ws += 1; ls = 0; mws = max(mws, ws)
        else:               ls += 1; ws = 0; mls = max(mls, ls)
    win_sum  = sum(w["NetPnL"] for w in wins)
    loss_sum = sum(l["NetPnL"] for l in losses)
    pf = round(abs(win_sum / loss_sum), 2) if loss_sum else None
    return {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate":   round(len(wins) / len(trades) * 100, 1),
        "total_pnl":  round(win_sum + loss_sum, 0),
        "return_pct": round((final_cap - init_cap) / init_cap * 100, 2),
        "final_cap":  round(final_cap, 0),
        "avg_win":    round(win_sum / len(wins), 0)    if wins   else 0,
        "avg_loss":   round(loss_sum / len(losses), 0) if losses else 0,
        "profit_factor": pf,
        "max_dd":     round(mdd, 2),
        "max_win_streak":  mws,
        "max_loss_streak": mls,
    }


def run_backtest_job(ticker, start_date, end_date, p, send_tg):
    bt_state.update({"running": True, "error": None, "result": None,
                     "progress": 0, "total": 8, "current": "Fetching data..."})
    try:
        df = _bt_fetch(ticker, start_date, end_date)
        if df is None: raise ValueError(f"No data for {ticker}")

        bt_state.update({"current": "Detecting setups...", "progress": 1})
        sd = pd.Timestamp(start_date)
        all_setups = detect_setups_all(df, p)
        all_setups = [s for s in all_setups if df.index[s["consol_start_idx"]] >= sd]

        results_by_key = {}
        metrics_out    = {}
        all_trades     = []
        combos = [("EOD","2R"),("EOD","3R"),("EOD","EMA9"),
                  ("BREAK","2R"),("BREAK","3R"),("BREAK","EMA9")]

        for i, (etype, emode) in enumerate(combos, 2):
            bt_state.update({"current": f"Simulating {etype}/{emode}...", "progress": i})
            trades, fc = _bt_simulate(all_setups, df, etype, emode, p)
            results_by_key[(etype, emode)] = trades
            metrics_out[f"{etype}/{emode}"] = _bt_metrics(trades, p["initial_cash"], fc)
            all_trades.extend(trades)
            time.sleep(0.05)

        short = ticker.replace(".NS","")
        bt_state.update({"progress": 8, "current": "Done"})
        bt_state["result"] = {
            "ticker": short, "start": start_date, "end": end_date,
            "total_setups": len(all_setups),
            "params": {k: p[k] for k in ["min_move_pct","box_tight","min_consol_days",
                                          "initial_cash","risk_per_trade","breakout_pct"]},
            "results": metrics_out,
        }

        if send_tg and TELEGRAM_ENABLED and BOT_TOKEN:
            _send_bt_telegram(short, metrics_out, all_trades,
                              results_by_key, df, all_setups,
                              start_date, end_date, p)

    except Exception as e:
        import traceback; traceback.print_exc()
        bt_state["error"] = str(e)
    finally:
        bt_state.update({"running": False, "current": "Done"})


def _send_bt_telegram(ticker, metrics_out, all_trades, results_by_key,
                      df, setups, start, end, p):
    lines = [f"📊 <b>Backtest: {ticker}</b>  ({start} to {end})\n"
             f"Setups found: {len(setups)}\n"]
    for combo, m in metrics_out.items():
        if not m: continue
        pf = str(m["profit_factor"]) if m["profit_factor"] else "inf"
        lines.append(
            f"<b>{combo}</b>\n"
            f"  Trades:{m['trades']}  Win:{m['win_rate']}%  Ret:{m['return_pct']}%\n"
            f"  PF:{pf}  MaxDD:{m['max_dd']}%  Cap:{m['final_cap']:,.0f}\n"
            f"  WS:{m['max_win_streak']}  LS:{m['max_loss_streak']}\n")
    _send_telegram("\n".join(lines))

    # Equity chart
    try:
        eq = _make_equity_chart(results_by_key, ticker, start, end, p["initial_cash"])
        _send_telegram_photo(eq, caption=f"Equity curves -- {ticker}")
    except Exception: pass

    # Up to 3 setup charts
    for setup in setups[:3]:
        try:
            ce = setup["consol_end_idx"]
            bk = None
            for k in range(ce+1, min(ce+5, len(df))):
                if float(df.iloc[k]["Close"]) > setup["box_high"]:
                    bk = k; break
            ep = round(float(df.iloc[bk]["Close"]), 2) if bk else None
            chart = _make_setup_chart(df, setup, ticker, entry_price=ep,
                                      title_suffix=f"({setup['consol_start_date']})")
            _send_telegram_photo(chart,
                caption=f"{ticker}  +{setup['move_pct']}%  {setup['consol_days']}d box")
        except Exception: pass

    # CSV
    if all_trades:
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=all_trades[0].keys())
        w.writeheader(); w.writerows(all_trades)
        buf.seek(0)
        _send_telegram_doc(buf.read().encode(),
                           f"bt_{ticker}_{start}_{end}.csv",
                           caption=f"All trades -- {ticker}")


# ======================================================
# PERSISTENCE
# ======================================================

def _persist_signal(sig, kind):
    f = os.path.join(DATA_DIR, f"{kind}_{date.today()}.json")
    existing = []
    if os.path.exists(f):
        try:
            with open(f) as fh: existing = json.load(fh)
        except Exception: pass
    existing = [s for s in existing if s.get("ticker") != sig["ticker"]]
    existing.append(sig)
    with open(f, "w") as fh: json.dump(existing, fh, indent=2, default=str)


def _persist_scan_log(summary):
    f = os.path.join(DATA_DIR, "scan_log.json")
    existing = []
    if os.path.exists(f):
        try:
            with open(f) as fh: existing = json.load(fh)
        except Exception: pass
    existing.insert(0, summary)
    with open(f, "w") as fh: json.dump(existing[:200], fh, indent=2)


def _load_today_signals():
    for kind, key in [("watchlist","watchlist_today"),("breakout","breakouts_today")]:
        f = os.path.join(DATA_DIR, f"{kind}_{date.today()}.json")
        if os.path.exists(f):
            try:
                with open(f) as fh:
                    for s in json.load(fh): state[key][s["ticker"]] = s
            except Exception: pass


def _load_history():
    history = []
    for fname in sorted(os.listdir(DATA_DIR), reverse=True):
        for kind in ["breakout","watchlist"]:
            if fname.startswith(f"{kind}_") and fname.endswith(".json"):
                ds = fname.replace(f"{kind}_","").replace(".json","")
                try:
                    with open(os.path.join(DATA_DIR, fname)) as fh:
                        sigs = json.load(fh)
                    history.append({"date": ds, "kind": kind,
                                    "signals": sigs, "count": len(sigs)})
                except Exception: pass
    return sorted(history, key=lambda x: x["date"], reverse=True)


# ======================================================
# EOD SUMMARY
# ======================================================

def send_eod_summary():
    today = ist_now().strftime("%d %b %Y")
    w = list(state["watchlist_today"].values())
    b = list(state["breakouts_today"].values())
    lines = [f"<b>EOD Summary -- {today}</b>\n"]
    if b:
        lines.append(f"<b>{len(b)} Breakout(s)</b>")
        for s in b:
            lines.append(f"  {s['ticker']}  Box:{s['box_high']}  "
                         f"Entry:{s.get('breakout_entry_eod','--')}")
    if w:
        lines.append(f"\n<b>{len(w)} Watchlist</b>")
        for s in w:
            lines.append(f"  {s['ticker']}  Box:{s['box_high']}  ({s['consol_days']}d)")
    if not b and not w:
        lines.append("No signals today.")
    _send_telegram("\n".join(lines))


# ======================================================
# SCHEDULER
# ======================================================

def _reset_cache():
    with _lock:
        state["watchlist_today"].clear()
        state["breakouts_today"].clear()
    _load_today_signals()


def _start_scheduler():
    schedule.every().day.at("09:15").do(_reset_cache)
    schedule.every().day.at("15:30").do(send_eod_summary)
    for t in SCAN_TIMES:
        schedule.every().day.at(t).do(
            lambda: _bg_scan(manual=False) if state["auto_schedule"] else None)
    with _lock: state["next_scan_time"] = _next_scan_str()
    def _loop():
        while True: schedule.run_pending(); time.sleep(10)
    threading.Thread(target=_loop, daemon=True).start()


# ======================================================
# FLASK ROUTES
# ======================================================

app = Flask(__name__)


@app.route("/")
def index(): return render_template("index.html")


@app.route("/api/status")
def api_status():
    with _lock:
        s = {k: v for k, v in state.items()
             if k not in ("watchlist_today","breakouts_today","scan_log")}
    s.update({
        "market_open":     is_market_open(),
        "ist_time":        ist_now().strftime("%H:%M:%S"),
        "ist_date":        ist_now().strftime("%d %b %Y"),
        "total_tickers":   len(TICKERS),
        "watchlist_count": len(state["watchlist_today"]),
        "breakout_count":  len(state["breakouts_today"]),
    })
    return jsonify(s)


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify({"params": params, "defaults": PARAM_DEFAULTS})


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    data = request.get_json(silent=True) or {}
    updated = {}
    for k, v in data.items():
        if k in PARAM_DEFAULTS:
            try: params[k] = float(v); updated[k] = params[k]
            except Exception: pass
    return jsonify({"ok": True, "updated": updated, "params": params})


@app.route("/api/settings/reset", methods=["POST"])
def api_settings_reset():
    params.update(PARAM_DEFAULTS)
    return jsonify({"ok": True, "params": params})


@app.route("/api/scan/start", methods=["POST"])
def api_scan_start():
    if state["scan_running"]:
        return jsonify({"ok": False, "msg": "Scan already running"})
    _bg_scan(manual=True)
    return jsonify({"ok": True})


@app.route("/api/scan/stop", methods=["POST"])
def api_scan_stop():
    with _lock: state["status"] = "stopping"
    return jsonify({"ok": True})


@app.route("/api/scan/progress")
def api_scan_progress():
    with _lock:
        return jsonify({
            "running":          state["scan_running"],
            "scanned":          state["scanned"],
            "total":            state["total"],
            "current_ticker":   state["current_ticker"],
            "watchlist_so_far": len(state["watchlist_today"]),
            "breakouts_so_far": len(state["breakouts_today"]),
            "pct": round(state["scanned"] / state["total"] * 100, 1)
                   if state["total"] else 0,
        })


@app.route("/api/schedule/toggle", methods=["POST"])
def api_schedule_toggle():
    with _lock:
        state["auto_schedule"] = not state["auto_schedule"]
        val = state["auto_schedule"]
    return jsonify({"ok": True, "auto_schedule": val})


@app.route("/api/signals/watchlist")
def api_signals_watchlist():
    sigs = sorted(state["watchlist_today"].values(),
                  key=lambda x: x["timestamp"], reverse=True)
    return jsonify({"date": ist_now().strftime("%d %b %Y"), "signals": sigs})


@app.route("/api/signals/breakouts")
def api_signals_breakouts():
    sigs = sorted(state["breakouts_today"].values(),
                  key=lambda x: x["timestamp"], reverse=True)
    return jsonify({"date": ist_now().strftime("%d %b %Y"), "signals": sigs})


@app.route("/api/signals/history")
def api_signals_history():
    return jsonify(_load_history())


@app.route("/api/scan/log")
def api_scan_log():
    with _lock: logs = list(state["scan_log"])
    return jsonify(logs)


@app.route("/api/backtest/run", methods=["POST"])
def api_backtest_run():
    if bt_state["running"]:
        return jsonify({"ok": False, "msg": "Backtest already running"})
    data       = request.get_json(silent=True) or {}
    ticker     = data.get("ticker","RELIANCE").upper().strip()
    if not ticker.endswith(".NS"): ticker += ".NS"
    start_date = data.get("start_date","2022-01-01")
    end_date   = data.get("end_date", ist_now().strftime("%Y-%m-%d"))
    send_tg    = bool(data.get("send_telegram", False))
    p = dict(params)
    for k in PARAM_DEFAULTS:
        if k in data:
            try: p[k] = float(data[k])
            except Exception: pass
    threading.Thread(target=run_backtest_job,
                     args=(ticker, start_date, end_date, p, send_tg),
                     daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/backtest/progress")
def api_backtest_progress():
    return jsonify({"running": bt_state["running"], "progress": bt_state["progress"],
                    "total": bt_state["total"], "current": bt_state["current"],
                    "error": bt_state["error"]})


@app.route("/api/backtest/result")
def api_backtest_result():
    return jsonify(bt_state["result"] or {})


# ======================================================
# STARTUP
# ======================================================

_load_today_signals()
_start_scheduler()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

