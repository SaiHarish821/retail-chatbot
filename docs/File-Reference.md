# File Reference

This document provides file-by-file documentation of every significant file in the project.

---

## Root Files

### `.env.example`
**Lines:** 70 · **Purpose:** Template for environment variable configuration.

Contains all required Azure service credentials, agent names, and application settings with inline documentation. Copy to `.env` and fill in values. Never commit `.env` to version control.

### `requirements.txt`
**Lines:** 26 · **Purpose:** Python dependency specification.

Key dependencies: FastAPI 0.115.5, Uvicorn, azure-ai-agents 1.1.0, azure-ai-voicelive, azure-identity 1.19.0, azure-cognitiveservices-speech 1.41.1, LangChain, LangGraph, psycopg2-binary, azure-monitor-opentelemetry.

### `vercel.json`
**Lines:** 17 · **Purpose:** Vercel deployment URL rewrite rules.

Routes `/static/(.*)` to frontend assets, API endpoints to the serverless function, and all other paths to `index.html` (SPA fallback).

### `current_agents_backup.json`
**Lines:** 60 · **Purpose:** Snapshot of Azure AI Foundry agent definitions.

Contains the agent names, IDs, model, instructions, and tool definitions for all 7 configured agents. Used as a reference backup — the runtime fetches these dynamically from Azure.

---

## `api/`

### `api/index.py`
**Lines:** 10 · **Purpose:** Vercel serverless entry point.

Adds root and backend directories to `sys.path` for clean imports, then imports and re-exports the FastAPI `app` from `backend.main`. Vercel's runtime expects an `app` variable at this path.

---

## `backend/`

### `backend/main.py`
**Lines:** 792 · **Purpose:** FastAPI application definition and all HTTP/WebSocket route handlers.

**Key Responsibilities:**
- Application initialisation (dotenv, telemetry, CORS, static files)
- Database initialisation and seeding
- `AgentRouter` and `ACSBotManager` singleton creation
- Voice filler pre-rendering at startup
- 13+ route handlers (chat, voice, customer, inventory, ACS webhooks, voice WebSocket)
- SSE streaming implementation for chat responses
- Voice Live WebSocket relay (browser and ACS media stream)

**Critical Functions:**
- `chat_endpoint()` — Main chat handler with streaming support
- `voice_chat_endpoint()` — Ultra-fast voice path
- `voice_realtime_websocket()` — Browser voice-to-voice relay
- `media_stream_websocket()` — ACS media stream relay

### `backend/agents/__init__.py`
**Lines:** 5 · **Purpose:** Package initialiser. Exports `AgentRouter`.

### `backend/agents/router.py`
**Lines:** 325 · **Purpose:** Core orchestration class.

**`AgentRouter` class:**
- `__init__(customer_data)` — Initialises Azure clients, fetches agent instructions
- `_init_clients()` — Creates `AIProjectClient` and `openai_client` with credential
- `_fetch_instructions()` — Lists all agents from Foundry, matches by name, extracts instructions
- `_get_llm()` — Returns `ChatOpenAI` instance with automatic token refresh (300s buffer)
- `handle(message, history, is_voice, stream_queue)` — Entry point: loads data, builds context, invokes LangGraph
- Tool methods: `check_stock()`, `search_products()`, `get_active_promotions()`, `update_customer_address()`, `issue_refund()`

### `backend/agents/graph.py`
**Lines:** 509 · **Purpose:** LangGraph state graph definition and compilation.

**Key Components:**
- `AgentState` TypedDict — State schema for the graph
- `router_node()` — Intent classification (heuristic + LLM)
- `context_resolver_node()` — Ambiguous follow-up resolution
- `specialist_agent_node()` — LLM invocation with tools
- `tool_execution_node()` — Tool call execution
- `validation_node()` — Response validation and sanitisation
- `route_after_router()`, `route_after_context()`, `route_after_specialist()` — Conditional edge functions
- `compiled_graph` — Compiled graph singleton

### `backend/agents/intent.py`
**Lines:** 150 · **Purpose:** Intent classification and context resolution.

**`classify_intent(message, history)` flow:**
1. Check static responses (greetings, thanks)
2. Check heuristic keyword map
3. Fall back to LLM intent classification via Foundry Intent-Classifier agent

**`resolve_context(message, history)` flow:**
1. Send ambiguous message + history to Context-Resolver agent
2. Parse JSON response: `{type: "clarification"|"resolved_query", query: "..."}`
3. Return resolution for routing

### `backend/agents/tools.py`
**Lines:** 645 · **Purpose:** All tool function implementations.

**Functions:**
- `search_products(router, query, category, dietary_filters, sort_by, is_on_promotion, limit)` — Fuzzy product search with scoring, filtering, and sorting
- `check_stock(router, product_name, store_name)` — Store-level inventory check with Haversine proximity
- `get_active_promotions(router)` — Active promotion retrieval from database
- `update_customer_address(router, postcode, line1, city)` — Address update with database persistence
- `issue_refund(router, order_id, reason)` — Refund processing with order validation

**Helper Functions:**
- `_haversine(lat1, lon1, lat2, lon2)` — Distance calculation
- `_postcode_to_coords(postcode)` — London postcode geocoding
- `_get_synonyms(term)` — Synonym resolution
- `_calculate_relevance_score(product, query_tokens)` — Multi-field scoring
- `_get_recommendation_sort_key(product)` — Recommendation ranking

### `backend/agents/validation.py`
**Lines:** 161 · **Purpose:** Response validation and security guardrails.

**Functions:**
- `validate_and_sanitize_response(reply)` — Main validation pipeline
- `check_security_guardrails(reply)` — Sensitive pattern detection
- `run_validation_layer(reply, router)` — Combined validation + product grid injection
- `is_raw_routing_json(text)` — Detect raw routing JSON leakage

**`SENSITIVE_PATTERNS` list:** Environment variable keys, API keys, connection strings, agent IDs, customer IDs, bearer tokens, base64 encoded secrets.

### `backend/agents/foundry_config.py`
**Lines:** 161 · **Purpose:** Centralised Azure AI Foundry configuration.

**`FoundryConfig` (frozen dataclass):** Reads all Foundry-related environment variables and provides validation. Singleton pattern via module-level instantiation.

**`AgentNames` (frozen dataclass):** Maps environment variable names to agent role identifiers.

---

## `backend/database/`

### `backend/database/__init__.py`
**Lines:** 12 · **Purpose:** Package initialiser. Exports `init_db`, `seed_db`, `load_db_customer_data`, `load_db_inventory_data`, `save_db_customer_data`, `get_connection`.

### `backend/database/database.py`
**Lines:** 1051 · **Purpose:** Complete database abstraction layer.

**Key Classes:**
- `DatabaseCursor` — Wraps cursor with SQL dialect translation and retry policy
- `DatabaseConnection` — Wraps connection with pool return for PostgreSQL

**Key Functions:**
- `get_db_type()` — Detect and cache database type (SQLite or PostgreSQL)
- `get_connection()` — Get wrapped database connection (pooled for PostgreSQL)
- `init_db()` — Create 7 tables with `CREATE TABLE IF NOT EXISTS`
- `seed_db(force)` — Seed data from `seed_data.py` with schema migration support
- `check_needs_reseed()` — Check if schema needs migration
- `decorate_product(item)` — Generate deterministic rich metadata for products
- `load_db_inventory_data()` — Load and cache all inventory data
- `load_db_customer_data()` — Load customer with orders, items, refunds
- `save_db_customer_data(data)` — Upsert customer, orders, items, refunds

### `backend/database/seed_data.py`
**Lines:** 6 (66KB) · **Purpose:** Hardcoded seed data as Python dictionaries.

Contains `CUSTOMER_SEED` (1 customer, 4 orders) and `INVENTORY_SEED` (3 stores, 20+ products with full details).

---

## `backend/services/`

### `backend/services/__init__.py`
**Lines:** 5 · **Purpose:** Package initialiser. Exports `ACSBotManager`.

### `backend/services/acs_bot.py`
**Lines:** 155 · **Purpose:** Azure Communication Services call automation.

**`ACSBotManager` class:**
- `__init__()` — Initialises CallAutomationClient and IdentityClient from connection string
- `get_token_for_user()` — Creates new ACS user identity and VOIP token
- `answer_incoming_call(context)` — Answers call with bidirectional media streaming
- `handle_callback_events(events, router)` — Processes CallConnected/CallDisconnected events
- `sanitize_text_for_tts(text)` — Removes HTML/XML tags, markdown, emojis, and internal IDs from TTS text

### `backend/services/voice_realtime.py`
**Lines:** 177 · **Purpose:** Voice Live tool execution and credential resolution.

**Functions:**
- `get_azure_credential()` — Resolves ClientSecretCredential (production) or AzureCliCredential (development)
- `execute_voice_tool(name, arguments, router)` — Dispatches voice tool calls to backend functions
- `strip_markdown(text)` — Removes asterisks for clean voice transcripts

**`REALTIME_TOOLS` list:** 6 tool definitions in OpenAI Realtime API format (search_products, check_stock, get_active_promotions, update_customer_address, issue_refund, transfer_to_human_agent).

### `backend/services/voice_fillers.py`
**Lines:** 125 · **Purpose:** Pre-rendered TTS filler audio system.

**Data:**
- `FILLER_TREES` — 5 escalation sequences of 4 phrases each
- `FILLER_THINKING` — 6 short interjection clips

**Functions:**
- `_synthesize_pcm(text, token, endpoint, voice)` — Render text to base64 PCM16 via Azure TTS REST API
- `render_filler_clips(credential, endpoint, voice)` — Parallel pre-render of all filler clips at startup

---

## `backend/tests/`

### `backend/tests/test_followup.py`
**Lines:** 76 · **Purpose:** Integration tests for context resolution and follow-up handling.

Tests 4 scenarios:
1. Ambiguous confirmation with multiple options
2. Ambiguous confirmation on directions/online
3. Intent classification for acknowledgements
4. Context resolution with single option

---

## `frontend/`

### `frontend/index.html`
**Lines:** 2452 · **Purpose:** Complete Sainsbury's-themed SPA.

Contains inline CSS overrides, full page layout (top bar, header, hero, product grid, footer), chat widget HTML structure, phone call UI overlay, customer sidebar, and script includes.

### `frontend/js/app.js`
**Lines:** 2273 · **Purpose:** All frontend application logic.

**Key Sections:**
- State management (conversation history, recording state, call state)
- Sidebar rendering and customer data fetching
- Event binding (send, voice, phone, suggestions, TTS toggle)
- Chat message sending with SSE streaming
- AI message rendering with markdown and product grid parsing
- Voice recording (push-to-talk with Web Audio API)
- Phone call mode (WebSocket to Voice Live, PCM16 encoding/decoding)
- Voice filler playback system
- Product card rendering from `<product-grid>` XML tags

### `frontend/css/styles.css`
**Lines:** ~900 · **Purpose:** Chat widget styling.

Glassmorphism effects, responsive layout, message bubbles, typing animations, product cards, phone call overlay, and suggestion chips.

### `frontend/js/azure-communication-services.js`
**Lines:** Large (bundled) · **Purpose:** Bundled ACS Web Calling SDK for browser-based WebRTC calls.

### `frontend/js/azure-sdk.js`
**Lines:** Small shim · **Purpose:** Azure SDK utility shim.

---

## `Tools/`

Tool JSON definitions matching the Azure AI Foundry agent tool schemas:

| File | Tool | Key Parameters |
|------|------|---------------|
| `search_products.json` | Product catalog search | query, category, dietary_filters, sort_by |
| `check_stock.json` | Inventory check | product_name, store_name |
| `issue_refund.json` | Refund processing | order_id, reason, amount |
| `update_customer_address.json` | Address update | postcode, new_address |
| `get_active_promotions.json` | Promotions listing | (none) |
