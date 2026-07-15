# 🔍 Code Trace — "Where Is My Order?" End-to-End

This document traces one real user question through every file and function in the codebase.

**User question:** `"Where is my order?"`

---

## Step 1 — User Types the Message

**File:** `frontend/index.html` + `frontend/js/app.js`

The chat input box captures the text. When the user presses Enter, `app.js` calls `sendMessage()`.

```javascript
// frontend/js/app.js (simplified)
async function sendMessage() {
    const message = chatInput.value.trim();
    // ...
    const response = await fetch('/chat', {
        method: 'POST',
        body: JSON.stringify({
            message: "Where is my order?",
            conversation_history: [...history],
            stream: true
        })
    });
}
```

The previous conversation history is included so the AI knows what was said before.

---

## Step 2 — HTTP Request Arrives at FastAPI

**File:** `backend/main.py` — function `chat()` at line ~208

FastAPI receives the `POST /chat` request. Since streaming is enabled, it creates an async queue and starts the agent in a background task:

```python
# backend/main.py
@app.post("/chat")
async def chat(request: ChatRequest):
    stream_queue = asyncio.Queue()
    asyncio.create_task(run_graph_task())  # Runs in background
    return StreamingResponse(sse_generator(), media_type="text/event-stream")
```

The `sse_generator()` function reads from the queue and streams tokens to the browser as they arrive.

---

## Step 3 — Agent Router Prepares the State

**File:** `backend/agents/router.py` — function `handle()`

```python
# backend/agents/router.py
async def handle(self, message: str, history: list, is_voice: bool = False, stream_queue = None):
    # Load latest customer data from database
    customer_data = await asyncio.to_thread(self._load_customer_data)
    
    # Build context block (customer's orders/deliveries summary)
    context_block = await asyncio.to_thread(build_context_block, customer_data)
    
    # Create the initial LangGraph state
    initial_state = {
        "message_text": "Where is my order?",
        "history": [],
        "customer_data": customer_data,
        "context_block": context_block,  # All customer order history
        "is_voice": False,
        "intent": "",
        "specialist_role": "order",
        "reply": "",
        ...
    }
    
    # Run the LangGraph pipeline
    result_state = await compiled_graph.ainvoke(initial_state, config=config)
```

**What is `context_block`?**  
It's a text summary of the customer's orders, built from the database. It looks like:
```
Customer: Jamie Thornton | Email: jamie@example.com
Orders:
  ORD-99102 [refund_completed] GBP15.15 | Delivery: June 16 14:00-16:00 | Driver: Maria S.
  ORD-98741 [refund_completed] GBP9.53  | Delivery: June 10 09:00-11:00 | Driver: Raj P.
```
This context is injected into every AI prompt so the agent knows the customer's history.

---

## Step 4 — LangGraph Runs: router_node

**File:** `backend/agents/graph.py` — function `_router_node_impl()`

```python
# "Where is my order?" → cleaned: "where is my order"
cleaned_msg = "where is my order"

# Not a greeting, thanks, or acknowledgement
# Not a voice call (is_voice=False)
# Check heuristic keywords...
for role, keywords in DIRECT_ROUTING_KEYWORDS.items():
    if any(kw in cleaned_msg for kw in keywords):
        return {"intent": "specialist", "specialist_role": role}
```

The word **"order"** appears in `DIRECT_ROUTING_KEYWORDS["order"]`:
```python
"order": ["order", "payment", "buy", "purchase", "receipt", ...]
```

So the router immediately classifies this as `specialist_role = "order"` without calling any AI. This saves ~2 seconds.

**Result:** `{"intent": "specialist", "specialist_role": "order"}`

---

## Step 5 — LangGraph Conditional Edge: Go to specialist_agent_node

**File:** `backend/agents/graph.py` — function `route_after_router()`

```python
def route_after_router(state: AgentState) -> str:
    intent = state["intent"]
    if intent in ("greeting", "thanks", "out_of_scope"):
        return "validation_node"
    if intent == "clarification_confirmation":
        return "context_resolver_node"
    return "specialist_agent_node"  # ← This path is taken
```

---

## Step 6 — specialist_agent_node Runs the Order Agent

**File:** `backend/agents/graph.py` — function `_specialist_agent_node_impl()`

```python
async def _specialist_agent_node_impl(state, config):
    role = state["specialist_role"]  # "order"
    
    # Get the Order Agent's instructions (fetched from Azure AI Foundry at startup)
    instructions = state["agent_instructions"]["order"]
    
    # Build the system message: instructions + customer context
    system_content = f"{instructions}\n\n{state['context_block']}"
    
    messages = [
        SystemMessage(content=system_content),
        HumanMessage(content="Where is my order?")
    ]
    
    # Call the AI (with tools bound)
    llm_with_tools = llm.bind_tools([
        search_products_tool,
        check_stock_tool,
        get_active_promotions_tool,
        update_customer_address_tool,
        issue_refund_tool
    ])
    
    # Stream the response
    async for chunk in llm_with_tools.astream(messages):
        if chunk.content:
            stream_queue.put_nowait({"type": "token", "content": chunk.content})
```

**What the AI model receives:**
```
SYSTEM: You are the Order specialist agent for Sainsbury's...
        [Order Agent instructions from AI Foundry Portal]
        
        Customer: Jamie Thornton | Email: jamie@example.com
        Orders:
          ORD-99102 [refund_completed] GBP15.15 - ...
          ORD-98741 [refund_completed] GBP9.53 - ...
          ORD-97830 [refund_completed] GBP10.30 - ...
        
USER: Where is my order?
```

**What the AI responds with:**
The AI has the customer's full order history in the context, so it can answer with real data without needing to call any tools.

---

## Step 7 — No Tool Call Needed (Direct Response)

Since the context block already contains order data, the AI doesn't need to call `check_stock_tool` or any other tool. It responds directly.

**The AI's raw response:**
```
Hi Jamie 😊 I can see a few recent orders on your account, all showing refunds completed:

• ORD-99102 – Home Delivery – 16 June slot...
• ORD-98741 – Home Delivery – 10 June slot...
...

Which order were you asking about?
```

Since no tool calls were generated, LangGraph routes to `validation_node`.

---

## Step 8 — validation_node Cleans Up

**File:** `backend/agents/validation.py` — `run_validation_layer()` and `validate_and_sanitize_response()`

The response is sanitized:
- `* ORD-99102` → `• ORD-99102` (bullet conversion)
- `CUST-001` → removed (ID masking)
- No sensitive patterns detected → response is safe
- `# Heading` would be stripped (not present here)

---

## Step 9 — Tokens Stream to the Browser

**File:** `backend/main.py` — `sse_generator()`

```python
async def sse_generator():
    while True:
        item = await stream_queue.get()
        if item is None:
            break
        yield f"data: {json.dumps(item)}\n\n"
```

Each token appears as a Server-Sent Event (SSE):
```
data: {"type": "token", "content": "Hi"}
data: {"type": "token", "content": " Jamie"}
data: {"type": "token", "content": " 😊"}
...
data: {"type": "done", "intent": "order", "sources": ["order_agent"], ...}
```

---

## Step 10 — Browser Renders the Response

**File:** `frontend/js/app.js`

```javascript
// app.js reads each SSE token and appends it to the chat bubble
eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'token') {
        // Append to current message bubble (streaming effect)
        currentBubble.textContent += data.content;
    }
    if (data.type === 'done') {
        // Show suggestion buttons
        renderSuggestions(data.suggestions);
    }
};
```

The user sees the words appear in real-time, character by character, just like ChatGPT.

---

## Files Touched in This Request

| Step | File | What it did |
|------|------|------------|
| 1 | `frontend/js/app.js` | Captured user input, sent POST /chat |
| 2 | `backend/main.py` | Received request, started async task |
| 3 | `backend/agents/router.py` | Loaded customer data, built state |
| 4 | `backend/database/database.py` | Loaded customer + order data |
| 4 | `backend/agents/tools.py` | Built context_block from customer data |
| 5 | `backend/agents/graph.py` (router_node) | Detected "order" keyword, routed to specialist |
| 6 | `backend/agents/graph.py` (specialist_node) | Called Order Agent via Azure OpenAI |
| 7 | Azure AI Foundry (GPT-5-mini) | Generated the response |
| 8 | `backend/agents/validation.py` | Cleaned and secured the response |
| 9 | `backend/main.py` (sse_generator) | Streamed tokens as SSE |
| 10 | `frontend/js/app.js` | Rendered response in chat |

**Total time:** ~3-5 seconds (most of it is the AI generating the response)
