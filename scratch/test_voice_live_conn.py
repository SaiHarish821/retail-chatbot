import os
import sys
import asyncio
import json
import websockets
from dotenv import load_dotenv

# Include backend directory in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from services.voice_realtime import get_azure_entra_token, get_azure_voice_live_url, REALTIME_TOOLS

load_dotenv()

async def test_conn():
    print("=== TESTING PRODUCTION AZURE VOICE LIVE CONFIGURATION ===")
    
    try:
        print("Retrieving Entra ID Token...")
        token = get_azure_entra_token()
        print(f"Token retrieved successfully (length: {len(token)} chars).")
        
        print("Generating Voice Live URL...")
        url = get_azure_voice_live_url()
        print(f"URL: {url}")
        
        print("Connecting to WebSocket...")
        async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"}, open_timeout=5, ping_interval=None) as ws:
            print("SUCCESS! Connected to Voice Live.")
            
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["audio", "text"],
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "tools": REALTIME_TOOLS,
                    "tool_choice": "auto"
                }
            }
            print("Sending session update configuration...")
            await ws.send(json.dumps(session_update))
            
            print("Waiting for response...")
            raw_msg = await ws.recv()
            event = json.loads(raw_msg)
            print(f"Received event type: {event.get('type')}")
            print(f"Content: {event}")
            
    except Exception as e:
        print(f"\nCONNECTION FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_conn())
