# Sainsbury's Retail AI Assistant – 1-Day POC

A fully working retail chatbot POC built with **FastAPI**, **Azure AI Foundry**, **GPT-4o**, and vanilla HTML/CSS/JS.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.11+) |
| AI Model | GPT-4o via Azure AI Foundry (Azure OpenAI endpoint) |
| Agents | Azure AI Foundry Agents (pre-created, connected via ID) |
| Voice | Azure Communication Services Speech SDK |
| Frontend | HTML · CSS · Vanilla JS |
| Data | JSON mock data (no database) |

---

## Project Structure

```
retail-ai-poc/
├── backend/
│   ├── main.py          # FastAPI app, routes /chat and /voice/transcribe
│   ├── agents.py        # AI Foundry agent router + GPT-4o fallback
│   └── voice.py         # Azure Speech-to-Text transcription
├── frontend/
│   ├── index.html       # Full chat UI (served by FastAPI)
│   ├── css/styles.css   # Premium orange/white glassmorphism theme
│   └── js/app.js        # Chat logic, voice recording, API calls
├── mock_data/
│   ├── customer.json    # Demo customer + 4 orders (delivered, in-transit, refunds)
│   └── store.json       # Store info, hours, delivery zones, policies
├── requirements.txt
├── .env.example
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
cd retail-ai-poc
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> [!IMPORTANT]
> **Windows Users:** If you run the application and get a `FileNotFoundError` or DLL load error for `Microsoft.CognitiveServices.Speech.core.dll` when using speech features, it is because your machine is missing the Visual C++ runtime. 
> To resolve this, download and install the **[Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe)**, then restart your terminal or computer.


### 2. Configure environment

```bash
cp .env.example .env
```

Open `.env` and fill in your values (see section below for where to find each one):

```env
AZURE_AI_FOUNDRY_API_KEY=your_api_key_here
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://retail-ai-poc-resource.services.ai.azure.com/api/projects/your-project-name
AZURE_OPENAI_ENDPOINT=https://retail-ai-poc-resource.openai.azure.com/openai/v1
AZURE_AI_FOUNDRY_DEPLOYMENT_NAME=gpt-4o

# Optional – leave blank to use GPT-4o direct fallback
AZURE_AGENT_ORDER_ID=
AZURE_AGENT_REFUND_ID=
AZURE_AGENT_DELIVERY_ID=
AZURE_AGENT_STORE_ID=

AZURE_SPEECH_KEY=your_speech_key
AZURE_SPEECH_REGION=eastus
```

### 3. Run

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000**

---

## Finding Your Azure Credentials

### AI Foundry credentials (3 values from one screen)

1. Go to [ai.azure.com](https://ai.azure.com) → open your project
2. Click **Overview** on the left nav
3. You will see three values on that page:

| .env variable | Where to find it | Example value |
|---|---|---|
| `AZURE_AI_FOUNDRY_API_KEY` | **API key** field (masked) | `abc123...` |
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | **Project endpoint** | `https://retail-ai-poc-resource.services.ai.azure.com/api/projects/retail-ai-poc` |
| `AZURE_OPENAI_ENDPOINT` | **Azure OpenAI endpoint** | `https://retail-ai-poc-resource.openai.azure.com/openai/v1` |

Copy all three using the copy icons next to each field.

### GPT-4o deployment name

1. In your AI Foundry project: **Models + endpoints** → **Deploy model**
2. Select **gpt-4o**, name the deployment `gpt-4o` (or any name – just match it in `.env`)
3. Set `AZURE_AI_FOUNDRY_DEPLOYMENT_NAME` to that exact deployment name

---

## Azure AI Foundry Agents (optional)

If you leave the `AZURE_AGENT_*_ID` variables blank, the backend automatically calls GPT-4o directly. The POC works either way.

To wire up specialist agents:

1. AI Foundry Studio → **Agents** → **+ New agent**
2. Create four agents with these system prompts:

**Order Agent → `AZURE_AGENT_ORDER_ID`**
```
You are a Sainsbury's order specialist. Help customers understand their order details,
payment, confirmation, and order history. Be warm, concise, and solution-oriented.
Use the context provided at the start of the conversation for all data.
```

**Refund Agent → `AZURE_AGENT_REFUND_ID`**
```
You are a Sainsbury's refund and returns specialist. Help customers with damaged goods,
missing items, incorrect substitutions, and refund tracking. Always tell the customer
their refund reference and expected timeline. Never create refund data not in context.
```

**Delivery Agent → `AZURE_AGENT_DELIVERY_ID`**
```
You are a Sainsbury's delivery tracking specialist. Help customers track deliveries,
understand ETA, delivery slots, driver details, and proof of delivery. Be proactive
and reassuring. Only reference delivery data given in context.
```

**Store Agent → `AZURE_AGENT_STORE_ID`**
```
You are a Sainsbury's store information specialist. Help customers with store hours,
locations, services (pharmacy, ATM, café), Click & Collect, and store policies.
```

3. Copy each agent's ID and paste into `.env`

---

## Azure Speech Setup (Voice Input)

1. Azure Portal → **Create resource** → **Speech**
2. Go to the resource → **Keys and Endpoint**
3. Copy **Key 1** → `AZURE_SPEECH_KEY`
4. Copy the **Location/Region** → `AZURE_SPEECH_REGION` (e.g. `eastus`)

---

## API Reference

### `POST /chat`

```json
{
  "message": "Where is my order ORD-99102?",
  "conversation_history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

Response:
```json
{
  "reply": "Your order ORD-99102 is currently in transit...",
  "intent": "delivery",
  "sources": ["gpt4o_direct"]
}
```

`sources` is either `foundry_agent` (agent used) or `gpt4o_direct` (fallback).

### `POST /voice/transcribe`

Multipart form upload with field `audio` (WAV blob from browser MediaRecorder).

Response:
```json
{ "transcript": "Where is my delivery?" }
```

### `GET /health`

```json
{ "status": "ok", "service": "Retail AI Assistant" }
```

---

## Mock Data – Edge Cases Covered

| Scenario | Order ID |
|---|---|
| Normal delivered order | ORD-98741 |
| Live in-transit delivery (ETA today) | ORD-99102 |
| Refund in progress (mouldy product) | ORD-97830 |
| Completed refund (expired juice) | ORD-96210 |

---

## Limitations (POC scope)

- Single demo customer (Jamie Thornton)
- No database — all data from JSON files
- No authentication or session management
- Voice transcription requires microphone permission in browser
- Azure credentials required for AI features
