# API Reference

## Base URL

- **Local:** `http://localhost:8000`
- **Production:** `https://<your-deployment>.vercel.app`

---

## Endpoints

### GET `/`

**Description:** Serve the frontend SPA.

**Response:** HTML page (`frontend/index.html`)

---

### GET `/health`

**Description:** Health check endpoint.

**Response:**
```json
{
  "status": "ok"
}
```

---

### GET `/customer`

**Description:** Load and return current customer data including profile, orders, items, and refunds.

**Response:**
```json
{
  "customer": {
    "id": "CUST-00421",
    "name": "Jamie Thornton",
    "email": "jamie.thornton@example.com",
    "phone": "+44 7700 900421",
    "loyalty_tier": "Gold",
    "loyalty_points": 3240,
    "registered_since": "2021-03-14",
    "default_address": {
      "line1": "50 Oak Lane",
      "city": "London",
      "postcode": "SW1A 1AA",
      "country": "UK"
    }
  },
  "orders": [
    {
      "order_id": "ORD-98741",
      "date": "2025-06-10",
      "status": "refund_completed",
      "items": [
        {"name": "Organic Whole Milk 2L", "qty": 2, "price": 1.89}
      ],
      "total": 9.53,
      "payment_method": "Visa ending 4821",
      "delivery": {
        "method": "Home Delivery",
        "slot": "2025-06-10 09:00–11:00",
        "delivered_at": "2025-06-10 10:23",
        "driver": "Raj P."
      },
      "refund": {
        "reason": "Milk was spoiled",
        "requested_on": "2026-06-18",
        "amount": 3.5,
        "status": "completed",
        "method": "Original payment method",
        "completed_on": "2026-06-18",
        "reference": "REF-78934"
      }
    }
  ]
}
```

---

### GET `/inventory`

**Description:** Load and return full inventory data including products, stores, and stock levels.

**Response:**
```json
{
  "metadata": {
    "version": "2.0",
    "generated": "2026-06-18",
    "total_products": 20,
    "stores": {
      "STR-001": {
        "name": "Sainsbury's Islington Superstore",
        "address": "48 Liverpool Road, Islington, London N1 0PL",
        "lat": 51.5362,
        "lng": -0.1072,
        "type": "Superstore",
        "phone": "020 7609 2120",
        "opening_hours": {"mon_sat": "07:00–23:00", "sunday": "11:00–17:00"}
      }
    }
  },
  "inventory": [
    {
      "product_id": "PRD-001",
      "name": "Organic Whole Milk 2L",
      "description": "Certified organic whole milk...",
      "price": 1.89,
      "category": "Dairy",
      "stock": {
        "STR-001": {"quantity": 25, "in_stock": true, "low_stock": false}
      },
      "customer_rating": 4.3,
      "best_seller": true,
      "diet_tags": ["Healthy"]
    }
  ]
}
```

---

### POST `/chat`

**Description:** Main chat endpoint. Sends a message to the AI agent pipeline and returns the response. Supports SSE streaming when `stream: true`.

**Request Body:**
```json
{
  "message": "Is milk in stock at Camden?",
  "conversation_history": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi Jamie! How can I help?"}
  ],
  "stream": true
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `message` | string | Yes | User's message text |
| `conversation_history` | array | No | Previous conversation turns |
| `stream` | boolean | No | Enable SSE streaming (default: true) |

**Response (non-streaming):**
```json
{
  "reply": "Great news! Organic Whole Milk 2L is in stock at Sainsbury's Camden Local with 45 units available.",
  "intent": "store",
  "sources": ["heuristic_keyword_match", "store_agent", "check_stock_tool"],
  "suggestions": [
    "Check stock at other stores",
    "What promotions are available?",
    "Show me dairy products"
  ]
}
```

**Response (streaming — SSE):**

```
data: {"type": "token", "content": "Great"}

data: {"type": "token", "content": " news!"}

data: {"type": "token", "content": " Organic"}

data: {"type": "done", "reply": "Great news! Organic Whole Milk 2L...", "intent": "store", "suggestions": [...]}
```

| SSE Event Type | Description |
|---------------|-------------|
| `token` | Individual response token for streaming display |
| `done` | Final event with complete reply, intent, and suggestions |
| `error` | Error event with error message |

---

### POST `/chat/voice`

**Description:** Dedicated voice chat endpoint with ultra-fast path. Skips standard intent classification for lower latency.

**Request Body:** Same as `/chat`

**Response:** Same as `/chat` (non-streaming JSON)

---

### GET `/api/token`

**Description:** Generate an Azure Communication Services VOIP token for browser-based calling.

**Response:**
```json
{
  "token": "eyJ0eXAiOiJKV1Qi...",
  "user_id": "8:acs:abc123-...",
  "bot_user_id": "8:acs:def456-...",
  "expires_on": "2026-07-14T10:23:45Z"
}
```

---

### GET `/api/call-status`

**Description:** Get the current state of active phone calls (transcript, status).

**Response:**
```json
{
  "call_id": "server-call-123",
  "user_transcript": "What are your store hours?",
  "ai_response": "Sainsbury's Islington is open...",
  "status": "LISTENING",
  "history": []
}
```

---

### POST `/api/incoming-call`

**Description:** Webhook for ACS incoming call events. Called by Azure Communication Services when a phone call is received.

**Request Body:** ACS CloudEvent format

**Response:** `200 OK`

---

### POST `/api/callback`

**Description:** Webhook for ACS Call Automation events (CallConnected, CallDisconnected).

**Request Body:** ACS event array

**Response:** `200 OK`

---

### GET `/api/fillers`

**Description:** Retrieve pre-rendered voice filler audio clips.

**Response:**
```json
{
  "trees": [
    ["base64_audio_clip_1", "base64_audio_clip_2", "base64_audio_clip_3", "base64_audio_clip_4"],
    ["base64_audio_clip_5", "..."]
  ],
  "thinking": [
    "base64_audio_clip_hmm",
    "base64_audio_clip_let_me_see"
  ]
}
```

---

### WS `/api/voice-realtime`

**Description:** WebSocket endpoint for real-time voice-to-voice communication via Azure Voice Live.

**Protocol:**

| Direction | Format | Description |
|-----------|--------|-------------|
| Client → Server | Binary | Raw PCM16 audio bytes (24kHz, mono, 16-bit) |
| Server → Client | JSON | Event messages |

**Server → Client Message Types:**

```json
{"type": "speech_started"}
{"type": "speech_stopped"}
{"type": "user_transcript", "text": "Is milk in stock?"}
{"type": "audio_delta", "delta": "base64_pcm16_audio"}
{"type": "transcript_delta", "delta": "partial text"}
{"type": "agent_transcript", "text": "Yes, milk is in stock..."}
{"type": "response_done"}
{"type": "error", "message": "Connection failed"}
```

---

### WS `/api/media-stream`

**Description:** WebSocket endpoint for ACS media stream relay. Same protocol as `/api/voice-realtime` but adapted for ACS WebSocket media format.

---

### POST `/api/save_results`

**Description:** Save test runner results to disk.

**Request Body:**
```json
{
  "results": [
    {
      "test_name": "Order Status Check",
      "status": "pass",
      "response_time_ms": 1234
    }
  ]
}
```

**Response:**
```json
{
  "status": "ok",
  "saved_to": "mock_data/test_results.json"
}
```

---

## Error Responses

All endpoints may return error responses:

```json
{
  "detail": "Error message describing what went wrong"
}
```

| Status Code | Description |
|------------|-------------|
| `400` | Bad request (missing or invalid parameters) |
| `500` | Internal server error (Azure service failure, database error) |
| `503` | Service unavailable (Azure services not configured) |

## CORS Configuration

CORS is configured via the `CORS_ORIGIN` environment variable:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[cors_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Default: `*` (all origins allowed). Set to specific domain in production.
