"""
Retail AI Assistant – FastAPI Backend
Azure AI Foundry + GPT-4o + Azure Communication Services Speech
"""

import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents import AgentRouter
from services import transcribe_audio, ACSBotManager

load_dotenv()

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


# ─── Request / Response models ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []
    is_voice: bool = False


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
    Reload and return the latest customer data from the SQLite database.
    """
    try:
        return load_db_customer_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/inventory")
async def get_inventory():
    """
    Reload and return the latest inventory data from the SQLite database.
    """
    try:
        from database import load_db_inventory_data
        return load_db_inventory_data()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Route message to the appropriate AI Foundry agent and return response.
    Falls back to GPT-4o direct call if agent routing is unavailable.
    Pass is_voice=true for the ultra-fast voice path (no extra LLM calls).
    """
    try:
        result = await agent_router.handle(
            message=request.message,
            history=request.conversation_history,
            is_voice=request.is_voice,
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


@app.post("/voice/transcribe", response_model=TranscribeResponse)
async def voice_transcribe(audio: UploadFile = File(...)):
    """
    Accept audio blob from the browser and return the transcription
    using Azure Communication Services Speech-to-Text.
    """
    try:
        audio_bytes = await audio.read()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        transcript = await transcribe_audio(tmp_path)
        Path(tmp_path).unlink(missing_ok=True)
        return TranscribeResponse(transcript=transcript)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/voice/speak")
async def voice_speak(text: str):
    """
    Synthesize text to audio using Azure Cognitive Services Text-to-Speech (Sonia Neural).
    """
    try:
        from services import synthesize_speech
        from fastapi.responses import Response
        audio_data = await synthesize_speech(text)
        return Response(content=audio_data, media_type="audio/wav")
    except Exception as exc:
        import traceback
        traceback.print_exc()
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


