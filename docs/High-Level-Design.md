# High-Level Design (HLD)

## 1. Overall Architecture Diagram

```mermaid
graph TB
    subgraph "Client Layer"
        Browser["🌐 Browser<br/>(Chat + Voice)"]
        Phone["📞 PSTN Phone"]
    end

    subgraph "API Gateway"
        FastAPI["FastAPI Server<br/>(main.py)"]
    end

    subgraph "Orchestration Layer"
        Router["AgentRouter<br/>(Singleton)"]
        LangGraph["LangGraph<br/>Compiled Graph"]
    end

    subgraph "Agent Layer"
        RouterNode["Router Node<br/>(Intent Classification)"]
        ContextNode["Context Resolver Node"]
        SpecialistNode["Specialist Agent Node"]
        ToolNode["Tool Execution Node"]
        ValidationNode["Validation Node"]
    end

    subgraph "Azure AI Services"
        Foundry["Azure AI Foundry<br/>(Agent Instructions)"]
        OpenAI["Azure OpenAI<br/>(GPT-4o / GPT-5.1)"]
        VoiceLive["Azure Voice Live<br/>(Real-time Speech)"]
        ACS["Azure Communication<br/>Services"]
        Speech["Azure Cognitive<br/>Services Speech"]
    end

    subgraph "Data Layer"
        SQLite["SQLite<br/>(Development)"]
        PostgreSQL["Azure PostgreSQL<br/>(Production)"]
    end

    subgraph "Telemetry"
        Monitor["Azure Monitor<br/>+ Application Insights"]
    end

    Browser -->|"HTTP POST /chat<br/>SSE Streaming"| FastAPI
    Browser -->|"WebSocket<br/>/api/voice-realtime"| FastAPI
    Phone -->|"PSTN Call"| ACS
    ACS -->|"WebSocket<br/>/api/media-stream"| FastAPI

    FastAPI --> Router
    Router --> LangGraph
    LangGraph --> RouterNode
    RouterNode -->|"specialist"| SpecialistNode
    RouterNode -->|"clarification"| ContextNode
    RouterNode -->|"greeting/thanks"| ValidationNode
    ContextNode --> SpecialistNode
    ContextNode --> ValidationNode
    SpecialistNode --> ToolNode
    SpecialistNode --> ValidationNode
    ToolNode --> SpecialistNode
    ValidationNode -->|"Final Response"| FastAPI

    Router -->|"Fetch Instructions"| Foundry
    SpecialistNode -->|"LLM Inference"| OpenAI
    RouterNode -->|"Intent Classification"| OpenAI
    FastAPI -->|"Voice Relay"| VoiceLive
    VoiceLive --> Foundry
    ToolNode --> SQLite
    ToolNode --> PostgreSQL
    FastAPI -->|"Traces"| Monitor
    Speech -->|"TTS Filler Clips"| FastAPI
```

## 2. System Context Diagram

```mermaid
graph LR
    subgraph "External Actors"
        Customer["👤 Customer"]
        BusinessUser["👔 Business User<br/>(AI Foundry Portal)"]
    end

    subgraph "System Boundary"
        System["Retail AI Assistant<br/>──────────────────<br/>• Chat API<br/>• Voice API<br/>• Agent Orchestration<br/>• Tool Execution<br/>• Database"]
    end

    subgraph "External Systems"
        AzureAI["Azure AI Foundry"]
        AzureOpenAI["Azure OpenAI"]
        AzureACS["Azure Communication Services"]
        AzureVL["Azure Voice Live"]
        AzureDB["Azure PostgreSQL"]
        AzureMonitor["Azure Monitor"]
    end

    Customer -->|"Chat Messages<br/>Voice Audio<br/>Phone Calls"| System
    System -->|"Responses<br/>Product Cards<br/>Voice Audio"| Customer

    BusinessUser -->|"Update Agent<br/>Instructions"| AzureAI

    System -->|"Agent Instructions<br/>Model Inference"| AzureAI
    System -->|"LLM Completions<br/>Tool Calling"| AzureOpenAI
    System -->|"Telephony<br/>Identity Tokens"| AzureACS
    System -->|"Real-time<br/>Voice Relay"| AzureVL
    System -->|"Data Persistence"| AzureDB
    System -->|"Telemetry<br/>Traces"| AzureMonitor
```

## 3. Component Interaction Diagram

```mermaid
graph TD
    subgraph "Frontend Components"
        ChatUI["Chat UI<br/>(index.html)"]
        VoiceUI["Voice Controls<br/>(app.js)"]
        ProductGrid["Product Grid<br/>Renderer"]
        Sidebar["Customer<br/>Sidebar"]
    end

    subgraph "Backend Components"
        MainApp["FastAPI App<br/>(main.py)"]
        AgentRouter["AgentRouter<br/>(router.py)"]
        GraphEngine["LangGraph Engine<br/>(graph.py)"]
        IntentService["Intent Classifier<br/>(intent.py)"]
        ToolExecutor["Tool Functions<br/>(tools.py)"]
        Validator["Validation Layer<br/>(validation.py)"]
        FoundryConfig["Foundry Config<br/>(foundry_config.py)"]
    end

    subgraph "Service Components"
        ACSBot["ACS Bot Manager<br/>(acs_bot.py)"]
        VoiceRealtime["Voice Realtime<br/>(voice_realtime.py)"]
        VoiceFillers["Voice Fillers<br/>(voice_fillers.py)"]
    end

    subgraph "Data Components"
        Database["Database Layer<br/>(database.py)"]
        SeedData["Seed Data<br/>(seed_data.py)"]
    end

    ChatUI --> MainApp
    VoiceUI --> MainApp
    MainApp --> AgentRouter
    AgentRouter --> GraphEngine
    GraphEngine --> IntentService
    GraphEngine --> ToolExecutor
    GraphEngine --> Validator
    AgentRouter --> FoundryConfig
    MainApp --> ACSBot
    MainApp --> VoiceRealtime
    MainApp --> VoiceFillers
    ToolExecutor --> Database
    Database --> SeedData
    MainApp --> Database
    Sidebar --> MainApp
    ProductGrid --> ChatUI
```

## 4. User Journey

```mermaid
journey
    title Customer Support Journey
    section Web Chat
        Open website: 5: Customer
        View welcome card: 4: Customer
        Type query: 5: Customer
        See streaming response: 5: Customer
        View product cards: 4: Customer
        Click suggestion chip: 5: Customer
        Continue conversation: 4: Customer
    section Voice (Browser)
        Click phone button: 4: Customer
        Speak query: 5: Customer
        Hear agent response: 5: Customer
        Barge-in to interrupt: 3: Customer
        End call: 5: Customer
    section Voice (Phone)
        Dial phone number: 5: Customer
        Hear greeting: 5: Customer
        Speak request: 5: Customer
        Hear filler audio: 4: Customer
        Hear agent answer: 5: Customer
        Hang up: 5: Customer
```

## 5. Request Flow

### Chat Request Flow

```mermaid
sequenceDiagram
    participant C as Customer Browser
    participant F as FastAPI
    participant R as AgentRouter
    participant G as LangGraph
    participant LLM as Azure OpenAI
    participant DB as Database

    C->>F: POST /chat {message, history, stream: true}
    F->>R: router.handle(message, history)
    R->>R: Load customer data & context
    R->>R: Get/refresh LLM token
    R->>G: compiled_graph.ainvoke(state, config)

    Note over G: Router Node
    G->>G: Check heuristic keywords
    alt Keyword Match
        G-->>G: Set specialist_role directly
    else No Match
        G->>LLM: classify_intent(message)
        LLM-->>G: intent label
    end

    Note over G: Specialist Agent Node
    G->>LLM: Invoke with tools + instructions
    LLM-->>G: Response or tool_calls

    alt Has Tool Calls
        Note over G: Tool Execution Node
        G->>DB: Execute tool (e.g., search_products)
        DB-->>G: Tool results
        G->>LLM: Re-invoke with tool results
        LLM-->>G: Final response
    end

    Note over G: Validation Node
    G->>G: Sanitize response, mask IDs

    G-->>R: Final state
    R-->>F: {reply, intent, sources, suggestions}
    F-->>C: SSE stream tokens
```

### Voice Request Flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as FastAPI
    participant VL as Voice Live SDK
    participant Agent as Foundry Agent
    participant DB as Database

    B->>F: WebSocket /api/voice-realtime
    F->>VL: connect(agent_name, project_name)
    VL-->>F: Connection established
    F->>VL: session.update(voice, VAD, formats)

    loop Audio Streaming
        B->>F: Raw PCM16 audio bytes
        F->>VL: input_audio_buffer.append(audio)
    end

    VL-->>F: SPEECH_STARTED
    F-->>B: {type: "speech_started"}

    VL-->>F: SPEECH_STOPPED
    F-->>B: {type: "speech_stopped"}

    VL-->>F: TRANSCRIPTION_COMPLETED (user text)
    F-->>B: {type: "user_transcript", text}

    VL->>Agent: Process with agent instructions
    Agent-->>VL: Response audio + text

    VL-->>F: RESPONSE_AUDIO_DELTA (audio chunks)
    F-->>B: {type: "audio_delta", delta}

    VL-->>F: RESPONSE_AUDIO_TRANSCRIPT_DONE
    F-->>B: {type: "agent_transcript", text}

    opt Tool Call Required
        VL-->>F: FUNCTION_CALL_ARGUMENTS_DONE
        F->>DB: execute_voice_tool(name, args)
        DB-->>F: Tool output
        F->>VL: conversation_item.create(function_call_output)
        F->>VL: response.create()
    end
```

## 6. Service Interaction Flow

```mermaid
flowchart TD
    Start([User Query]) --> Gateway[FastAPI Gateway]

    Gateway -->|"Chat"| ChatRoute[POST /chat]
    Gateway -->|"Voice Browser"| VoiceRoute[WS /api/voice-realtime]
    Gateway -->|"Phone Call"| ACSRoute[WS /api/media-stream]

    ChatRoute --> AgentRouter
    VoiceRoute --> VoiceLiveRelay[Voice Live Relay]
    ACSRoute --> ACSMediaRelay[ACS Media Stream Relay]

    AgentRouter --> LangGraphExec[LangGraph Execution]
    VoiceLiveRelay --> VoiceLiveService[Azure Voice Live]
    ACSMediaRelay --> VoiceLiveService

    LangGraphExec --> RouterNode[Router Node]
    RouterNode -->|Heuristic| SpecialistDirect[Specialist Agent]
    RouterNode -->|LLM| IntentLLM[Intent Classifier LLM]
    IntentLLM --> SpecialistDirect

    SpecialistDirect -->|Tool Call| ToolExec[Tool Execution]
    ToolExec --> DBLayer[(Database)]
    ToolExec --> SpecialistDirect

    SpecialistDirect --> Validation[Validation Node]
    Validation --> Response([Response to User])

    VoiceLiveService -->|Audio| BrowserClient([Browser Audio Playback])
    VoiceLiveService -->|Audio| ACSClient([Phone Audio Playback])
```

## 7. External Integrations

| Integration | Protocol | Authentication | Purpose |
|------------|----------|---------------|---------|
| Azure AI Foundry | REST API | AzureCliCredential / ClientSecretCredential | Fetch agent instructions, list agents |
| Azure OpenAI | REST API (via LangChain) | Entra ID Bearer Token | LLM inference, tool calling |
| Azure Voice Live | WebSocket (SDK) | AzureCliCredential / ClientSecretCredential | Real-time voice relay |
| Azure Communication Services | REST API | Connection String | PSTN call handling, identity tokens |
| Azure Cognitive Services Speech | REST API | Bearer Token | TTS for filler audio clips |
| Azure Monitor | OpenTelemetry OTLP | Connection String | Distributed tracing |
| Azure PostgreSQL | TCP (psycopg2) | Username/Password | Production data persistence |

## 8. Azure Architecture Diagram

```mermaid
graph TB
    subgraph "Azure AI Foundry Hub"
        Project["AI Foundry Project"]
        AgentDefs["Agent Definitions<br/>• Order-Agent<br/>• Delivery-Agent<br/>• Refund-Agent<br/>• Store-Agent<br/>• Intent-Classifier-Agent<br/>• Context-Resolver-Agent<br/>• Voice-Assistant-Agent"]
        ModelDeploy["Model Deployment<br/>(GPT-4o / GPT-5.1)"]
    end

    subgraph "Azure Communication Services"
        ACSResource["ACS Resource"]
        CallAutomation["Call Automation"]
        IdentityService["Identity + Tokens"]
    end

    subgraph "Azure Voice Live"
        VLEndpoint["Voice Live Endpoint"]
        VLSession["Voice Live Session<br/>(Agent Mode)"]
    end

    subgraph "Azure Database"
        PGServer["PostgreSQL Flexible Server"]
        PGDatabase["retail_chatbot DB"]
    end

    subgraph "Azure Monitoring"
        AppInsights["Application Insights"]
        LogAnalytics["Log Analytics Workspace"]
    end

    Project --> AgentDefs
    Project --> ModelDeploy
    VLEndpoint --> VLSession
    VLSession --> AgentDefs
    ACSResource --> CallAutomation
    ACSResource --> IdentityService
    PGServer --> PGDatabase
    AppInsights --> LogAnalytics
```

## 9. Technology Stack Diagram

```mermaid
graph TB
    subgraph "Presentation"
        HTML["HTML5"]
        CSS["CSS3 + Glassmorphism"]
        JS["Vanilla JavaScript"]
        WebAudio["Web Audio API"]
        ACSCallSDK["ACS Calling SDK"]
    end

    subgraph "Application"
        FastAPIFW["FastAPI 0.115.5"]
        Uvicorn["Uvicorn (ASGI)"]
        LangChainFW["LangChain"]
        LangGraphFW["LangGraph"]
        Pydantic["Pydantic Models"]
    end

    subgraph "Azure SDKs"
        AIAgents["azure-ai-agents 1.1.0"]
        VoiceLiveSDK["azure-ai-voicelive"]
        AzureIdentity["azure-identity 1.19.0"]
        ACSCallAuto["azure-communication-callautomation"]
        ACSIdentity["azure-communication-identity"]
        AzureSpeech["azure-cognitiveservices-speech 1.41.1"]
        AzureMonitorSDK["azure-monitor-opentelemetry"]
    end

    subgraph "Data"
        SQLiteDB["sqlite3 (stdlib)"]
        Psycopg2["psycopg2-binary"]
        ConnectionPool["ThreadedConnectionPool"]
    end

    HTML --> FastAPIFW
    CSS --> HTML
    JS --> HTML
    FastAPIFW --> Uvicorn
    FastAPIFW --> LangChainFW
    LangChainFW --> LangGraphFW
    FastAPIFW --> Pydantic
    LangChainFW --> AIAgents
    FastAPIFW --> VoiceLiveSDK
    FastAPIFW --> ACSCallAuto
    FastAPIFW --> ACSIdentity
    LangChainFW --> AzureIdentity
    FastAPIFW --> AzureSpeech
    FastAPIFW --> AzureMonitorSDK
    FastAPIFW --> SQLiteDB
    FastAPIFW --> Psycopg2
    Psycopg2 --> ConnectionPool
```

## 10. Deployment Architecture

```mermaid
graph TB
    subgraph "Development"
        DevMachine["Developer Machine"]
        LocalUvicorn["Uvicorn :8000"]
        LocalSQLite["SQLite DB<br/>(mock_data/)"]
        AzureCLI["az login<br/>(AzureCliCredential)"]
    end

    subgraph "Vercel Production"
        VercelEdge["Vercel Edge Network"]
        VercelFunc["Serverless Function<br/>(api/index.py)"]
        VercelStatic["Static Assets<br/>(frontend/)"]
        TmpDB["/tmp/retail_chatbot.db"]
    end

    subgraph "Azure Production"
        AzurePG["Azure PostgreSQL"]
        AzureFoundry["Azure AI Foundry"]
        AzureVoice["Azure Voice Live"]
        AzureACSProd["Azure Communication Services"]
    end

    DevMachine --> LocalUvicorn
    LocalUvicorn --> LocalSQLite
    DevMachine --> AzureCLI

    VercelEdge --> VercelFunc
    VercelEdge --> VercelStatic
    VercelFunc --> TmpDB
    VercelFunc --> AzurePG
    VercelFunc --> AzureFoundry
    VercelFunc --> AzureVoice
    VercelFunc --> AzureACSProd
```
