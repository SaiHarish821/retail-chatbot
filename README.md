# Retail AI Assistant

A conversational AI-powered retail customer support chatbot built using the Azure AI ecosystem. This project is a Proof of Concept (POC) focused on handling retail customer journeys such as order tracking, refund queries, delivery tracking, and store-related support using conversational AI and voice-to-text capabilities.

---

## Overview

Retail AI Assistant provides an intelligent customer support experience through a web chatbot interface with optional voice input.

The system leverages Azure AI services, Semantic Kernel orchestration, and custom APIs to simulate enterprise-grade customer interactions while maintaining a lightweight MVP architecture suitable for rapid prototyping.

### Supported Customer Journeys

* Order Queries
* Refund Requests
* Delivery Tracking
* Store-Related Queries

### Features

* Conversational AI chatbot
* Voice-to-text integration
* Context-aware conversations
* Semantic Kernel orchestration
* Custom mock APIs
* Default demo customer profile
* Modern React frontend
* Enterprise-ready architecture
* Future-ready for Genesys IVR integration

---

## Tech Stack

### Frontend

* React.js
* Tailwind CSS
* Axios
* React Router

### Backend

* Python
* FastAPI
* Semantic Kernel
* Azure OpenAI

### Azure Services

* Azure AI Foundry
* Azure OpenAI
* Azure Communication Services (Voice-to-Text)

### Collaboration

* Git
* GitHub

---

## Architecture Overview

```text
Customer
   │
   ▼
React Chat UI
   │
   ▼
FastAPI Backend
   │
   ├── Semantic Kernel Orchestrator
   │       │
   │       ├── Order Plugin
   │       ├── Refund Plugin
   │       ├── Delivery Plugin
   │       └── Store Query Plugin
   │
   ├── Azure OpenAI
   │
   ├── Azure Communication Services
   │       └── Voice-to-Text
   │
   └── Mock APIs
           ├── Orders API
           ├── Refund API
           ├── Delivery API
           └── Store API
```

---

## Project Structure

```bash
retail-ai-assistant/
│
├── frontend/
│   ├── src/
│   ├── components/
│   ├── pages/
│   ├── hooks/
│   └── services/
│
├── backend/
│   ├── app/
│   │   ├── api/
│   │   ├── services/
│   │   ├── plugins/
│   │   ├── orchestration/
│   │   ├── models/
│   │   └── utils/
│   │
│   ├── mock_data/
│   └── main.py
│
├── docs/
│
├── README.md
└── .gitignore
```

---

## Installation

### Clone Repository

```bash
git clone https://github.com/your-username/retail-ai-assistant.git
cd retail-ai-assistant
```

---

### Backend Setup

```bash
cd backend

python -m venv venv

# Windows
venv\Scripts\activate

pip install -r requirements.txt

uvicorn main:app --reload
```

Backend runs on:

```text
http://localhost:8000
```

---

### Frontend Setup

```bash
cd frontend

npm install

npm run dev
```

Frontend runs on:

```text
http://localhost:5173
```

---

## Environment Variables

Create a `.env` file inside the backend folder.

```env
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_DEPLOYMENT=
AZURE_OPENAI_API_VERSION=

ACS_CONNECTION_STRING=
```

---

## Mock APIs

The project uses custom mock APIs for retail support journeys.

### Order API

* Order Status
* Order Details
* Order History

### Refund API

* Refund Eligibility
* Refund Status
* Refund Processing

### Delivery API

* Delivery Tracking
* Estimated Delivery Time
* Delivery Updates

### Store API

* Store Hours
* Store Policies
* Product Availability

---

## Team Collaboration Plan

### Backend Team (2 Members)

**Member 1**

* Semantic Kernel orchestration
* Azure OpenAI integration
* Conversation flow logic

**Member 2**

* Mock APIs
* Backend business logic
* Validation and response handling

### Frontend Team (2 Members)

**Member 3**

* Chat UI development
* React state management
* API integration

**Member 4**

* Voice-to-text integration
* UI polishing
* Chat experience improvements

---

## Git Workflow

### Main Branches

```text
main
develop
frontend/*
backend/*
feature/*
```

### Example Branch Naming

```text
feature/chat-ui
feature/order-api
feature/refund-flow
feature/semantic-kernel
feature/voice-input
```

### Development Flow

1. Create feature branch from `develop`
2. Complete feature implementation
3. Raise Pull Request
4. Code review by teammates
5. Merge into `develop`
6. Final tested merge into `main`

---

## MVP Scope

### Included

✅ Chatbot UI
✅ Voice-to-text input
✅ Order flow
✅ Refund flow
✅ Delivery tracking
✅ Store queries
✅ Mock APIs
✅ Semantic Kernel orchestration

---

## Future Enhancements

* Genesys Cloud IVR integration
* Multi-language support
* Customer authentication
* Real backend integrations
* Analytics dashboard
* Agent handover support

---

## Contributors

Built collaboratively as a Retail Conversational AI Proof of Concept using Azure AI technologies, Semantic Kernel, and React.
