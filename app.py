"""
Swing Scanner — Flask Web App  v2
===================================
New in v2:
  • Live-editable strategy parameters (EMA proximity, candle range, SL%)
  • Full backtest engine — all 3 exits, metrics, streaks
  • Optional Telegram delivery of backtest CSV
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
from datetime import datetime, date
from zoneinfo import ZoneInfo

# ══════════════════════════════════════════════════════════════════
# STATIC CONFIG
# ══════════════════════════════════════════════════════════════════
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
BOT_TOKEN        = os.getenv("BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

IST = ZoneInfo("Asia/Kolkata")

# Silence yfinance noise (delisted warnings, rate limit messages)
import logging as _logging
_logging.getLogger("yfinance").setLevel(_logging.CRITICAL)
_logging.getLogger("peewee").setLevel(_logging.CRITICAL)

# ══════════════════════════════════════════════════════════════════
# LIVE-EDITABLE STRATEGY PARAMETERS
# ══════════════════════════════════════════════════════════════════
PARAM_DEFAULTS = {
    "ema_proximity":  0.005,
    "max_candle_rng": 0.010,
    "max_sl_pct":     0.050,
    "lookback_days":  30,
    "be_trigger_r":   1.0,
    "target_2r":      2.0,
    "target_3r":      3.0,
    "max_hold_days":  40,
    "risk_per_trade": 0.02,
    "initial_cash":   100000,
    "brokerage":      0.001,
}
params = dict(PARAM_DEFAULTS)

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
    "CUMMINSIND.NS","DABUR.NS","DALBHARAT.NS","DEEPAKNTR.NS","DIVISLAB.NS","DIXON.NS","DLF.NS","DRREDDY.NS","EICHERMOT.NS",
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
    "POLYCAB.NS","POWERGRID.NS","RAMCOCEM.NS",
    "RECLTD.NS","RELIANCE.NS","SAIL.NS","SBICARD.NS","SBILIFE.NS",
    "SBIN.NS","SHREECEM.NS","SHRIRAMFIN.NS","SIEMENS.NS","SRF.NS",
    "SUNPHARMA.NS","SUNTV.NS","SUPREMEIND.NS","SYNGENE.NS","TATACONSUM.NS","TATAMOTORS.NS","TATAPOWER.NS","TATASTEEL.NS","TCS.NS",
    "TECHM.NS","TITAN.NS","TORNTPHARM.NS","TORNTPOWER.NS","TRENT.NS",
    "TRIDENT.NS","TVSMOTOR.NS","UBL.NS","ULTRACEMCO.NS",
    "UPL.NS","VEDL.NS","VOLTAS.NS","WIPRO.NS",
    "ZEEL.NS","ZYDUSLIFE.NS",
]

# ══════════════════════════════════════════════════════════════════
# SCANNER STATE
# ══════════════════════════════════════════════════════════════════
_lock = threading.Lock()

state = {
    "status": "idle", "scan_running": False, "auto_schedule": True,
    "current_ticker": "", "scanned": 0, "total": len(TICKERS),
    "signals_today": {}, "scan_log": [], "scan_number": 0,
    "last_scan_time": None, "next_scan_time": None, "scan_start_ts": None,
}

bt_state = {
    "running": False, "progress": 0, "total": 3,
    "current": "", "result": None, "error": None,
    "mode": "single",          # "single" | "full"
}

# Full F&O scan backtest state
scan_bt_state = {
    "running":  False,
    "progress": 0,          # stocks completed
    "total":    len(TICKERS),
    "current":  "",
    "result":   None,
    "error":    None,
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
    return future[0] if future else "—"


# ══════════════════════════════════════════════════════════════════
# LIVE SCANNER CORE
# ══════════════════════════════════════════════════════════════════

def fetch_and_check(ticker):
    short = ticker.replace(".NS","").replace(".BO","")
    if short in state["signals_today"]:
        return None
    try:
        import logging
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)

        # Use Ticker.history() — more reliable on cloud deployments
        _t = yf.Ticker(ticker)
        hist = _t.history(period=f"{int(params['lookback_days'])}d",
                          interval="1d", auto_adjust=True, actions=False)
        if hist is None or hist.empty or len(hist) < 10:
            # fallback to download()
            hist = yf.download(ticker, period=f"{int(params['lookback_days'])}d",
                               interval="1d", auto_adjust=True, progress=False, threads=False)
        if hist is None or hist.empty or len(hist) < 10:
            return None
        hist.dropna(inplace=True)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = [c[0] for c in hist.columns]
        else:
            hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]
        # Remove timezone from index if present
        if hasattr(hist.index, 'tz') and hist.index.tz is not None:
            hist.index = hist.index.tz_localize(None)

        live_raw = _t.history(period="1d", interval="1m", auto_adjust=True, actions=False)
        if live_raw is None or live_raw.empty:
            live_raw = yf.download(ticker, period="1d", interval="1m",
                                   auto_adjust=True, progress=False, threads=False)
        if live_raw.empty:
            return None
        live_raw.columns = [c[0] if isinstance(c, tuple) else c for c in live_raw.columns]

        today_row = pd.DataFrame([{
            "Open": float(live_raw["Open"].iloc[0]),
            "High": float(live_raw["High"].max()),
            "Low":  float(live_raw["Low"].min()),
            "Close":float(live_raw["Close"].iloc[-1]),
            "Volume":float(live_raw["Volume"].sum()),
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

        row  = df.iloc[-1]
        ema9 = float(row["EMA9"]); ema20 = float(row["EMA20"])

        if ema9 <= ema20:                                                    return None
        if row["Above20_3d"] < 1:                                           return None
        if row["MaxRng3"]    > params["max_candle_rng"]:                    return None
        today_low = float(row["Low"])
        if abs(today_low - ema20) / ema20 > params["ema_proximity"]:        return None

        range3_hi   = float(row["Range3Hi"])
        live_price  = float(row["Close"])
        entry_price = round(range3_hi, 2)
        if live_price <= range3_hi:                                         return None

        stop_loss = round(today_low, 2)
        rpu       = entry_price - stop_loss
        if rpu <= 0 or rpu / entry_price > params["max_sl_pct"]:           return None

        sl_pct = round(rpu / entry_price * 100, 2)
        return {
            "ticker":     short,
            "timestamp":  ist_now().strftime("%Y-%m-%d %H:%M:%S"),
            "live_price": round(live_price, 2),
            "entry":      entry_price,
            "stop_loss":  stop_loss,
            "sl_pct":     sl_pct,
            "target_2r":  round(entry_price + 2 * rpu, 2),
            "target_3r":  round(entry_price + 3 * rpu, 2),
            "ema9":       round(ema9, 2),
            "ema20":      round(ema20, 2),
        }
    except Exception as e:
        err = str(e).lower()
        if any(x in err for x in ["delisted","no timezone","tzmissing","yftzmissing"]):
            pass  # silently skip delisted tickers
        return None


def run_scan(manual=False):
    with _lock:
        if state["scan_running"]:
            return
        state.update({"scan_running": True, "status": "scanning",
                      "scanned": 0, "current_ticker": "",
                      "scan_start_ts": ist_now().strftime("%Y-%m-%d %H:%M:%S")})
        state["scan_number"] += 1

    total = len(TICKERS); found = []; num = state["scan_number"]; t0 = time.time()

    for i, ticker in enumerate(TICKERS, 1):
        short = ticker.replace(".NS","")
        with _lock:
            state["scanned"] = i; state["current_ticker"] = short
        sig = fetch_and_check(ticker)
        if sig:
            found.append(sig)
            with _lock: state["signals_today"][short] = sig
            _persist_signal(sig); _send_telegram_signal(sig)
        time.sleep(0.15)

    elapsed = round(time.time() - t0, 1)
    summary = {"scan_number": num, "time": ist_now().strftime("%H:%M:%S"),
               "date": ist_now().strftime("%Y-%m-%d"),
               "type": "manual" if manual else "auto",
               "total_stocks": total, "signals_found": len(found),
               "elapsed_sec": elapsed, "tickers_found": [s["ticker"] for s in found]}

    with _lock:
        state.update({"scan_running": False, "status": "idle",
                      "last_scan_time": ist_now().strftime("%H:%M:%S"),
                      "next_scan_time": _next_scan_str()})
        state["scan_log"].insert(0, summary); state["scan_log"] = state["scan_log"][:50]

    _persist_scan_log(summary)
    if TELEGRAM_ENABLED and len(found) > 1:
        _send_telegram(f"📋 <b>Scan #{num}</b> — {ist_now().strftime('%H:%M')} IST\n"
                       f"<b>{len(found)}</b> signals across {total} F&O stocks.")


def _bg_scan(manual=False):
    threading.Thread(target=run_scan, args=(manual,), daemon=True).start()


# ══════════════════════════════════════════════════════════════════
# BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════

def _fetch_ohlcv(ticker, start_date, end_date):
    """
    Fetch daily OHLCV using Ticker.history() — more reliable on cloud than yf.download().
    Falls back to yf.download() if history() fails.
    Returns clean DataFrame with columns [Open,High,Low,Close,Volume] or None.
    """
    import logging
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)

    def _clean(raw):
        """Flatten MultiIndex, keep OHLCV, drop NaN rows."""
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = [c[0] for c in raw.columns]
        else:
            raw.columns = [str(c[0]) if isinstance(c, tuple) else str(c) for c in raw.columns]
        needed = [c for c in ["Open","High","Low","Close","Volume"] if c in raw.columns]
        if not all(c in needed for c in ["Open","High","Low","Close"]):
            return None
        df = raw[needed].copy()
        df.dropna(subset=["Open","High","Low","Close"], inplace=True)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df[(df.index >= pd.Timestamp(start_date)) &
                (df.index <= pd.Timestamp(end_date))]
        return df if len(df) >= 10 else None

    # ── Method 1: Ticker.history() — uses different Yahoo endpoint ──
    try:
        t   = yf.Ticker(ticker)
        raw = t.history(start=start_date, end=end_date,
                        interval="1d", auto_adjust=True, actions=False)
        df  = _clean(raw)
        if df is not None:
            print(f"[BT] {ticker}: history() ✅ {len(df)} rows", flush=True)
            return df
        print(f"[BT] {ticker}: history() returned empty", flush=True)
    except Exception as e:
        print(f"[BT] {ticker}: history() error: {e}", flush=True)
        if any(x in str(e).lower() for x in ["delisted","no timezone","tzmissing","yftzmissing"]):
            return None

    time.sleep(0.5)

    # ── Method 2: yf.download() fallback ────────────────────────────
    try:
        raw = yf.download(ticker, start=start_date, end=end_date,
                          interval="1d", auto_adjust=True, progress=False,
                          threads=False)
        df  = _clean(raw)
        if df is not None:
            print(f"[BT] {ticker}: download() ✅ {len(df)} rows", flush=True)
            return df
        print(f"[BT] {ticker}: download() returned empty", flush=True)
    except Exception as e:
        print(f"[BT] {ticker}: download() error: {e}", flush=True)

    time.sleep(0.5)

    # ── Method 3: Manual Yahoo Finance v8 API call ───────────────────
    try:
        import requests as _req
        import datetime as _dt
        p1 = int(pd.Timestamp(start_date).timestamp())
        p2 = int(pd.Timestamp(end_date).timestamp())
        sym = ticker.replace(".NS", "") + ".NS"
        url = (f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
               f"?period1={p1}&period2={p2}&interval=1d&events=history")
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"),
            "Accept": "application/json",
        }
        r = _req.get(url, headers=headers, timeout=15)
        print(f"[BT] {ticker}: v8 API status={r.status_code}", flush=True)
        if r.status_code == 200:
            j      = r.json()
            result = j.get("chart", {}).get("result", [])
            if result:
                ts     = result[0]["timestamp"]
                q      = result[0]["indicators"]["quote"][0]
                adjc   = result[0]["indicators"].get("adjclose", [{}])[0].get("adjclose", q["close"])
                dates  = pd.to_datetime(ts, unit="s").tz_localize("UTC").tz_convert("Asia/Kolkata").tz_localize(None).normalize()
                raw2   = pd.DataFrame({
                    "Open":   q["open"],  "High":  q["high"],
                    "Low":    q["low"],   "Close": adjc,
                    "Volume": q["volume"],
                }, index=dates)
                df = _clean(raw2)
                if df is not None:
                    print(f"[BT] {ticker}: v8 API ✅ {len(df)} rows", flush=True)
                    return df
        print(f"[BT] {ticker}: v8 API returned no usable data", flush=True)
    except Exception as e:
        print(f"[BT] {ticker}: v8 API error: {e}", flush=True)

    print(f"[BT] {ticker}: ❌ all methods failed", flush=True)
    return None


def _bt_prepare(ticker, start_date, end_date, p):
    warmup = (pd.Timestamp(start_date) - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    df = _fetch_ohlcv(ticker, warmup, end_date)
    if df is None:
        return None

    df["EMA9"]       = df["Close"].ewm(span=9,  adjust=False).mean()
    df["EMA20"]      = df["Close"].ewm(span=20, adjust=False).mean()
    df["CandleRng"]  = (df["High"] - df["Low"]) / df["Low"]
    df["MaxRng3"]    = df["CandleRng"].shift(1).rolling(3).max()
    df["Range3Hi"]   = df["High"].shift(1).rolling(3).max()
    above            = (df["Close"] > df["EMA20"]).astype(int)
    df["Above20_3d"] = above.shift(1).rolling(3).min()
    return df


def _bt_signals(df, start_date, p):
    sigs = []; sd = pd.Timestamp(start_date)
    for i in range(5, len(df)):
        if df.index[i] < sd: continue
        row = df.iloc[i]
        if row["EMA9"] <= row["EMA20"]: continue
        if row["Above20_3d"] < 1: continue
        if row["MaxRng3"] > p["max_candle_rng"]: continue
        if abs(row["Low"] - row["EMA20"]) / row["EMA20"] > p["ema_proximity"]: continue
        sigs.append({"date": df.index[i], "idx": i,
                     "stop_loss": round(float(row["Low"]), 2),
                     "range3_hi": round(float(row["Range3Hi"]), 2)})
    return sigs


def _bt_simulate(signals, df, exit_mode, p):
    trades = []; capital = p["initial_cash"]; last_used = -1
    for sig in signals:
        si = sig["idx"]
        if si <= last_used: continue
        sl0 = sig["stop_loss"]; r3hi = sig["range3_hi"]
        entry = entry_idx = None
        for k in range(si + 1, min(si + 4, len(df))):
            if k <= last_used: break
            if float(df.iloc[k]["High"]) > r3hi:
                entry = round(r3hi, 2); entry_idx = k; break
        if entry is None: continue
        rps = entry - sl0
        if rps <= 0 or rps / entry > p["max_sl_pct"]: continue
        qty = int((capital * p["risk_per_trade"]) / rps)
        if qty <= 0: continue

        l1r = entry + p["be_trigger_r"] * rps
        l2r = entry + p["target_2r"]    * rps
        l3r = entry + p["target_3r"]    * rps
        stop = sl0; be_hit = False; qty_rem = qty
        gross = cost = 0.0; exit_date = outcome = None
        end_idx = min(entry_idx + int(p["max_hold_days"]), len(df))

        for j in range(entry_idx + 1, end_idx):
            c = df.iloc[j]
            c_hi = float(c["High"]); c_lo = float(c["Low"])
            c_cl = float(c["Close"]); c_e9 = float(c["EMA9"])

            if c_lo <= stop:
                gross += (stop - entry) * qty_rem
                cost  += (entry + stop) * qty_rem * p["brokerage"]
                exit_date = df.index[j]; outcome = "BE_EXIT" if be_hit else "LOSS"
                qty_rem = 0; break

            if not be_hit and c_hi >= l1r:
                stop = entry; be_hit = True

            if exit_mode == "2R" and c_hi >= l2r:
                gross += (l2r - entry) * qty_rem
                cost  += (entry + l2r) * qty_rem * p["brokerage"]
                exit_date = df.index[j]; outcome = "WIN_2R"; qty_rem = 0; break
            elif exit_mode == "3R" and c_hi >= l3r:
                gross += (l3r - entry) * qty_rem
                cost  += (entry + l3r) * qty_rem * p["brokerage"]
                exit_date = df.index[j]; outcome = "WIN_3R"; qty_rem = 0; break
            elif exit_mode == "EMA9" and be_hit and c_cl < c_e9:
                gross += (c_cl - entry) * qty_rem
                cost  += (entry + c_cl) * qty_rem * p["brokerage"]
                exit_date = df.index[j]; outcome = "EMA9_TRAIL"; qty_rem = 0; break

        if qty_rem > 0:
            px = round(float(df.iloc[end_idx - 1]["Close"]), 2)
            gross += (px - entry) * qty_rem
            cost  += (entry + px) * qty_rem * p["brokerage"]
            exit_date = df.index[end_idx - 1]; outcome = "TIMEOUT"

        net = round(gross - cost, 2); capital += net
        last_used = entry_idx + int(p["max_hold_days"])
        trades.append({
            "Exit_Mode": exit_mode,
            "Setup":     sig["date"].strftime("%Y-%m-%d"),
            "Entry":     df.index[entry_idx].strftime("%Y-%m-%d"),
            "Exit":      exit_date.strftime("%Y-%m-%d") if exit_date else "",
            "EntryPx":   entry, "SL": sl0,
            "Outcome":   outcome, "NetPnL": net, "Capital": round(capital, 2),
        })
    return trades, capital


def _bt_metrics(trades, init_cap, final_cap):
    if not trades: return {}
    wins   = [t for t in trades if t["NetPnL"] >  0]
    losses = [t for t in trades if t["NetPnL"] <= 0]
    cap_c  = [init_cap] + [t["Capital"] for t in trades]
    peak = init_cap; mdd = 0
    for c in cap_c:
        peak = max(peak, c); mdd = max(mdd, (peak - c) / peak * 100)
    loss_sum = sum(l["NetPnL"] for l in losses)
    win_sum  = sum(w["NetPnL"] for w in wins)
    pf = round(abs(win_sum / loss_sum), 2) if loss_sum != 0 else None

    # Streaks
    max_ws = cur_ws = max_ls = cur_ls = 0
    for t in trades:
        if t["NetPnL"] > 0: cur_ws += 1; cur_ls = 0; max_ws = max(max_ws, cur_ws)
        else:               cur_ls += 1; cur_ws = 0; max_ls = max(max_ls, cur_ls)

    return {
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate":    round(len(wins) / len(trades) * 100, 1),
        "total_pnl":   round(win_sum + loss_sum, 0),
        "return_pct":  round((final_cap - init_cap) / init_cap * 100, 2),
        "final_cap":   round(final_cap, 0),
        "avg_win":     round(win_sum / len(wins), 0)   if wins   else 0,
        "avg_loss":    round(loss_sum / len(losses), 0) if losses else 0,
        "profit_factor": pf,
        "max_dd":      round(mdd, 2),
        "max_win_streak":  max_ws,
        "max_loss_streak": max_ls,
    }


def run_backtest_job(ticker, start_date, end_date, p, send_tg):
    bt_state.update({"running": True, "error": None, "result": None,
                     "progress": 0, "total": 3, "current": "Fetching data…"})
    try:
        df = _bt_prepare(ticker, start_date, end_date, p)
        if df is None:
            raise ValueError(
                f"Could not fetch data for {ticker}. "
                f"Check the ticker is valid (e.g. RELIANCE.NS) and date range is not too recent."
            )
        bt_state["current"] = "Detecting signals…"
        sigs = _bt_signals(df, start_date, p)

        all_trades = []; results = {}
        for i, mode in enumerate(["2R","3R","EMA9"], 1):
            bt_state.update({"current": f"Simulating {mode} exit…", "progress": i})
            trades, final_cap = _bt_simulate(sigs, df, mode, p)
            metrics = _bt_metrics(trades, p["initial_cash"], final_cap)
            results[mode] = {"metrics": metrics}
            all_trades.extend(trades)
            time.sleep(0.05)

        short = ticker.replace(".NS","")
        bt_state["result"] = {
            "ticker": short, "start": start_date, "end": end_date,
            "signals": len(sigs),
            "params": {k: p[k] for k in ["ema_proximity","max_candle_rng","max_sl_pct",
                                          "initial_cash","risk_per_trade"]},
            "results": results,
        }

        if send_tg and TELEGRAM_ENABLED and BOT_TOKEN:
            _send_backtest_telegram(short, results, all_trades, start_date, end_date)

    except Exception as e:
        bt_state["error"] = str(e)
    finally:
        bt_state.update({"running": False, "current": "Done"})


def _send_backtest_telegram(ticker, results, all_trades, start, end):
    labels = {"2R": "Exit 2R", "3R": "Exit 3R", "EMA9": "Trail EMA9"}
    lines  = [f"📊 <b>Backtest: {ticker}</b>  ({start} → {end})\n"]
    for mode, data in results.items():
        m = data["metrics"]
        if not m: continue
        pf = f"{m['profit_factor']}" if m["profit_factor"] else "∞"
        lines.append(
            f"<b>{labels[mode]}</b>\n"
            f"  Trades {m['trades']} | Win {m['win_rate']}% | Return {m['return_pct']}%\n"
            f"  PF {pf} | MaxDD {m['max_dd']}% | Cap ₹{m['final_cap']:,.0f}\n"
            f"  🏆 WStreak {m['max_win_streak']} | 📉 LStreak {m['max_loss_streak']}\n"
        )
    _send_telegram("\n".join(lines))

    if not all_trades: return
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=all_trades[0].keys())
    writer.writeheader(); writer.writerows(all_trades)
    buf.seek(0)
    try:
        req.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
            data={"chat_id": TELEGRAM_CHAT_ID,
                  "caption": f"Backtest trades — {ticker} ({start}→{end})"},
            files={"document": (f"bt_{ticker}_{start}_{end}.csv",
                                buf.read().encode(), "text/csv")},
            timeout=20,
        )
    except Exception: pass



# ══════════════════════════════════════════════════════════════════
# FULL F&O SCAN BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════════

def run_full_scan_backtest(start_date, end_date, p, send_tg):
    """
    Backtests every F&O ticker independently.
    Returns per-stock leaderboard + combined portfolio equity.
    """
    scan_bt_state.update({
        "running": True, "error": None, "result": None,
        "progress": 0, "total": len(TICKERS), "current": "Starting…",
    })

    stock_results = []
    all_trades    = []
    failed        = []
    succeeded     = 0

    for idx, ticker in enumerate(TICKERS):
        short = ticker.replace(".NS", "")
        scan_bt_state.update({"progress": idx + 1,
                               "current": f"{short} ({idx+1}/{len(TICKERS)})"})
        try:
            df = _bt_prepare(ticker, start_date, end_date, p)
            if df is None:
                failed.append(short)
                time.sleep(0.5)   # back off before next ticker
                continue

            sigs = _bt_signals(df, start_date, p)
            if not sigs:
                time.sleep(0.3)
                continue

            succeeded += 1
            for mode in ["2R", "3R", "EMA9"]:
                trades, final_cap = _bt_simulate(sigs, df, mode, p)
                if not trades:
                    continue
                m = _bt_metrics(trades, p["initial_cash"], final_cap)
                stock_results.append({
                    "ticker":          short,
                    "exit_mode":       mode,
                    "trades":          m["trades"],
                    "win_rate":        m["win_rate"],
                    "return_pct":      m["return_pct"],
                    "profit_factor":   m["profit_factor"],
                    "max_dd":          m["max_dd"],
                    "max_win_streak":  m["max_win_streak"],
                    "max_loss_streak": m["max_loss_streak"],
                })
                for t in trades:
                    t2 = dict(t); t2["Ticker"] = short
                    all_trades.append(t2)

        except Exception as e:
            failed.append(f"{short}:{e}")
            time.sleep(0.5)
            continue

        # Throttle: 0.8s between tickers to avoid yfinance rate limiting
        time.sleep(0.8)

    print(f"[BT] Full scan done — {succeeded} stocks with data, "
          f"{len([r for r in stock_results if r['exit_mode']=='2R'])} with trades, "
          f"{len(failed)} failed")

    if not stock_results:
        # Give a helpful error with how many stocks actually failed
        msg = (f"No trades found across {len(TICKERS)} stocks. "
               f"{len(failed)} tickers had no data (yfinance may be throttling). "
               f"Try a longer date range e.g. 2020-01-01 to today, or wait a few minutes and retry.")
        scan_bt_state.update({"running": False, "error": msg})
        return

    # ── Leaderboard: top 10 per exit mode ─────────────────────────
    leaderboard = {}
    for mode in ["2R", "3R", "EMA9"]:
        rows = [r for r in stock_results if r["exit_mode"] == mode]
        rows.sort(key=lambda x: x["return_pct"], reverse=True)
        leaderboard[mode] = rows[:10]

    # ── Combined portfolio simulation ─────────────────────────────
    # For each exit mode, take all trades, sort by entry date,
    # re-run through shared capital sequentially
    combined = {}
    for mode in ["2R", "3R", "EMA9"]:
        mode_trades = [t for t in all_trades if t["Exit_Mode"] == mode]
        mode_trades.sort(key=lambda x: x["Entry"])
        cap = p["initial_cash"]; equity = [cap]
        for t in mode_trades:
            cap += t["NetPnL"]
            equity.append(round(cap, 0))
        # Metrics on combined
        cm = _bt_metrics(mode_trades, p["initial_cash"], cap) if mode_trades else {}
        combined[mode] = {
            "metrics": cm,
            "equity_curve": equity[::max(1, len(equity)//200)],  # max 200 points
        }

    # ── Summary stats ──────────────────────────────────────────────
    total_stocks_traded = len(set(r["ticker"] for r in stock_results))

    scan_bt_state["result"] = {
        "type":                 "full_scan",
        "start":                start_date,
        "end":                  end_date,
        "total_stocks":         len(TICKERS),
        "stocks_with_trades":   total_stocks_traded,
        "params":               {k: p[k] for k in ["ema_proximity","max_candle_rng","max_sl_pct"]},
        "leaderboard":          leaderboard,
        "combined":             combined,
    }

    if send_tg and TELEGRAM_ENABLED and BOT_TOKEN:
        _send_full_scan_telegram(scan_bt_state["result"])

    scan_bt_state.update({"running": False, "current": "Done"})


def _send_full_scan_telegram(result):
    lines = [
        f"📊 <b>Full F&O Scan Backtest</b>  ({result['start']} → {result['end']})",
        f"Stocks traded: <b>{result['stocks_with_trades']}</b> / {result['total_stocks']}\n",
    ]
    labels = {"2R": "Exit 2R", "3R": "Exit 3R", "EMA9": "Trail EMA9"}
    for mode, data in result["combined"].items():
        m = data["metrics"]
        if not m: continue
        pf = str(m["profit_factor"]) if m["profit_factor"] else "∞"
        lines.append(
            f"<b>{labels[mode]}</b> (Combined Portfolio)\n"
            f"  Return {m['return_pct']}% | Win {m['win_rate']}% | PF {pf}\n"
            f"  MaxDD {m['max_dd']}% | Trades {m['trades']}\n"
        )
    for mode, top10 in result["leaderboard"].items():
        lines.append(f"\n🏆 <b>Top 10 — {labels[mode]}</b>")
        for i, r in enumerate(top10[:5], 1):
            lines.append(f"  {i}. {r['ticker']} → {r['return_pct']}% | W {r['win_rate']}%")
    _send_telegram("\n".join(lines))

# ══════════════════════════════════════════════════════════════════
# EOD SUMMARY
# ══════════════════════════════════════════════════════════════════

def send_eod_summary():
    sigs = list(state["signals_today"].values())
    today = ist_now().strftime("%d %b %Y")
    if not sigs:
        msg = f"📋 <b>EOD Summary — {today}</b>\n\nNo signals today."
    else:
        lines = [f"📋 <b>EOD Summary — {today}</b>",
                 f"<b>{len(sigs)} signal(s)</b>\n",
                 "<code>Stock        Entry      SL      2R      3R</code>"]
        for s in sigs:
            lines.append(f"<code>{s['ticker']:<12}"
                         f"₹{s['entry']:>7.2f} ₹{s['stop_loss']:>7.2f} "
                         f"₹{s['target_2r']:>7.2f} ₹{s['target_3r']:>7.2f}</code>")
        msg = "\n".join(lines)
    _send_telegram(msg)


# ══════════════════════════════════════════════════════════════════
# PERSISTENCE
# ══════════════════════════════════════════════════════════════════

def _persist_signal(sig):
    f = os.path.join(DATA_DIR, f"signals_{date.today()}.json")
    existing = []
    if os.path.exists(f):
        try:
            with open(f) as fh: existing = json.load(fh)
        except Exception: pass
    existing = [s for s in existing if s.get("ticker") != sig["ticker"]]
    existing.append(sig)
    with open(f, "w") as fh: json.dump(existing, fh, indent=2)


def _persist_scan_log(summary):
    f = os.path.join(DATA_DIR, "scan_log.json")
    existing = []
    if os.path.exists(f):
        try:
            with open(f) as fh: existing = json.load(fh)
        except Exception: pass
    existing.insert(0, summary)
    with open(f, "w") as fh: json.dump(existing[:200], fh, indent=2)


def _load_history():
    history = []
    for fname in sorted(os.listdir(DATA_DIR), reverse=True):
        if fname.startswith("signals_") and fname.endswith(".json"):
            ds = fname.replace("signals_","").replace(".json","")
            try:
                with open(os.path.join(DATA_DIR, fname)) as fh:
                    sigs = json.load(fh)
                history.append({"date": ds, "signals": sigs, "count": len(sigs)})
            except Exception: pass
    return history


def _load_today_signals():
    f = os.path.join(DATA_DIR, f"signals_{date.today()}.json")
    if os.path.exists(f):
        try:
            with open(f) as fh:
                for s in json.load(fh): state["signals_today"][s["ticker"]] = s
        except Exception: pass


# ══════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════

def _send_telegram(msg):
    if not TELEGRAM_ENABLED or not BOT_TOKEN: return
    try:
        req.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                 json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
                 timeout=10)
    except Exception: pass


def _send_telegram_signal(sig):
    _send_telegram(
        f"🚨 <b>SIGNAL — {sig['ticker']}</b>\n📅 {sig['timestamp']}\n\n"
        f"🟢 <b>Entry    :</b> ₹{sig['entry']}\n"
        f"🔴 <b>Stop Loss:</b> ₹{sig['stop_loss']} ({sig['sl_pct']}%)\n"
        f"🎯 <b>Target 2R:</b> ₹{sig['target_2r']}\n"
        f"🏆 <b>Target 3R:</b> ₹{sig['target_3r']}\n"
        f"💹 <b>Live     :</b> ₹{sig['live_price']}\n\n"
        f"<i>EMA9: {sig['ema9']} | EMA20: {sig['ema20']}</i>"
    )


# ══════════════════════════════════════════════════════════════════
# SCHEDULER
# ══════════════════════════════════════════════════════════════════

def _reset_cache():
    with _lock: state["signals_today"].clear()
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


# ══════════════════════════════════════════════════════════════════
# FLASK ROUTES
# ══════════════════════════════════════════════════════════════════

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def api_status():
    with _lock:
        s = {k: v for k, v in state.items() if k not in ("signals_today","scan_log")}
    s.update({"market_open": is_market_open(), "ist_time": ist_now().strftime("%H:%M:%S"),
              "ist_date": ist_now().strftime("%d %b %Y"),
              "total_tickers": len(TICKERS), "signals_count": len(state["signals_today"])})
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
    _bg_scan(manual=True); return jsonify({"ok": True})


@app.route("/api/scan/stop", methods=["POST"])
def api_scan_stop():
    with _lock: state["status"] = "stopping"
    return jsonify({"ok": True})


@app.route("/api/scan/progress")
def api_scan_progress():
    with _lock:
        return jsonify({
            "running": state["scan_running"], "scanned": state["scanned"],
            "total": state["total"], "current_ticker": state["current_ticker"],
            "signals_so_far": len(state["signals_today"]),
            "pct": round(state["scanned"] / state["total"] * 100, 1) if state["total"] else 0,
        })


@app.route("/api/schedule/toggle", methods=["POST"])
def api_schedule_toggle():
    with _lock:
        state["auto_schedule"] = not state["auto_schedule"]; val = state["auto_schedule"]
    return jsonify({"ok": True, "auto_schedule": val})


@app.route("/api/signals/today")
def api_signals_today():
    sigs = sorted(state["signals_today"].values(), key=lambda x: x["timestamp"], reverse=True)
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
    ticker     = data.get("ticker", "RELIANCE").upper().strip()
    if not ticker.endswith(".NS"): ticker += ".NS"
    start_date = data.get("start_date", "2022-01-01")
    end_date   = data.get("end_date",   ist_now().strftime("%Y-%m-%d"))
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



@app.route("/api/backtest/full/run", methods=["POST"])
def api_full_bt_run():
    if scan_bt_state["running"] or bt_state["running"]:
        return jsonify({"ok": False, "msg": "A backtest is already running"})
    data       = request.get_json(silent=True) or {}
    start_date = data.get("start_date", "2022-01-01")
    end_date   = data.get("end_date",   ist_now().strftime("%Y-%m-%d"))
    send_tg    = bool(data.get("send_telegram", False))
    p = dict(params)
    for k in PARAM_DEFAULTS:
        if k in data:
            try: p[k] = float(data[k])
            except Exception: pass
    threading.Thread(target=run_full_scan_backtest,
                     args=(start_date, end_date, p, send_tg),
                     daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/backtest/full/progress")
def api_full_bt_progress():
    return jsonify({
        "running":  scan_bt_state["running"],
        "progress": scan_bt_state["progress"],
        "total":    scan_bt_state["total"],
        "current":  scan_bt_state["current"],
        "error":    scan_bt_state["error"],
        "pct":      round(scan_bt_state["progress"] / scan_bt_state["total"] * 100, 1)
                    if scan_bt_state["total"] else 0,
    })


@app.route("/api/backtest/full/result")
def api_full_bt_result():
    return jsonify(scan_bt_state["result"] or {})


@app.route("/api/backtest/test")
def api_backtest_test():
    """Quick test — downloads one ticker and returns what happened."""
    ticker = request.args.get("ticker", "RELIANCE.NS")
    start  = request.args.get("start",  "2022-01-01")
    end    = request.args.get("end",    ist_now().strftime("%Y-%m-%d"))
    try:
        df = _fetch_ohlcv(ticker, start, end)
        if df is None:
            return jsonify({"ok": False, "msg": f"All fetch methods failed for {ticker}. Check Railway logs for details.",
                            "ticker": ticker, "start": start, "end": end})
        sigs = _bt_signals(df, start, params) if df is not None else []
        return jsonify({
            "ok":         True,
            "ticker":     ticker,
            "rows":       len(df),
            "signals":    len(sigs),
            "cols":       list(df.columns),
            "date_range": [str(df.index[0].date()), str(df.index[-1].date())],
            "sample_close": round(float(df["Close"].iloc[-1]), 2),
        })
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e), "ticker": ticker})

# ══════════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════════

_load_today_signals()
_start_scheduler()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

