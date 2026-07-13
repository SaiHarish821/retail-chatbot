import os
import sys
import asyncio
import json
import websockets
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from services.voice_realtime import get_azure_entra_token, REALTIME_TOOLS

load_dotenv()

async def test_model(model_name):
    print(f"\n=== TESTING DIRECT MODEL VOICE LIVE (model={model_name}) ===")
    
    endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    host = endpoint.split("://")[-1].split("/")[0]
    api_version = "2026-04-10"
    
    url = f"wss://{host}/voice-live/realtime?api-version={api_version}&model={model_name}"
    print(f"URL: {url}")
    
    try:
        print("Retrieving Entra ID Token...")
        token = get_azure_entra_token()
        print("Token retrieved successfully.")
        
        print("Connecting to WebSocket...")
        async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"}, open_timeout=5, ping_interval=None) as ws:
            print("SUCCESS! Connected to Voice Live.")
            
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["audio", "text"],
                    "voice": "alloy"
                }
            }
            print("Sending session update...")
            await ws.send(json.dumps(session_update))
            
            print("Waiting for response...")
            raw_msg = await ws.recv()
            event = json.loads(raw_msg)
            print(f"Received event type: {event.get('type')}")
            print(f"Content: {event}")
            
    except Exception as e:
        print(f"Failed: {e}")

async def main():
    await test_model("gpt-4o")
    await test_model("gpt-4o-mini")

if __name__ == "__main__":
    asyncio.run(main())
