# 📁 Folder & File Reference — What Does Each File Do?

This explains every folder and important file in the project.

---

## Project Root Structure

```
retail-chatbot/
├── frontend/          ← Everything the user sees in the browser
├── backend/           ← The Python server (the brains)
├── api/               ← Vercel serverless entry point
├── docs/              ← Documentation files
├── mock_data/         ← SQLite database + test data
├── scratch/           ← Developer utility scripts (not used in production)
├── Tools/             ← Azure AI Foundry tool definitions
├── .env               ← Secret configuration (API keys, etc.)
├── vercel.json        ← Vercel deployment routing rules
└── requirements.txt   ← Python package dependencies
```

---

## 📂 `frontend/` — The User Interface

**Purpose:** Everything the user sees and interacts with in their browser.

| File/Folder | What it does |
|-------------|-------------|
| `index.html` | The entire chat UI — 89KB of HTML with the chat window, voice call overlay, customer sidebar, and product grid display |
| `js/app.js` | 78KB of JavaScript — handles ALL frontend logic: sending messages, streaming responses, recording voice, managing the call overlay, and WebSocket audio streaming |
| `js/azure-communication-services.js` | The Azure SDK for browser-based phone calls (VoIP) |
| `js/azure-sdk.js` | Tiny loader that imports the Azure SDK |
| `css/` | Styling for the UI |
| `images/` | Product and brand images |
| `test_runner.html` | A developer test page to run automated tests against the chatbot |
| `test_cases.json` | 50+ test cases for automated validation |

**How it interacts:** The frontend calls the backend via HTTP (`fetch`) and WebSocket. It never directly touches the database or AI.

**If removed:** No user interface — nothing to interact with.

---

## 📂 `backend/` — The Server (The Brains)

**Purpose:** Handles all business logic, AI routing, database queries, and voice processing.

### `backend/main.py` — The Central Server

**What it does:**
- Starts the FastAPI web server
- Defines all API routes (URLs the frontend can call)
- Initialises the database, AI agent, and voice services at startup
- Manages the WebSocket connections for voice calls

**Key routes defined here:**
| Route | Method | What it does |
|-------|--------|-------------|
| `/` | GET | Serves the frontend HTML |
| `/health` | GET | Checks if server is running |
| `/customer` | GET | Returns customer data |
| `/chat` | POST | Processes text messages |
| `/chat/voice` | POST | Fast voice-optimised text path |
| `/api/token` | GET | Issues ACS tokens for VoIP calls |
| `/api/voice-realtime` | WebSocket | Browser voice ↔ Voice Live relay |
| `/api/media-stream` | WebSocket | Phone call ↔ Voice Live relay |
| `/api/fillers` | GET | Returns pre-recorded "hold on" audio |

**If removed:** The entire server stops working — nothing else can run.

---

### 📂 `backend/agents/` — The AI Brains

| File | What it does |
|------|-------------|
| `router.py` | **Main AI controller** — connects to Azure AI Foundry, fetches agent instructions, manages credentials, and provides the `handle()` method that processes every chat message |
| `graph.py` | **LangGraph pipeline** — defines the flow: router → specialist → tool execution → validation. This is the brain's decision tree |
| `intent.py` | **Intent classifier** — decides what the user is asking: order? delivery? refund? store? Or just saying "yes" in response to a question? |
| `tools.py` | **Database tools** — `search_products`, `check_stock`, `get_active_promotions`, `update_customer_address`, `issue_refund`. These are the actual database queries |
| `validation.py` | **Security & formatting** — blocks sensitive data from being exposed, strips markdown, masks internal IDs |
| `foundry_config.py` | **Configuration hub** — single place that defines all Azure AI Foundry settings, agent names, and endpoints |
| `__init__.py` | Makes `agents` importable as a Python package |

---

### 📂 `backend/services/` — Supporting Services

| File | What it does |
|------|-------------|
| `acs_bot.py` | **Phone call manager** — manages Azure Communication Services (ACS) phone calls: generates user tokens, answers incoming calls, tracks active call state |
| `voice_realtime.py` | **Voice authentication + tools** — provides Azure credentials for Voice Live, implements all voice tool functions (`search_products`, `check_stock`, etc. for the voice agent), and holds the JSON tool definitions Voice Live uses |
| `voice_fillers.py` | **"Hold on" audio** — pre-renders short spoken phrases ("Let me check that for you...") using TTS at server startup so callers don't hear silence while the AI thinks |
| `__init__.py` | Makes `services` importable |

---

### 📂 `backend/database/` — Data Layer

| File | What it does |
|------|-------------|
| `database.py` | **Database engine** — manages both SQLite (local dev) and PostgreSQL (production). Handles all CRUD operations: customers, orders, products, stores, stock levels, promotions, refunds |
| `seed_data.py` | **Mock data generator** — creates realistic fake Sainsbury's data (customers, orders, products, stores) for development and demo purposes. This is what populates the database on startup |
| `__init__.py` | Exports `init_db`, `seed_db`, `load_db_customer_data` etc. |

---

## 📂 `api/` — Vercel Entry Point

| File | What it does |
|------|-------------|
| `index.py` | Tiny adapter — adds the project to Python's path and imports `app` from `backend/main.py` so Vercel can run it as a serverless function |
| `requirements.txt` | Python packages needed on Vercel |

**Why it exists:** Vercel expects a file at `api/index.py` as the serverless function handler.

**If removed:** The production deployment on Vercel stops working.

---

## 📂 `mock_data/` — Test Database

| File | What it does |
|------|-------------|
| `retail_chatbot.db` | The SQLite database file — contains all demo customer, order, product, and store data |

**Why it exists:** The app needs a working database. The SQLite file lets you run the whole app without a cloud database.

---

## 📂 `Tools/` — AI Foundry Tool Definitions

**Purpose:** JSON definitions of tools that the Azure AI Foundry agents can call. These define the interface (what parameters each tool accepts, what it returns).

---

## 📄 Key Config Files

| File | What it does |
|------|-------------|
| `.env` | Secret keys — Azure API keys, database passwords, endpoints. **Never commit to Git.** |
| `.env.example` | Template showing which env variables are needed (no real secrets) |
| `vercel.json` | Tells Vercel how to route URLs — static files go to `/frontend/`, API calls go to `/api/index.py` |
| `requirements.txt` | All Python packages the backend needs |
| `.gitignore` | Files Git should not track (`.env`, virtual environment, etc.) |
