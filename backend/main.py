"""
Retail AI Assistant – FastAPI Backend
Azure AI Foundry + GPT-4o + Azure Communication Services Speech
"""

import json
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agents import AgentRouter
from voice import transcribe_audio

load_dotenv()

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

with open(MOCK_DIR / "customer.json", encoding="utf-8") as f:
    CUSTOMER_DATA = json.load(f)

with open(MOCK_DIR / "inventory.json", encoding="utf-8") as f:
    INVENTORY_DATA = json.load(f)

# ─── Agent router (singleton) ─────────────────────────────────────────────

agent_router = AgentRouter(
    customer_data=CUSTOMER_DATA,
)

# ─── Request / Response models ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []


class ChatResponse(BaseModel):
    reply: str
    intent: str
    sources: list[str] = []


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
    Reload and return the latest customer data from customer.json.
    """
    try:
        with open(MOCK_DIR / "customer.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/inventory")
async def get_inventory():
    """
    Reload and return the latest inventory data from inventory.json.
    """
    try:
        with open(MOCK_DIR / "inventory.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Route message to the appropriate AI Foundry agent and return response.
    Falls back to GPT-4o direct call if agent routing is unavailable.
    """
    try:
        result = await agent_router.handle(
            message=request.message,
            history=request.conversation_history,
        )
        return ChatResponse(
            reply=result["reply"],
            intent=result["intent"],
            sources=result.get("sources", []),
        )
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
