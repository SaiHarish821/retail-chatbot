# Voice Live Architecture

## 1. Overview

Azure Voice Live provides **real-time voice-to-voice** capabilities for the Retail AI Assistant. It operates in **Agent Mode**, where the Azure AI Foundry agent owns the instructions, model, and tools — the backend only configures speech parameters and relays audio.

Two voice paths are supported:
1. **Browser Voice** — WebSocket at `/api/voice-realtime` between the browser and Voice Live
2. **ACS Media Stream** — WebSocket at `/api/media-stream` for PSTN telephone calls via Azure Communication Services

## 2. Architecture

```mermaid
graph TD
    subgraph "Browser"
        Mic["🎤 Microphone"]
        Speaker["🔊 Speaker"]
        AudioCtx["Web Audio API<br/>AudioContext (24kHz)"]
    end

    subgraph "FastAPI Backend"
        WS_Endpoint["WebSocket<br/>/api/voice-realtime"]
        VL_Relay["Voice Live Relay<br/>(Bidirectional)"]
        ToolExec["Tool Executor<br/>(voice_realtime.py)"]
    end

    subgraph "Azure Voice Live"
        VL_Session["Voice Live Session"]
        VL_Agent["Agent Mode<br/>(Foundry Agent)"]
        VL_VAD["Server VAD"]
        VL_TTS["Text-to-Speech"]
        VL_STT["Speech-to-Text"]
    end

    Mic -->|PCM16 24kHz| AudioCtx
    AudioCtx -->|Raw bytes| WS_Endpoint
    WS_Endpoint -->|Base64 audio| VL_Relay
    VL_Relay -->|input_audio_buffer.append| VL_Session
    VL_Session --> VL_VAD
    VL_VAD --> VL_STT
    VL_STT --> VL_Agent
    VL_Agent --> VL_TTS
    VL_TTS -->|Audio deltas| VL_Session
    VL_Session -->|Events| VL_Relay
    VL_Relay -->|JSON messages| WS_Endpoint
    WS_Endpoint -->|Base64 audio| AudioCtx
    AudioCtx --> Speaker

    VL_Agent -->|Tool call| VL_Session
    VL_Session -->|FUNCTION_CALL| VL_Relay
    VL_Relay --> ToolExec
    ToolExec -->|Result| VL_Relay
    VL_Relay -->|conversation_item.create| VL_Session
```

## 3. WebSocket Lifecycle

```mermaid
sequenceDiagram
    participant B as Browser
    participant WS as WebSocket Handler
    participant VL as Voice Live SDK
    participant Agent as Foundry Agent

    Note over B,WS: Connection Phase
    B->>WS: WebSocket CONNECT /api/voice-realtime
    WS->>WS: get_azure_credential()
    WS->>WS: Resolve endpoint + agent name
    WS->>VL: connect(endpoint, agent_name, project_name)
    VL-->>WS: async context manager entered

    Note over WS,VL: Session Configuration
    WS->>VL: session.update(RequestSession)
    Note right of VL: modalities: TEXT + AUDIO<br/>voice: en-US-Ava:DragonHDLatest<br/>input_format: PCM16<br/>output_format: PCM16<br/>transcription: whisper-1<br/>VAD: threshold=0.5, prefix=300ms, silence=500ms

    Note over B,Agent: Audio Streaming Phase
    par Browser → Voice Live
        loop While connected
            B->>WS: Binary PCM16 frame
            WS->>WS: base64 encode
            WS->>VL: input_audio_buffer.append(b64)
        end
    and Voice Live → Browser
        loop Events
            VL-->>WS: ServerEvent
            WS->>WS: Process event type
            WS-->>B: JSON message
        end
    end

    Note over B,WS: Disconnection
    B->>WS: WebSocket CLOSE
    WS->>WS: Exit VL context manager
    WS->>WS: Close WebSocket
```

## 4. Event Types

### Incoming Events (Voice Live → Backend)

| Event | Description | Action |
|-------|-------------|--------|
| `SPEECH_STARTED` | User started speaking | Notify browser: `{type: "speech_started"}` |
| `SPEECH_STOPPED` | User stopped speaking | Notify browser: `{type: "speech_stopped"}` |
| `TRANSCRIPTION_COMPLETED` | User speech transcribed | Send: `{type: "user_transcript", text}` |
| `RESPONSE_AUDIO_DELTA` | Audio response chunk | Send: `{type: "audio_delta", delta}` |
| `RESPONSE_AUDIO_TRANSCRIPT_DELTA` | Partial agent text | Send: `{type: "transcript_delta", delta}` |
| `RESPONSE_AUDIO_TRANSCRIPT_DONE` | Complete agent text | Send: `{type: "agent_transcript", text}` |
| `RESPONSE_DONE` | Response complete | Send: `{type: "response_done"}` |
| `FUNCTION_CALL_ARGUMENTS_DONE` | Tool call ready | Execute tool, return result |
| `ERROR` | Error occurred | Send: `{type: "error", message}` |

### Outgoing Commands (Backend → Voice Live)

| Command | Description |
|---------|-------------|
| `input_audio_buffer.append(audio)` | Send user audio chunk |
| `input_audio_buffer.clear()` | Clear audio buffer (on barge-in) |
| `conversation_item.create(...)` | Add tool result to conversation |
| `response.create()` | Trigger agent response after tool execution |
| `session.update(config)` | Update session configuration |

## 5. Audio Pipeline

### Input Audio (User → Agent)

```mermaid
flowchart LR
    Mic["Microphone"] -->|MediaStream| AudioCtx["AudioContext<br/>(24kHz sample rate)"]
    AudioCtx -->|ScriptProcessor<br/>bufferSize=4096| Process["Float32 → Int16<br/>PCM16 conversion"]
    Process -->|Uint8Array| WS["WebSocket<br/>binary frame"]
    WS -->|Base64 encode| VL["Voice Live<br/>input_audio_buffer"]
```

### Output Audio (Agent → User)

```mermaid
flowchart LR
    VL["Voice Live<br/>audio_delta event"] -->|Base64 PCM16| WS["WebSocket<br/>JSON message"]
    WS -->|Decode Base64| Buffer["ArrayBuffer<br/>Int16 PCM"]
    Buffer -->|Int16 → Float32| AudioBuf["AudioBuffer<br/>(24kHz)"]
    AudioBuf -->|AudioBufferSourceNode| Speaker["Speaker"]
```

### Audio Format

| Parameter | Value |
|-----------|-------|
| Sample Rate | 24,000 Hz |
| Bit Depth | 16-bit signed integer |
| Channels | 1 (mono) |
| Encoding | PCM (raw, uncompressed) |
| Endianness | Little-endian |

## 6. Voice Activity Detection (VAD)

Server-side VAD is configured in the session update:

```python
RequestSession(
    turn_detection=RequestTurnDetection(
        type="server_vad",
        threshold=0.5,           # Sensitivity (0.0 = most sensitive)
        prefix_padding_ms=300,   # Audio before speech detection
        silence_duration_ms=500  # Silence before end-of-turn
    )
)
```

```mermaid
stateDiagram-v2
    [*] --> Listening
    Listening --> SpeechDetected: Audio level > threshold
    SpeechDetected --> Speaking: Sustained speech
    Speaking --> SilenceDetected: Audio level < threshold
    SilenceDetected --> Speaking: Speech resumes < 500ms
    SilenceDetected --> EndOfTurn: Silence > 500ms
    EndOfTurn --> Processing: Trigger transcription
    Processing --> ResponseGeneration: LLM inference
    ResponseGeneration --> AudioPlayback: Audio streaming
    AudioPlayback --> Listening: Response complete
    AudioPlayback --> SpeechDetected: Barge-in detected
```

## 7. Tool Execution in Voice Mode

When the Voice Live agent invokes a tool, the flow is:

```mermaid
sequenceDiagram
    participant VL as Voice Live
    participant Backend as FastAPI
    participant DB as Database

    VL-->>Backend: FUNCTION_CALL_ARGUMENTS_DONE<br/>{name: "check_stock_tool", args: {product_name: "milk"}}
    
    Backend->>Backend: execute_voice_tool("check_stock_tool", {product_name: "milk"})
    Backend->>DB: check_stock(router, "milk", None)
    DB-->>Backend: Stock results string
    
    Backend->>VL: conversation_item.create(<br/>  type="function_call_output",<br/>  call_id=event.call_id,<br/>  output=stock_results<br/>)
    Backend->>VL: response.create()
    
    Note over VL: Agent processes tool results<br/>and generates audio response
    VL-->>Backend: RESPONSE_AUDIO_DELTA (audio chunks)
```

### Available Voice Tools

| Tool Name | Maps To | Description |
|-----------|---------|-------------|
| `search_products_tool` | `search_products()` | Search product catalog |
| `check_stock_tool` | `check_stock()` | Check inventory levels |
| `get_active_promotions_tool` | `get_active_promotions()` | List promotions |
| `update_customer_address_tool` | `update_customer_address()` | Update delivery address |
| `issue_refund_tool` | `issue_refund()` | Process a refund |
| `transfer_to_human_agent_tool` | (inline handler) | Handoff to human agent |

## 8. Voice Filler System

To eliminate dead silence while the agent processes queries, the system pre-renders filler audio clips at startup:

### Filler Trees (5 escalation sequences)

Each tree is a 4-step escalation sequence. One tree is chosen per wait to prevent repetition:

| Step | Tree 1 | Tree 2 | Tree 3 |
|------|--------|--------|--------|
| 1 | "Alright, let me check that for you." | "Sure, let me look into this for you." | "Good question, let me dig into that." |
| 2 | "Searching our system now." | "Going through the details now." | "Checking my sources on this." |
| 3 | "Almost there, give me a moment." | "Bear with me, nearly got it." | "Hold on, piecing it together." |
| 4 | "Okay, just pulling it all together." | "Right, just finalising your answer." | "Nearly there, thanks for your patience." |

### Thinking Interjections (6 clips)

Short sounds sprinkled between tree steps for natural feel:
- "Hmm..."
- "Mmm, let me see..."
- "Uh, one moment..."
- "Hmm, okay..."
- "Let me think..."
- "Right..."

### Timing

| Parameter | Value | Purpose |
|-----------|-------|---------|
| Grace period | 5,000ms | Skip fillers if response arrives quickly |
| Min gap between fillers | 3,500ms | Prevent overlapping |
| Max gap between fillers | 6,000ms | Keep conversation alive |

### Rendering Pipeline

```mermaid
flowchart TD
    Start["Server Startup"] --> GetToken["Get TTS Token<br/>(Cognitive Services)"]
    GetToken --> Flatten["Flatten all phrases<br/>(20 tree + 6 thinking = 26)"]
    Flatten --> Parallel["ThreadPoolExecutor<br/>max_workers=10"]
    
    subgraph "Parallel TTS Synthesis"
        S1["_synthesize_pcm(phrase1)"]
        S2["_synthesize_pcm(phrase2)"]
        S3["_synthesize_pcm(...)"]
        S4["_synthesize_pcm(phrase26)"]
    end
    
    Parallel --> S1
    Parallel --> S2
    Parallel --> S3
    Parallel --> S4
    
    S1 --> Reassemble["Reassemble into<br/>tree_clips + thinking_clips"]
    S2 --> Reassemble
    S3 --> Reassemble
    S4 --> Reassemble
    
    Reassemble --> Serve["GET /api/fillers<br/>(base64 PCM16 JSON)"]
```

## 9. ACS Media Stream Integration

For PSTN phone calls, the same Voice Live session is established but audio comes from ACS instead of the browser:

```mermaid
sequenceDiagram
    participant Phone as PSTN Phone
    participant ACS as Azure Communication Services
    participant WS as /api/media-stream
    participant VL as Voice Live

    Phone->>ACS: Incoming call
    ACS->>WS: WebSocket connect (media stream)
    WS->>VL: connect(endpoint, agent_name)
    VL-->>WS: Session established

    Note over Phone,VL: Bidirectional audio relay

    Phone->>ACS: Caller audio
    ACS->>WS: Mixed audio (base64 PCM)
    WS->>VL: input_audio_buffer.append(audio)

    VL-->>WS: RESPONSE_AUDIO_DELTA
    WS->>ACS: Audio response
    ACS->>Phone: Play to caller
```

## 10. Credential Resolution

```mermaid
flowchart TD
    Start["get_azure_credential()"] --> CheckSP{"AZURE_CLIENT_ID +<br/>AZURE_CLIENT_SECRET<br/>+ AZURE_TENANT_ID<br/>all set?"}
    
    CheckSP -->|Yes| CSC["ClientSecretCredential<br/>(Production/Render/Railway)"]
    CheckSP -->|No| CheckTenant{"AZURE_TENANT_ID<br/>set?"}
    
    CheckTenant -->|Yes| CLI_Tenant["AzureCliCredential<br/>(tenant_id=value)"]
    CheckTenant -->|No| CLI_Default["AzureCliCredential<br/>(no tenant)"]
    
    CSC --> Return["Return credential"]
    CLI_Tenant --> Return
    CLI_Default --> Return
```
