# 📋 Quick Reference Cheat Sheet

A single-page summary of everything important in the project.

---

## What It Is

A Sainsbury's AI customer support assistant with **text chat** and **real-time voice calls**.  
Built with **FastAPI + LangGraph + Azure AI Foundry**.

---

## Key Numbers

| Stat | Value |
|------|-------|
| Number of AI agents | 5 specialist + 1 voice agent |
| Number of API routes | ~15 |
| Target chat response time | < 5 seconds |
| Target voice latency | < 3 seconds |
| Number of LangGraph nodes | 5 |
| Database tables | 8 (customers, orders, order_items, products, stores, deliveries, refunds, promotions) |

---

## What Each Agent Handles

| Agent Name | Handles |
|-----------|---------|
| Order Agent | Order status, payment, Nectar points |
| Delivery Agent | Tracking, driver info, slot changes, address updates |
| Refund Agent | Damaged/missing items, refund processing |
| Store Agent | Hours, locations, stock, allergens, promotions, nutrition |
| General Agent | Everything else (jokes, recipes, general queries) |
| Voice Assistant Agent | Voice calls (Azure Voice Live, Agent Mode) |

---

## The 5 LangGraph Nodes

| Node | Job |
|------|-----|
| `router_node` | Classify intent: greeting, thanks, specialist, or out of scope |
| `context_resolver_node` | Resolve ambiguous follow-ups like "yes", "okay" |
| `specialist_agent_node` | Call the right AI agent with customer context |
| `tool_execution_node` | Run database/search queries the AI requested |
| `validation_node` | Clean formatting + block sensitive data |

---

## Routing Logic (Fast Path)

```
"where is my order"   → "order" keyword → Order Agent
"when will it arrive" → "arrive" keyword → Delivery Agent
"I want a refund"     → "refund" keyword → Refund Agent
"is this in stock"    → "stock" keyword → Store Agent
"hello"               → instant local greeting
"yes / sure / okay"   → context resolver
anything else         → AI intent classifier
```

---

## API Endpoints

| Route | Method | Purpose |
|-------|--------|---------|
| `/` | GET | Serve frontend HTML |
| `/health` | GET | Health check |
| `/customer` | GET | Get customer data |
| `/inventory` | GET | Get inventory data |
| `/chat` | POST | Text chat (streaming or standard) |
| `/chat/voice` | POST | Voice-optimised text path |
| `/api/token` | GET | Issue ACS VOIP token |
| `/api/incoming-call` | POST | Handle phone call from ACS |
| `/api/callback` | POST | ACS call automation events |
| `/api/voice-realtime` | WebSocket | Browser voice ↔ Voice Live |
| `/api/media-stream` | WebSocket | ACS phone ↔ Voice Live |
| `/api/fillers` | GET | Pre-rendered filler audio |

---

## Environment Variables

| Variable | What it's for |
|----------|--------------|
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | AI Foundry project URL |
| `AZURE_AI_FOUNDRY_API_KEY` | AI Foundry API key (fallback) |
| `AZURE_AI_FOUNDRY_DEPLOYMENT_NAME` | Model name (e.g., gpt-5.1) |
| `AZURE_OPENAI_ENDPOINT` | Direct OpenAI endpoint |
| `AZURE_TENANT_ID` | Azure tenant for auth |
| `AZURE_CLIENT_ID` | Service principal client ID |
| `AZURE_CLIENT_SECRET` | Service principal secret |
| `ACS_CONNECTION_STRING` | Azure Communication Services |
| `AZURE_VOICELIVE_ENDPOINT` | Voice Live endpoint |
| `AZURE_AGENT_VOICE_NAME` | Name of the voice agent in Foundry |
| `DB_HOST` | PostgreSQL host (if using Postgres) |

---

## Database (SQLite / PostgreSQL)

```
customers     → name, email, phone, postcode
orders        → customer_id, total, status
order_items   → order_id, product_id, quantity, unit_price
products      → name, category, price, dietary_tags, nutritional info
stores        → name, postcode, opening_hours
deliveries    → order_id, method, driver, slot
refunds       → order_id, amount, reason, status
promotions    → title, discount_percent, valid_until
product_stock → product_id, store_id, quantity
```

---

## Key Files

| File | What to edit when... |
|------|---------------------|
| `backend/main.py` | Adding a new API route |
| `backend/agents/graph.py` | Changing the AI pipeline / adding a new node |
| `backend/agents/intent.py` | Changing how intent is classified |
| `backend/agents/tools.py` | Adding a new database tool for the AI to call |
| `backend/agents/validation.py` | Changing security rules or formatting |
| `backend/agents/foundry_config.py` | Changing Azure AI Foundry settings |
| `backend/services/acs_bot.py` | Changing phone call handling |
| `backend/services/voice_realtime.py` | Changing voice call authentication or tools |
| `backend/services/voice_fillers.py` | Changing the filler phrases |
| `backend/database/database.py` | Adding a new database table or query |
| `frontend/js/app.js` | Changing the UI behaviour |
| `vercel.json` | Changing Vercel deployment routing |
| `.env` | Updating API keys / config |

---

## Authentication Flow

```
Local dev:
  If AZURE_CLIENT_ID + AZURE_CLIENT_SECRET + AZURE_TENANT_ID set → ClientSecretCredential
  Else → AzureCliCredential (requires az login)

Production (Vercel):
  AZURE_CLIENT_ID + AZURE_CLIENT_SECRET + AZURE_TENANT_ID → ClientSecretCredential
  (AzureCliCredential doesn't work in serverless — CLI is not available)
```

---

## Common Terms Explained

| Term | Meaning |
|------|---------|
| **LangGraph** | Workflow manager for AI pipelines |
| **Node** | One step in the LangGraph pipeline |
| **State** | The shared data dictionary passed between nodes |
| **Tool** | A function the AI can call (e.g., `check_stock`) |
| **Intent** | What category of question the user is asking |
| **Specialist Agent** | An AI agent trained for one domain |
| **Agent Mode** | Voice Live lets the Foundry agent own the conversation |
| **VAD** | Voice Activity Detection — knows when you stop speaking |
| **PCM16** | Raw audio format (bytes) used by Voice Live |
| **ACS** | Azure Communication Services (phone/VoIP calls) |
| **PSTN** | Public Switched Telephone Network (regular phone calls) |
| **SSE** | Server-Sent Events — streaming text to the browser |
| **Entra ID** | Microsoft's identity system (replaces Azure AD) |
| **ClientSecretCredential** | Production auth using an app + secret instead of user login |
| **Guardrails** | Rules that block the AI from revealing sensitive data |
