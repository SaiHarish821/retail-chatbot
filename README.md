# Sainsbury's Retail AI Assistant — Chat & Voice Telephony Platform

An enterprise-ready customer service platform featuring a Sainsbury's-branded web chatbot, automated local test runner, and a real-time **voice call telephony bot** (answering actual PSTN telephone calls). Built on a FastAPI backend, it utilizes a multi-agent orchestration pipeline powered by **Azure AI Foundry (Agents SDK)** with direct **Azure OpenAI (GPT-4o)** fallbacks.

---

## Technical Features

*   **Unified Multi-Agent Pipeline:** Orchestrated by a `Supervisor-Agent` that decomposes user questions into parallel tasks for specialized agents:
    *   **Order Agent:** Customer account balance, recent purchases, order history, and Nectar loyalty points.
    *   **Refund Agent:** Handles claims for damaged or spoiled items, issues refunds, and tracks policy windows.
    *   **Delivery Agent:** Real-time driver mapping, ETA, stop number tracking, and address changes.
    *   **Store Agent:** Opening hours, branch locations, stock availability, Click & Collect policies, product nutrition, and allergens.
    *   **General Agent:** Handles out-of-domain chats gracefully.
*   **Dual Voice Paths:**
    *   *Browser Microphone:* Record high-quality audio WAV blobs on the web interface, transcribed using Azure Speech SDK.
    *   *Real-time Telephone Calls (PSTN):* Pick up real phone calls via an **Azure Communication Services (ACS)** telephony bot. Answers with the British neural voice `en-GB-SoniaNeural`, processes real-time Speech-to-Text, runs routing agents, and plays responses directly to the caller.
*   **SQLite Relational Database:** Structured relational database in `mock_data/retail_chatbot.db` replacing static JSON files. Houses details on customers, orders, itemized lines, refund requests, store branch directories, product catalogs (with rich nutritional/dietary tags), and active promotions.
*   **Dynamic UI with WebRTC Call Integration:** A glassmorphism theme frontend featuring standard text chat, voice record transcription, direct browser-to-agent WebRTC calling, and an automated Test Runner running custom client scenario sets.
*   **Serverless Ready:** Configured for local running (Uvicorn) or cloud scaling on **Vercel** serverless functions with automatic writeable `/tmp` database copying.

---

## Repository Structure

```
retail-chatbot/
├── .env                          # Local secrets, endpoints, API keys, and agent names
├── vercel.json                   # Vercel URL rewrite routes mapping static & API endpoints
├── requirements.txt              # Python requirements
├── api/
│   ├── index.py                  # Vercel serverless main entrypoint
│   └── requirements.txt          # Python dependencies required for Vercel functions
├── backend/
│   ├── main.py                   # FastAPI Application: routes, CORS middlewares, and database seeding
│   ├── agents/
│   │   ├── __init__.py           # Exports AgentRouter
│   │   ├── router.py             # AgentRouter: core logic, domain/intent parsing, agent task dispatch
│   │   ├── tools.py              # Agent tool implementations (stock check, product search, address updates, refunds)
│   │   ├── prompts.py            # All system and supervisor instructions
│   │   └── validation.py         # Response validation and markdown sanitization layers
│   ├── database/
│   │   ├── __init__.py           # Exports DB methods
│   │   ├── database.py           # SQLite DDL database schema definitions and CRUD functions
│   │   └── seed_data.py          # Python seed dict structure containing products and orders
│   ├── services/
│   │   ├── __init__.py           # Exports helper voice & call managers
│   │   ├── voice.py              # Azure Speech SDK: speech transcription and voice synthesis (Sonia Neural)
│   │   └── acs_bot.py            # ACS Call Automation Manager: webhook callbacks, call pickups, and play controls
│   └── tests/                    # Backend unit tests
├── frontend/
│   ├── index.html                # Sainsbury's-themed SPA interface with text, voice, and call buttons
│   ├── css/
│   │   └── styles.css            # Responsive layout and glassmorphism styling
│   ├── js/
│   │   ├── app.js                # Browser chat/voice controller and WebRTC calling logic
│   │   ├── azure-sdk.js          # Shim utility script
│   │   └── azure-communication-services.js # Bundled ACS Web Calling SDK
│   ├── test_runner.html          # Interactive browser test runner UI
│   └── test_cases.json           # Definitions for test scenarios
└── mock_data/
    ├── retail_chatbot.db         # SQLite database file (created and seeded automatically)
    └── test_results.json         # Automated/runner output results
```

---

## Getting Started

### 1. Install Dependencies

Ensure Python 3.11+ is installed. Clone the repository and run:

```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

> [!IMPORTANT]
> **Windows Users:** If you get a `FileNotFoundError` or DLL load error for `Microsoft.CognitiveServices.Speech.core.dll` when running, download and install the **[Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe)**, then restart your terminal or IDE.

### 2. Configuration Setup

Copy the example template to `.env`:

```bash
cp .env.example .env
```

Open `.env` and fill in the required variables (described below):

```env
# ─────────────────────────────────────────────────────────────────────────────
# Azure AI Foundry & Model Deployments
# ─────────────────────────────────────────────────────────────────────────────
AZURE_AI_FOUNDRY_API_KEY=your_azure_ai_foundry_api_key
AZURE_TENANT_ID=your_azure_tenant_id_guid
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-region.api.azureml.ms/agents/v1.0/subscriptions/sub-id/resourceGroups/rg/workspaces/project-name
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/openai/v1
AZURE_AI_FOUNDRY_DEPLOYMENT_NAME=gpt-4o

# Agent Names as defined in your AI Foundry Portal
AZURE_AGENT_SUPERVISOR_NAME=Supervisor-Agent
AZURE_AGENT_ORDER_NAME=Order-Agent
AZURE_AGENT_REFUND_NAME=Refund-Agent
AZURE_AGENT_DELIVERY_NAME=Delivery-Agent
AZURE_AGENT_STORE_NAME=Store-Agent
AZURE_AGENT_GENERAL_NAME=General-Assistant-Agent

# ─────────────────────────────────────────────────────────────────────────────
# Speech Services (STT and TTS)
# ─────────────────────────────────────────────────────────────────────────────
AZURE_SPEECH_KEY=your_speech_key
AZURE_SPEECH_REGION=eastus

# ─────────────────────────────────────────────────────────────────────────────
# Azure Communication Services (ACS Telephony)
# ─────────────────────────────────────────────────────────────────────────────
ACS_CONNECTION_STRING=endpoint=https://your-acs.communication.azure.com/;accesskey=your_key
PUBLIC_CALLBACK_URL=https://your-public-tunnel-domain.link
COGNITIVE_SERVICES_ENDPOINT=https://your-cognitive-services-resource.cognitiveservices.azure.com/
CORS_ORIGIN=*
```

### 3. Run Locally

```bash
# Start the FastAPI server using Uvicorn
uvicorn backend.main:app --reload --port 8000
```

1. Open **`http://localhost:8000`** in your browser.
2. The SQLite database is created and seeded automatically in `mock_data/retail_chatbot.db` on first start.

### 4. Telephony Tunneling (Optional for Incoming Phone Calls)

The phone call bot uses Webhooks/Event Grid to receive callback events from Azure. To test this locally, expose port `8000` to a public URL:

```bash
# Using Cloudflared
cloudflared tunnel --url http://localhost:8000

# Or Localtunnel
lt --port 8000
```

Set the generated public HTTPS URL as the `PUBLIC_CALLBACK_URL` in your `.env`, and configure your ACS phone number in the Azure Portal to route incoming calls to `<PUBLIC_CALLBACK_URL>/api/incoming-call`.

---

## API Endpoints

### Core Chat & Voice

*   **`POST /chat`**
    *   Routes message through classification and specialized agent dispatching.
    *   *Payload:* `{ "message": "Where is my order?", "conversation_history": [] }`
    *   *Response:* `{ "reply": "Your order ... is out for delivery", "intent": "delivery", "sources": ["Supervisor-Agent", "Delivery-Agent"], "suggestions": [...] }`
*   **`POST /chat/voice`**
    *   Fast-path endpoint mapping user speech keywords directly to a target agent (skipping classification stages). Reduces latency under 3 seconds.
*   **`POST /voice/transcribe`**
    *   Accepts multipart form-data upload with WAV audio files and returns the text transcript.
*   **`GET /voice/speak`**
    *   Receives `text` query and returns raw `audio/wav` bytes synthesized using the British neural voice.

### Telephony & VoIP Integration

*   **`GET /api/token`**
    *   Generates an ACS identity token for WebRTC calling so the browser client can make direct VoIP calls to the virtual assistant.
*   **`GET /api/call-status`**
    *   Queries active call transcription log and status metrics by `server_call_id`.
*   **`POST /api/incoming-call`**
    *   Receives EventGrid notifications for incoming phone calls and answers the call via ACS.
*   **`POST /api/callback`**
    *   Processes ACS Call Automation events (`CallConnected`, `RecognizeCompleted`, `PlayCompleted`, `CallDisconnected`).

### Database Queries

*   **`GET /customer`**
    *   Fetches the latest profile data for the active demo customer.
*   **`GET /inventory`**
    *   Fetches the active stock list, dietary filters, and details from the SQLite product table.
*   **`POST /api/save_results`**
    *   Saves browser Test Runner results to `mock_data/test_results.json` for validation reports.

---

## Relational SQLite Database Schema

The system initializes a SQLite schema inside `mock_data/retail_chatbot.db` with the following relationships:

1.  **`customer`**: ID, name, email, phone, loyalty tier (Gold/Silver), Nectar points, registered date, and default address.
2.  **`orders`**: Order ID, customer ID (foreign key), status, total, delivery slot, driver name, current delivery stop, total stops, ETA, and live tracking map link.
3.  **`order_items`**: Order ID (foreign key), item name, quantity, and unit price.
4.  **`refunds`**: Order ID (primary/foreign key), refund reason, date requested, amount, processing status, payment method, completed date, and refund reference number.
5.  **`stores`**: ID, name, address, latitude/longitude, store type, telephone, and opening hours.
6.  **`products`**: ID, name, description, unit price, category, subcategory, brand, SKU, aisle location, expiry date, storage guidelines, allergens, nutritional values (calories, fat, protein, carbs), dietary flags (organic, vegan, gluten-free, sugar-free, lactose-free), Nectar rewards, and stock availability flags.
7.  **`product_stock`**: Junction table mapping `product_id` and `store_id` to available stock quantity levels.
8.  **`promotions`**: Offer ID, promo name, category/product qualifiers, coupon codes, expiry date, and priority details.

---

## Mock Data Test Scenarios

The database seeds a default customer (**Jamie Thornton**, Gold loyalty tier) with four order states designed to test edge cases:

| Scenario | Order ID | Status | Key Details |
|---|---|---|---|
| **Delivered / Completed Refund** | `ORD-98741` | `refund_completed` | Milk was spoiled; refund reference `REF-78934` issued to original card. |
| **Active Delivery In Transit** | `ORD-99102` | `in_transit` | In progress delivery slot with driver Maria S.; currently at Stop 4 of 9; ETA details provided. |
| **Completed Collection / Pending Refund** | `ORD-97830` | `refund_processing` | Click & Collect order at Sainsbury's Holborn. Refund reference `REF-20441` processing for mouldy cheese. |
| **Delivered / Nectar Point Refund** | `ORD-96210` | `refund_completed` | Expired orange juice refunded as Nectar Points; reference `REF-19987`. |

---

## Deploying to Vercel

The application is fully compatible with serverless hosting on Vercel. 

1.  Deploy the root directory containing `vercel.json` and the `/api` directory.
2.  FastAPI is served via `api/index.py` which maps the WSGI handler.
3.  **Writeable Database handling:** On serverless environments (detected by `VERCEL` environment variable), the app automatically copies the seeded database to `/tmp/retail_chatbot.db` to ensure address updates, refunds, and test logs can write changes.
