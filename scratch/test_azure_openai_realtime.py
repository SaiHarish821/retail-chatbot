import os
import sys
import asyncio
import json
import websockets
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from services.voice_realtime import get_azure_entra_token, REALTIME_TOOLS

load_dotenv()

async def main():
    print("=== TESTING DIRECT AZURE OPENAI REALTIME CONNECTION ===")
    
    # Host endpoint for Azure OpenAI
    host = "retail-ai-hub-01.openai.azure.com"
    deployment_name = "gpt-realtime-voice"
    
    url = f"wss://{host}/openai/v1/realtime?model={deployment_name}"
    print(f"URL: {url}")
    
    try:
        print("Retrieving Entra ID Token...")
        token = get_azure_entra_token()
        print("Token retrieved successfully.")
        
        print("Connecting to Azure OpenAI Realtime WebSocket...")
        headers = {"Authorization": f"Bearer {token}"}
        async with websockets.connect(url, additional_headers=headers, open_timeout=5, ping_interval=None) as ws:
            print("SUCCESS! Connected to Azure OpenAI Realtime.")
            
            # Send session configuration update
            session_update = {
                "type": "session.update",
                "session": {
                    "modalities": ["audio", "text"],
                    "voice": "alloy",
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
            print(f"Received initial event type: {event.get('type')}")
            print(f"Content: {event}")
            
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
