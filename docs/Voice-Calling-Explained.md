# 🎤 Voice Calling — How It Works

The voice calling feature is one of the most impressive parts of this project. This document explains both voice modes in plain language.

---

## Two Voice Modes

| Mode | How it works | When to use |
|------|-------------|-------------|
| **Browser Voice** | Click a call button on the website, speak through your computer microphone | In-browser chat + voice |
| **PSTN Phone Call** | Dial a real phone number (via Azure) | Traditional telephone call |

---

## Mode 1: Browser Voice Call

### How It Works Step by Step

```
Customer clicks "📞 Call" button
         ↓
Browser requests a token from GET /api/token
         ↓
Azure Communication Services (ACS) validates and returns a VOIP token
         ↓
Browser opens a WebSocket to ws://backend/api/voice-realtime
         ↓
Backend connects to Azure Voice Live using the Foundry agent's credentials
         ↓
Voice Live session opens in "Agent Mode" (the AI Foundry agent takes over)
         ↓
       ┌─────────────────────────────────────────┐
       │         LIVE CALL LOOP                   │
       │                                          │
       │  Customer speaks → Mic captures PCM16    │
       │         ↓                                │
       │  Browser sends raw audio bytes over WS   │
       │         ↓                                │
       │  Backend forwards to Voice Live          │
       │         ↓                                │
       │  Voice Live detects end of speech (VAD)  │
       │         ↓                                │
       │  Azure Speech converts speech → text     │
       │         ↓                                │
       │  Foundry Agent reads transcribed text    │
       │         ↓                                │
       │  (If needed) Agent calls tools:          │
       │    check_stock, search_products, etc.    │
       │         ↓                                │
       │  Agent writes a short response           │
       │         ↓                                │
       │  Voice Live TTS: text → speech audio     │
       │         ↓                                │
       │  Audio sent back to browser via WS       │
       │         ↓                                │
       │  Browser plays audio through speaker     │
       └─────────────────────────────────────────┘
         ↓
Customer clicks "End Call" → WebSocket closes → Session ends
```

### The "Filler Audio" System

When the AI is thinking, there would normally be an awkward silence. To make the experience more natural, the system pre-renders short audio clips at startup:

- "Alright, let me check that for you."
- "Going through the details now."
- "Bear with me, nearly got it."

These are generated using Azure TTS at the exact same voice as the main agent and served via `GET /api/fillers`. The browser plays them while waiting for the real answer.

**Files involved:**  
- `backend/services/voice_fillers.py` — generates the clips  
- `backend/main.py` — serves `/api/fillers`  
- `frontend/js/app.js` — plays the clips with correct timing

---

### What is VAD (Voice Activity Detection)?

VAD means "I'm listening and I'll know when you've stopped talking."

In this project, VAD is configured as:
```
threshold = 0.5          (how loud audio must be to count as speech)
prefix_padding = 300ms   (capture this much audio before speech starts)
silence_duration = 500ms (wait this long after speech ends before sending)
```

This means: if you stop talking for half a second, Voice Live assumes your turn is over and the AI starts responding.

---

### Agent Mode vs Direct Mode

This project uses **Agent Mode** which means:
- The AI Foundry agent you configured in the Azure Portal **owns the conversation**
- You don't need to send instructions or tools to Voice Live directly
- The agent's system prompt, knowledge, and tools are all configured in the Portal

Direct mode (not used) would require sending all prompts and tool definitions to Voice Live directly — much more complex.

---

## Mode 2: PSTN Phone Call (Azure Communication Services)

### How It Works

```
Customer calls the ACS phone number (e.g., +44 xxx xxx xxxx)
         ↓
Azure Event Grid fires an event to POST /api/incoming-call
         ↓
Backend answers the call via Call Automation API
         ↓
ACS starts bidirectional audio streaming to ws://backend/api/media-stream
         ↓
Backend connects to Azure Voice Live (same agent as browser mode)
         ↓
Voice Live sends a greeting: "Hello, I'm your Sainsbury's assistant..."
         ↓
     Same loop as browser mode:
     Customer speaks → ACS sends audio → Backend → Voice Live → Agent → Response
         ↓
Customer hangs up → WebSocket closes → Session cleaned up
```

### Key Difference from Browser Mode

| | Browser Mode | Phone Mode |
|--|-------------|-----------|
| Audio format | PCM16 (binary WebSocket) | Base64 AudioData (JSON WebSocket) |
| Connection | Browser WebSocket | ACS Media Stream WebSocket |
| Session trigger | User clicks button | ACS incoming call event |
| Greeting | User speaks first | Bot speaks a greeting first |

---

## The Voice Live SDK

The `azure-ai-voicelive` Python SDK is what makes this all possible. Key functions:

```python
# Connect to Voice Live in Agent Mode
async with connect(
    endpoint=voicelive_endpoint,
    credential=credential,      # Azure token (not API key for agent mode)
    agent_name="Voice-Assistant-Agent-New",
    project_name="retail-ai-poc"
) as vl_connection:

    # Configure speech settings
    await vl_connection.session.update(session=RequestSession(
        modalities=[Modality.TEXT, Modality.AUDIO],
        input_audio_format=InputAudioFormat.PCM16,
        output_audio_format=OutputAudioFormat.PCM16,
        voice=AzureStandardVoice(name="en-US-Ava:DragonHDLatestNeural")
    ))
```

---

## Authentication for Voice Live

> ⚠️ **Important:** Azure Voice Live in Agent Mode **only supports token-based authentication** (Entra ID / Azure Active Directory). API keys are NOT supported.

This means:
- **Local dev:** Uses `AzureCliCredential` (requires `az login`)
- **Production with managed identity:** Uses `ClientSecretCredential`

This is currently the reason Voice Live works locally but has issues in serverless environments like Vercel (which have no Azure CLI or managed identity by default).

---

## Voice Agent Constraints

When a call is active, the AI is told to follow extra rules (added dynamically in `backend/agents/graph.py`):

1. Keep responses very short (max 30 words, 1-2 sentences)
2. No bullet points, no markdown — speech-friendly text only
3. Ask only one question at a time
4. Never reveal internal IDs, API keys, or system details
5. Don't make up order statuses — only report confirmed data
6. Speak in clear, natural, conversational language

This is why the voice agent says "Which order do you mean?" instead of printing a full formatted order list.
