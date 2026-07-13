"""
Retail AI Assistant – FastAPI Backend
Azure AI Foundry + GPT-4o + Azure Communication Services Speech
"""

import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import sys
import asyncio
import time
import base64
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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents import AgentRouter
from services import ACSBotManager

load_dotenv()

# ─── Tracing and Telemetry setup (Azure AI Foundry / Application Insights) ───
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from azure.ai.projects.telemetry import AIProjectInstrumentor
        
        # Enable GenAI OpenTelemetry collection
        os.environ["AZURE_EXPERIMENTAL_ENABLE_GENAI_TRACING"] = "true"
        os.environ["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] = "true"
        
        configure_azure_monitor()
        instrumentor = AIProjectInstrumentor()
        instrumentor.instrument()
        logging.info("[Telemetry] Azure AI Projects telemetry tracing configured successfully.")
    except Exception as telemetry_err:
        logging.warning(f"[Telemetry] Tracing setup skipped (missing libraries or invalid string): {telemetry_err}")

import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="Retail AI Assistant", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGIN", "*")],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# ─── Load mock data ────────────────────────────────────────────────────────

MOCK_DIR = Path(__file__).parent.parent / "mock_data"

# Initialize and seed database
try:
    from database import init_db, seed_db
    init_db()
    seed_db()
except Exception as e:
    print(f"Database initialization skipped (running in read-only environment): {e}")

from database import load_db_customer_data
CUSTOMER_DATA = load_db_customer_data()

# ─── Agent router (singleton) ─────────────────────────────────────────────

agent_router = AgentRouter(
    customer_data=CUSTOMER_DATA,
)

acs_bot_manager = ACSBotManager()

def resolve_agent_voice_name(cred, project_endpoint: str, agent_name: str) -> str:
    """Fetch the voice name configured on the Voice Live Agent in Azure AI Foundry."""
    try:
        from azure.ai.projects import AIProjectClient
        if not project_endpoint:
            project_endpoint = "https://retail-ai-poc.services.ai.azure.com/api/projects/retail-ai-poc"
        client = AIProjectClient(endpoint=project_endpoint, credential=cred)
        agents = list(client.agents.list())
        agent = next((a for a in agents if a.name == agent_name), None)
        if agent and hasattr(agent, "versions"):
            latest = agent.versions.get("latest", {})
            metadata = latest.get("metadata", {}) if hasattr(latest, "get") else {}
            vl_config_str = metadata.get("microsoft.voice-live.configuration")
            if vl_config_str:
                import json
                vl_config = json.loads(vl_config_str)
                voice_info = vl_config.get("session", {}).get("voice", {})
                voice_name = voice_info.get("name")
                if voice_name:
                    logging.info(f"[VoiceLive] Dynamically resolved voice name from portal: '{voice_name}'")
                    return voice_name
    except Exception as ex:
        logging.warning(f"[VoiceLive] Could not resolve voice from portal metadata: {ex}")
    return "en-US-Ava:DragonHDLatestNeural"  # Fallback


# ─── Voice Live Filler Audio ──────────────────────────────────────────────
# Pre-render filler clips at startup so the caller isn't left in silence
# while the agent is processing. Uses the same Azure voice as Voice Live.
FILLER_TREE_CLIPS = []
FILLER_THINKING_CLIPS = []
try:
    from services.voice_fillers import render_filler_clips
    from services.voice_realtime import get_azure_credential
    _vl_endpoint = os.getenv("AZURE_VOICELIVE_ENDPOINT", "").strip()
    _project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not _vl_endpoint:
        if _project_endpoint:
            from urllib.parse import urlparse
            _parsed = urlparse(_project_endpoint)
            _vl_endpoint = f"{_parsed.scheme}://{_parsed.netloc}"
    if _vl_endpoint:
        _cred = get_azure_credential()
        _vl_voice = resolve_agent_voice_name(_cred, _project_endpoint, os.getenv("AZURE_AGENT_VOICE_NAME", "Voice-Assistant-Agent-New").strip())
        FILLER_TREE_CLIPS, FILLER_THINKING_CLIPS = render_filler_clips(_cred, _vl_endpoint, _vl_voice)
    else:
        logging.info("[VoiceFillers] AZURE_VOICELIVE_ENDPOINT not set and cannot be derived — fillers disabled.")
except Exception as filler_err:
    logging.warning(f"[VoiceFillers] Filler initialization skipped: {filler_err}")


# ─── Request / Response models ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []
    is_voice: bool = False
    stream: bool = False


class ChatResponse(BaseModel):
    reply: str
    intent: str
    sources: list[str] = []
    suggestions: list[str] = []


class SaveResultsRequest(BaseModel):
    results: list[dict]
    stats: dict


class TranscribeResponse(BaseModel):
    transcript: str


# ─── Routes ───────────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Retail AI Assistant"}


@app.get("/customer")
async def get_customer():
    """
    Reload and return the latest customer data from the database.
    """
    try:
        return await asyncio.to_thread(load_db_customer_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/inventory")
async def get_inventory():
    """
    Reload and return the latest inventory data from the database.
    """
    try:
        from database import load_db_inventory_data
        return await asyncio.to_thread(load_db_inventory_data)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Route message to the appropriate AI Foundry agent and return response.
    Falls back to GPT-4o direct call if agent routing is unavailable.
    Pass is_voice=true for the ultra-fast voice path (no extra LLM calls).
    """
    try:
        if request.stream:
            start_time = time.time()
            stream_queue = asyncio.Queue()
            
            async def run_graph_task():
                try:
                    result = await agent_router.handle(
                        message=request.message,
                        history=request.conversation_history,
                        is_voice=request.is_voice,
                        stream_queue=stream_queue
                    )
                    await stream_queue.put({
                        "type": "done",
                        "intent": result["intent"],
                        "sources": result.get("sources", []),
                        "suggestions": result.get("suggestions", []),
                        "reply": result["reply"]
                    })
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    await stream_queue.put({"type": "error", "content": str(e)})
                finally:
                    await stream_queue.put(None)
                    
            asyncio.create_task(run_graph_task())
            
            async def sse_generator():
                while True:
                    item = await stream_queue.get()
                    if item is None:
                        logging.info(f"[Perf] Streaming chat request completed in {time.time() - start_time:.3f}s")
                        break
                    yield f"data: {json.dumps(item)}\n\n"
                    
            return StreamingResponse(sse_generator(), media_type="text/event-stream")
            
        # Non-streaming standard path
        start_time = time.time()
        result = await agent_router.handle(
            message=request.message,
            history=request.conversation_history,
            is_voice=request.is_voice,
        )
        logging.info(f"[Perf] Non-streaming chat request completed in {time.time() - start_time:.3f}s")
        return ChatResponse(
            reply=result["reply"],
            intent=result["intent"],
            sources=result.get("sources", []),
            suggestions=result.get("suggestions", []),
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chat/voice", response_model=ChatResponse)
async def chat_voice(request: ChatRequest):
    """
    Dedicated voice endpoint — always uses the ultra-fast path.
    Skips all LLM classification calls; goes straight to keyword routing + specialist agent.
    Target latency: <3s end-to-end.
    """
    try:
        result = await agent_router.handle(
            message=request.message,
            history=request.conversation_history,
            is_voice=True,
        )
        return ChatResponse(
            reply=result["reply"],
            intent=result["intent"],
            sources=result.get("sources", []),
            suggestions=result.get("suggestions", []),
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/save_results")
async def save_results(request: SaveResultsRequest):
    """
    Save test runner results to a file for analysis.
    """
    try:
        if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            results_file = Path("/tmp") / "test_results.json"
        else:
            results_file = Path(__file__).parent.parent / "mock_data" / "test_results.json"
            
        with open(results_file, "w", encoding="utf-8") as f:
            json.dump({
                "stats": request.stats,
                "results": request.results
            }, f, indent=2)
        return {"status": "success"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/token")
async def get_token():
    """
    Generate an ACS token for WebRTC call connection and return bot identity.
    """
    try:
        return acs_bot_manager.get_token_for_user()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/call-status")
async def get_call_status(server_call_id: str):
    """
    Retrieve current transcript and status of the call.
    """
    try:
        status_data = acs_bot_manager.active_calls.get(server_call_id)
        if not status_data:
            raise HTTPException(status_code=404, detail="Call session not found")
        return status_data
    except HTTPException as hexc:
        raise hexc
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/incoming-call")
async def incoming_call(request: Request):
    """
    Handle incoming call event from ACS Web SDK.
    """
    try:
        body = await request.json()
        events = body if isinstance(body, list) else [body]
        for event in events:
            if not isinstance(event, dict):
                continue
            
            # Handle EventGrid validation (might be in event['data'] or flat)
            validation_code = event.get("validationCode")
            if not validation_code:
                data = event.get("data", {})
                if isinstance(data, dict):
                    validation_code = data.get("validationCode")
                    
            if validation_code:
                return {"validationResponse": validation_code}
                
            # Handle incoming call context (might be in event['data'] or flat)
            incoming_call_context = event.get("incomingCallContext")
            if not incoming_call_context:
                data = event.get("data", {})
                if isinstance(data, dict):
                    incoming_call_context = data.get("incomingCallContext")
                    
            if incoming_call_context:
                await acs_bot_manager.answer_incoming_call(incoming_call_context)
                return {"status": "answering"}
                
        return {"status": "ignored"}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/api/callback")
async def call_callback(request: Request):
    """
    Callback webhook for Call Automation events.
    """
    try:
        body = await request.json()
        events = body if isinstance(body, list) else [body]
        await acs_bot_manager.handle_callback_events(events, agent_router)
        return {"status": "ok"}
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/fillers")
async def get_fillers():
    """Serve pre-rendered filler audio clips for the browser voice client.
    The browser plays these while waiting for the agent's response."""
    return {"trees": FILLER_TREE_CLIPS, "thinking": FILLER_THINKING_CLIPS}


@app.websocket("/api/voice-realtime")
async def voice_realtime(websocket: WebSocket):
    """Browser-based real-time voice relay.
    
    Architecture (matching the reference implementation):
    Browser <--(plain WebSocket, JSON messages)--> FastAPI <--(authenticated VoiceLive SDK)--> Voice Live (Agent mode)
    
    The backend holds the authenticated Voice Live connection and relays
    audio/events in both directions. In agent mode, the Foundry agent owns
    the instructions, model, and knowledge base — we only configure the
    speech-layer options (voice, audio formats, turn detection, transcription).
    """
    await websocket.accept()
    logging.info("[VoiceLive] Client connected for browser-based real-time voice-to-voice.")
    
    try:
        from services.voice_realtime import (
            get_azure_credential,
            execute_voice_tool,
            strip_markdown,
            REALTIME_TOOLS
        )
        
        credential = get_azure_credential()
        voicelive_endpoint = os.getenv("AZURE_VOICELIVE_ENDPOINT", "").strip()
        if not voicelive_endpoint:
            # Derive from project endpoint if AZURE_VOICELIVE_ENDPOINT not set
            project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
            if project_endpoint:
                from urllib.parse import urlparse
                parsed = urlparse(project_endpoint)
                voicelive_endpoint = f"{parsed.scheme}://{parsed.netloc}"
            else:
                voicelive_endpoint = "https://retail-ai-foundry-new.services.ai.azure.com"
        
        project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
        if not project_endpoint:
            project_endpoint = "https://retail-ai-foundry-new.services.ai.azure.com/api/projects/retail-ai-foundry"
        project_name = os.getenv("AZURE_FOUNDRY_PROJECT_NAME", "").strip() or project_endpoint.rstrip("/").split("/")[-1]
        agent_name = os.getenv("AZURE_AGENT_VOICE_NAME", "Voice-Assistant-Agent-New").strip()
        agent_version = os.getenv("AZURE_AGENT_VERSION", "").strip() or None
        
        logging.info("=== VOICE LIVE DIAGNOSTICS (Realtime) ===")
        logging.info(f"  VoiceLive Endpoint: {voicelive_endpoint}")
        logging.info(f"  Agent Name: {agent_name}")
        logging.info(f"  Agent Version: {agent_version}")
        logging.info(f"  Project Name: {project_name}")
        logging.info("=========================================")
        
    except Exception as auth_err:
        logging.error(f"[VoiceLive] Realtime auth/initialization failed: {auth_err}")
        await websocket.close()
        return

    try:
        # Agent mode: pass the Foundry agent's name + project.
        # Voice Live drives the conversation through that agent, so spoken
        # replies are grounded in its knowledge base. Omit `model` and
        # `api_version` — let the SDK negotiate the correct version.
        connect_kwargs = dict(
            endpoint=voicelive_endpoint,
            credential=credential,
            agent_name=agent_name,
            project_name=project_name,
        )
        if agent_version:
            connect_kwargs["agent_version"] = agent_version

        async with connect(**connect_kwargs) as vl_connection:
            logging.info("[VoiceLive] Successfully established connection to upstream Voice Live API.")

            # Configure the Voice Live session. In agent mode the agent owns
            # the instructions/model/knowledge base, so we only set the
            # speech-layer options and deliberately do NOT send `instructions`,
            # `tools`, or `tool_choice` here.
            session_config = RequestSession(
                modalities=[Modality.TEXT, Modality.AUDIO],
                input_audio_format=InputAudioFormat.PCM16,
                output_audio_format=OutputAudioFormat.PCM16,
                turn_detection=ServerVad(threshold=0.5, prefix_padding_ms=300, silence_duration_ms=500),
                input_audio_transcription={"model": "azure-speech"},
                voice=AzureStandardVoice(name=_vl_voice),
            )
            await vl_connection.session.update(session=session_config)
            logging.info("[VoiceLive] Session configured (agent mode — no instructions/tools sent).")

            async def browser_to_voicelive():
                """Read raw PCM16 audio bytes from browser, forward to Voice Live."""
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        audio_b64 = base64.b64encode(data).decode("utf-8")
                        await vl_connection.input_audio_buffer.append(audio=audio_b64)
                except WebSocketDisconnect:
                    logging.info("[VoiceLive] Browser disconnected (audio in).")
                except Exception as e:
                    logging.error(f"[VoiceLive] browser_to_voicelive error: {repr(e)}")

            async def voicelive_to_browser():
                """Read events from Voice Live, forward relevant audio/text to browser as JSON."""
                try:
                    async for event in vl_connection:
                        logging.debug(f"[VoiceLive] Event: {event.type}")
                        
                        if event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
                            delta = event.delta
                            if isinstance(delta, (bytes, bytearray)):
                                delta = base64.b64encode(delta).decode("utf-8")
                            await websocket.send_text(json.dumps({
                                "type": "audio_delta",
                                "delta": delta,
                            }))
                            
                        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                            logging.info("[VoiceLive] User speech started.")
                            await websocket.send_text(json.dumps({"type": "speech_started"}))
                            
                        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STOPPED:
                            logging.info("[VoiceLive] User speech stopped.")
                            await websocket.send_text(json.dumps({"type": "speech_stopped"}))
                            
                        elif event.type == ServerEventType.RESPONSE_AUDIO_DONE:
                            logging.info("[VoiceLive] Agent audio response complete.")
                            await websocket.send_text(json.dumps({"type": "audio_done"}))
                            
                        elif event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_DELTA:
                            # Partial user speech-to-text, streamed live as they speak.
                            await websocket.send_text(json.dumps({
                                "type": "user_transcript_delta",
                                "delta": strip_markdown(getattr(event, "delta", "") or ""),
                            }))
                            
                        elif event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                            # Final user transcript (replaces the streamed partials).
                            transcript = strip_markdown(getattr(event, "transcript", "") or "").strip()
                            if transcript:
                                logging.info(f"[VoiceLive] User Transcript: '{transcript}'")
                                await websocket.send_text(json.dumps({
                                    "type": "user_transcript",
                                    "text": transcript,
                                }))
                                
                        elif event.type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                            transcript = strip_markdown(getattr(event, "transcript", "") or "").strip()
                            if transcript:
                                logging.info(f"[VoiceLive] Agent Transcript: '{transcript}'")
                                await websocket.send_text(json.dumps({
                                    "type": "agent_transcript",
                                    "text": transcript,
                                }))
                                
                        elif event.type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
                            call_id = getattr(event, "call_id", None)
                            tool_name = getattr(event, "name", None)
                            args_str = getattr(event, "arguments", "{}")
                            logging.info(f"[VoiceLive] Tool call: {tool_name} args={args_str}")
                            try:
                                args = json.loads(args_str)
                            except Exception:
                                args = {}
                                
                            output = await execute_voice_tool(tool_name, args, agent_router)
                            logging.info(f"[VoiceLive] Tool {tool_name} result: {len(output)} chars.")
                            
                            await vl_connection.conversation_item.create(
                                item={
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": output
                                }
                            )
                            await vl_connection.response.create()
                            
                        elif event.type == ServerEventType.ERROR:
                            err_msg = getattr(getattr(event, "error", None), "message", str(event))
                            logging.error(f"[VoiceLive] Error: {err_msg}")
                            await websocket.send_text(json.dumps({"type": "error", "message": err_msg}))
                            
                except Exception as e:
                    logging.error(f"[VoiceLive] voicelive_to_browser error: {repr(e)}")

            await asyncio.gather(browser_to_voicelive(), voicelive_to_browser())

    except WebSocketDisconnect:
        logging.info("[VoiceLive] Browser disconnected.")
    except Exception as conn_err:
        logging.error(f"[VoiceLive] Connection error: {conn_err}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(conn_err)}))
        except Exception:
            pass
    finally:
        logging.info("[VoiceLive] Browser voice-to-voice session closed.")


@app.websocket("/api/media-stream")
async def media_stream(websocket: WebSocket):
    """ACS Media Stream relay — same agent-mode architecture as /api/voice-realtime
    but adapted for the ACS WebSocket protocol (JSON AudioData messages)."""
    await websocket.accept()
    logging.info("[VoiceLive-ACS] ACS Media Stream connection accepted.")
    
    try:
        from services.voice_realtime import (
            get_azure_credential,
            execute_voice_tool,
            strip_markdown,
            REALTIME_TOOLS
        )
        credential = get_azure_credential()
        voicelive_endpoint = os.getenv("AZURE_VOICELIVE_ENDPOINT", "").strip()
        if not voicelive_endpoint:
            project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
            if project_endpoint:
                from urllib.parse import urlparse
                parsed = urlparse(project_endpoint)
                voicelive_endpoint = f"{parsed.scheme}://{parsed.netloc}"
            else:
                voicelive_endpoint = "https://retail-ai-foundry-new.services.ai.azure.com"
        
        project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
        if not project_endpoint:
            project_endpoint = "https://retail-ai-foundry-new.services.ai.azure.com/api/projects/retail-ai-foundry"
        project_name = os.getenv("AZURE_FOUNDRY_PROJECT_NAME", "").strip() or project_endpoint.rstrip("/").split("/")[-1]
        agent_name = os.getenv("AZURE_AGENT_VOICE_NAME", "Voice-Assistant-Agent-New").strip()
        agent_version = os.getenv("AZURE_AGENT_VERSION", "").strip() or None
        
        logging.info("=== VOICE LIVE DIAGNOSTICS (ACS) ===")
        logging.info(f"  VoiceLive Endpoint: {voicelive_endpoint}")
        logging.info(f"  Agent Name: {agent_name}")
        logging.info(f"  Agent Version: {agent_version}")
        logging.info(f"  Project Name: {project_name}")
        logging.info("====================================")
        
    except Exception as e:
        logging.error(f"[VoiceLive-ACS] Failed to resolve Voice Live setup: {e}")
        await websocket.close()
        return

    try:
        # Agent mode: omit model/api_version, let SDK negotiate.
        connect_kwargs = dict(
            endpoint=voicelive_endpoint,
            credential=credential,
            agent_name=agent_name,
            project_name=project_name,
        )
        if agent_version:
            connect_kwargs["agent_version"] = agent_version

        async with connect(**connect_kwargs) as vl_connection:
            logging.info("[VoiceLive-ACS] Successfully connected to upstream Voice Live API.")
            
            # Agent mode session config — no instructions/tools.
            session_config = RequestSession(
                modalities=[Modality.TEXT, Modality.AUDIO],
                input_audio_format=InputAudioFormat.PCM16,
                output_audio_format=OutputAudioFormat.PCM16,
                turn_detection=ServerVad(threshold=0.5, prefix_padding_ms=300, silence_duration_ms=500),
                input_audio_transcription={"model": "azure-speech"},
                voice=AzureStandardVoice(name=_vl_voice),
            )
            await vl_connection.session.update(session=session_config)
            logging.info("[VoiceLive-ACS] Session configured (agent mode).")
            
            # Trigger initial greeting
            await vl_connection.conversation_item.create(
                item={
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Greet the customer by saying: Hello, I am your Sainsbury's virtual assistant. How can I help you today?"
                        }
                    ]
                }
            )
            await vl_connection.response.create()
            logging.info("[VoiceLive-ACS] Triggered initial greeting.")

            call_connection_id = None

            async def forward_acs_to_voicelive():
                nonlocal call_connection_id
                try:
                    async for message in websocket.iter_text():
                        payload = json.loads(message)
                        kind = payload.get("kind")
                        
                        if kind == "AudioMetadata":
                            meta = payload.get("audioMetadata", {})
                            call_connection_id = meta.get("connectionId")
                            logging.info(f"[VoiceLive-ACS] ACS Metadata. ConnectionId: {call_connection_id}")
                            
                        elif kind == "AudioData":
                            audio_data = payload.get("audioData", {})
                            b64_audio = audio_data.get("data")
                            if b64_audio:
                                await vl_connection.input_audio_buffer.append(audio=b64_audio)
                except WebSocketDisconnect:
                    logging.info("[VoiceLive-ACS] ACS WebSocket disconnected.")
                except Exception as ex:
                    logging.error(f"[VoiceLive-ACS] Error forwarding ACS audio: {ex}")

            async def forward_voicelive_to_acs():
                nonlocal call_connection_id
                try:
                    async for event in vl_connection:
                        if event.type == ServerEventType.RESPONSE_AUDIO_DELTA:
                            delta = event.delta
                            if not isinstance(delta, str):
                                delta = base64.b64encode(delta).decode("utf-8")
                            await websocket.send_text(json.dumps({
                                "kind": "AudioData",
                                "audioData": {"data": delta}
                            }))
                                
                        elif event.type == ServerEventType.INPUT_AUDIO_BUFFER_SPEECH_STARTED:
                            logging.info("[VoiceLive-ACS] Barge-in detected.")
                            
                        elif event.type == ServerEventType.CONVERSATION_ITEM_INPUT_AUDIO_TRANSCRIPTION_COMPLETED:
                            transcript = strip_markdown(getattr(event, "transcript", "") or "").strip()
                            if transcript:
                                logging.info(f"[VoiceLive-ACS] Caller: '{transcript}'")
                                for scid in acs_bot_manager.active_calls.keys():
                                    acs_bot_manager.active_calls[scid]["user_transcript"] = transcript
                                    acs_bot_manager.active_calls[scid]["status"] = "PROCESSING"
                                    if "history" not in acs_bot_manager.active_calls[scid]:
                                        acs_bot_manager.active_calls[scid]["history"] = []
                                    acs_bot_manager.active_calls[scid]["history"].append({"role": "user", "content": transcript})
                                    
                        elif event.type == ServerEventType.RESPONSE_AUDIO_TRANSCRIPT_DONE:
                            transcript = strip_markdown(getattr(event, "transcript", "") or "").strip()
                            if transcript:
                                logging.info(f"[VoiceLive-ACS] Agent: '{transcript}'")
                                for scid in acs_bot_manager.active_calls.keys():
                                    acs_bot_manager.active_calls[scid]["ai_response"] = transcript
                                    acs_bot_manager.active_calls[scid]["status"] = "LISTENING"
                                    if "history" not in acs_bot_manager.active_calls[scid]:
                                        acs_bot_manager.active_calls[scid]["history"] = []
                                    acs_bot_manager.active_calls[scid]["history"].append({"role": "assistant", "content": transcript})
                                    
                        elif event.type == ServerEventType.RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
                            call_id = getattr(event, "call_id", None)
                            tool_name = getattr(event, "name", None)
                            args_str = getattr(event, "arguments", "{}")
                            logging.info(f"[VoiceLive-ACS] Tool call: {tool_name}")
                            try:
                                args = json.loads(args_str)
                            except Exception:
                                args = {}
                                
                            output = await execute_voice_tool(tool_name, args, agent_router)
                            await vl_connection.conversation_item.create(
                                item={
                                    "type": "function_call_output",
                                    "call_id": call_id,
                                    "output": output
                                }
                            )
                            await vl_connection.response.create()
                            
                        elif event.type == ServerEventType.ERROR:
                            err_msg = getattr(getattr(event, "error", None), "message", str(event))
                            logging.error(f"[VoiceLive-ACS] Error: {err_msg}")
                except Exception as ex:
                    logging.error(f"[VoiceLive-ACS] voicelive_to_acs error: {repr(ex)}")
 
            await asyncio.gather(
                forward_acs_to_voicelive(),
                forward_voicelive_to_acs()
            )
    except Exception as ex:
        logging.error(f"[VoiceLive-ACS] Connection failure: {ex}")
        await websocket.close()
    finally:
        logging.info("[VoiceLive-ACS] ACS Media Stream session closed.")
