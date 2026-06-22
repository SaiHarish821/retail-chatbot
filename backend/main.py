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

# ─── Request / Response models ─────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    conversation_history: list[dict] = []


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
            suggestions=result.get("suggestions", []),
        )
    except Exception as exc:
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
