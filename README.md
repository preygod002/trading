# 📡 Swing Scanner — Mobile Web App

NSE F&O swing scanner with a mobile-friendly web UI.
Runs 24/7 in the cloud. Access from any phone via browser.

## What it does
- Scans ~175 F&O stocks every 15 min (9:20 AM – 3:15 PM IST)
- Sends Telegram alerts on signals
- EOD summary at 3:30 PM
- Mobile UI: Start/Stop scan, live progress, today's signals, history, scan log

---

## 🚀 Deploy FREE on Railway (Recommended)

### Step 1 — Push to GitHub
```bash
git init
git add .
git commit -m "swing scanner"
# Create a repo on github.com, then:
git remote add origin https://github.com/YOUR_USERNAME/swing-scanner.git
git push -u origin main
```

### Step 2 — Deploy on Railway
1. Go to **railway.app** → Sign up free (GitHub login)
2. Click **New Project** → **Deploy from GitHub repo**
3. Select your repo → Railway auto-detects Python + deploys

### Step 3 — Set Environment Variables
In Railway → your project → **Variables** tab, add:
```
TELEGRAM_ENABLED   = true
BOT_TOKEN          = your_bot_token_from_botfather
TELEGRAM_CHAT_ID   = your_chat_id
```

### Step 4 — Get your URL
Railway gives you a URL like:
`https://swing-scanner-production.up.railway.app`

Open it on your phone → **Add to Home Screen** → works like an app!

---

## 🌐 Alternative: Deploy FREE on Render

1. Go to **render.com** → New → Web Service
2. Connect GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120`
5. Add environment variables (same as above)

⚠️ Render free tier **spins down after 15 min of inactivity**.
Use Railway for always-on behaviour.

---

## 📱 Add to Phone Home Screen

**iPhone (Safari):**
Share button → Add to Home Screen → Add

**Android (Chrome):**
Menu (⋮) → Add to Home Screen → Add

---

## ⚙️ Environment Variables

| Variable | Description | Default |
|---|---|---|
| `TELEGRAM_ENABLED` | Enable Telegram alerts | `false` |
| `BOT_TOKEN` | From @BotFather | — |
| `TELEGRAM_CHAT_ID` | Your chat/group ID | — |
| `PORT` | Auto-set by Railway/Render | `5000` |

---

## 📁 File Structure
```
swing_app/
├── app.py              ← Flask backend + scanner engine
├── templates/
│   └── index.html      ← Mobile UI
├── data/               ← Signal JSON files (auto-created)
│   ├── signals_2026-03-13.json
│   └── scan_log.json
├── requirements.txt
├── Procfile
├── railway.toml
└── render.yaml
```

---

## 🔌 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/` | Mobile UI |
| GET | `/api/status` | Scanner status + market open/closed |
| POST | `/api/scan/start` | Start a manual scan |
| POST | `/api/scan/stop` | Stop running scan |
| GET | `/api/scan/progress` | Live progress (poll while scanning) |
| POST | `/api/schedule/toggle` | Toggle auto schedule on/off |
| GET | `/api/signals/today` | Today's signals |
| GET | `/api/signals/history` | All past signal days |
| GET | `/api/scan/log` | Scan run history |
