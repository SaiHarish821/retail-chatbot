# 🗺️ Architecture Diagrams — Simple Visual Explanations

---

## High-Level Architecture

```mermaid
graph TD
    User["👤 Customer"]

    subgraph Browser ["🌐 Browser (frontend/)"]
        UI["Chat UI\nindex.html"]
        JS["App Logic\napp.js"]
    end

    subgraph Server ["⚙️ FastAPI Server (backend/main.py)"]
        Router["Agent Router\nrouter.py"]
        LG["LangGraph Pipeline\ngraph.py"]
        DB_Tools["Database Tools\ntools.py"]
        Validation["Validator\nvalidation.py"]
    end

    subgraph Azure ["☁️ Azure Cloud"]
        Foundry["Azure AI Foundry\nGPT-5-mini + Agents"]
        Search["Azure AI Search\nProduct Catalog"]
        ACS["Azure Communication\nServices (Calls)"]
        VL["Azure Voice Live\nSpeech AI"]
    end

    subgraph Database ["🗄️ Database"]
        SQLite["SQLite / PostgreSQL\nOrders, Customers,\nProducts, Stores"]
    end

    User -->|Types message| UI
    UI -->|POST /chat| JS
    JS -->|HTTP Request| Router
    Router -->|LangGraph run| LG
    LG -->|Calls tools| DB_Tools
    DB_Tools -->|SQL queries| SQLite
    DB_Tools -->|Vector search| Search
    LG -->|AI completion| Foundry
    LG -->|Validate| Validation
    Validation -->|Clean response| Router
    Router -->|JSON response| JS
    JS -->|Display| UI
    UI -->|Shows to| User

    User -->|Clicks Call| ACS
    ACS -->|Phone call| VL
    VL -->|Speech + AI| Foundry
```

---

## What Each Layer Does (Simple Explanation)

| Layer | Job | Think of it as... |
|-------|-----|------------------|
| **Browser / Frontend** | Shows the chat UI, captures voice | The storefront window |
| **FastAPI Server** | Receives requests, coordinates everything | The receptionist |
| **LangGraph** | Decides what to do and in what order | The team manager |
| **Azure AI Foundry** | The actual AI that writes answers | The expert staff |
| **Database** | Stores real customer and order data | The filing cabinet |
| **Azure AI Search** | Finds products by meaning not just keywords | The smart catalogue |
| **Azure Voice Live** | Converts speech ↔ text in real time | The phone interpreter |
| **Azure ACS** | Connects and manages real phone calls | The telephone exchange |

---

## Request Flow — Chat Message

```mermaid
sequenceDiagram
    participant U as 👤 Customer
    participant FE as 🌐 Browser (app.js)
    participant API as ⚙️ FastAPI (main.py)
    participant LG as 🔀 LangGraph (graph.py)
    participant AI as 🤖 Azure AI Foundry
    participant DB as 🗄️ Database

    U->>FE: Types "Where is my order?"
    FE->>API: POST /chat {message, history}
    API->>LG: agent_router.handle()
    LG->>LG: router_node (classify intent → "order")
    LG->>AI: specialist_agent_node (Order Agent)
    AI->>LG: Requests check_stock_tool / order lookup
    LG->>DB: tool_execution_node (SQL query)
    DB-->>LG: Order data
    LG->>AI: Re-invoke with data
    AI-->>LG: "Your order ORD-99102 arrived June 16..."
    LG->>LG: validation_node (clean + secure)
    LG-->>API: Final reply
    API-->>FE: JSON {reply, intent, sources}
    FE-->>U: Displays answer in chat
```

---

## Voice Call Flow — Browser

```mermaid
sequenceDiagram
    participant U as 👤 Customer
    participant FE as 🌐 Browser
    participant API as ⚙️ FastAPI
    participant VL as 🔊 Azure Voice Live
    participant Agent as 🤖 Foundry Agent

    U->>FE: Clicks "Call" button
    FE->>API: GET /api/token
    API-->>FE: ACS token + bot identity
    FE->>API: WebSocket /api/voice-realtime
    API->>VL: connect(agent_name, credential)
    VL-->>API: Session established
    API-->>FE: Connected

    loop While call is active
        U->>FE: Speaks (microphone PCM16 audio)
        FE->>API: Binary audio bytes (WebSocket)
        API->>VL: input_audio_buffer.append(audio)
        VL->>VL: Speech-to-text (azure-speech)
        VL->>Agent: Transcribed text
        Agent-->>VL: AI response text
        VL->>VL: Text-to-speech (Ava voice)
        VL-->>API: Audio delta events
        API-->>FE: {type: audio_delta, delta: base64}
        FE-->>U: Plays audio through speaker
    end

    U->>FE: Clicks "End Call"
    FE->>API: WebSocket close
    API->>VL: Disconnect
```

---

## LangGraph Decision Tree

```mermaid
graph TD
    Start([New Message]) --> Router{router_node}

    Router -->|"hello / hi"| Greeting[Instant greeting response]
    Router -->|"thanks"| Thanks[Instant thank you response]
    Router -->|Out of scope| OOS[Sorry, I only handle retail queries]
    Router -->|yes/okay/sure| Context[context_resolver_node]
    Router -->|Order/Delivery/Refund keyword| Specialist[specialist_agent_node]

    Context -->|Ambiguous - needs clarity| ClarReply[Ask for clarification]
    Context -->|Resolved query| Specialist

    Specialist -->|No tool needed| Validate[validation_node]
    Specialist -->|Needs data| Tool[tool_execution_node]
    Tool -->|Results| Specialist

    Greeting --> Validate
    Thanks --> Validate
    OOS --> Validate
    ClarReply --> Validate
    Validate --> End([Send to customer])
```

---

## Database Schema (Simplified)

```mermaid
erDiagram
    CUSTOMERS {
        string id PK
        string name
        string email
        string phone
        string postcode
    }

    ORDERS {
        string order_id PK
        string customer_id FK
        float total
        string status
    }

    ORDER_ITEMS {
        int id PK
        string order_id FK
        string product_id FK
        int quantity
        float unit_price
    }

    PRODUCTS {
        string id PK
        string name
        string category
        float price
        string dietary_tags
    }

    STORES {
        string id PK
        string name
        string postcode
        json opening_hours
    }

    DELIVERIES {
        int id PK
        string order_id FK
        string method
        string driver
        string slot
    }

    REFUNDS {
        string id PK
        string order_id FK
        float amount
        string reason
        string status
    }

    PROMOTIONS {
        string offer_id PK
        string title
        float discount_percent
        date valid_until
    }

    CUSTOMERS ||--o{ ORDERS : places
    ORDERS ||--o{ ORDER_ITEMS : contains
    ORDER_ITEMS }o--|| PRODUCTS : references
    ORDERS ||--o| DELIVERIES : has
    ORDERS ||--o| REFUNDS : may_have
    STORES ||--o{ PRODUCT_STOCK : holds
```

---

## Component Diagram

```mermaid
graph LR
    subgraph FE ["Frontend"]
        HTML[index.html]
        APPJS[app.js]
        ACSJS[azure-communication-services.js]
    end

    subgraph BE ["Backend"]
        MAIN[main.py]
        ROUTER[router.py]
        GRAPH[graph.py]
        INTENT[intent.py]
        TOOLS[tools.py]
        VALID[validation.py]
        DB[database.py]
        ACS_BOT[acs_bot.py]
        VR[voice_realtime.py]
        VF[voice_fillers.py]
        FC[foundry_config.py]
    end

    subgraph AZURE_SVC ["Azure Services"]
        FOUNDRY[AI Foundry\nGPT-5-mini]
        SEARCH[AI Search]
        ACS[ACS]
        VL[Voice Live]
    end

    HTML --> APPJS
    APPJS --> MAIN
    MAIN --> ROUTER
    MAIN --> ACS_BOT
    ROUTER --> GRAPH
    GRAPH --> INTENT
    GRAPH --> TOOLS
    GRAPH --> VALID
    TOOLS --> DB
    TOOLS --> SEARCH
    GRAPH --> FOUNDRY
    ACS_BOT --> ACS
    MAIN --> VR
    VR --> VL
    VL --> FOUNDRY
    MAIN --> VF
    VF --> VL
    ROUTER --> FC
```
