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
    print("=== TESTING AGENT VOICE LIVE CONNECTION (2026-04-10) ===")
    
    endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    agent_id = "Voice-Assistant-New"
    api_version = "2026-04-10"
    
    hosts_to_try = [
        "retail-ai-hub-01.services.ai.azure.com",
        "retail-ai-hub-01.cognitiveservices.azure.com"
    ]
    
    for host in hosts_to_try:
        url = f"wss://{host}/voice-live/realtime?api-version={api_version}&agent_id={agent_id}&project_id=retail-ai-hub"
        print(f"\n--- Testing host: {host} ---")
        
        try:
            print("Retrieving Entra ID Token...")
            try:
                token = get_azure_entra_token()
                print("Using production token scope.")
            except Exception as e:
                print(f"Fallback to ai.azure.com scope due to: {e}")
                from azure.identity import AzureCliCredential
                tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
                credential = AzureCliCredential(tenant_id=tenant_id)
                token_obj = credential.get_token("https://ai.azure.com/.default")
                token = token_obj.token
            
            print("Connecting to WebSocket...")
            async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"}, open_timeout=5, ping_interval=None) as ws:
                print("SUCCESS! Connected to Voice Live.")
                
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
                print("Sending session update...")
                await ws.send(json.dumps(session_update))
                
                print("Waiting for response...")
                raw_msg = await ws.recv()
                event = json.loads(raw_msg)
                print(f"Received event type: {event.get('type')}")
                print(f"Content: {event}")
        except Exception as e:
            print(f"Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
