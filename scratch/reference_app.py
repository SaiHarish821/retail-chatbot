"""
MTN Voice + Chat Prototype (Relay Architecture)
- Chat box: FastAPI -> Foundry Agent (my-local-agent) via classic AgentsClient (REST)
- Voice: Browser <--(plain WebSocket, audio bytes only)--> FastAPI <--(authenticated WebSocket via VoiceLive SDK)--> Voice Live (Agent mode) -> my-local-agent

This avoids the browser limitation where WebSocket cannot send Authorization headers -
the FastAPI backend holds the authenticated Voice Live connection (using AzureCliCredential),
and simply relays raw PCM16 audio bytes to/from the browser over a local, unauthenticated WebSocket.

Run:
    uvicorn mtn_voice_chat_relay:app --reload --port 8003
"""

import os
import json
import base64
import asyncio
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from azure.identity import AzureCliCredential, ClientSecretCredential
from azure.ai.projects import AIProjectClient

from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import (
    AzureStandardVoice,
    InputAudioFormat,
    Modality,
    OutputAudioFormat,
    RequestSession,
    ServerEventType,
    ServerVad,
)

load_dotenv(override=True)

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

TENANT_ID = os.environ.get("AZURE_TENANT_ID")
FOUNDRY_ENDPOINT = os.environ["FOUNDRY_ENDPOINT"]
VOICELIVE_ENDPOINT = os.environ["AZURE_VOICELIVE_ENDPOINT"]
VOICELIVE_MODEL = os.environ.get("AZURE_VOICELIVE_MODEL", "gpt-realtime")
VOICE_NAME = os.environ.get("AZURE_VOICELIVE_VOICE", "en-US-Ava:DragonHDLatestNeural")

# Both chat and voice route through the same *new* Foundry agent (e.g.
# "gpt-4o-mtn"), so every answer is grounded in that agent's knowledge base.
# The agent is identified by name + project (not a classic asst_ id).
PROJECT_NAME = os.environ.get("AZURE_FOUNDRY_PROJECT_NAME") or FOUNDRY_ENDPOINT.rstrip("/").split("/")[-1]
AGENT_NAME = os.environ["AZURE_AGENT_NAME"]  # new Foundry agent name, e.g. "gpt-4o-mtn"
AGENT_VERSION = os.environ.get("AZURE_AGENT_VERSION")  # optional: pin a version

# Deployed (Render/Railway): use the service principal from env vars.
# Local dev: fall back to `az login` (AzureCliCredential), which matches the
# resource tenant automatically.
if os.environ.get("AZURE_CLIENT_SECRET"):
    credential = ClientSecretCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
    )
else:
    credential = AzureCliCredential(tenant_id=TENANT_ID) if TENANT_ID else AzureCliCredential()
print(f"Foundry agent -> project={PROJECT_NAME!r} agent={AGENT_NAME!r}")

# Chat uses the new Foundry agent via its OpenAI-compatible Responses API.
# `agent_reference` selects the named agent so replies use its instructions,
# tools, and knowledge base. AGENT_VERSION pins a version when set.
project_client = AIProjectClient(endpoint=FOUNDRY_ENDPOINT, credential=credential)
openai_client = project_client.get_openai_client()

AGENT_REFERENCE = {"name": AGENT_NAME, "type": "agent_reference"}
if AGENT_VERSION:
    AGENT_REFERENCE["version"] = AGENT_VERSION

# One shared server-side conversation for this prototype (single-user demo only),
# so multi-turn context carries across messages.
conversation = openai_client.conversations.create()
print("Chat conversation created:", conversation.id)


def _strip_markdown(text: str) -> str:
    """Remove asterisks the model uses for markdown emphasis/bullets, so the
    voice transcript reads as clean plain text (it's spoken, not rendered)."""
    return text.replace("*", "")


# ---- Filler clips -------------------------------------------------------------
# Short phrases spoken while the agent is still composing its answer, so the
# caller isn't left in silence. We pre-render them with the SAME Azure voice the
# agent uses (via the Speech TTS REST endpoint), so the filler is
# indistinguishable from the agent's own voice. Rendered once at startup as
# base64 PCM16 24 kHz (the format the browser already plays for agent audio).
# Each "tree" is an ordered escalation spoken across a long wait: the 1st line
# acknowledges, the middle lines show progress ("checking the knowledge base"),
# the last reassures ("almost there"). One tree is chosen per wait, so the
# structure never repeats turn-to-turn. Short "thinking" sounds are sprinkled
# between steps for a natural, human feel.
FILLER_TREES = [
    [
        "Alright, let me check that for you.",
        "Searching the knowledge base now.",
        "Almost there, give me a moment.",
        "Okay, just pulling it all together.",
    ],
    [
        "Sure, let me look into this for you.",
        "Going through the details now.",
        "Bear with me, nearly got it.",
        "Right, just finalizing your answer.",
    ],
    [
        "Good question, let me dig into that.",
        "Checking my sources on this.",
        "Hold on, piecing it together.",
        "Nearly there, thanks for your patience.",
    ],
    [
        "Okay, give me a second on that.",
        "Looking through the knowledge base.",
        "Just making sure I get this right.",
        "Almost ready with your answer.",
    ],
    [
        "Let me find that for you.",
        "Pulling up the relevant info.",
        "A few more seconds, hang tight.",
        "Right, putting the answer together now.",
    ],
]

# Short interjections sprinkled between tree steps.
FILLER_THINKING = [
    "Hmm...",
    "Mmm, let me see...",
    "Uh, one moment...",
    "Hmm, okay...",
    "Let me think...",
    "Right...",
]


def _synthesize_pcm(text: str, token: str) -> str:
    """Render `text` to base64 PCM16 24 kHz using the same voice as Voice Live."""
    ssml = (
        f"<speak version='1.0' xml:lang='en-US'>"
        f"<voice name='{VOICE_NAME}'>{text}</voice></speak>"
    )
    url = VOICELIVE_ENDPOINT.rstrip("/") + "/tts/cognitiveservices/v1"
    req = urllib.request.Request(url, data=ssml.encode("utf-8"), method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/ssml+xml")
    req.add_header("X-Microsoft-OutputFormat", "raw-24khz-16bit-mono-pcm")
    req.add_header("User-Agent", "mtn-voice-filler")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return base64.b64encode(resp.read()).decode("utf-8")


FILLER_TREE_CLIPS = []
FILLER_THINKING_CLIPS = []
try:
    _tts_token = credential.get_token("https://cognitiveservices.azure.com/.default").token
    _tree_phrases = [p for tree in FILLER_TREES for p in tree]
    _all_phrases = _tree_phrases + FILLER_THINKING
    # Render in parallel so startup stays fast despite the larger phrase set.
    with ThreadPoolExecutor(max_workers=10) as _ex:
        _clips = list(_ex.map(lambda p: _synthesize_pcm(p, _tts_token), _all_phrases))
    _flat = iter(_clips[: len(_tree_phrases)])
    FILLER_TREE_CLIPS = [[next(_flat) for _ in tree] for tree in FILLER_TREES]
    FILLER_THINKING_CLIPS = _clips[len(_tree_phrases):]
    print(f"Pre-rendered {len(FILLER_TREES)} filler trees + {len(FILLER_THINKING_CLIPS)} thinking clips")
except Exception as e:
    print("Filler synthesis failed (voice fillers disabled):", repr(e))


@app.get("/fillers")
async def fillers():
    """Browser fetches the pre-rendered filler clips (escalation trees + interjections)."""
    return {"trees": FILLER_TREE_CLIPS, "thinking": FILLER_THINKING_CLIPS}


class ChatRequest(BaseModel):
    message: str


@app.post("/chat")
async def chat(req: ChatRequest):
    resp = openai_client.responses.create(
        extra_body={"agent_reference": AGENT_REFERENCE},
        conversation=conversation.id,
        input=req.message,
    )
    return {"reply": resp.output_text}


@app.post("/chat-stream")
async def chat_stream(req: ChatRequest):
    """Streams the agent's reply token-by-token using Server-Sent Events.

    Uses the Responses API streaming protocol: text arrives as
    `response.output_text.delta` events carrying a `.delta` string.
    """

    def event_generator():
        # Use create(stream=True) rather than the .stream() helper: the helper
        # requires a `model` argument, which we don't pass because the agent
        # (and its model) is selected via `agent_reference` in extra_body.
        stream = openai_client.responses.create(
            extra_body={"agent_reference": AGENT_REFERENCE},
            conversation=conversation.id,
            input=req.message,
            stream=True,
        )
        for event in stream:
            event_type = getattr(event, "type", "")

            if event_type == "response.output_text.delta":
                if event.delta:
                    yield f"data: {json.dumps({'delta': event.delta})}\n\n"

            elif event_type == "error":
                yield f"data: {json.dumps({'error': str(getattr(event, 'message', event))})}\n\n"

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.websocket("/ws/voice")
async def voice_ws(websocket: WebSocket):
    """
    Browser connects here (no auth needed - localhost only for this prototype).
    This handler opens its OWN authenticated connection to Voice Live and
    relays events/audio both directions.
    """
    await websocket.accept()
    print("Browser connected to /ws/voice")

    try:
        # Agent mode: omit `model` and pass the new Foundry agent's name +
        # project. Voice Live drives the conversation through that agent, so
        # spoken replies are grounded in its knowledge base. Agent mode requires
        # Entra ID auth, which we already use.
        connect_kwargs = dict(
            endpoint=VOICELIVE_ENDPOINT,
            credential=credential,
            agent_name=AGENT_NAME,
            project_name=PROJECT_NAME,
        )
        if AGENT_VERSION:
            connect_kwargs["agent_version"] = AGENT_VERSION

        async with connect(**connect_kwargs) as vl_connection:

            # Configure the Voice Live session. In agent mode the agent owns the
            # instructions/model/knowledge base, so we only set the speech-layer
            # options (voice, audio formats, turn detection, transcription) and
            # deliberately do NOT send `instructions` here.
            voice_config = AzureStandardVoice(name=VOICE_NAME)
            session_config = RequestSession(
                modalities=[Modality.TEXT, Modality.AUDIO],
                voice=voice_config,
                input_audio_format=InputAudioFormat.PCM16,
                output_audio_format=OutputAudioFormat.PCM16,
                turn_detection=ServerVad(threshold=0.5, prefix_padding_ms=300, silence_duration_ms=500),
                input_audio_transcription={"model": "azure-speech"},
            )
            await vl_connection.session.update(session=session_config)
            print("Voice Live session configured (agent mode)")

            async def browser_to_voicelive():
                """Read raw PCM16 audio bytes from browser, forward to Voice Live."""
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        audio_b64 = base64.b64encode(data).decode("utf-8")
                        await vl_connection.input_audio_buffer.append(audio=audio_b64)
                except WebSocketDisconnect:
                    print("Browser disconnected (audio in)")
                except Exception as e:
                    print("browser_to_voicelive error:", repr(e))

            async def voicelive_to_browser():
                """Read events from Voice Live, forward relevant audio/text to browser as JSON."""
                try:
                    async for event in vl_connection:
                        if event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
                            delta = event.delta
                            if isinstance(delta, (bytes, bytearray)):
                                delta = base64.b64encode(delta).decode("utf-8")
                            await websocket.send_text(json.dumps({
                                "type": "audio_delta",
                                "delta": delta,
                            }))
                        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                            await websocket.send_text(json.dumps({"type": "speech_started"}))
                        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
                            await websocket.send_text(json.dumps({"type": "speech_stopped"}))
                        elif event.type == ServerEventType.RESPONSE_AUDIO_DONE:
                            await websocket.send_text(json.dumps({"type": "audio_done"}))
                        elif event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_DELTA:
                            # Partial user speech-to-text, streamed live as they speak.
                            await websocket.send_text(json.dumps({
                                "type": "user_transcript_delta",
                                "delta": _strip_markdown(event.delta or ""),
                            }))
                        elif event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                            # Final user transcript (replaces the streamed partials).
                            await websocket.send_text(json.dumps({
                                "type": "user_transcript",
                                "text": _strip_markdown(event.transcript or ""),
                            }))
                        elif event.type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                            await websocket.send_text(json.dumps({
                                "type": "agent_transcript",
                                "text": _strip_markdown(event.transcript or ""),
                            }))
                        elif event.type == ServerEventType.ERROR:
                            await websocket.send_text(json.dumps({"type": "error", "message": str(event.error.message)}))
                except Exception as e:
                    print("voicelive_to_browser error:", repr(e))

            await asyncio.gather(browser_to_voicelive(), voicelive_to_browser())

    except WebSocketDisconnect:
        print("Browser disconnected from /ws/voice")
    except Exception as e:
        print("Voice WS error:", e)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass


@app.get("/", response_class=HTMLResponse)
async def ui():
    return """
<!DOCTYPE html>
<html>
<head>
<title>MTN Voice + Chat Assistant</title>
<style>
* { box-sizing: border-box; }
body {
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    max-width: 760px;
    margin: 0 auto;
    padding: 0;
    background: #f4f4f4;
    color: #1a1a1a;
}
.header {
    background: #000000;
    padding: 20px 30px;
    display: flex;
    align-items: center;
    gap: 12px;
}
.header .dot { width: 14px; height: 14px; background: #FFCC08; border-radius: 50%; }
.header h1 { color: #ffffff; font-size: 20px; font-weight: 600; margin: 0; letter-spacing: 0.5px; }

.container { padding: 25px 30px; }

.tabs { display: flex; gap: 8px; margin-bottom: 18px; }
.tab-btn {
    flex: 1;
    padding: 12px;
    border: none;
    border-radius: 10px;
    background: #ffffff;
    color: #444;
    font-weight: 600;
    cursor: pointer;
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
}
.tab-btn.active { background: #FFCC08; color: #1a1a1a; }

#chat {
    height: 380px;
    overflow-y: auto;
    background: #ffffff;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    margin-bottom: 16px;
}
.user { background: #000000; color: #ffffff; padding: 10px 16px; border-radius: 16px; margin: 6px 0; display: inline-block; max-width: 75%; font-size: 14px; }
.agent { background: #FFCC08; color: #1a1a1a; padding: 10px 16px; border-radius: 16px; margin: 6px 0; display: inline-block; max-width: 75%; font-size: 14px; font-weight: 500; }

.chat-input-row { display: flex; gap: 10px; margin-bottom: 20px; }
.chat-input-row input {
    flex: 1;
    padding: 12px 16px;
    border-radius: 24px;
    border: 1px solid #ddd;
    font-size: 14px;
}
.chat-input-row button {
    padding: 12px 22px;
    border: none;
    border-radius: 24px;
    background: #000000;
    color: #FFCC08;
    font-weight: 700;
    cursor: pointer;
}

.action-bar { display: flex; flex-direction: column; align-items: center; gap: 10px; }
#micBtn {
    background: #FFCC08;
    color: #1a1a1a;
    border: none;
    padding: 16px 40px;
    border-radius: 30px;
    cursor: pointer;
    font-size: 16px;
    font-weight: 700;
    box-shadow: 0 4px 12px rgba(255,204,8,0.4);
}
#micBtn.recording { background: #000000; color: #FFCC08; }
#status { font-size: 13px; color: #777; font-weight: 500; min-height: 18px; }
.hidden { display: none; }
</style>
</head>
<body>
<div class="header">
    <div class="dot"></div>
    <h1>MTN AI Assistant</h1>
</div>

<div class="container">
    <div class="tabs">
        <button class="tab-btn active" id="tabChatBtn" onclick="showTab('chat')">Chat</button>
        <button class="tab-btn" id="tabVoiceBtn" onclick="showTab('voice')">Live Voice</button>
    </div>

    <div id="chat"></div>

    <div id="chatPanel">
        <div class="chat-input-row">
            <input type="text" id="chatInput" placeholder="Type a message..." onkeypress="if(event.key==='Enter') sendChat()">
            <button onclick="sendChat()">Send</button>
            <button onclick="sendChatStream()">Send (Streaming)</button>
        </div>
    </div>

    <div id="voicePanel" class="hidden">
        <div class="action-bar">
            <button id="micBtn" onclick="toggleVoice()">Start Live Voice</button>
            <div id="status"></div>
        </div>
    </div>
</div>

<script>
function showTab(tab) {
    document.getElementById('chatPanel').classList.toggle('hidden', tab !== 'chat');
    document.getElementById('voicePanel').classList.toggle('hidden', tab !== 'voice');
    document.getElementById('tabChatBtn').classList.toggle('active', tab === 'chat');
    document.getElementById('tabVoiceBtn').classList.toggle('active', tab === 'voice');
}

function addMessage(role, text) {
    const chat = document.getElementById('chat');
    const div = document.createElement('div');
    div.style.textAlign = role === 'user' ? 'right' : 'left';
    div.innerHTML = `<span class="${role}">${text}</span>`;
    chat.appendChild(div);
    chat.scrollTop = chat.scrollHeight;
}

// Live user transcription: a single bubble grows as partial deltas arrive,
// then is replaced by the final transcript when the user stops speaking.
let liveUserSpan = null;
function appendUserDelta(delta) {
    if (!delta) return;
    const chat = document.getElementById('chat');
    if (!liveUserSpan) {
        const div = document.createElement('div');
        div.style.textAlign = 'right';
        liveUserSpan = document.createElement('span');
        liveUserSpan.className = 'user';
        div.appendChild(liveUserSpan);
        chat.appendChild(div);
    }
    liveUserSpan.textContent += delta;
    chat.scrollTop = chat.scrollHeight;
}
function finalizeUserTranscript(text) {
    if (liveUserSpan) {
        if (text) liveUserSpan.textContent = text;  // replace partials with clean final
        liveUserSpan = null;
    } else if (text) {
        addMessage('user', text);  // no deltas arrived; just show the final
    }
}

// ---------- Chat (non-streaming, original working) ----------
async function sendChat() {
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    if (!text) return;
    addMessage('user', text);
    input.value = '';
    const res = await fetch('/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text })
    });
    const data = await res.json();
    addMessage('agent', data.reply);
}

// ---------- Chat (streaming, new) ----------
async function sendChatStream() {
    const input = document.getElementById('chatInput');
    const text = input.value.trim();
    if (!text) return;
    addMessage('user', text);
    input.value = '';

    const chat = document.getElementById('chat');
    const agentDiv = document.createElement('div');
    agentDiv.style.textAlign = 'left';
    const span = document.createElement('span');
    span.className = 'agent';
    span.textContent = '';
    agentDiv.appendChild(span);
    chat.appendChild(agentDiv);
    chat.scrollTop = chat.scrollHeight;

    const res = await fetch('/chat-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text })
    });

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\\n\\n');
        buffer = lines.pop();

        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const payload = JSON.parse(line.slice(6));
            if (payload.delta) {
                span.textContent += payload.delta;
                chat.scrollTop = chat.scrollHeight;
            }
        }
    }
}

// ---------- Voice (relay through FastAPI /ws/voice) ----------
let ws = null;
let audioContext, processor, input, globalStream;
let recording = false;
let playbackQueue = [];
let playing = false;

// ---------- Filler speech (mask the wait before the agent replies) ----------
// While we wait for the agent's audio we play an escalating "tree" of fillers:
// the 1st line acknowledges, the middle lines show progress, the last reassures
// ("almost there"), with short "hmm" interjections sprinkled between. One tree
// is picked per wait so the structure never repeats. Rules: once a filler
// starts we let it finish before the real response plays (no overlap); a fast
// response (within the grace delay) skips fillers entirely. All clips are
// pre-rendered server-side in the SAME Azure voice as the agent and played
// through the same audio path, so they're indistinguishable from the agent.
const FILLER_GRACE_MS = 5000;   // wait 5s before the first filler (skip if reply is faster)
const FILLER_GAP_MIN_MS = 3500; // min pause between consecutive fillers
const FILLER_GAP_MAX_MS = 6000; // max pause between consecutive fillers
let fillerTrees = [];          // escalation sequences; each is an array of base64 clips
let fillerThinking = [];       // short "hmm"-style interjection clips
let currentTree = null;        // the tree chosen for the current wait
let treeStep = 0;              // position within the current tree
let awaitingResponse = false;  // user finished; we're waiting for agent audio
let fillerActive = false;      // a filler clip is currently playing
let fillerSource = null;       // current AudioBufferSourceNode for the filler
let fillerTimer = null;
let responseDone = false;      // agent signalled its audio response is complete

async function loadFillerClips() {
    if (fillerTrees.length) return;
    try {
        const res = await fetch('/fillers');
        const data = await res.json();
        fillerTrees = data.trees || [];
        fillerThinking = data.thinking || [];
    } catch (e) { console.warn('Could not load filler clips', e); }
}

function randomThinking() {
    if (!fillerThinking.length) return null;
    return fillerThinking[Math.floor(Math.random() * fillerThinking.length)];
}

// Next clip for this wait: walk the chosen tree in order, occasionally slipping
// in a "hmm" before the next step. Once the tree is exhausted, keep stalling
// with thinking sounds.
function pickNextFillerClip() {
    if (treeStep > 0 && Math.random() < 0.5) {
        const t = randomThinking();
        if (t) return t;
    }
    if (currentTree && treeStep < currentTree.length) {
        return currentTree[treeStep++];
    }
    return randomThinking();
}

function randomGapMs() {
    return FILLER_GAP_MIN_MS + Math.random() * (FILLER_GAP_MAX_MS - FILLER_GAP_MIN_MS);
}

// Decode + play one base64 PCM16 24kHz clip; calls onended when finished.
function playPcmClip(base64, onended) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    const int16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;
    const audioBuffer = ctx.createBuffer(1, float32.length, 24000);
    audioBuffer.copyToChannel(float32, 0);
    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);
    source.onended = () => { try { ctx.close(); } catch (e) {} if (onended) onended(); };
    source.start();
    return source;
}

function speakFiller() {
    if (!awaitingResponse) return;            // response already started
    const clip = pickNextFillerClip();
    if (!clip) return;                        // nothing to play -> stay silent
    fillerActive = true;
    fillerSource = playPcmClip(clip, () => {
        fillerSource = null;
        fillerActive = false;
        if (playbackQueue.length > 0) {       // response arrived during filler
            awaitingResponse = false;
            playNext();
        } else if (awaitingResponse && !responseDone) {
            // Still waiting: pause a beat before the next filler so it sounds
            // natural, not a run-on. If the response lands during the gap,
            // queueAudio() clears this timer and plays it instead.
            fillerTimer = setTimeout(() => {
                if (awaitingResponse && playbackQueue.length === 0 && !responseDone) speakFiller();
            }, randomGapMs());
        } else {                              // response finished with no audio left
            cancelFillers();
        }
    });
}

function startFillerCycle() {
    cancelFillers();
    awaitingResponse = true;
    responseDone = false;
    treeStep = 0;
    currentTree = fillerTrees.length
        ? fillerTrees[Math.floor(Math.random() * fillerTrees.length)]
        : null;
    fillerTimer = setTimeout(() => {
        if (awaitingResponse && playbackQueue.length === 0) speakFiller();
    }, FILLER_GRACE_MS);
}

function cancelFillers() {
    awaitingResponse = false;
    fillerActive = false;
    if (fillerTimer) { clearTimeout(fillerTimer); fillerTimer = null; }
    if (fillerSource) {
        try { fillerSource.onended = null; fillerSource.stop(); } catch (e) {}
        fillerSource = null;
    }
}

async function toggleVoice() {
    if (!recording) {
        await startVoice();
    } else {
        stopVoice();
    }
}

async function startVoice() {
    document.getElementById('status').textContent = 'Connecting...';
    loadFillerClips();   // fetch the agent-voice filler clips (once)

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${window.location.host}/ws/voice`);

    ws.onopen = () => {
        document.getElementById('status').textContent = 'Connected. Listening...';
        recording = true;
        document.getElementById('micBtn').textContent = 'Stop Live Voice';
        document.getElementById('micBtn').classList.add('recording');
        startMic();
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        handleServerEvent(msg);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error', err);
        document.getElementById('status').textContent = 'Connection error - see console';
    };

    ws.onclose = () => {
        document.getElementById('status').textContent = 'Disconnected';
        recording = false;
        document.getElementById('micBtn').textContent = 'Start Live Voice';
        document.getElementById('micBtn').classList.remove('recording');
    };
}

function handleServerEvent(event) {
    if (event.type === 'audio_delta' && event.delta) {
        queueAudio(event.delta);
    } else if (event.type === 'speech_started') {
        document.getElementById('status').textContent = 'Listening...';
        cancelFillers();          // barge-in: stop any filler/response gating
        playbackQueue = [];
    } else if (event.type === 'speech_stopped') {
        document.getElementById('status').textContent = 'Processing...';
        startFillerCycle();       // begin masking the wait with fillers
    } else if (event.type === 'audio_done') {
        document.getElementById('status').textContent = 'Ready for next input...';
        responseDone = true;
        // If the turn produced no audio to play, don't keep firing fillers.
        if (!playing && !fillerActive && playbackQueue.length === 0) cancelFillers();
    } else if (event.type === 'user_transcript_delta') {
        appendUserDelta(event.delta);
    } else if (event.type === 'user_transcript') {
        finalizeUserTranscript(event.text);
    } else if (event.type === 'agent_transcript') {
        addMessage('agent', event.text);
    } else if (event.type === 'error') {
        console.error('VoiceLive error', event.message);
        document.getElementById('status').textContent = 'Error: ' + event.message;
    }
}

async function startMic() {
    globalStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    audioContext = new AudioContext({ sampleRate: 24000 });
    input = audioContext.createMediaStreamSource(globalStream);
    processor = audioContext.createScriptProcessor(2048, 1, 1);

    processor.onaudioprocess = (e) => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        const data = e.inputBuffer.getChannelData(0);
        const pcm16 = floatTo16BitPCM(data);
        ws.send(pcm16.buffer);
    };

    input.connect(processor);
    processor.connect(audioContext.destination);
}

function floatTo16BitPCM(float32Array) {
    const out = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
        let s = Math.max(-1, Math.min(1, float32Array[i]));
        out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return out;
}

function queueAudio(base64Delta) {
    playbackQueue.push(base64Delta);

    // If a filler is mid-sentence, hold the response audio; the filler's
    // onend handler will start playback as soon as it finishes (no overlap).
    if (fillerActive) return;

    // Response arrived during the grace delay (before any filler spoke):
    // cancel the pending filler and play immediately.
    if (awaitingResponse) {
        awaitingResponse = false;
        if (fillerTimer) { clearTimeout(fillerTimer); fillerTimer = null; }
    }
    if (!playing) playNext();
}

function playNext() {
    if (playbackQueue.length === 0) { playing = false; return; }
    playing = true;
    const base64 = playbackQueue.shift();
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

    const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    const int16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) float32[i] = int16[i] / 32768;

    const audioBuffer = ctx.createBuffer(1, float32.length, 24000);
    audioBuffer.copyToChannel(float32, 0);
    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(ctx.destination);
    source.onended = playNext;
    source.start();
}

function stopVoice() {
    recording = false;
    if (processor) processor.disconnect();
    if (input) input.disconnect();
    if (globalStream) globalStream.getTracks().forEach(t => t.stop());
    if (ws) ws.close();
    document.getElementById('micBtn').textContent = 'Start Live Voice';
    document.getElementById('micBtn').classList.remove('recording');
    document.getElementById('status').textContent = 'Stopped';
}
</script>
</body>
</html>
"""