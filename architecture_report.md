# Retail AI Chatbot – Complete Architecture & File Documentation Report

---

## Project Overview

This is a **Sainsbury's-branded retail AI assistant** built as a full-stack Python + vanilla JavaScript application. The backend is a **FastAPI** server that orchestrates multiple **Azure AI Foundry** specialist agents (Order, Delivery, Refund, Store, General, Supervisor) to answer customer queries about groceries, orders, deliveries, and refunds. It also integrates **Azure Communication Services (ACS)** for live phone-call voice interactions. The frontend is a standalone HTML/CSS/JS SPA served directly by FastAPI. Data is persisted in a **SQLite** database (`retail_chatbot.db`) seeded with a simulated Sainsbury's customer, orders, and product inventory. The system supports two distinct paths: a rich **chat path** (multi-agent orchestration through Azure AI Foundry) and an **ultra-low-latency voice path** (direct GPT-4o call, target <3s). The project is deployable locally (uvicorn) or to **Vercel** as a serverless function.

---

## Folder Structure Tree

```
retail-chatbot/
├── .env                             ← All secrets and service configuration
├── .gitignore
├── README.md
├── requirements.txt                 ← Python dependencies (root)
├── vercel.json                      ← Vercel serverless rewrite rules
├── current_agents_backup.json       ← Snapshot of Azure AI Foundry agent configs
├── onboarding_manual.md             ← Developer onboarding guide
├── project_review_guide.md          ← Project review notes
├── test_case.txt                    ← Manual test cases (plaintext)
│
├── api/
│   ├── index.py                     ← Vercel serverless entrypoint (imports FastAPI app)
│   └── requirements.txt             ← Vercel-specific pinned deps
│
├── backend/
│   ├── main.py                      ← FastAPI app, all routes, startup logic
│   ├── agents/
│   │   ├── __init__.py              ← Exports AgentRouter
│   │   ├── router.py                ← Core orchestration: AgentRouter class (1604 lines)
│   │   ├── prompts.py               ← All LLM system prompts (constants + factories)
│   │   ├── tools.py                 ← Tool function implementations bound to AgentRouter
│   │   └── validation.py           ← Response sanitization and guardrail helpers
│   ├── database/
│   │   ├── __init__.py              ← Exports init_db, seed_db, load/save functions
│   │   ├── database.py              ← SQLite schema creation, seeding, read/write ops
│   │   └── seed_data.py             ← Static Python dicts: CUSTOMER_SEED, INVENTORY_SEED
│   ├── services/
│   │   ├── __init__.py              ← Exports transcribe_audio, ACSBotManager
│   │   ├── acs_bot.py               ← ACS phone call management (CallAutomation loop)
│   │   └── voice.py                 ← Azure Speech SDK: STT + TTS functions
│   └── tests/
│       ├── __init__.py
│       ├── test_followup.py         ← Async integration tests for follow-up routing
│       └── test_voice_data.py       ← Voice data utility tests
│
├── frontend/
│   ├── index.html                   ← Full SPA HTML (87KB, all UI in one file)
│   ├── css/
│   │   └── styles.css               ← All UI styles (39KB)
│   ├── js/
│   │   ├── app.js                   ← All frontend logic (1821 lines)
│   │   ├── azure-sdk.js             ← Thin loader for Azure Communication Services SDK
│   │   └── azure-communication-services.js  ← Vendored ACS Web SDK (5.5MB bundle)
│   ├── images/
│   │   └── products/
│   │       └── prd-001.png to prd-004.png, prd-011.png  ← Product images
│   ├── package.json                 ← Frontend dev metadata (minimal, no bundler)
│   ├── package-lock.json
│   ├── test_cases.json              ← Automated test cases for UI test runner
│   └── test_runner.html             ← In-browser automated test runner UI
│
├── mock_data/
│   ├── retail_chatbot.db            ← SQLite database (seeded, 224KB)
│   └── test_results.json            ← Output from automated test runner
│
└── scratch/
    ├── deploy_new_resources.py      ← One-off Azure provisioning script (az CLI)
    └── sync_env_to_vercel.py        ← One-off: pushes .env secrets to Vercel project
```

---

## Section-wise File Breakdown

### `/` (Root)

| File | Purpose |
|------|---------|
| `.env` | All secrets and Azure service config. Contains live credentials — see env var table below. |
| `.gitignore` | Excludes `.venv`, `__pycache__`, `*.db` (local copy), node_modules, etc. |
| `README.md` | Project documentation (setup, deployment, environment variables). |
| `requirements.txt` | Python dependencies for local dev: FastAPI, uvicorn, azure-ai-agents, azure-cognitiveservices-speech, openai, azure-communication-*, etc. |
| `vercel.json` | URL rewrite rules for Vercel deployment. Routes `/static/*` to `/frontend/$1`, API paths to `/api/index`, falls back all other paths to `/frontend/index.html`. |
| `current_agents_backup.json` | Snapshot JSON of Azure AI Foundry agent definitions (name, ID, model, instructions, tools). Reference artifact only — NOT loaded by code at runtime. |
| `onboarding_manual.md` | Step-by-step setup guide for new developers. |
| `project_review_guide.md` | Review notes and project evaluation criteria. |
| `test_case.txt` | Large plaintext file listing manual test cases to validate chatbot behavior. Not loaded by code. |

---

### `/api/`

| File | Purpose |
|------|---------|
| `index.py` | Vercel serverless entrypoint. Adds `root_dir` and `root_dir/backend` to `sys.path`, then imports the FastAPI `app` object from `backend.main`. Vercel invokes this as a Python serverless function handler. |
| `requirements.txt` | Vercel-specific (pinned) dependency list. Separate from root `requirements.txt` because Vercel reads this from the `/api/` directory at build time. |

---

### `/backend/`

#### `main.py` — FastAPI Application Entry Point

The central server file. At startup it:
1. Calls `dotenv.load_dotenv()` to pull in `.env` variables.
2. Initialises the SQLite database (`init_db()`, `seed_db()`).
3. Loads customer data (`load_db_customer_data()`) into a `CUSTOMER_DATA` dict.
4. Instantiates an `AgentRouter` singleton with `CUSTOMER_DATA`.
5. Instantiates an `ACSBotManager` singleton.
6. Mounts `/static` → serves the `frontend/` directory.

**Route summary:**

| Route | Method | Handler | Purpose |
|-------|--------|---------|---------|
| `/` | GET | `serve_frontend` | Returns `frontend/index.html` |
| `/health` | GET | `health` | Health check |
| `/customer` | GET | `get_customer` | Reloads + returns full customer dict from DB |
| `/inventory` | GET | `get_inventory` | Returns full inventory dict from DB |
| `/chat` | POST | `chat` | Main chat endpoint; delegates to `agent_router.handle()` |
| `/chat/voice` | POST | `chat_voice` | Same as `/chat` but forces `is_voice=True` |
| `/api/save_results` | POST | `save_results` | Saves test runner results to `mock_data/test_results.json` |
| `/voice/transcribe` | POST | `voice_transcribe` | Accepts WAV upload → returns transcript via Azure Speech STT |
| `/voice/speak` | GET | `voice_speak` | Synthesizes text → returns WAV bytes via Azure TTS |
| `/api/token` | GET | `get_token` | Issues ACS VOIP token for browser WebRTC calls |
| `/api/call-status` | GET | `get_call_status` | Returns live call state (transcript, AI reply, status) |
| `/api/incoming-call` | POST | `incoming_call` | ACS EventGrid webhook for incoming calls |
| `/api/callback` | POST | `call_callback` | ACS Call Automation event callback (speech events, call state) |

---

#### `/backend/agents/`

##### `router.py` — `AgentRouter` class (1604 lines) — Core Orchestrator

The most complex file in the project. `AgentRouter` is a singleton that:

**Initialization (`__init__`):**
- Builds a `context` string from customer data via `build_context_block()`.
- `_init_clients()`: sets up `AzureOpenAI`/`AsyncAzureOpenAI` (key-based, lowest latency) or falls back to `AIProjectClient` (credential-based via `AzureCliCredential`/`DefaultAzureCredential`).
- `_resolve_agent_ids()`: calls `agents_client.list_agents()` on Azure AI Foundry, builds `{role: asst_*_id}` map from `.env` agent names.
- Defines `_tools_order`, `_tools_delivery`, `_tools_refund`, `_tools_store` — JSON tool schemas passed to Foundry runs.

**Domain/Intent Classification pipeline (chat path only):**
- `_classify_domain()`: returns `"retail"` or `"general"`. Priority: keyword match on `_RETAIL_KEYWORDS` → keyword match on `_GENERAL_KEYWORDS` → LLM call (`max_tokens=5`). LLM bypassed for voice.
- `_classify_intent()`: returns `"new_retail"`, `"new_general"`, `"follow_up"`, or `"clarification_confirmation"`. Uses last-5-turn history + LLM fallback.
- `_is_out_of_context()`: LLM guardrail call with `GUARDRAIL_SYSTEM_PROMPT`; returns `True` if `BLOCKED`.

**Routing logic:**
- `_get_direct_routing_tasks()`: keyword-only fast path; returns `[{agent, task_query}]` only if exactly ONE agent type keyword matches and no conjunction words (`and`, `also`, `then`, etc.) are present.
- `_decompose_via_supervisor()`: calls Supervisor-Agent on Foundry (or direct LLM fallback) to produce routing JSON: `[{"agent": "delivery", "task_query": "..."}]`.
- `_classify_fallback()`: pure keyword fallback for voice and error scenarios.

**Agent invocation:**
- `_call_foundry_agent()`: creates a Foundry thread, injects customer context as first user message, replays last 4 history turns, appends task query, creates a run, polls with exponential backoff (0.1s→0.4s), handles `requires_action` (tool calls), returns final assistant text.
- `call_agent()` (inner async function in `handle()`): calls `_call_foundry_agent()` or falls back to direct OpenAI API with tool use.
- Multiple agents run **in parallel** via `asyncio.gather()`.

**Voice path (`is_voice=True`):**
- Skips all LLM classification. Uses `_classify_fallback()` + direct `AsyncAzureOpenAI` call (`max_tokens=60`, `temperature=0.0`). Hard token cap forces short TTS-friendly answers. Target <3s end-to-end.

**Key frozensets:**
- `_RETAIL_KEYWORDS` — 80+ tokens triggering retail domain classification.
- `_GENERAL_KEYWORDS` — triggers general/off-topic classification.
- `_ACKNOWLEDGEMENTS` — triggers `clarification_confirmation` intent locally (no LLM).
- `_DIRECT_ROUTING_KEYWORDS` — maps `{agent_type: [keywords]}` for single-agent fast routing.
- `_PRODUCT_INFO_SIGNALS` — triggers DB-first product lookup for nutrition/allergen questions.

**Other key methods:**
- `_resolve_context()`: resolves ambiguous follow-ups via LLM, returns `{type: "clarification", response}` or `{type: "resolved_query", query}`.
- `_merge_replies()`: for multi-agent responses, calls Supervisor-Agent (or direct LLM) to merge into a single reply.
- `_generate_suggestions()`: generates 3–5 LLM-driven follow-up suggestions shown as chips in UI.
- `_search_db_for_product_question()`: if message contains nutrition/allergen signals AND a known product name, queries local DB and returns a product card — bypasses Foundry entirely.
- `_execute_tool()`: dispatches Foundry `requires_action` tool calls to local Python implementations.

##### `prompts.py` — All LLM Prompts

Pure constants and factory functions. No side effects.

| Export | Type | Used By | Purpose |
|--------|------|---------|---------|
| `CLASSIFY_DOMAIN_SYSTEM_PROMPT` | str | `_classify_domain()` | Forces `retail`/`general` single-word output |
| `CLASSIFY_INTENT_SYSTEM_PROMPT` | str | `_classify_intent()` | Forces `follow_up`/`clarification_confirmation`/`new_retail`/`new_general` |
| `get_context_resolver_prompt()` | factory | `_resolve_context()` | Dynamic prompt injecting last assistant response; forces JSON output |
| `SUPERVISOR_ROUTING_PROMPT` | str | `_decompose_via_supervisor()` | Decomposes message into `[{agent, task_query}]` JSON |
| `SUPERVISOR_MERGE_PROMPT` | str | `_merge_replies()` | Instructs merger of specialist agent replies |
| `SUGGESTIONS_SYSTEM_PROMPT` | str | `_generate_suggestions()` | Forces JSON array of 3–5 follow-up suggestions |
| `get_voice_system_prompt()` | factory | `_call_voice_openai()` | Injects customer name, orders, voice rules (1–2 sentences, no markdown) |
| `GUARDRAIL_SYSTEM_PROMPT` | str | `_is_out_of_context()` | Forces `ALLOWED`/`BLOCKED` output |
| `CHAT_DECLINE_MESSAGE` | str | `handle()` | Standard out-of-context chat reply |
| `VOICE_DECLINE_MESSAGE` | str | `handle()` | Short out-of-context voice reply |

##### `tools.py` — Database Tool Functions

Module-level functions **bound as instance methods** onto `AgentRouter` via class-body assignment (`check_stock = check_stock`). All accept `self` to access `self._load_customer_data()`, `self._load_inventory_data()`, `self._save_customer_data()`.

| Function | Purpose |
|----------|---------|
| `geocode_postcode()` | Maps UK postcode prefixes to hardcoded lat/lng coordinates (London-only lookup table). Returns London center as fallback. |
| `haversine_distance()` | Great-circle distance in miles between two lat/lng points. Used to sort stores by proximity to customer. |
| `build_context_block()` | Serializes customer + orders + store data into a compact text block injected into every Foundry thread as a user message (not a system prompt override). |
| `clean_name_for_matching()` | Strips volume/weight suffixes (e.g., "2L", "800g") from product names for fuzzy matching. |
| `check_stock()` | Queries inventory DB by product name + optional store filter. Sorts results by distance. Returns formatted multi-store stock report. |
| `search_products()` | Full catalog search with scoring, synonym expansion, dietary filters, sorting, and UI product-grid JSON embedding. Returns text + `<product-grid>` XML blob. |
| `get_active_promotions()` | Queries `promotions` table via raw SQLite, formats discount offers with coupon codes. |
| `update_customer_address()` | Updates `customer.default_address` in SQLite. |
| `issue_refund()` | Finds order by ID, appends refund dict with generated reference (REF-XXXXX), sets status to `refund_completed`, saves to DB. |
| `append_product_grid_if_mentioned()` | Scans agent reply text for product name mentions using word-boundary regex; appends `<product-grid>` JSON blob (max 3 cards). |

##### `validation.py` — Response Sanitization

| Function | Purpose |
|----------|---------|
| `validate_and_sanitize_response()` | Line-by-line cleanup: removes `---`/`===` rules, strips `#` headers, converts `* `/`- ` bullets to `•`, converts markdown links to plain text, masks `CUST-*` and `STR-*` internal IDs. |
| `run_validation_layer()` | Async wrapper that detects and logs formatting violations (markdown, raw quantities, exposed IDs), then calls `validate_and_sanitize_response()`. |
| `is_raw_routing_json()` | Detects if an agent accidentally returned routing JSON `[{"agent":...}]` instead of a customer reply. Used to trigger fallback. |

---

#### `/backend/database/`

##### `database.py` — SQLite ORM Layer (822 lines)

**DB path logic:** Uses `mock_data/retail_chatbot.db` locally; copies to `/tmp/retail_chatbot.db` on Vercel/Lambda (read-only filesystem workaround).

**Schema — 8 tables:**
- `customer` — single customer record (id, name, email, phone, loyalty_tier, loyalty_points, address fields)
- `orders` — order records with denormalized delivery fields
- `order_items` — line items per order
- `refunds` — refund records linked to orders
- `stores` — store metadata (name, address, lat/lng, hours, type)
- `products` — 44-column product catalog with nutritional info, dietary flags, discount JSON, ratings
- `product_stock` — join table: `(product_id, store_id) → quantity`
- `promotions` — active discount offers with coupon codes

| Function | Purpose |
|----------|---------|
| `get_connection()` | Returns `sqlite3.connect(DB_PATH)`. |
| `init_db()` | Creates all tables with `CREATE TABLE IF NOT EXISTS`. |
| `decorate_product()` | Deterministically computes rating, reviews, popularity, best_seller, dietary flags, and discount from product's MD5 hash. Reproducible — no randomness on re-seed. |
| `check_needs_reseed()` | Checks if `promotions` table and `customer_rating` column exist; returns `True` if schema is stale. |
| `seed_db()` | Drops and recreates tables if stale. Inserts CUSTOMER_SEED (customer, orders, items, refunds), INVENTORY_SEED (stores, products, stock), and 5 hardcoded promotions. |
| `load_db_inventory_data()` | Joins `stores`, `products`, `product_stock` tables into a rich Python dict. Returns `{metadata: {stores}, inventory: [...]}`. |
| `load_db_customer_data()` | Joins `customer`, `orders`, `order_items`, `refunds` into a nested Python dict. Returns `{customer: {...}, orders: [...]}`. |
| `save_db_customer_data()` | Upserts customer + orders using `ON CONFLICT DO UPDATE`. Rewrites order items (DELETE + INSERT). Upserts refunds. |

##### `seed_data.py` (66KB) — Static Seed Dictionaries

Contains two massive Python dicts:
- `CUSTOMER_SEED` — simulated customer with multiple orders (delivered, in_transit, refund states), order items, refund records, and delivery tracking metadata.
- `INVENTORY_SEED` — simulated product catalog (15+ products across Dairy, Bakery, Produce, Pantry, Drinks, Fresh Meat & Fish), with nutritional info, allergens, certifications, store stock levels per store ID.

This is the **source of truth** for all product and customer demo data.

---

#### `/backend/services/`

##### `acs_bot.py` — Azure Communication Services Phone Call Manager

`ACSBotManager` manages a stateful phone call lifecycle using Azure's **Call Automation API**:

- `__init__()`: initialises `CallAutomationClient` and `CommunicationIdentityClient` from `ACS_CONNECTION_STRING`. Loads or auto-generates a persistent bot identity.
- `get_token_for_user()`: creates a new ACS user + VOIP token for browser WebRTC (used by `/api/token`).
- `answer_incoming_call()`: answers an incoming ACS call, pointing callbacks to `/api/callback`.
- `handle_callback_events()`: the main call event loop. Processes:
  - `CallConnected` → plays greeting, starts speech recognition.
  - `RecognizeCompleted` → gets `speechResult.speech`, calls `agent_router.handle(is_voice=True)`, sanitizes reply via `sanitize_text_for_tts()`, calls `_speak_and_recognize()`.
  - `RecognizeFailed` → reprompts.
  - `PlayCompleted`/`PlayFailed` → sets status to `LISTENING`.
  - `CallDisconnected` → marks call `DISCONNECTED`.
- `_speak_and_recognize()`: uses `start_recognizing_media()` with `TextSource(voice_name="en-GB-SoniaNeural")` to simultaneously play TTS and listen for barge-in speech.
- `sanitize_text_for_tts()`: strips product-grid XML, HTML tags, markdown, emojis, and normalizes whitespace before sending to TTS engine.

`active_calls` dict stores per-call state: `{server_call_id: {user_transcript, ai_response, status, history, intent, suggestions}}`.

##### `voice.py` — Azure Speech SDK STT + TTS

Used by `/voice/transcribe` and `/voice/speak` browser-based routes (NOT the phone call path — those use ACS Call Automation's built-in recognition).

| Function | Purpose |
|----------|---------|
| `transcribe_audio(file_path)` | Async wrapper; runs blocking Azure Speech SDK STT in thread pool. Uses `en-GB`. Returns text string. |
| `_transcribe_sync()` | Blocking SDK call using `SpeechRecognizer.recognize_once_async()`. |
| `synthesize_speech(text)` | Async wrapper; runs blocking Azure TTS in thread pool. Uses `en-GB-SoniaNeural`. |
| `_synthesize_sync()` | Blocking SDK call; returns `result.audio_data` (WAV bytes). `audio_config=None` forces in-memory synthesis. |

---

#### `/backend/tests/`

| File | Purpose |
|------|---------|
| `test_followup.py` | 4 async integration test scenarios: ambiguous confirmation on multiple options, context resolver with yes/no questions, intent classification of acknowledgements, context resolution for single-option follow-ups. Uses raw `asyncio.run()` + manual assertions — no pytest. |
| `test_voice_data.py` | Uncertain based on code (not fully reviewed). Appears to test voice data pipeline utilities. |

---

### `/frontend/`

##### `index.html` (87KB) — Monolithic SPA

Single-file HTML containing ALL UI markup:
- Left sidebar: customer profile, loyalty tier, order pills, quick action buttons.
- Chat panel: message bubbles, product grid cards, suggestion chips, welcome card.
- Voice recording UI (browser mic + waveform visualizer).
- Phone call modal: dial pad overlay, call status panel, mute/speaker controls.
- Test runner toggle (hidden in production).

All component HTML is inline — no templating engine.

##### `css/styles.css` (39KB)

All visual styles for the SPA:
- CSS custom properties (`--primary`, `--surface`, etc.) for theming.
- Responsive layout (sidebar + chat panel).
- Product card styles, suggestion chip animations.
- Phone call modal, dial pad, status indicators.
- Waveform animation for voice recording.
- Order pill status badges.

##### `js/app.js` (1821 lines) — Frontend Logic

| Section | Purpose |
|---------|---------|
| State vars | `conversationHistory`, `isRecording`, `callState`, `isInCallMode`, etc. — manages all UI state. |
| `DOMContentLoaded` | Fetches customer data, binds events, focuses chat input. |
| `renderSidebar()`, `fetchCustomerData()` | Displays customer profile and order pills. Clicking a pill sends "What is the status of order X?" to chat. |
| `sendMessage()`, `appendMessage()` | POSTs to `/chat`, renders bot reply with markdown-to-HTML conversion and product grid card parsing. |
| `startRecording()`, `stopRecording()` | Uses `AudioContext`/`ScriptProcessorNode` for 2.5s silence detection; encodes WAV; POSTs to `/voice/transcribe`; sends transcript to `/chat/voice`. Optionally plays TTS via `/voice/speak`. |
| Phone call mode | Uses browser `SpeechRecognition` + `SpeechSynthesis` (or Azure Neural via `/voice/speak`). Polls `/api/call-status` for live transcript/status updates. |
| `renderProductGrid()` | Parses `<product-grid>JSON</product-grid>` blob from reply text; renders visual product cards with image, price, rating, availability badge. |
| `runTestSuite()` | Loads `test_cases.json`, runs each case against `/chat`, evaluates pass/fail by checking expected intent and keyword presence, POSTs results to `/api/save_results`. |

##### `js/azure-sdk.js` (263 bytes)

Thin loader that attaches the ACS SDK to `window.AzureCommunicationCalling`. Ensures global availability before `app.js` references it.

##### `js/azure-communication-services.js` (5.5MB)

Vendored, minified Azure Communication Services Web SDK bundle. Static asset — not authored code.

##### `test_runner.html` (16KB)

Standalone in-browser test runner UI. Loads `test_cases.json`, renders a test table, shows pass/fail badges and expected vs. actual responses. POSTs results to `/api/save_results`.

##### `test_cases.json` (16KB)

JSON array of test case objects: each has `id`, `category`, `user_message`, `expected_intent`, `expected_keywords`, and optional `conversation_history`. Used by both `test_runner.html` and `app.js` test mode.

##### `frontend/images/products/`

5 product images (`prd-001.png` to `prd-004.png`, `prd-011.png`) referenced by product ID in product grid cards. Missing images for most catalog products — UI silently falls back.

---

### `/mock_data/`

| File | Purpose |
|------|---------|
| `retail_chatbot.db` | The SQLite database. **Committed to the repo** as a pre-seeded binary (224KB). Also doubles as the Vercel source DB (copied to `/tmp` at cold start). |
| `test_results.json` | Output of the test runner (stats + per-test results). Overwritten on each test run. Committed to source control — no `.gitignore` entry for it. |

---

### `/scratch/`

| File | Purpose |
|------|---------|
| `deploy_new_resources.py` | One-off provisioning script using `subprocess` + Azure CLI (`az` commands). Creates Speech resource, ACS resource, OpenAI deployment, AI Foundry hub + project, and agents. Not part of application runtime. |
| `sync_env_to_vercel.py` | Reads `.env` file, POSTs each key-value to Vercel API (`api.vercel.com/v9/projects/.../env`). One-off DevOps utility. |

---

## Environment Variables (`.env`) Reference

| Variable | Service | Purpose |
|----------|---------|---------|
| `AZURE_AI_FOUNDRY_API_KEY` | Azure AI Foundry | API key for direct AzureOpenAI client (lowest latency path) |
| `AZURE_TENANT_ID` | Azure AD | Ensures AzureCliCredential targets the correct corporate tenant |
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | Azure AI Foundry | AgentsClient endpoint (`eastus2.api.azureml.ms/agents/...`) |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI | Direct OpenAI API endpoint (`cognitiveservices.azure.com/openai/v1`) |
| `AZURE_AI_FOUNDRY_DEPLOYMENT_NAME` | Azure OpenAI | GPT-4o deployment name used for all LLM calls |
| `AZURE_AGENT_ORDER_NAME` | Azure AI Foundry | Display name of the Order Agent in the Foundry portal |
| `AZURE_AGENT_REFUND_NAME` | Azure AI Foundry | Display name of the Refund Agent |
| `AZURE_AGENT_DELIVERY_NAME` | Azure AI Foundry | Display name of the Delivery Agent |
| `AZURE_AGENT_STORE_NAME` | Azure AI Foundry | Display name of the Store Agent |
| `AZURE_AGENT_SUPERVISOR_NAME` | Azure AI Foundry | Display name of the Supervisor Agent |
| `AZURE_AGENT_GENERAL_NAME` | Azure AI Foundry | Display name of the General Assistant Agent |
| `AZURE_SPEECH_KEY` | Azure Cognitive Services | STT/TTS API key (browser voice path) |
| `AZURE_SPEECH_REGION` | Azure Cognitive Services | Region for Speech SDK (e.g., `eastus`) |
| `CORS_ORIGIN` | FastAPI | CORS allowed origin (`*` for dev) |
| `ACS_CONNECTION_STRING` | Azure Communication Services | Connection string for call automation and identity management |
| `PUBLIC_CALLBACK_URL` | ACS | Publicly accessible URL for ACS to POST call events to (e.g., ngrok/pinggy tunnel in dev) |
| `COGNITIVE_SERVICES_ENDPOINT` | Azure | Cognitive Services endpoint used by ACS Call Automation for speech recognition |

---

## System Architecture Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                               BROWSER (User)                                        │
│  ┌──────────────────┐   ┌──────────────────────┐   ┌────────────────────────────┐  │
│  │   Chat UI        │   │   Browser Voice UI   │   │   Phone Call Modal (ACS)   │  │
│  │  (app.js)        │   │  (Mic + AudioContext) │   │   (WebRTC / SpeechRecog)   │  │
│  └────────┬─────────┘   └──────────┬───────────┘   └────────────────────────────┘  │
│           │ POST /chat              │ POST /voice/transcribe                         │
└───────────┼─────────────────────────┼──────────────────────────────────────────────┘
            │                         │
            ▼                         ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                      FastAPI Backend (backend/main.py)                              │
│   /chat → AgentRouter.handle()        /voice/transcribe → voice.transcribe_audio()  │
│   /customer → load_db_customer_data() /voice/speak → voice.synthesize_speech()      │
│   /inventory → load_db_inventory_data()                                             │
│   /api/token → ACSBotManager.get_token_for_user()                                  │
│   /api/incoming-call → ACSBotManager.answer_incoming_call()                        │
│   /api/callback → ACSBotManager.handle_callback_events()                           │
└──────────┬──────────────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         AgentRouter (agents/router.py)                              │
│                                                                                     │
│  1. Greeting short-circuit (no LLM)                                                 │
│  2. Guardrail check (ALLOWED/BLOCKED via GPT-4o, 5 tokens)                         │
│                                                                                     │
│  ┌── VOICE PATH (is_voice=True) ───────────────────────────────────────────────┐   │
│  │  Keyword classify → AsyncAzureOpenAI (max_tokens=60) → return reply          │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
│                                                                                     │
│  ┌── CHAT PATH ────────────────────────────────────────────────────────────────┐   │
│  │  Intent Classify (LLM, 10 tokens)                                            │   │
│  │  → Domain Classify (keyword first, LLM fallback, 5 tokens)                  │   │
│  │  → Product DB lookup (direct SQL, no LLM)                                   │   │
│  │  → Direct keyword routing OR Supervisor decomposition (JSON)                 │   │
│  │  → Parallel Foundry Agent calls (asyncio.gather)                             │   │
│  │  → Merge replies (Supervisor or LLM)                                         │   │
│  │  → Validate/Sanitize → Append product-grid → Generate suggestions            │   │
│  └─────────────────────────────────────────────────────────────────────────────┘   │
└──────────┬─────────────────────────────────────────────────────────────────────────┘
           │
    ┌──────┴──────────────────────────────────────────────┐
    ▼                                                      ▼
┌────────────────────────────────┐       ┌────────────────────────────────────────┐
│  Azure AI Foundry              │       │  SQLite DB (retail_chatbot.db)         │
│  (azure.ai.agents SDK)         │       │  customer, orders, order_items         │
│  Supervisor-Agent              │       │  refunds, stores, products             │
│  Order-Agent                   │       │  product_stock, promotions             │
│  Delivery-Agent                │       └────────────────────────────────────────┘
│  Refund-Agent                  │
│  Store-Agent                   │
│  General-Agent                 │
└────────────────────────────────┘
           │ requires_action (tool calls)
           ▼
    tools.py: check_stock, search_products, get_active_promotions,
              issue_refund, update_customer_address
           │
           ▼
    SQLite DB (read/write)
```

---

## Execution Flow — Step-by-Step Request Lifecycle

### Chat Request (Typed Message)

1. **Browser**: User types "Where is my order ORD-99102?" → `sendMessage()` appends to `conversationHistory`, POSTs `{message, conversation_history, is_voice:false}` to `POST /chat`.
2. **`main.py`**: calls `agent_router.handle(message, history, is_voice=False)`.
3. **`AgentRouter.handle()`**:
   - Greeting short-circuit? No.
   - Refreshes `customer_data` from DB.
   - Guardrail: GPT-4o call → `ALLOWED`.
   - `_classify_intent()`: no prior history → `_classify_domain()` → "order" keyword found → `"retail"` → `"new_retail"`.
   - `_search_db_for_product_question()`: no nutrition signals → `None`.
   - `_get_direct_routing_tasks()`: "order" matched once, no conjunctions → `[{agent:"order", task_query:"..."}]`.
   - `call_agent({agent:"order"})`: Foundry order agent found → `_call_foundry_agent()` → creates thread, injects context, creates run, polls, run completes → returns order details text.
   - `_run_validation_layer()`: sanitizes reply.
   - `append_product_grid_if_mentioned()`: no product names → no grid appended.
   - `_generate_suggestions()`: GPT-4o call → 3–5 contextual follow-ups.
4. **`main.py`**: returns `ChatResponse(reply, intent="order", sources=["order_agent"], suggestions=[...])`.
5. **`app.js`**: appends bot bubble, parses `<product-grid>` if present, renders suggestion chips.

### Voice Request (Browser Mic)

1. User clicks mic button → `startRecording()` opens `AudioContext`, buffers PCM.
2. 2.5s silence detection → `stopRecording()` encodes WAV, POSTs to `/voice/transcribe`.
3. **`main.py`**: writes WAV to `/tmp`, calls `transcribe_audio()` → Azure Speech SDK STT → returns transcript.
4. `app.js` sends transcript to `POST /chat/voice` (forces `is_voice=True`).
5. **`AgentRouter.handle(is_voice=True)`**: keyword classify → `_call_voice_openai()` → `AsyncAzureOpenAI(max_tokens=60)` → short reply.
6. If TTS enabled: `app.js` calls `GET /voice/speak?text=...` → Azure TTS → WAV → plays in browser `<audio>` element.

### Phone Call (ACS Call Automation)

1. User clicks "Start Call" → `GET /api/token` → ACS issues VOIP token + bot identity.
2. Browser places WebRTC call to bot identity via ACS infrastructure.
3. ACS fires `POST /api/incoming-call` → `answer_incoming_call()` → call answered, callback pointed to `PUBLIC_CALLBACK_URL/api/callback`.
4. `POST /api/callback` receives `CallConnected` → plays greeting via `_speak_and_recognize()` (TTS + speech recognition simultaneously, barge-in enabled).
5. User speaks → ACS fires `RecognizeCompleted` with `speechResult.speech`.
6. `handle_callback_events()` calls `agent_router.handle(message=speech_text, is_voice=True)`.
7. Reply sanitized via `sanitize_text_for_tts()` → `_speak_and_recognize()` → loop continues until `CallDisconnected`.

---

## Key Design Decisions

1. **Dual execution path (voice vs. chat):** Voice uses keyword routing + direct GPT-4o (60-token cap) to target <3s. Chat uses full multi-LLM pipeline for richer responses. This avoids sacrificing chat quality for voice speed.

2. **Supervisor-worker multi-agent pattern:** A single query can be split across e.g. Delivery-Agent + Refund-Agent in parallel (`asyncio.gather()`). Supervisor-Agent decomposes and re-merges. This maps cleanly to Sainsbury's operational domain boundaries.

3. **Keyword-first, LLM-fallback classifiers:** Every classifier tries keyword matching before an LLM API call. Reduces latency and cost for common unambiguous queries.

4. **Context injection via user message (not system override):** Customer data is injected as a user message into each Foundry thread. Explicitly documented in `build_context_block()` as an Azure AI Foundry architectural constraint (system prompt cannot be overridden per-run).

5. **`<product-grid>` XML protocol:** Tool functions embed `<product-grid>JSON</product-grid>` in reply text. Frontend parses and renders visual product cards. This allows text-only Foundry agents to pass structured UI data to the browser.

6. **Deterministic product decoration:** `decorate_product()` uses MD5 hash of product ID to compute reproducible ratings, reviews, and flags. Avoids randomness on re-seed; consistent demo data across environments.

7. **Serverless compatibility:** DB path switches to `/tmp/` on Vercel/Lambda. Pre-seeded `retail_chatbot.db` is committed to repo so cold starts can copy it without re-seeding from scratch.

8. **Guardrail before routing:** `_is_out_of_context()` fires before any specialist agent, blocking general-knowledge queries early and avoiding wasted Foundry API calls.

---

## Problems / Risks / Improvements

### Critical Risks

| Issue | Detail |
|-------|--------|
| **Live API keys in `.env` visible in repo** | `AZURE_AI_FOUNDRY_API_KEY`, `AZURE_SPEECH_KEY`, `ACS_CONNECTION_STRING` contain live credentials in `.env`. Even if gitignored, they are exposed in this analysis context. These must be rotated immediately and stored in a secrets manager. |
| **Single customer, no authentication** | The entire system serves one hardcoded customer from `CUSTOMER_SEED`. There is no auth, session isolation, or multi-user support. Any browser accessing the deployed URL gets the same customer's data. A production privacy violation. |
| **SQLite writes lost on Vercel cold start** | Vercel serverless is stateless. Writes (refunds, address changes) go to `/tmp` (ephemeral). On next cold start the DB is re-copied from the committed binary, losing all mutations. Not suitable for production persistence. |

### Architecture Issues

| Issue | Detail |
|-------|--------|
| **`router.py` is 1604 lines, violates SRP** | Does domain classification, intent classification, context resolution, Foundry orchestration, tool dispatch, voice routing, suggestions, AND product DB lookup. Should be split into `classifier.py`, `orchestrator.py`, `voice_handler.py`. |
| **Polling-based Foundry run** | `_call_foundry_agent()` polls in a `while` loop with `asyncio.sleep()`. Azure AI Agents SDK supports event streaming which would eliminate polling and reduce latency by ~0.5–1s. |
| **Up to 5 LLM calls per chat message** | Guardrail + intent + domain + Supervisor decomposition + suggestions = potentially 5 sequential/parallel LLM calls. The suggestions call in particular adds latency for low-value UI chips. |
| **`_RETAIL_KEYWORDS` / `_GENERAL_KEYWORDS` are brittle** | 80+ hardcoded keyword strings fail on paraphrases, typos, Hinglish, and non-English. The LLM fallback exists but the keyword-first approach can misroute on edge cases. |
| **`geocode_postcode()` is London-only** | Hardcoded prefix→coordinates map for ~12 London postcodes. All other UK postcodes fall back to London center. Store distance calculations are incorrect for non-London customers. |

### Code Quality Issues

| Issue | Detail |
|-------|--------|
| **Tool functions bound as instance methods via class-body assignment** | `check_stock = check_stock` at class level is non-idiomatic Python and breaks IDE type checking. |
| **`test_voice_data.py` not fully reviewed** | Uncertain of complete purpose based on partial code inspection. |
| **`current_agents_backup.json` in repo root** | Not referenced by any code. Operational artifact that should live in `scratch/` or `docs/`. |
| **`mock_data/test_results.json` committed** | Test output committed to source control creates noisy diffs. Should be `.gitignore`d. |
| **Product images only for 5 of 15+ products** | Missing images (`prd-005` through `prd-011` except `prd-011`) cause broken image icons in product cards. |
| **`test_followup.py` uses raw `asyncio.run()` + manual assertions** | No pytest framework. Failures produce bare stack traces instead of structured test reports. |
| **Two separate STT pipelines** | Browser voice uses Azure Speech SDK (`voice.py`). Phone call uses ACS Call Automation built-in recognition (`acs_bot.py`). Intentional but not documented — could confuse maintainers. |

### Cleanup Suggestions

1. Add `mock_data/test_results.json` and `__pycache__/` patterns to `.gitignore`.
2. Move `current_agents_backup.json` to `scratch/` or `docs/`.
3. Remove `frontend/node_modules/` if no build step is in use.
4. Add product images for all catalog product IDs or add CSS `onerror` fallback for missing images.
5. Extract `router.py` into focused modules: `classifier.py`, `orchestrator.py`, `voice_handler.py`.
6. Add pytest + `conftest.py` for proper test isolation and reporting.
7. Replace polling in `_call_foundry_agent()` with Azure AI Agents SDK streaming when available.
8. For production: replace SQLite with PostgreSQL, add proper user authentication and session management, and rotate all secrets into Azure Key Vault.
