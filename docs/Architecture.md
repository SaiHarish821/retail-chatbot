# Architecture

## End-to-End Request Flows

### 1. Chat Request — Full Lifecycle

```mermaid
sequenceDiagram
    actor User
    participant Browser
    participant FastAPI
    participant Router as AgentRouter
    participant Graph as LangGraph
    participant OpenAI as Azure OpenAI
    participant DB as Database

    User->>Browser: Types "Is my milk still in stock?"
    Browser->>FastAPI: POST /chat<br/>{message, history, stream: true}

    FastAPI->>FastAPI: Parse ChatRequest (Pydantic)
    FastAPI->>Router: handle(message, history, is_voice=false, stream_queue)

    Note over Router: Data Loading
    Router->>Router: asyncio.to_thread(load_db_customer_data)
    Router->>Router: build_context_block(customer_data)
    Router->>Router: _get_llm() — check token expiry

    Note over Router: Graph Invocation
    Router->>Graph: compiled_graph.ainvoke(initial_state)

    Note over Graph: STEP 1: Router Node
    Graph->>Graph: check_static_responses("Is my milk still in stock?")
    Graph->>Graph: check_heuristic_keywords(message)
    Note right of Graph: "stock" keyword → specialist_role = "store"
    Graph-->>Graph: specialist_role = "store", intent = "store"

    Note over Graph: STEP 2: Specialist Agent Node
    Graph->>Graph: Load store agent instructions
    Graph->>Graph: Build message thread [system, context, history, user]
    Graph->>Graph: Bind tools [check_stock, get_active_promotions]
    Graph->>OpenAI: llm_with_tools.ainvoke(messages)
    OpenAI-->>Graph: AIMessage with tool_calls: [check_stock(product_name="Organic Whole Milk 2L")]

    Note over Graph: STEP 3: Tool Execution Node
    Graph->>DB: check_stock("Organic Whole Milk 2L", None)
    DB-->>Graph: Stock data across 3 stores

    Note over Graph: Back to Specialist Agent Node (loop)
    Graph->>OpenAI: Re-invoke with ToolMessage (stock results)
    OpenAI-->>Graph: "Great news! Organic Whole Milk 2L is in stock at all stores..."

    Note over Graph: STEP 4: Validation Node
    Graph->>Graph: validate_and_sanitize_response(reply)
    Graph->>Graph: check_security_guardrails(reply)
    Graph->>Graph: append_product_grid_if_mentioned(reply)

    Graph-->>Router: Final state {reply, intent, sources, suggestions}
    Router-->>FastAPI: Result dict

    Note over FastAPI: SSE Streaming
    FastAPI-->>Browser: data: {"type": "token", "content": "Great"}
    FastAPI-->>Browser: data: {"type": "token", "content": " news!"}
    FastAPI-->>Browser: ...more tokens...
    FastAPI-->>Browser: data: {"type": "done", "reply": "...", "intent": "store", "suggestions": [...]}

    Browser-->>User: Rendered response with product cards
```

### 2. Voice Request — Browser Voice-to-Voice

```mermaid
sequenceDiagram
    actor User
    participant Browser
    participant FastAPI
    participant VoiceLive as Azure Voice Live
    participant Agent as Foundry Voice Agent
    participant DB as Database

    User->>Browser: Clicks phone button
    Browser->>Browser: Create AudioContext (24kHz PCM16)
    Browser->>FastAPI: WebSocket connect /api/voice-realtime
    FastAPI->>FastAPI: Resolve credentials (CLI or ClientSecret)
    FastAPI->>VoiceLive: connect(endpoint, agent_name, project_name)
    VoiceLive-->>FastAPI: Connection established

    FastAPI->>VoiceLive: session.update(RequestSession)<br/>modalities=TEXT+AUDIO, voice=Ava:DragonHD
    VoiceLive-->>FastAPI: session.updated

    Note over Browser,VoiceLive: Conversation Loop

    User->>Browser: "What promotions do you have?"
    Browser->>Browser: Capture mic audio (PCM16 24kHz)
    Browser->>FastAPI: Binary audio frames (raw bytes)
    FastAPI->>VoiceLive: input_audio_buffer.append(base64_audio)

    VoiceLive-->>FastAPI: SPEECH_STARTED
    FastAPI-->>Browser: {"type": "speech_started"}

    VoiceLive-->>FastAPI: SPEECH_STOPPED
    FastAPI-->>Browser: {"type": "speech_stopped"}

    VoiceLive-->>FastAPI: TRANSCRIPTION_COMPLETED("What promotions do you have?")
    FastAPI-->>Browser: {"type": "user_transcript", "text": "..."}

    VoiceLive->>Agent: Process query with agent instructions
    Agent->>Agent: Determine tool call needed

    VoiceLive-->>FastAPI: FUNCTION_CALL_ARGUMENTS_DONE(get_active_promotions_tool, {})
    FastAPI->>DB: execute_voice_tool("get_active_promotions_tool", {})
    DB-->>FastAPI: Promotions data
    FastAPI->>VoiceLive: conversation_item.create(function_call_output)
    FastAPI->>VoiceLive: response.create()

    VoiceLive->>Agent: Process with tool results
    Agent-->>VoiceLive: Audio response

    loop Audio Chunks
        VoiceLive-->>FastAPI: RESPONSE_AUDIO_DELTA(base64_chunk)
        FastAPI-->>Browser: {"type": "audio_delta", "delta": "base64..."}
        Browser->>Browser: Decode + queue + play PCM16
    end

    VoiceLive-->>FastAPI: RESPONSE_AUDIO_TRANSCRIPT_DONE("We have several great promotions...")
    FastAPI-->>Browser: {"type": "agent_transcript", "text": "..."}
    Browser-->>User: Audio plays + transcript displayed
```

### 3. Phone Call — PSTN via ACS

```mermaid
sequenceDiagram
    actor Caller
    participant PSTN
    participant ACS as Azure Communication Services
    participant FastAPI
    participant VoiceLive as Azure Voice Live
    participant Agent as Foundry Voice Agent

    Caller->>PSTN: Dials phone number
    PSTN->>ACS: Route to ACS resource
    ACS->>FastAPI: POST /api/incoming-call (IncomingCall event)
    FastAPI->>FastAPI: Extract incomingCallContext

    FastAPI->>ACS: answer_call(context, callback_url, media_streaming)
    Note right of ACS: Media streaming configured:<br/>WebSocket URL = /api/media-stream

    ACS-->>FastAPI: Call answered
    ACS->>FastAPI: WebSocket /api/media-stream (bidirectional audio)

    FastAPI->>VoiceLive: connect(endpoint, agent_name, project_name)
    VoiceLive-->>FastAPI: Connection established
    FastAPI->>VoiceLive: session.update(RequestSession)

    Note over Caller,Agent: Real-time Conversation

    Caller->>PSTN: Speaks "Where is my delivery?"
    PSTN->>ACS: Audio stream
    ACS->>FastAPI: Media stream audio (base64 PCM)
    FastAPI->>VoiceLive: input_audio_buffer.append(audio)

    VoiceLive->>Agent: Process speech
    Agent-->>VoiceLive: Response audio

    loop Audio Response
        VoiceLive-->>FastAPI: RESPONSE_AUDIO_DELTA
        FastAPI->>ACS: Media stream audio response
        ACS->>PSTN: Play audio
        PSTN-->>Caller: Hears agent response
    end

    Caller->>PSTN: Hangs up
    ACS->>FastAPI: POST /api/callback (CallDisconnected)
    FastAPI->>FastAPI: Cleanup call state
```

### 4. Suggestion Generation Flow

After each agent response, the system generates follow-up suggestion chips:

```mermaid
sequenceDiagram
    participant Graph as LangGraph
    participant Router as AgentRouter
    participant OpenAI as Azure OpenAI

    Note over Graph: After specialist response
    Graph->>Graph: Reply = "Your order ORD-98741 was..."

    Note over Router: Generate Suggestions
    Router->>OpenAI: "Based on this reply + customer history,<br/>generate 3-5 follow-up question suggestions"
    OpenAI-->>Router: ["Check refund status for ORD-98741",<br/>"Track my current delivery",<br/>"What promotions are available?"]

    Router->>Router: Store suggestions in state
    Router-->>Graph: suggestions = [...]
```

### 5. Multi-Agent Routing

For complex queries requiring multiple specialist agents:

```mermaid
sequenceDiagram
    participant User
    participant Router as Router Node
    participant Supervisor as Supervisor Agent
    participant OrderAgent as Order Agent
    participant DeliveryAgent as Delivery Agent
    participant OpenAI as Azure OpenAI

    User->>Router: "What's the status of my orders and when will my delivery arrive?"

    Note over Router: Heuristic match for "order" AND "delivery"
    Router->>Supervisor: Decompose query
    Supervisor->>OpenAI: Route analysis
    OpenAI-->>Supervisor: [<br/>  {agent: "order", task: "Order status overview"},<br/>  {agent: "delivery", task: "Delivery ETA for ORD-99102"}<br/>]

    par Parallel Execution
        Supervisor->>OrderAgent: "Order status overview"
        OrderAgent->>OpenAI: Process with order context
        OpenAI-->>OrderAgent: "You have 4 orders..."
    and
        Supervisor->>DeliveryAgent: "Delivery ETA for ORD-99102"
        DeliveryAgent->>OpenAI: Process with delivery context
        OpenAI-->>DeliveryAgent: "ORD-99102 is currently at stop 4/9..."
    end

    Supervisor->>Supervisor: Merge responses
    Supervisor-->>User: Combined response
```

### 6. Token Refresh Flow

```mermaid
sequenceDiagram
    participant Router as AgentRouter
    participant Azure as Azure Identity
    participant LLM as ChatOpenAI

    Router->>Router: _get_llm() called

    alt Token not cached or expired
        Router->>Azure: credential.get_token("https://ai.azure.com/.default")
        Azure-->>Router: AccessToken(token, expires_on)
        Router->>Router: Cache token + expires_on
        Router->>LLM: ChatOpenAI(api_key=new_token, base_url)
        Router->>Router: Cache LLM instance
    else Token still valid (> 300s remaining)
        Router->>Router: Return cached LLM instance
    end

    Router-->>Router: Return ChatOpenAI instance
```

### 7. Database Initialisation Flow

```mermaid
sequenceDiagram
    participant App as FastAPI App
    participant DB as database.py
    participant Seed as seed_data.py

    App->>DB: init_db()
    DB->>DB: Detect database type (SQLite or PostgreSQL)
    DB->>DB: CREATE TABLE IF NOT EXISTS × 7 tables

    App->>DB: seed_db()
    DB->>DB: check_needs_reseed()
    alt Schema mismatch or new tables
        DB->>DB: DROP all tables
        DB->>DB: init_db() (recreate)
    end

    DB->>DB: SELECT COUNT(*) FROM customer
    alt Not seeded
        DB->>Seed: Import CUSTOMER_SEED
        DB->>DB: INSERT customer, orders, order_items, refunds
    end

    DB->>DB: SELECT COUNT(*) FROM products
    alt Not seeded
        DB->>Seed: Import INVENTORY_SEED
        DB->>DB: INSERT stores (3)
        DB->>DB: INSERT products (20+) with decorate_product()
        DB->>DB: INSERT product_stock (60+)
        DB->>DB: INSERT promotions (5)
    end
```

### 8. Filler Audio System Flow

```mermaid
sequenceDiagram
    participant Browser
    participant FastAPI
    participant TTS as Azure TTS

    Note over FastAPI: Startup
    FastAPI->>TTS: render_filler_clips(credential, endpoint, voice)
    TTS->>TTS: Render 5 trees × 4 phrases = 20 clips
    TTS->>TTS: Render 6 thinking clips
    Note right of TTS: Parallel synthesis<br/>ThreadPoolExecutor(max_workers=10)
    TTS-->>FastAPI: (tree_clips, thinking_clips)

    Note over Browser: Voice Call Started
    Browser->>FastAPI: GET /api/fillers
    FastAPI-->>Browser: {trees: [...], thinking: [...]}
    Browser->>Browser: Cache base64 audio clips

    Note over Browser: User stops speaking (waiting for response)
    Browser->>Browser: Start filler timer (5s grace)
    Note right of Browser: If response arrives < 5s, skip fillers

    alt Response takes > 5s
        Browser->>Browser: Pick random tree
        Browser->>Browser: Play tree[0]: "Let me check that for you"
        Note right of Browser: Wait 3.5-6s
        Browser->>Browser: Play thinking[random]: "Hmm..."
        Note right of Browser: Wait 3.5-6s
        Browser->>Browser: Play tree[1]: "Searching our system now"
    end

    Note over Browser: Agent response arrives
    Browser->>Browser: Stop filler playback
    Browser->>Browser: Queue and play agent audio
```
