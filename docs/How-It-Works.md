# 🔄 How the Project Works — End-to-End Workflow

This document walks you through the entire system from the moment a user types a message to when they see the answer.

---

## The Simple Version (Plain English)

1. Customer types "Where is my order?" on the Sainsbury's website
2. The website sends this to the backend server
3. The backend figures out what type of question it is (an "order" question)
4. It passes the question to the Order Specialist AI agent
5. The AI agent looks at the customer's order history in the database
6. It writes a natural, helpful response
7. The response is sent back to the website and shown to the customer

---

## Step-by-Step Detailed Workflow

### Step 1 — Customer Opens the Website
**What happens:** The browser loads `frontend/index.html`.  
**Why:** This is the full chat UI — the input box, chat bubbles, call button, and customer info panel.  
**File:** `frontend/index.html`

---

### Step 2 — Customer Sidebar Loads Their Data
**What happens:** On page load, JavaScript calls `GET /customer` to fetch the logged-in customer's orders, deliveries, and refund history.  
**Why:** The frontend shows this data in a panel, so the customer can see their info.  
**Files:** `frontend/js/app.js` → calls `backend/main.py` route `/customer` → `backend/database/database.py`

---

### Step 3 — Customer Types a Message and Hits Send
**What happens:** The user types "Where is my order?" and presses Enter.  
**Why:** The frontend listens to this event and prepares a request.  
**File:** `frontend/js/app.js` — function `sendMessage()`

---

### Step 4 — Frontend Sends the Message to the Backend
**What happens:** JavaScript sends a `POST /chat` request with:
```json
{
  "message": "Where is my order?",
  "conversation_history": [...previous messages...]
}
```
**Why:** The frontend is just a display — the AI brains are on the server.  
**File:** `frontend/js/app.js` → `backend/main.py` route `/chat`

---

### Step 5 — FastAPI Receives the Request
**What happens:** The `chat()` function in `main.py` receives the request and calls `agent_router.handle()`.  
**Why:** FastAPI is the web server. It validates the input and delegates the thinking to the agent system.  
**File:** `backend/main.py`

---

### Step 6 — LangGraph Orchestrates the Workflow
**What happens:** The request enters a **LangGraph** pipeline — a decision tree of nodes (steps). The journey is:

```
router_node → (decides what type of question)
    ↓ (if it's a retail question)
specialist_agent_node → (calls the right AI agent)
    ↓ (if AI wants to look up data)
tool_execution_node → (runs database/search queries)
    ↓
specialist_agent_node → (AI reads data and writes answer)
    ↓
validation_node → (cleans up the response)
```

**Why:** LangGraph ensures every request follows a reliable, predictable path with proper error handling.  
**File:** `backend/agents/graph.py`

---

### Step 7 — Intent Classification (What Kind of Question?)
**What happens:** The `router_node` checks whether the question is:
- A greeting ("hi") → instant local response
- An acknowledgement ("yes", "okay") → sends to context resolver
- A retail question → keyword check routes directly to right agent
- Something else → calls the AI intent classifier

**Why:** We avoid calling the AI for simple cases to save time and cost.  
**File:** `backend/agents/intent.py`, `backend/agents/graph.py`

---

### Step 8 — Specialist Agent Answers
**What happens:** The correct specialist agent (Order, Delivery, Refund, or Store) receives:
- The customer's question
- The customer's full order history (as context)
- Its own instructions (fetched from Azure AI Foundry)

The AI (GPT-5-mini) generates an answer. If it needs real data, it calls a **tool**.

**Why:** Each specialist is trained for its specific domain — this gives more accurate answers.  
**File:** `backend/agents/graph.py` (specialist_agent_node), `backend/agents/router.py`

---

### Step 9 — Database / Search Tool Execution
**What happens:** If the AI decides it needs data (e.g., stock levels, product details), it calls a tool like `check_stock_tool` or `search_products_tool`. These query:
- **SQLite/PostgreSQL database** — for orders, customers, refunds, store data
- **Azure AI Search** — for natural-language product searches

**Why:** The AI alone doesn't know your order details — it needs real data.  
**File:** `backend/agents/tools.py`, `backend/database/database.py`

---

### Step 10 — Response Validation & Cleanup
**What happens:** Before sending the answer back, a validation layer:
- Strips markdown formatting (no `**bold**` — it formats with bullet points)
- Masks internal IDs (hides `CUST-001` unless the user asked for an ID)
- Blocks any response that accidentally contains API keys, system prompts, or other customers' data

**Why:** Security and consistency — the user sees a clean, safe response.  
**File:** `backend/agents/validation.py`

---

### Step 11 — Response Streams Back to the Browser
**What happens:** If streaming is enabled, the words appear character-by-character (like ChatGPT). Otherwise, the full response arrives at once.  
**Why:** Streaming makes the experience feel faster and more natural.  
**File:** `backend/main.py` (streaming SSE logic), `frontend/js/app.js`

---

## Voice Call Path (Additional Step)

When the user clicks the **Call** button instead of typing:

1. Frontend requests an ACS token from `GET /api/token`
2. Azure Communication Services connects a WebRTC call
3. The browser captures microphone audio (PCM16 format, 24kHz)
4. Audio is sent over WebSocket to `ws://backend/api/voice-realtime`
5. The backend forwards audio to **Azure Voice Live**
6. Voice Live runs speech-to-text, sends it to the AI Foundry agent
7. The agent responds in text, Voice Live converts it to speech
8. The spoken audio is sent back to the browser WebSocket
9. The browser plays it through the speaker

**Why Voice Live instead of doing it ourselves:** Voice Live handles all the complexity — when to listen, when to speak, background noise, interruptions, and staying in sync with the AI agent.
