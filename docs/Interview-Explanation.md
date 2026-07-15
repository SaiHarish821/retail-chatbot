# 🎤 Interview Explanation — "Tell Me About Your Project"

This is a natural-sounding explanation you can give in interviews, demos, or presentations. It covers the full project in 5–10 minutes.

---

## Short Version (1–2 Minutes)

> "I built an AI-powered customer support chatbot for Sainsbury's, the UK supermarket. It handles real customer queries — order tracking, refunds, product searches, and store information — using actual database records, not generic responses. What makes it interesting is that it supports both text chat and real-time voice calls, where a customer can speak to the AI just like calling a real helpline. It uses Azure AI Foundry agents, LangGraph for orchestration, and Azure Voice Live for real-time speech processing."

---

## Full Version (5–10 Minutes)

### The Problem

Most retail chatbots are frustrating. They either give generic answers like "please call our support line" or they look up information using simple keyword matching that misses context. A customer asking "When will my stuff arrive?" shouldn't get a list of FAQs — they should get their actual delivery time.

### What I Built

I built a full-stack AI customer support assistant for Sainsbury's. The system:

- Takes customer messages via text chat or real voice calls
- Understands the type of question (order? refund? store? product?)
- Looks up the customer's actual data from a database
- Uses Azure AI Foundry agents to generate natural, personalised responses
- Streams the response back in real time

### The Architecture

The system has three main layers:

**1. Frontend** — Plain HTML/CSS/JS. No frameworks. The UI has a chat window, a customer data sidebar, and a voice call overlay. It communicates with the backend over REST and WebSocket.

**2. Backend** — FastAPI Python server. This is where the intelligence lives. It uses LangGraph to orchestrate a multi-step AI pipeline.

**3. Azure Cloud** — AI Foundry for models and agents, AI Search for product discovery, Communication Services for phone calls, and Voice Live for real-time speech.

### How LangGraph Works Here

LangGraph is an AI workflow framework. Instead of one giant function that does everything, I have separate nodes:

- **Router node** — classifies the query (order? delivery? refund?)
- **Specialist agent node** — calls the right AI agent with customer context
- **Tool execution node** — runs database queries the AI requested
- **Validation node** — cleans and secures the response

Each node does one thing. This makes it easy to add new capabilities — just add a new node.

### The Specialist Agent System

Instead of one general AI agent, I have 5 specialists: Order, Delivery, Refund, Store, and General. Each has its own instructions configured in the Azure AI Foundry Portal. This means we can change an agent's behaviour without touching code — just update it in the Portal and the backend picks it up on the next restart.

### The Voice Feature

This is the most technically impressive part. When a customer clicks the call button:

1. Azure Communication Services handles the VoIP connection
2. The browser captures microphone audio as PCM16 (raw audio bytes)
3. These bytes are streamed over WebSocket to our backend
4. The backend forwards them to Azure Voice Live
5. Voice Live does speech-to-text, routes text to the AI Foundry agent, and converts the AI's response back to speech
6. That audio streams back to the browser

The whole thing operates in agent mode, which means the AI Foundry agent owns the conversation — Voice Live just handles the speech layer. There's also a pre-rendered filler audio system that plays "Alright, let me check that for you" while the AI thinks, preventing awkward silences.

### Challenges

The biggest challenge was the authentication difference between local development and production. Azure Voice Live in Agent Mode requires Entra ID token credentials — it doesn't support direct API keys. This caused the voice feature to fail on Vercel (which has no Azure CLI). The solution is to use a Service Principal with Client Secret credentials in production.

Another challenge was latency. The reasoning model (GPT-5-mini) has a thinking phase that consumes tokens before producing output. Setting `max_completion_tokens` too low (we had it at 80) caused the model to cut off before producing any visible text. We increased it to 1024 to give the reasoning phase enough room.

### Performance Optimisations

- **Keyword routing bypass**: Simple queries like "where is my order" skip the AI classifier entirely — keyword matching handles them in <1ms
- **Token caching**: Azure credentials are cached to avoid repeated CLI calls (each call was adding ~2 seconds)
- **Streaming responses**: Users see the first words in ~1-2 seconds even if the full response takes 5-8 seconds
- **Voice fast path**: Voice calls skip the intent classifier LLM entirely and go straight to keyword routing
- **Filler audio pre-rendered at startup**: No TTS latency during calls

### Technologies Used

| What | Technology |
|------|-----------|
| Frontend | HTML + CSS + JavaScript |
| Backend | Python + FastAPI |
| AI Orchestration | LangGraph |
| AI Models | Azure AI Foundry (GPT-5-mini) |
| Voice | Azure Voice Live + Azure Communication Services |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Product Search | Azure AI Search |
| Deployment | Vercel (serverless) |

### What I'd Do Differently

If I were building this from scratch again, I would:

1. Use Azure Managed Identity from the start instead of trying to support both CLI and API key auth
2. Set up proper environment separation (dev/staging/prod) earlier
3. Add more automated tests for the LangGraph routing logic

---

## Common Follow-Up Questions

**Q: Why LangGraph instead of just calling OpenAI directly?**  
A: LangGraph gives us conditional routing (different paths for different intent types), tool calling management (running database queries mid-conversation), and clean separation of concerns. Without it, we'd have one spaghetti function.

**Q: Why Azure AI Foundry instead of OpenAI directly?**  
A: Azure AI Foundry lets us manage agent instructions in a Portal — no code deployments needed to update a prompt. It also integrates with Azure Voice Live for real-time voice in Agent Mode.

**Q: Why 5 separate agents instead of one big one?**  
A: Each specialist is better at its domain. The Refund Agent has detailed refund policy instructions. The Delivery Agent has logistics-specific context. Using one general agent would require mixing all these instructions together, which makes the AI less focused and more likely to give wrong answers.

**Q: How do guardrails work?**  
A: The validation layer in `backend/agents/validation.py` scans every response before it reaches the user. It blocks responses containing API keys, system prompts, internal IDs, or other customers' email addresses. If a blocked pattern is found, it replaces the response with a safe generic message.

**Q: How is conversation history maintained?**  
A: The frontend keeps the conversation history in a JavaScript array and sends it with every request. The backend injects the last 5-6 messages into the AI context. There's no server-side session storage — the client owns the conversation state.

**Q: What happens if Azure is down?**  
A: The system has fallbacks. If the AI Foundry project client fails, it falls back to a direct Azure OpenAI connection using the API key. If intent classification fails, keyword heuristics take over. The system degrades gracefully rather than crashing completely.
