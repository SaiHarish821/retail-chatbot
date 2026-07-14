# Low-Level Design (LLD)

## 1. Folder Structure

```
retail-chatbot/
├── .env                              # Environment variables (secrets, endpoints, agent names)
├── .env.example                      # Template for .env configuration
├── .gitignore                        # Git exclusions (venv, .env, __pycache__, .db, node_modules)
├── README.md                         # Project overview and getting started
├── requirements.txt                  # Python dependencies (26 packages)
├── vercel.json                       # Vercel URL rewrite rules for serverless deployment
├── current_agents_backup.json        # Snapshot of Azure AI Foundry agent definitions
│
├── api/                              # Vercel serverless entrypoint
│   ├── index.py                      # Imports and re-exports FastAPI app for Vercel
│   └── requirements.txt              # Vercel-specific Python dependencies
│
├── backend/                          # Python backend application
│   ├── main.py                       # FastAPI app definition, routes, CORS, WebSocket handlers
│   │
│   ├── agents/                       # AI agent orchestration package
│   │   ├── __init__.py               # Exports AgentRouter
│   │   ├── router.py                 # AgentRouter class: client init, instruction fetch, LLM caching, handle()
│   │   ├── graph.py                  # LangGraph state graph: nodes, edges, conditional routing
│   │   ├── intent.py                 # Intent classification (heuristic + LLM) and context resolution
│   │   ├── tools.py                  # Tool function implementations (search, stock, refund, address, promotions)
│   │   ├── validation.py             # Response validation, sanitisation, security guardrails
│   │   └── foundry_config.py         # Centralised Azure AI Foundry configuration dataclass
│   │
│   ├── database/                     # Database abstraction layer
│   │   ├── __init__.py               # Exports init_db, seed_db, load/save functions, get_connection
│   │   ├── database.py               # DDL, connection pooling, CRUD, dual SQLite/PostgreSQL support
│   │   └── seed_data.py              # Hardcoded seed data (customer, orders, 20+ products, 3 stores)
│   │
│   ├── services/                     # External service integrations
│   │   ├── __init__.py               # Exports ACSBotManager
│   │   ├── acs_bot.py                # Azure Communication Services call automation manager
│   │   ├── voice_realtime.py         # Voice Live tool execution, credential resolution, realtime tools
│   │   └── voice_fillers.py          # Pre-rendered TTS filler audio clip system
│   │
│   └── tests/                        # Backend test suite
│       ├── __init__.py               # Test package marker
│       ├── test_followup.py          # Context resolution and follow-up conversation tests
│       ├── test_voice_data.py        # Voice data processing tests
│       └── test_voice_pipeline.py    # Voice pipeline integration tests
│
├── frontend/                         # Browser-based SPA
│   ├── index.html                    # Full Sainsbury's-themed page (2452 lines, all-in-one)
│   ├── css/
│   │   └── styles.css                # Chat widget, glassmorphism, responsive styles
│   ├── js/
│   │   ├── app.js                    # Chat/voice controller, SSE streaming, WebSocket voice, phone call
│   │   ├── azure-sdk.js              # Azure SDK shim/stub (263 bytes)
│   │   └── azure-communication-services.js  # Bundled ACS Web Calling SDK (5.5MB)
│   ├── images/
│   │   └── products/                 # Product image assets
│   ├── test_runner.html              # Automated test runner UI
│   └── test_cases.json               # Test scenario definitions
│
├── mock_data/                        # Persistent data files
│   ├── retail_chatbot.db             # SQLite database (auto-seeded on first run)
│   └── test_results.json             # Test runner output
│
├── Tools/                            # Azure AI Foundry tool definitions (JSON)
│   ├── search_products.json          # Product search tool schema
│   ├── check_stock.json              # Stock check tool schema
│   ├── issue_refund.json             # Refund tool schema
│   ├── get_active_promotions.json    # Promotions tool schema
│   └── update_customer_address.json  # Address update tool schema
│
└── scratch/                          # Temporary development files
```

## 2. File Responsibilities

### Backend Core

| File | Lines | Responsibility |
|------|-------|---------------|
| `main.py` | 792 | FastAPI app setup, all HTTP/WS routes, CORS, static files, telemetry init, filler clip pre-rendering |
| `router.py` | 325 | `AgentRouter` class — client initialisation, instruction fetching, LLM token caching, `handle()` entry point |
| `graph.py` | 509 | LangGraph `StateGraph` definition — 5 nodes, conditional edges, compiled graph singleton |
| `intent.py` | 150 | `classify_intent()` and `resolve_context()` — hybrid heuristic + LLM classification |
| `tools.py` | 645 | 5 tool functions + helpers: `search_products`, `check_stock`, `get_active_promotions`, `update_customer_address`, `issue_refund` |
| `validation.py` | 161 | `validate_and_sanitize_response()`, `check_security_guardrails()`, `run_validation_layer()`, `is_raw_routing_json()` |
| `foundry_config.py` | 161 | `FoundryConfig` and `AgentNames` dataclasses — singleton configuration |

### Database

| File | Lines | Responsibility |
|------|-------|---------------|
| `database.py` | 1051 | DDL schema (7 tables), `DatabaseConnection`/`DatabaseCursor` wrappers, connection pooling, CRUD, inventory caching |
| `seed_data.py` | 6* | Hardcoded Python dicts: `CUSTOMER_SEED` (1 customer, 4 orders) and `INVENTORY_SEED` (20+ products, 3 stores) |

*seed_data.py is 6 lines but contains ~66KB of inline data

### Services

| File | Lines | Responsibility |
|------|-------|---------------|
| `acs_bot.py` | 155 | `ACSBotManager` — identity/token creation, incoming call answering, media streaming, callback event handling |
| `voice_realtime.py` | 177 | Azure credential resolution, `execute_voice_tool()`, `strip_markdown()`, `REALTIME_TOOLS` JSON definitions |
| `voice_fillers.py` | 125 | Filler phrase definitions (5 trees × 4 phrases + 6 thinking clips), TTS synthesis, parallel rendering |

### Frontend

| File | Lines | Responsibility |
|------|-------|---------------|
| `index.html` | 2452 | Full Sainsbury's page: header, hero, product grid, chat widget, phone call UI, customer sidebar |
| `app.js` | 2273 | Chat controller, SSE streaming, voice recording, WebSocket voice relay, phone call mode, product grid rendering |
| `styles.css` | ~900 | Chat widget styling, glassmorphism effects, responsive breakpoints, animations |

## 3. Module Responsibilities

```mermaid
graph TD
    subgraph "agents package"
        A1["router.py<br/>─────────<br/>• Client initialisation<br/>• Instruction fetching<br/>• LLM token caching<br/>• handle() entry point"]
        A2["graph.py<br/>─────────<br/>• State definition<br/>• Node implementations<br/>• Conditional routing<br/>• Graph compilation"]
        A3["intent.py<br/>─────────<br/>• Heuristic classification<br/>• LLM intent calling<br/>• Context resolution<br/>• Acknowledgement detection"]
        A4["tools.py<br/>─────────<br/>• Product search<br/>• Stock checking<br/>• Refund processing<br/>• Address updates<br/>• Promotion retrieval"]
        A5["validation.py<br/>─────────<br/>• Security guardrails<br/>• Markdown sanitisation<br/>• ID masking<br/>• PII protection"]
        A6["foundry_config.py<br/>─────────<br/>• Config dataclass<br/>• Agent name mapping<br/>• Validation warnings"]
    end

    A1 --> A2
    A2 --> A3
    A2 --> A4
    A2 --> A5
    A1 --> A6
```

## 4. API Flow

```mermaid
sequenceDiagram
    participant Client
    participant FastAPI
    participant AgentRouter
    participant LangGraph
    participant OpenAI
    participant Database

    Client->>FastAPI: POST /chat {message, history, stream}
    FastAPI->>FastAPI: Parse ChatRequest (Pydantic)
    FastAPI->>AgentRouter: handle(message, history, is_voice, stream_queue)

    AgentRouter->>Database: load_db_customer_data() [async thread]
    AgentRouter->>AgentRouter: build_context_block(customer_data)
    AgentRouter->>AgentRouter: _get_llm() [token refresh if needed]

    AgentRouter->>LangGraph: compiled_graph.ainvoke(initial_state, config)

    Note over LangGraph: router_node
    LangGraph->>LangGraph: Check static (greeting/thanks)
    LangGraph->>LangGraph: Check heuristic keywords
    alt No heuristic match
        LangGraph->>OpenAI: classify_intent(message, history)
        OpenAI-->>LangGraph: intent label
    end

    Note over LangGraph: specialist_agent_node
    LangGraph->>LangGraph: Load role instructions
    LangGraph->>LangGraph: Build message thread
    LangGraph->>LangGraph: Bind tools to LLM
    LangGraph->>OpenAI: llm_with_tools.ainvoke(messages)
    OpenAI-->>LangGraph: response (text or tool_calls)

    opt Tool calls present
        Note over LangGraph: tool_execution_node
        LangGraph->>Database: Execute tool function
        Database-->>LangGraph: Tool result
        LangGraph->>OpenAI: Re-invoke with ToolMessage
        OpenAI-->>LangGraph: Final text response
    end

    Note over LangGraph: validation_node
    LangGraph->>LangGraph: run_validation_layer()
    LangGraph->>LangGraph: append_product_grid_if_mentioned()

    LangGraph-->>AgentRouter: Final state
    AgentRouter-->>FastAPI: {reply, intent, sources, suggestions}
    FastAPI-->>Client: ChatResponse / SSE stream
```

## 5. LangGraph Workflow

```mermaid
stateDiagram-v2
    [*] --> router_node

    router_node --> validation_node: greeting / thanks / out_of_scope
    router_node --> context_resolver_node: clarification_confirmation
    router_node --> specialist_agent_node: specialist

    context_resolver_node --> validation_node: clarification
    context_resolver_node --> specialist_agent_node: resolved_query

    specialist_agent_node --> tool_execution_node: has tool_calls
    specialist_agent_node --> validation_node: no tool_calls

    tool_execution_node --> specialist_agent_node: tool results

    validation_node --> [*]
```

## 6. Azure AI Foundry Integration

```mermaid
sequenceDiagram
    participant Router as AgentRouter
    participant Foundry as Azure AI Foundry
    participant OpenAI as Azure OpenAI

    Note over Router: Startup (_init_clients)
    Router->>Router: AzureCliCredential(tenant_id)
    Router->>Foundry: AIProjectClient(endpoint, credential)
    Foundry-->>Router: project_client
    Router->>Foundry: project_client.get_openai_client()
    Foundry-->>Router: openai_client

    Note over Router: Startup (_fetch_instructions)
    Router->>Foundry: project_client.agents.list()
    Foundry-->>Router: List of agent definitions
    loop Each role (order, delivery, refund, store, ...)
        Router->>Router: Match agent by name
        Router->>Router: Extract instructions from definition
        Router->>Router: Store in _agent_instructions dict
    end

    Note over Router: Runtime (handle)
    Router->>Router: _get_llm() → ChatOpenAI(token, base_url)
    Router->>OpenAI: LLM inference via LangChain
    OpenAI-->>Router: Completion / tool calls
```

## 7. Azure Database Integration

```mermaid
flowchart TD
    Start([Application Start]) --> DetectDB{Check DB_HOST<br/>env var}

    DetectDB -->|Set| TryPG[Try PostgreSQL<br/>Connection]
    DetectDB -->|Not Set| UseSQLite[Use SQLite]

    TryPG -->|Success| SetPG[_cached_db_type = postgres]
    TryPG -->|Fail| UseSQLite

    UseSQLite --> SetSQLite[_cached_db_type = sqlite]

    SetPG --> InitPool[Create ThreadedConnectionPool<br/>minconn=1, maxconn=20]
    SetSQLite --> InitSQLite[sqlite3.connect(DB_PATH)]

    InitPool --> GetConn[get_connection()]
    InitSQLite --> GetConn

    GetConn --> DBConn[DatabaseConnection wrapper]
    DBConn --> DBCursor[DatabaseCursor wrapper<br/>• ? → %s translation<br/>• AUTOINCREMENT → SERIAL<br/>• INSERT OR IGNORE → ON CONFLICT<br/>• Retry policy (3 attempts)]
```

## 8. Voice Live Integration

```mermaid
sequenceDiagram
    participant Browser
    participant FastAPI
    participant VoiceLive as Azure Voice Live
    participant Agent as Foundry Agent

    Browser->>FastAPI: WebSocket connect /api/voice-realtime
    FastAPI->>FastAPI: Resolve credentials & endpoint
    FastAPI->>VoiceLive: connect(endpoint, agent_name, project_name)
    VoiceLive-->>FastAPI: Connection established

    FastAPI->>VoiceLive: session.update(RequestSession)
    Note right of VoiceLive: • Modalities: TEXT + AUDIO<br/>• Format: PCM16<br/>• VAD: threshold=0.5<br/>• Voice: en-US-Ava:DragonHDLatest

    par Browser → Voice Live
        loop Audio frames
            Browser->>FastAPI: Raw PCM16 bytes
            FastAPI->>VoiceLive: input_audio_buffer.append(b64)
        end
    and Voice Live → Browser
        loop Events
            VoiceLive-->>FastAPI: Server events
            FastAPI-->>Browser: JSON messages
        end
    end
```

## 9. Authentication Flow

```mermaid
flowchart TD
    Start([Need Azure Credential]) --> CheckEnv{AZURE_CLIENT_ID +<br/>AZURE_CLIENT_SECRET<br/>set?}

    CheckEnv -->|Yes| UseCSC[ClientSecretCredential<br/>(tenant_id, client_id, client_secret)]
    CheckEnv -->|No| UseAzCLI[AzureCliCredential<br/>(tenant_id)]

    UseCSC --> GetToken[credential.get_token<br/>'https://ai.azure.com/.default']
    UseAzCLI --> GetToken

    GetToken --> CacheToken[Cache token + expires_on]
    CacheToken --> CreateLLM[ChatOpenAI<br/>(api_key=token, base_url)]

    CreateLLM --> CheckExpiry{Token expires<br/>in < 300s?}
    CheckExpiry -->|Yes| GetToken
    CheckExpiry -->|No| UseCached[Use cached LLM instance]
```

## 10. Configuration Flow

```mermaid
flowchart LR
    subgraph "Environment"
        EnvFile[".env file"]
        EnvVars["System env vars"]
    end

    subgraph "Load"
        DotEnv["load_dotenv()"]
    end

    subgraph "Configuration"
        FoundryConfig["FoundryConfig<br/>(dataclass singleton)"]
        AgentNames["AgentNames<br/>(dataclass)"]
    end

    subgraph "Runtime"
        Router["AgentRouter"]
        VoiceRT["voice_realtime.py"]
        MainApp["main.py"]
    end

    EnvFile --> DotEnv
    EnvVars --> DotEnv
    DotEnv --> FoundryConfig
    FoundryConfig --> AgentNames
    FoundryConfig --> Router
    FoundryConfig --> VoiceRT
    FoundryConfig --> MainApp
```

## 11. Dependency Relationships

```mermaid
graph TD
    subgraph "Entry Points"
        Main["main.py"]
        APIIndex["api/index.py"]
    end

    subgraph "agents/"
        Init["__init__.py"]
        Router["router.py"]
        Graph["graph.py"]
        Intent["intent.py"]
        Tools["tools.py"]
        Validation["validation.py"]
        FoundryConf["foundry_config.py"]
    end

    subgraph "database/"
        DBInit["__init__.py"]
        Database["database.py"]
        SeedData["seed_data.py"]
    end

    subgraph "services/"
        SvcInit["__init__.py"]
        ACSBot["acs_bot.py"]
        VoiceRT["voice_realtime.py"]
        VoiceFillers["voice_fillers.py"]
    end

    APIIndex -->|imports| Main
    Main -->|imports| Init
    Main -->|imports| SvcInit
    Main -->|imports| DBInit
    Main -->|imports| VoiceFillers
    Main -->|imports| VoiceRT

    Init -->|exports| Router
    SvcInit -->|exports| ACSBot

    Router -->|imports| Validation
    Router -->|imports| Tools
    Router -->|imports| Graph

    Graph -->|imports| Intent
    Graph -->|imports| Validation
    Graph -->|imports| Tools

    Tools -->|imports| Database
    Database -->|imports| SeedData
    VoiceRT -->|imports| Tools

    DBInit -->|exports| Database
```

## 12. Class Relationships

```mermaid
classDiagram
    class AgentRouter {
        +customer_data: dict
        +context: str
        -_openai_client: OpenAI
        -_project_client: AIProjectClient
        -_agent_instructions: dict
        -_agent_ids: dict
        -_llm_instance: ChatOpenAI
        -_token_expires_on: float
        -_cached_token: str
        +__init__(customer_data)
        -_init_clients()
        -_fetch_instructions()
        -_get_llm(): ChatOpenAI
        -_load_customer_data(): dict
        -_save_customer_data(data)
        -_load_inventory_data(): dict
        +handle(message, history, is_voice, stream_queue): dict
        +check_stock(product_name, store_name): str
        +search_products(query, ...): str
        +get_active_promotions(): str
        +update_customer_address(line1, city, postcode): str
        +issue_refund(order_id, reason, amount): str
        +append_product_grid_if_mentioned(reply): str
    }

    class AgentState {
        <<TypedDict>>
        +messages: List~BaseMessage~
        +message_text: str
        +history: List~dict~
        +customer_data: dict
        +context_block: str
        +is_voice: bool
        +intent: str
        +specialist_role: str
        +reply: str
        +sources: List~str~
        +suggestions: List~str~
        +handoff_required: bool
        +agent_instructions: dict
        +error: Optional~str~
    }

    class ACSBotManager {
        +active_calls: dict
        +connection_string: str
        +public_callback_url: str
        +call_automation_client: CallAutomationClient
        +identity_client: CommunicationIdentityClient
        +bot_user_id: str
        +get_token_for_user(): dict
        +answer_incoming_call(context): result
        +handle_callback_events(events, router)
    }

    class FoundryConfig {
        <<frozen dataclass>>
        +project_endpoint: str
        +api_key: str
        +openai_endpoint: str
        +deployment_name: str
        +voice_deployment_name: str
        +tenant_id: str
        +agent_names: AgentNames
        +has_api_key: bool
        +has_project_endpoint: bool
        +validate(): list
    }

    class AgentNames {
        <<frozen dataclass>>
        +order: str
        +delivery: str
        +refund: str
        +store: str
        +general: str
        +intent_classifier: str
        +context_resolver: str
        +voice_assistant: str
        +as_dict(): dict
    }

    class DatabaseConnection {
        +conn: Connection
        +db_type: str
        +cursor(): DatabaseCursor
        +commit()
        +rollback()
        +close()
    }

    class DatabaseCursor {
        +cursor: Cursor
        +db_type: str
        +execute(query, params)
        +fetchone()
        +fetchall()
        +close()
    }

    AgentRouter --> AgentState: creates
    AgentRouter --> ACSBotManager: used alongside
    AgentRouter --> FoundryConfig: reads config
    FoundryConfig --> AgentNames: contains
    DatabaseConnection --> DatabaseCursor: creates
    AgentRouter --> DatabaseConnection: uses via tools
```

## 13. State Diagram — LangGraph Execution

```mermaid
stateDiagram-v2
    [*] --> Initializing: handle() called

    Initializing --> RouterEval: Load data + build context
    
    state RouterEval {
        [*] --> CheckStatic
        CheckStatic --> StaticReply: greeting/thanks match
        CheckStatic --> CheckVoice: no match
        CheckVoice --> HeuristicRoute: is_voice=true
        CheckVoice --> CheckHeuristic: is_voice=false
        CheckHeuristic --> HeuristicRoute: keyword match
        CheckHeuristic --> LLMClassify: no match
        LLMClassify --> IntentResolved: label returned
    }

    RouterEval --> Validation: greeting/thanks/out_of_scope
    RouterEval --> ContextResolve: clarification_confirmation
    RouterEval --> SpecialistExec: specialist

    state ContextResolve {
        [*] --> LLMResolve
        LLMResolve --> Clarification: ambiguous options
        LLMResolve --> Resolved: query resolved
    }

    ContextResolve --> Validation: clarification
    ContextResolve --> SpecialistExec: resolved query

    state SpecialistExec {
        [*] --> BuildPrompt
        BuildPrompt --> InvokeLLM
        InvokeLLM --> HasTools: tool_calls returned
        InvokeLLM --> NoTools: text returned
    }

    SpecialistExec --> ToolExec: has tool_calls
    SpecialistExec --> Validation: no tool_calls

    state ToolExec {
        [*] --> ExecuteTools
        ExecuteTools --> ReturnResults
    }

    ToolExec --> SpecialistExec: tool results (loop back)

    Validation --> [*]: sanitised reply
```

## 14. Component Diagram

```mermaid
graph TB
    subgraph "API Layer"
        ChatEndpoint["POST /chat"]
        VoiceChatEndpoint["POST /chat/voice"]
        CustomerEndpoint["GET /customer"]
        InventoryEndpoint["GET /inventory"]
        HealthEndpoint["GET /health"]
        TokenEndpoint["GET /api/token"]
        CallStatusEndpoint["GET /api/call-status"]
        IncomingCallEndpoint["POST /api/incoming-call"]
        CallbackEndpoint["POST /api/callback"]
        FillersEndpoint["GET /api/fillers"]
        VoiceRealtimeWS["WS /api/voice-realtime"]
        MediaStreamWS["WS /api/media-stream"]
        SaveResultsEndpoint["POST /api/save_results"]
    end

    subgraph "Business Logic"
        RouterComp["AgentRouter"]
        GraphComp["LangGraph Engine"]
        IntentComp["Intent Classifier"]
        ToolComp["Tool Functions"]
        ValidComp["Validation Engine"]
    end

    subgraph "Infrastructure"
        DBComp["Database Adapter"]
        ACSComp["ACS Bot Manager"]
        VLComp["Voice Live Relay"]
        FillerComp["Filler Renderer"]
        ConfigComp["Foundry Config"]
    end

    ChatEndpoint --> RouterComp
    VoiceChatEndpoint --> RouterComp
    VoiceRealtimeWS --> VLComp
    MediaStreamWS --> VLComp
    TokenEndpoint --> ACSComp
    IncomingCallEndpoint --> ACSComp
    CallbackEndpoint --> ACSComp
    FillersEndpoint --> FillerComp
    CustomerEndpoint --> DBComp
    InventoryEndpoint --> DBComp

    RouterComp --> GraphComp
    GraphComp --> IntentComp
    GraphComp --> ToolComp
    GraphComp --> ValidComp
    ToolComp --> DBComp
    RouterComp --> ConfigComp
    VLComp --> ToolComp
```
