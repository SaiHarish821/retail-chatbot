# Sequence Diagrams

This document contains all Mermaid sequence diagrams for the major flows in the system.

---

## 1. Chat Flow — Standard Query

```mermaid
sequenceDiagram
    actor User
    participant Browser
    participant FastAPI
    participant Router as AgentRouter
    participant Graph as LangGraph
    participant Intent as Intent Classifier
    participant Specialist as Specialist Agent
    participant LLM as Azure OpenAI
    participant Tools as Tool Functions
    participant DB as Database
    participant Validator as Validation Layer

    User->>Browser: Type message
    Browser->>FastAPI: POST /chat {message, history, stream: true}
    FastAPI->>Router: handle(message, history)

    Router->>DB: load_db_customer_data()
    DB-->>Router: customer + orders + refunds
    Router->>Router: build_context_block()
    Router->>Router: _get_llm() (token check)

    Router->>Graph: compiled_graph.ainvoke(state)

    Graph->>Intent: router_node(state)
    Intent->>Intent: Check static (greeting?)
    Intent->>Intent: Check heuristic keywords
    alt No keyword match
        Intent->>LLM: classify_intent(message, history)
        LLM-->>Intent: intent label
    end
    Intent-->>Graph: {intent, specialist_role}

    Graph->>Specialist: specialist_agent_node(state)
    Specialist->>Specialist: Load role instructions
    Specialist->>Specialist: Build message thread
    Specialist->>Specialist: Bind tools to LLM
    Specialist->>LLM: llm_with_tools.ainvoke(messages)
    LLM-->>Specialist: Response (text or tool_calls)

    opt Tool calls present
        Graph->>Tools: tool_execution_node(state)
        Tools->>DB: Execute tool function
        DB-->>Tools: Tool result
        Tools-->>Graph: ToolMessage added to state
        Graph->>Specialist: Re-invoke specialist
        Specialist->>LLM: ainvoke(messages + ToolMessage)
        LLM-->>Specialist: Final text response
    end

    Graph->>Validator: validation_node(state)
    Validator->>Validator: Security guardrails
    Validator->>Validator: Sanitise response
    Validator->>Validator: Append product grid
    Validator-->>Graph: Validated reply

    Graph-->>Router: Final state
    Router-->>FastAPI: {reply, intent, sources, suggestions}

    loop SSE Streaming
        FastAPI-->>Browser: data: {type: "token", content: "..."}
    end
    FastAPI-->>Browser: data: {type: "done", reply, intent, suggestions}

    Browser-->>User: Rendered response
```

---

## 2. Voice Flow — Browser Voice-to-Voice

```mermaid
sequenceDiagram
    actor User
    participant Mic as Microphone
    participant AudioCtx as Web Audio API
    participant WS as WebSocket
    participant FastAPI
    participant VL as Voice Live SDK
    participant Agent as Foundry Agent
    participant Tools as Tool Functions
    participant DB as Database
    participant Speaker

    User->>Mic: Speak
    Mic->>AudioCtx: MediaStream (raw audio)
    AudioCtx->>AudioCtx: ScriptProcessor → PCM16 conversion
    AudioCtx->>WS: Binary PCM16 frame

    WS->>FastAPI: Binary message
    FastAPI->>FastAPI: Base64 encode audio
    FastAPI->>VL: input_audio_buffer.append(b64)

    VL->>VL: Server VAD processing
    VL-->>FastAPI: SPEECH_STARTED
    FastAPI-->>WS: {type: "speech_started"}

    User->>Mic: Stop speaking
    VL->>VL: Silence > 500ms detected
    VL-->>FastAPI: SPEECH_STOPPED
    FastAPI-->>WS: {type: "speech_stopped"}

    VL->>VL: Transcribe speech
    VL-->>FastAPI: TRANSCRIPTION_COMPLETED
    FastAPI-->>WS: {type: "user_transcript", text}

    VL->>Agent: Process with instructions
    
    opt Tool call needed
        VL-->>FastAPI: FUNCTION_CALL_ARGUMENTS_DONE
        FastAPI->>Tools: execute_voice_tool(name, args)
        Tools->>DB: Execute operation
        DB-->>Tools: Result
        Tools-->>FastAPI: Result string
        FastAPI->>VL: conversation_item.create(result)
        FastAPI->>VL: response.create()
    end

    Agent-->>VL: Audio response

    loop Audio chunks
        VL-->>FastAPI: RESPONSE_AUDIO_DELTA
        FastAPI-->>WS: {type: "audio_delta", delta}
        WS->>AudioCtx: Decode Base64 → PCM16
        AudioCtx->>Speaker: Play audio
    end

    VL-->>FastAPI: RESPONSE_AUDIO_TRANSCRIPT_DONE
    FastAPI-->>WS: {type: "agent_transcript", text}
```

---

## 3. Phone Call Flow — PSTN via ACS

```mermaid
sequenceDiagram
    actor Caller
    participant PSTN as Phone Network
    participant ACS as Azure Communication Services
    participant CallAuto as Call Automation
    participant FastAPI as FastAPI Backend
    participant VL as Voice Live SDK
    participant Agent as Foundry Agent

    Caller->>PSTN: Dial phone number
    PSTN->>ACS: Route to ACS resource

    ACS->>FastAPI: POST /api/incoming-call<br/>(IncomingCall event)
    FastAPI->>FastAPI: Extract incomingCallContext

    FastAPI->>CallAuto: answer_call(context, callback, media_streaming)
    Note right of CallAuto: Media streaming WS URL<br/>= /api/media-stream
    CallAuto-->>FastAPI: Call answered

    CallAuto->>FastAPI: POST /api/callback<br/>(CallConnected)
    FastAPI->>FastAPI: Update call status = LISTENING

    CallAuto->>FastAPI: WebSocket /api/media-stream
    FastAPI->>VL: connect(endpoint, agent, project)
    VL-->>FastAPI: Session established
    FastAPI->>VL: session.update(config)

    loop Conversation
        Caller->>PSTN: Speech
        PSTN->>ACS: Audio stream
        ACS->>FastAPI: Media stream audio
        FastAPI->>VL: input_audio_buffer.append

        VL->>Agent: Process speech
        Agent-->>VL: Audio response

        VL-->>FastAPI: RESPONSE_AUDIO_DELTA
        FastAPI->>ACS: Audio response
        ACS->>PSTN: Play audio
        PSTN-->>Caller: Hear response
    end

    Caller->>PSTN: Hang up
    ACS->>FastAPI: POST /api/callback<br/>(CallDisconnected)
    FastAPI->>FastAPI: Cleanup call state
```

---

## 4. Context Resolution Flow

```mermaid
sequenceDiagram
    participant User
    participant Router as Router Node
    participant Context as Context Resolver
    participant LLM as Azure OpenAI
    participant Specialist as Specialist Agent

    Note over User,Router: Previous turn
    User->>Router: "Is milk in stock?"
    Router->>Specialist: Route to store agent
    Specialist-->>User: "Yes, at Islington and Camden.<br/>Want directions or to order online?"

    Note over User,Router: Current turn (ambiguous)
    User->>Router: "yes"
    Router->>Router: Heuristic: no keyword match
    Router->>LLM: classify_intent("yes", history)
    LLM-->>Router: "clarification_confirmation"

    Router->>Context: context_resolver_node(state)
    Context->>LLM: "Resolve: user said 'yes' after<br/>'Want directions or to order online?'"
    LLM-->>Context: {type: "clarification",<br/>query: "Did you mean directions or ordering online?"}

    Context-->>User: "Just to clarify — would you like<br/>directions to the store, or help ordering online?"
```

---

## 5. Product Search Flow

```mermaid
sequenceDiagram
    participant Agent as Store Agent
    participant Tool as search_products()
    participant DB as Database
    participant Scorer as Scoring Engine

    Agent->>Tool: search_products(query="organic milk",<br/>dietary_filters=["organic"])
    
    Tool->>DB: load_db_inventory_data()
    DB-->>Tool: 20+ products

    Tool->>Tool: Synonym resolution
    Tool->>Tool: Tokenise → ["organic", "milk"]

    loop Each product
        Tool->>Scorer: Calculate score
        Scorer->>Scorer: Name exact match? (+150)
        Scorer->>Scorer: Name partial? (+100)
        Scorer->>Scorer: Word in name? (+40)
        Scorer->>Scorer: Category? (+30)
        Scorer->>Scorer: Tag? (+20)
        Scorer->>Scorer: Description? (+10)
        Scorer-->>Tool: score
    end

    Tool->>Tool: Filter: score > 0
    Tool->>Tool: Filter: organic == 1
    Tool->>Tool: Sort: stock → popularity → rating
    Tool->>Tool: Limit to 5 results
    Tool->>Tool: Format as markdown

    Tool-->>Agent: "Found 1 matching product:\n\n1. **Organic Whole Milk 2L** - £1.89\n   ⭐ 4.3 | 📍 In stock at all stores"
```

---

## 6. Refund Processing Flow

```mermaid
sequenceDiagram
    participant User
    participant Agent as Refund Agent
    participant LLM as Azure OpenAI
    participant Tool as issue_refund()
    participant DB as Database

    User->>Agent: "The eggs in my latest delivery were broken"
    Agent->>LLM: Process with refund instructions + context
    LLM->>LLM: Identify order ORD-99102 (in_transit)
    LLM-->>Agent: tool_call: issue_refund(order_id="ORD-99102",<br/>reason="Broken eggs")

    Agent->>Tool: issue_refund("ORD-99102", "Broken eggs")
    Tool->>DB: Load customer data
    Tool->>Tool: Find order ORD-99102
    Tool->>Tool: Verify status = "in_transit" or "delivered"
    Tool->>Tool: Calculate refund amount from items
    Tool->>Tool: Generate refund reference REF-XXXXX
    Tool->>DB: Insert refund record
    Tool->>DB: Update order status
    DB-->>Tool: Success
    Tool-->>Agent: "Refund of £3.50 processed for ORD-99102.<br/>Reference: REF-XXXXX"

    Agent->>LLM: Re-invoke with tool result
    LLM-->>Agent: "I'm sorry about the broken eggs. I've processed<br/>a refund of £3.50 for order ORD-99102."

    Agent-->>User: Formatted response
```

---

## 7. Token Refresh Flow

```mermaid
sequenceDiagram
    participant Handler as Request Handler
    participant Router as AgentRouter
    participant Azure as Azure Identity
    participant Cache as Token Cache

    Handler->>Router: handle(message, history)
    Router->>Router: _get_llm()

    Router->>Cache: Check _cached_token
    alt Token missing or expires in < 300s
        Router->>Azure: credential.get_token<br/>("https://ai.azure.com/.default")
        Azure-->>Router: AccessToken(token, expires_on)
        Router->>Cache: Store token + expiry
        Router->>Router: Create new ChatOpenAI(api_key=token)
        Router->>Cache: Store LLM instance
    else Token valid (> 300s remaining)
        Router->>Cache: Return cached ChatOpenAI
    end

    Cache-->>Router: ChatOpenAI instance
    Router-->>Handler: Continue processing
```

---

## 8. Database Initialisation Flow

```mermaid
sequenceDiagram
    participant App as FastAPI Startup
    participant DB as database.py
    participant Seed as seed_data.py

    App->>DB: init_db()
    DB->>DB: get_db_type() → sqlite or postgres
    DB->>DB: CREATE TABLE customer
    DB->>DB: CREATE TABLE orders
    DB->>DB: CREATE TABLE order_items
    DB->>DB: CREATE TABLE refunds
    DB->>DB: CREATE TABLE stores
    DB->>DB: CREATE TABLE products (45 columns)
    DB->>DB: CREATE TABLE product_stock
    DB->>DB: CREATE TABLE promotions

    App->>DB: seed_db()
    DB->>DB: check_needs_reseed()
    alt Schema outdated
        DB->>DB: DROP all 8 tables
        DB->>DB: init_db() again
    end

    DB->>DB: SELECT COUNT(*) FROM customer
    alt = 0
        DB->>Seed: Import CUSTOMER_SEED
        DB->>DB: INSERT 1 customer
        DB->>DB: INSERT 4 orders
        DB->>DB: INSERT 12 order_items
        DB->>DB: INSERT 3 refunds
    end

    DB->>DB: SELECT COUNT(*) FROM products
    alt = 0
        DB->>Seed: Import INVENTORY_SEED
        DB->>DB: INSERT 3 stores
        loop 20+ products
            DB->>DB: decorate_product(item) → rich metadata
            DB->>DB: INSERT product
            DB->>DB: INSERT stock (3 per product)
        end
        DB->>DB: INSERT 5 promotions
    end
```

---

## 9. Filler Audio Playback Flow

```mermaid
sequenceDiagram
    participant User
    participant Browser
    participant FillerSystem as Filler System
    participant AudioQueue as Audio Queue
    participant VoiceLive as Voice Live

    User->>Browser: Stops speaking
    Browser->>Browser: awaitingResponse = true
    Browser->>FillerSystem: Start filler timer (5s grace)

    alt Response arrives < 5s
        VoiceLive-->>Browser: RESPONSE_AUDIO_DELTA
        Browser->>FillerSystem: Cancel filler timer
        Browser->>AudioQueue: Queue audio chunk
        AudioQueue->>Browser: Play response audio
    else Response takes > 5s
        FillerSystem->>FillerSystem: Pick random tree (0-4)
        FillerSystem->>Browser: Play tree[0] clip
        Note right of Browser: "Let me check that for you"
        
        loop Until response arrives
            FillerSystem->>FillerSystem: Wait 3.5-6s
            FillerSystem->>Browser: Play thinking clip
            Note right of Browser: "Hmm..."
            FillerSystem->>FillerSystem: Wait 3.5-6s
            FillerSystem->>Browser: Play tree[next] clip
        end

        VoiceLive-->>Browser: RESPONSE_AUDIO_DELTA
        Browser->>FillerSystem: Stop filler (fillerActive = false)
        Browser->>AudioQueue: Queue response audio
        AudioQueue->>Browser: Play response immediately
    end
```

---

## 10. Suggestion Generation Flow

```mermaid
sequenceDiagram
    participant Graph as LangGraph
    participant Router as AgentRouter
    participant LLM as Azure OpenAI

    Note over Graph: After specialist response
    Graph->>Graph: reply = "Your milk is in stock at..."

    Graph->>Router: validation_node → generate suggestions

    Router->>LLM: System: "Generate 3-5 follow-up suggestions<br/>based on this conversation"
    Note right of LLM: Context includes:<br/>• Current reply<br/>• Customer profile<br/>• Order history<br/>• Previous topics

    LLM-->>Router: [<br/>"Check stock at other stores",<br/>"What dairy products do you have?",<br/>"Show me current promotions"<br/>]

    Router->>Router: Store in state.suggestions
    Router-->>Graph: suggestions = [...]

    Note over Graph: Included in final response
```
