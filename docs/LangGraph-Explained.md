# 🤖 LangGraph Explained for Beginners

LangGraph is a core part of this project. This document explains what it is, why we use it, and how it works — all in simple language.

---

## What is LangGraph?

LangGraph is a **workflow manager for AI systems**. Think of it as a flowchart that runs automatically.

Without LangGraph, you'd have one giant Python function that does everything: classify intent, call the AI, query the database, validate the response... If anything goes wrong, the whole thing breaks.

With LangGraph, each step is a separate **node** (box in a flowchart). You connect the boxes together, and LangGraph handles the flow. Each node does ONE thing and passes its result to the next node.

---

## Why Do We Use It?

| Problem Without LangGraph | Solution With LangGraph |
|--------------------------|------------------------|
| One giant messy function | Clean, separate nodes |
| Hard to add new steps | Just add a new node |
| No conditional branching | Conditional edges (if/else routing) |
| Hard to debug | Each node logs what it does |
| Tools (DB queries) are complex to manage | Built-in tool calling support |

---

## The Nodes in This Project

Here is the full pipeline defined in `backend/agents/graph.py`:

### 1. `router_node`
**Job:** Decides what category the user's message belongs to.

**It checks (in this order):**
1. Is it a greeting? → Reply immediately with "Hello!"
2. Is it a thank you? → Reply immediately with "You're welcome!"
3. Is it an acknowledgement like "yes/sure/okay"? → Go to context resolver
4. Is it a voice message? → Skip AI classification, use keywords (faster)
5. Does it match a keyword? (order, refund, delivery, store) → Route directly
6. None of the above? → Ask the AI intent classifier

**Why it matters:** This is the first decision point. Getting routing right means the right specialist handles the question.

```python
# From backend/agents/graph.py
if cleaned_msg in ("hello", "hi", "hey", "good morning"):
    return {"intent": "greeting", "reply": "Hello! How can I help..."}
```

---

### 2. `context_resolver_node`
**Job:** Resolves ambiguous follow-up messages.

**Example:**
- AI asks: "Would you like home delivery or Click & Collect?"
- Customer says: "Yes"
- Context resolver figures out: "Yes what? They need to pick one."
- It responds: "Could you confirm which — delivery or Click & Collect?"

**Why it matters:** Without this, the AI would get confused by one-word responses.

---

### 3. `specialist_agent_node`
**Job:** Sends the question (plus customer context) to the right AI agent and gets an answer.

**The 5 specialists:**
| Agent | What it handles |
|-------|----------------|
| Order Agent | Order status, payment history, Nectar points |
| Delivery Agent | Tracking, slot reschedules, driver info |
| Refund Agent | Processing refunds for damaged or missing items |
| Store Agent | Hours, locations, stock availability, promotions |
| General Agent | Anything else that doesn't fit the above |

Each agent has its own instructions configured in Azure AI Foundry Portal.

**How the AI decides to call a tool:**  
The AI sees a message like: "Is there avocado in stock at the Islington store?"  
It responds with a **tool call**: `check_stock_tool(product_name="avocado", store_name="Islington")`  
LangGraph detects this and routes to `tool_execution_node`.

---

### 4. `tool_execution_node`
**Job:** Runs the actual database or search query the AI requested.

**Tools available:**

| Tool | What it does |
|------|-------------|
| `search_products_tool` | Finds products by name, category, dietary tags |
| `check_stock_tool` | Checks stock level at a specific store |
| `get_active_promotions_tool` | Lists current deals and offers |
| `update_customer_address_tool` | Updates the customer's delivery address |
| `issue_refund_tool` | Issues a refund for an order |

After the tool runs, LangGraph **goes back** to `specialist_agent_node` so the AI can incorporate the results and write its final answer.

---

### 5. `validation_node`
**Job:** Cleans up the AI's response before it reaches the customer.

**What it checks:**
- ✅ Removes markdown (no `**bold**`, no `# Headings`)
- ✅ Converts `- bullets` to `• bullets`
- ✅ Strips internal database IDs (`CUST-001` → hidden)
- ✅ Blocks any response containing API keys, endpoints, system prompts
- ✅ Blocks responses that mention other customers' emails

```python
# From backend/agents/validation.py
SENSITIVE_PATTERNS = [
    r"sk-[a-zA-Z0-9]{20,}",   # OpenAI keys
    r"api_key",                 # Keys
    r"system prompt",           # Prompts
    r"langgraph",               # Internal tools
]
```

---

## How the State Works

LangGraph passes a shared **state dictionary** between nodes. Think of it as a notepad that gets passed from person to person — each person reads it, adds something, and passes it on.

```python
# The state (from backend/agents/graph.py)
class AgentState(TypedDict):
    message_text: str          # The customer's message
    history: list              # Previous messages in the conversation
    customer_data: dict        # The customer's orders, deliveries, etc.
    intent: str                # "specialist", "greeting", "thanks" etc.
    specialist_role: str       # "order", "delivery", "refund", "store"
    reply: str                 # The AI's final answer
    sources: list              # Which agents/tools contributed
    suggestions: list          # Quick-reply buttons to show the customer
    is_voice: bool             # Is this a voice call? (affects response style)
```

Every node reads from this state and writes back to it. By the time it reaches `validation_node`, all the fields are filled in and the `reply` is the final answer.

---

## LangGraph in One Sentence

> LangGraph is a **decision tree that routes customer messages through the right specialist AI agents, runs database queries when needed, and cleans up the response** — all automatically, reliably, and in the right order.

---

## Conversation Memory

The `history` field in the state carries the last few messages. This is how the AI knows what was said before:

```
Customer: "Do you have avocados?"
AI: "Yes, we have avocados at the Islington store."
Customer: "How much are they?"
```

Without history, the AI wouldn't know what "they" refers to. With history, it resolves "they" to "avocados".
