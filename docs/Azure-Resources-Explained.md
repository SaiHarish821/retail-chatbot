# ☁️ Azure Resources — Why We Use Each One

This explains every Azure service in the project and what would happen without it.

---

## 1. Azure AI Foundry (AI Hub + Project)

### What is it?
Azure AI Foundry is Microsoft's platform for hosting AI models and AI agents. Think of it as "a cloud workplace for AI assistants."

### Why do we use it?
- It hosts our **5 specialist AI agents** (Order, Delivery, Refund, Store, General)
- It hosts the **Voice Assistant Agent** for voice calls
- All agent instructions (system prompts) are stored here — not in our code
- You can edit agent behaviour without changing or redeploying code

### How it connects
The backend (`router.py`) connects at startup using `AIProjectClient`. It reads each agent's instructions from the Portal and stores them in memory. When a question comes in, it uses these instructions to set up the correct AI prompt.

```
backend/agents/router.py → AIProjectClient → Azure AI Foundry Portal
```

### What would happen without it?
- No AI agents — the chatbot would only give hardcoded static responses
- No voice assistant — Voice Live requires an agent to operate in agent mode

---

## 2. Azure OpenAI (GPT-5-mini Model Deployment)

### What is it?
Azure OpenAI is the service that actually runs the AI model (GPT-5-mini). Azure AI Foundry wraps around it.

### Why do we use it?
- The model generates all AI responses
- We use the chat completions endpoint for text responses
- The same model endpoint is used for intent classification, context resolution, and specialist agent responses

### How it connects
```
router.py / graph.py → ChatOpenAI (LangChain) → Azure OpenAI endpoint
```

The endpoint format is:
```
https://retail-ai-poc.services.ai.azure.com/api/projects/retail-ai-poc/openai/v1/
```

### What would happen without it?
- No AI responses at all — the entire chat system stops working

---

## 3. Azure AI Search

### What is it?
Azure AI Search is a cloud search service that understands meaning, not just exact keywords. It powers semantic product search.

### Why do we use it?
When a customer asks "Do you have anything gluten-free for breakfast?", Azure AI Search can find gluten-free porridge, cereal, and toast even if none of those exact words were in the query.

Regular SQL `WHERE name LIKE '%gluten-free%'` would miss many products. AI Search uses **vector embeddings** to understand intent.

### How it connects
The `search_products_tool` in `backend/agents/tools.py` calls Azure AI Search when the AI decides it needs to search the product catalogue.

```
graph.py (tool call) → tools.py → Azure AI Search → returns product list
```

### What would happen without it?
- Product search falls back to basic SQL keyword matching
- Results would be less accurate and miss semantic matches

---

## 4. Azure Database (PostgreSQL — Production)

### What is it?
Azure Database for PostgreSQL is a managed cloud database. In local development, SQLite is used instead.

### Why do we use it?
- Stores all customer data, orders, deliveries, refunds, products, stores
- The AI uses this data to give personalised answers
- More reliable, scalable, and concurrent than SQLite in production

### How it connects
`backend/database/database.py` automatically detects whether to use SQLite or PostgreSQL based on environment variables (`DB_HOST`, `DB_NAME`, etc.).

```
tools.py → database.py → PostgreSQL or SQLite → returns real data
```

### What would happen without it?
- No customer data → AI can only give generic answers
- Refund processing, order tracking, stock checks all fail

---

## 5. Azure Communication Services (ACS)

### What is it?
ACS is Microsoft's cloud telephony platform. It enables real-time voice, video, and messaging — including real phone calls.

### Why do we use it?
- Issues **VOIP tokens** so browsers can make internet-based calls
- Manages incoming **real phone calls** to the chatbot's phone number
- Connects phone audio to our backend for processing

### How it connects
```
Browser → GET /api/token → acs_bot.py → ACS → returns token
Real phone call → ACS Event Grid → POST /api/incoming-call → acs_bot.py → answers call
```

### What would happen without it?
- Browser calling doesn't work (no token, no VOIP)
- PSTN phone calls can't be received

---

## 6. Azure Voice Live

### What is it?
Azure Voice Live is a real-time voice-to-voice AI service. It handles the entire speech pipeline: capture speech → transcribe → send to AI → receive AI text → speak it back.

### Why do we use it?
Doing this ourselves would require:
1. A speech-to-text service
2. Sending transcribed text to the AI
3. A text-to-speech service
4. Managing the timing of when to listen vs. speak
5. Handling interruptions ("barge-in")
6. Managing audio buffering

Voice Live does ALL of this in one service, tightly integrated with Azure AI Foundry agents.

### How it connects
```
Browser WebSocket → backend/main.py (/api/voice-realtime) → Voice Live SDK → Voice Live Cloud → Foundry Agent
```

### What would happen without it?
- Voice calls fall back to the browser's local Web Speech API (less accurate, no agent integration)
- All the sophisticated real-time features (barge-in detection, agent mode, Voice Activity Detection) are lost

### ⚠️ Key Constraint
Voice Live in **Agent Mode** requires Entra ID token authentication — API keys are not supported. This is why it works locally (with `az login`) but needs proper Entra credentials in production.

---

## 7. Azure Application Insights (Optional Telemetry)

### What is it?
Application Insights is Azure's monitoring and logging service.

### Why do we use it?
When configured, it automatically captures:
- Every AI request and response
- LangChain / LangGraph execution traces
- Error logs
- Response times

### How it connects
Configured in `main.py` using `configure_azure_monitor()` if `APPLICATIONINSIGHTS_CONNECTION_STRING` env variable is set.

### What would happen without it?
- No cloud monitoring (app still works, just no telemetry)

---

## Summary Table

| Azure Service | Required? | What breaks without it |
|--------------|-----------|----------------------|
| AI Foundry (GPT-5-mini) | ✅ Yes | No AI responses |
| AI Foundry Agents | ✅ Yes | No specialist routing, no voice agent |
| AI Search | ⚠️ Optional | Product search degrades to keyword matching |
| Azure PostgreSQL | ⚠️ Optional | Falls back to SQLite (fine for dev) |
| Azure Communication Services | ⚠️ Optional | No voice/phone calling |
| Azure Voice Live | ⚠️ Optional | Voice falls back to browser speech API |
| Application Insights | ❌ Not required | No cloud monitoring |
