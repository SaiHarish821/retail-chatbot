# Deployment Guide

## 1. Prerequisites

- **Python 3.11+** with pip
- **Node.js 18+** (for frontend ACS SDK bundling, optional)
- **Azure CLI** (`az login`) for local development authentication
- **Azure subscription** with the following resources provisioned:
  - Azure AI Foundry project with agents configured
  - Azure OpenAI resource with GPT-4o deployed
  - Azure Communication Services resource (for telephony)
  - Azure PostgreSQL Flexible Server (for production)

## 2. Environment Variables

Copy `.env.example` to `.env` and configure:

### Required Variables

| Variable | Example | Description |
|----------|---------|-------------|
| `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` | `https://hub.services.ai.azure.com/api/projects/project` | AI Foundry project endpoint |
| `AZURE_AI_FOUNDRY_API_KEY` | `abc123...` | API key for Foundry authentication |
| `AZURE_OPENAI_ENDPOINT` | `https://resource.cognitiveservices.azure.com/openai/v1` | Azure OpenAI endpoint |
| `AZURE_AI_FOUNDRY_DEPLOYMENT_NAME` | `gpt-4o` | Model deployment name |
| `AZURE_TENANT_ID` | `12345-abcde-...` | Azure AD tenant ID |

### Agent Names

| Variable | Default | Description |
|----------|---------|-------------|
| `AZURE_AGENT_SUPERVISOR_NAME` | `Supervisor-Agent` | Supervisor agent name |
| `AZURE_AGENT_ORDER_NAME` | `Order-Agent` | Order agent name |
| `AZURE_AGENT_DELIVERY_NAME` | `Delivery-Agent` | Delivery agent name |
| `AZURE_AGENT_REFUND_NAME` | `Refund-Agent` | Refund agent name |
| `AZURE_AGENT_STORE_NAME` | `Store-Agent` | Store agent name |
| `AZURE_AGENT_GENERAL_NAME` | `General-Assistant-Agent` | General agent name |
| `AZURE_AGENT_INTENT_NAME` | `Intent-Classifier-Agent` | Intent classifier name |
| `AZURE_AGENT_CONTEXT_NAME` | `Context-Resolver-Agent` | Context resolver name |
| `AZURE_AGENT_VOICE_NAME` | `Voice-Assistant-Agent` | Voice assistant name |

### Voice Configuration

| Variable | Example | Description |
|----------|---------|-------------|
| `AZURE_VOICELIVE_ENDPOINT` | `https://hub.services.ai.azure.com` | Voice Live endpoint |
| `AZURE_VOICELIVE_VOICE` | `en-US-Ava:DragonHDLatestNeural` | Voice name for TTS |
| `ACS_CONNECTION_STRING` | `endpoint=https://...;accesskey=...` | ACS connection string |
| `PUBLIC_CALLBACK_URL` | `https://abc.ngrok.io` | Public URL for ACS callbacks |
| `COGNITIVE_SERVICES_ENDPOINT` | `https://resource.cognitiveservices.azure.com/` | TTS endpoint |

### Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGIN` | `*` | CORS allowed origin |
| `AZURE_CLIENT_ID` | (none) | Service principal client ID |
| `AZURE_CLIENT_SECRET` | (none) | Service principal secret |
| `AZURE_POSTGRESQL_HOST` | (none) | PostgreSQL host |
| `AZURE_POSTGRESQL_DB` | `retail_chatbot` | PostgreSQL database name |
| `AZURE_POSTGRESQL_USER` | `postgres` | PostgreSQL user |
| `AZURE_POSTGRESQL_PASSWORD` | (none) | PostgreSQL password |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | (none) | Application Insights |

## 3. Local Development Setup

### Step 1: Clone and Create Virtual Environment

```bash
git clone <repo-url>
cd retail-chatbot
python -m venv .venv

# Windows:
.venv\Scripts\activate

# macOS/Linux:
source .venv/bin/activate
```

### Step 2: Install Dependencies

```bash
pip install -r requirements.txt
```

> **Windows Users:** If you get `FileNotFoundError: Could not find module Microsoft.CognitiveServices.Speech.core.dll`, install the Visual C++ Redistributable from: https://aka.ms/vs/17/release/vc_redist.x64.exe

### Step 3: Configure Environment

```bash
cp .env.example .env
# Edit .env with your Azure credentials
```

### Step 4: Azure CLI Login

```bash
az login --tenant <your-tenant-id>
```

### Step 5: Run the Server

```bash
uvicorn backend.main:app --reload --port 8000
```

### Step 6: Access the Application

Open `http://localhost:8000` in your browser.

### Voice Testing (Local)

For voice features, you need HTTPS. Use ngrok:

```bash
ngrok http 8000
```

Update `PUBLIC_CALLBACK_URL` in `.env` with the ngrok URL.

## 4. Production Deployment — Vercel

### Configuration

The project includes `vercel.json` with URL rewrite rules:

```json
{
  "rewrites": [
    {"source": "/static/(.*)", "destination": "/frontend/$1"},
    {"source": "/(customer|inventory|chat|api/save_results|voice/transcribe|health)", "destination": "/api/index"},
    {"source": "/(.*)", "destination": "/frontend/index.html"}
  ]
}
```

### Deploy to Vercel

```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel

# Set environment variables
vercel env add AZURE_AI_FOUNDRY_PROJECT_ENDPOINT
vercel env add AZURE_AI_FOUNDRY_API_KEY
# ... etc
```

### Serverless Considerations

1. **Database:** The SQLite database is automatically copied to `/tmp` on first invocation (Vercel's writable directory)
2. **Cold starts:** First request initialises the database and agent connections (~5-10s)
3. **WebSockets:** Vercel serverless does not support WebSocket connections. Voice features require a persistent server (e.g., Render, Railway, Azure App Service)
4. **Timeout:** Vercel functions have a 60s timeout (Pro plan: 300s)

## 5. Production Deployment — Persistent Server

For full feature support (including WebSockets and voice), deploy to a persistent server:

### Docker (Recommended)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Render / Railway

1. Connect your GitHub repository
2. Set build command: `pip install -r requirements.txt`
3. Set start command: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
4. Add all environment variables
5. Set `AZURE_CLIENT_ID` and `AZURE_CLIENT_SECRET` for production authentication

### Azure App Service

```bash
az webapp create --name retail-chatbot --resource-group myRG --plan myPlan --runtime "PYTHON|3.11"
az webapp config appsettings set --name retail-chatbot --resource-group myRG --settings @env-settings.json
az webapp deployment source config --name retail-chatbot --resource-group myRG --repo-url <repo-url>
```

## 6. Database Setup

### Development (SQLite)

No setup needed. The database is automatically created and seeded at `mock_data/retail_chatbot.db` on first run.

### Production (Azure PostgreSQL)

1. Create Azure PostgreSQL Flexible Server
2. Create database: `CREATE DATABASE retail_chatbot;`
3. Set environment variables:
   ```
   AZURE_POSTGRESQL_HOST=myserver.postgres.database.azure.com
   AZURE_POSTGRESQL_DB=retail_chatbot
   AZURE_POSTGRESQL_USER=adminuser
   AZURE_POSTGRESQL_PASSWORD=<password>
   AZURE_POSTGRESQL_PORT=5432
   AZURE_POSTGRESQL_SSLMODE=require
   ```
4. Tables are auto-created and seeded on first run

## 7. Azure Resource Provisioning

### AI Foundry Setup

1. Create AI Foundry Hub + Project in Azure Portal
2. Deploy GPT-4o model in the project
3. Create agents with names matching `.env` (see `current_agents_backup.json` for reference)
4. Register tools on appropriate agents
5. Note the project endpoint and API key

### Communication Services Setup

1. Create ACS resource in Azure Portal
2. Note the connection string
3. (Optional) Purchase a phone number for PSTN
4. Configure incoming call webhook to `<your-url>/api/incoming-call`

### Voice Live Setup

1. Enable Voice Live on your AI Foundry project
2. Create or reference the Voice-Assistant-Agent
3. Note the Voice Live endpoint

## 8. CI/CD

### GitHub Actions (Example)

```yaml
name: Deploy
on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python -m pytest backend/tests/
      - uses: amondnet/vercel-action@v25
        with:
          vercel-token: ${{ secrets.VERCEL_TOKEN }}
          vercel-org-id: ${{ secrets.VERCEL_ORG_ID }}
          vercel-project-id: ${{ secrets.VERCEL_PROJECT_ID }}
```

## 9. Health Checks

```bash
# Check server health
curl http://localhost:8000/health
# Expected: {"status": "ok"}

# Check customer data loading
curl http://localhost:8000/customer
# Expected: JSON with customer profile and orders

# Check inventory loading
curl http://localhost:8000/inventory
# Expected: JSON with products and store data
```
