# Executive Overview

## 1. Project Purpose

The **Sainsbury's Retail AI Assistant** is an enterprise-grade, AI-powered customer service platform that provides both **text chat** and **real-time voice telephony** support for Sainsbury's grocery retail operations. It replaces traditional FAQ pages and basic chatbots with an intelligent, multi-agent system capable of handling complex, multi-turn customer conversations.

## 2. Business Problem

Retail customer service teams face:

- **High volume of repetitive inquiries** — order tracking, delivery ETAs, refund status, stock availability — that consume human agent time
- **Inconsistent response quality** across channels (web, phone, in-store)
- **Long wait times** for telephone-based support
- **Inability to scale** customer service during peak periods (holidays, promotions)
- **No self-service capability** for common operations like address updates or refund requests

## 3. Solution Overview

The platform delivers an AI assistant accessible via:

1. **Web Chat** — A branded Sainsbury's web interface with streaming responses, product cards, and quick-action suggestion chips
2. **Browser Voice** — Real-time voice-to-voice conversation via WebSocket relay to Azure Voice Live
3. **PSTN Telephony** — A phone bot that answers actual telephone calls via Azure Communication Services, processes speech in real time, and responds with a natural British voice

The backend uses a **multi-agent orchestration architecture** powered by LangGraph, where specialised AI agents handle different domains (orders, deliveries, refunds, stores) with tool-calling capabilities that execute real database operations.

## 4. Key Features

### Intelligent Multi-Agent System
- **Intent Classification** — Hybrid heuristic + LLM classifier routes queries to the correct specialist agent
- **Context Resolution** — Handles ambiguous follow-up messages ("yes", "sure") by analysing conversation history
- **Specialist Agents** — Four domain-specific agents (Order, Delivery, Refund, Store) with tailored instructions and tool access
- **Tool Calling** — LLM-driven function calling that executes real database operations (stock checks, refund processing, address updates)

### Voice Capabilities
- **Browser Voice-to-Voice** — WebSocket relay to Azure Voice Live with real-time audio streaming, transcription, and barge-in support
- **PSTN Telephony** — Azure Communication Services integration for answering real phone calls
- **Voice Fillers** — Pre-rendered audio filler clips ("Let me check that for you...") played while the agent processes, eliminating dead silence
- **Server VAD** — Server-side Voice Activity Detection with configurable silence thresholds

### Product Intelligence
- **Rich Product Catalog** — 20+ products with full nutritional data, allergens, dietary tags, ratings, and stock levels across 3 stores
- **Proximity Search** — Haversine distance calculation to sort stores by proximity to the customer's postcode
- **Visual Product Cards** — Embedded `<product-grid>` XML tags rendered as interactive product cards in the frontend
- **Fuzzy Search** — Synonym mapping, multi-word matching, and relevance scoring

### Enterprise Readiness
- **Response Validation** — Multi-layer guardrails that mask internal IDs, block credential leakage, and sanitise markdown
- **Streaming Responses** — Server-Sent Events (SSE) for real-time token-by-token response streaming
- **Dual Database Support** — SQLite for development, Azure PostgreSQL for production, with automatic detection
- **Telemetry** — Azure Monitor + OpenTelemetry integration for production tracing
- **Serverless Deployment** — Vercel-ready with automatic `/tmp` database copying for read-only environments

## 5. Current Architecture

The system follows a **layered architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────┐
│                    Frontend Layer                     │
│   HTML/CSS/JS · Chat · Voice · Product Cards · TTS   │
├─────────────────────────────────────────────────────┤
│                   API Gateway Layer                   │
│      FastAPI · CORS · Static Files · WebSockets      │
├─────────────────────────────────────────────────────┤
│                 Orchestration Layer                    │
│         LangGraph · AgentRouter · Intent              │
│         Classification · Context Resolution           │
├─────────────────────────────────────────────────────┤
│                  Agent Layer                           │
│   Order · Delivery · Refund · Store · General         │
│   Specialist Instructions · Tool Binding              │
├─────────────────────────────────────────────────────┤
│                   Tool Layer                          │
│   search_products · check_stock · issue_refund        │
│   update_address · get_promotions                     │
├─────────────────────────────────────────────────────┤
│                 Data Layer                            │
│    SQLite/PostgreSQL · Seed Data · Caching            │
├─────────────────────────────────────────────────────┤
│              Azure Services Layer                     │
│   AI Foundry · Voice Live · ACS · Speech · Monitor    │
└─────────────────────────────────────────────────────┘
```

## 6. Technology Stack

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Backend Framework | FastAPI | 0.115.5 | REST API, WebSocket, SSE |
| AI Orchestration | LangGraph | Latest | Multi-node graph execution |
| LLM Integration | LangChain + OpenAI | Latest | Tool-calling LLM interface |
| AI Models | Azure OpenAI GPT-4o / GPT-5.1 | Latest | Text generation + function calling |
| Agent Platform | Azure AI Foundry Agents SDK | 1.1.0 | Agent instruction management |
| Voice Engine | Azure Voice Live SDK | Latest | Real-time voice-to-voice |
| Telephony | Azure Communication Services | Latest | PSTN call handling |
| Speech | Azure Cognitive Services Speech | 1.41.1 | TTS for voice fillers |
| Database (Dev) | SQLite | 3.x | Local development database |
| Database (Prod) | Azure PostgreSQL | Latest | Production database |
| Authentication | Azure Identity (CLI + ClientSecret) | 1.19.0 | Entra ID authentication |
| Telemetry | Azure Monitor OpenTelemetry | Latest | Distributed tracing |
| Frontend | Vanilla HTML/CSS/JS | N/A | No framework overhead |
| Deployment | Vercel | Latest | Serverless deployment |
| Package Manager | pip | Latest | Python dependencies |

## 7. Azure Services Used

| Service | Role |
|---------|------|
| **Azure AI Foundry** | Hosts agent definitions, instructions, and model deployments |
| **Azure OpenAI** | GPT-4o/GPT-5.1 model inference for chat and classification |
| **Azure Voice Live** | Real-time voice-to-voice with agent-mode integration |
| **Azure Communication Services** | PSTN telephony, WebRTC calling, identity tokens |
| **Azure Cognitive Services Speech** | Text-to-Speech for voice fillers |
| **Azure PostgreSQL** | Production-grade relational database |
| **Azure Monitor / Application Insights** | Telemetry, tracing, and performance monitoring |

## 8. AI Architecture

The AI layer uses a **hybrid routing strategy**:

1. **Heuristic Fast-Path** — Keyword matching routes 70%+ of queries directly to specialist agents with zero LLM latency
2. **LLM Intent Classification** — An Azure AI Foundry `Intent-Classifier-Agent` handles ambiguous queries
3. **Context Resolution** — A `Context-Resolver-Agent` resolves follow-up confirmations using conversation history
4. **Specialist Execution** — Domain agents receive tailored instructions + customer context and use LangChain tool calling
5. **Validation Layer** — All responses pass through security guardrails, ID masking, and formatting sanitisation

## 9. Deployment Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Browser    │────▶│   Vercel     │────▶│   Azure AI   │
│              │     │   Edge       │     │   Foundry    │
│  Chat / Voice│     │   Functions  │     │   + OpenAI   │
└──────────────┘     └──────────────┘     └──────────────┘
                            │                      │
                            ▼                      ▼
                     ┌──────────────┐     ┌──────────────┐
                     │   Azure      │     │   Azure      │
                     │   PostgreSQL │     │   Voice Live │
                     └──────────────┘     └──────────────┘
```

- **Local Development**: Uvicorn serves FastAPI with SQLite database
- **Production**: Vercel serverless functions with Azure PostgreSQL and full Azure service integration

## 10. Design Decisions

| Decision | Rationale |
|----------|-----------|
| **LangGraph over single-agent** | Enables composable, debuggable multi-step workflows with conditional routing |
| **Heuristic-first routing** | Eliminates LLM latency for 70%+ of queries; falls back to LLM only when needed |
| **Instructions from Foundry Portal** | Business users can update agent behaviour without code deployments |
| **SQLite + PostgreSQL dual mode** | Zero-config local development; production-grade scaling in Azure |
| **No frontend framework** | Minimises bundle size and avoids framework lock-in for a single-page chat interface |
| **SSE streaming** | Provides real-time token-by-token responses without WebSocket complexity for chat |
| **Voice filler system** | Pre-rendered audio clips eliminate perceived latency during agent processing |
| **Agent-mode Voice Live** | The Foundry agent owns instructions/model/knowledge — backend only configures speech |
| **Tool functions as class methods** | Tools bind to `AgentRouter` instance for access to customer data and database |
| **Validation as a separate graph node** | Decouples security/formatting concerns from agent logic; always executes |
