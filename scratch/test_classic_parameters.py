import os
import sys
import asyncio
import json
import websockets
from dotenv import load_dotenv

load_dotenv()

async def main():
    print("=== TESTING CLASSIC VOICE LIVE PARAMETERS (2026-01-01-preview) ===")
    
    endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    host = endpoint.split("://")[-1].split("/")[0]
    project_name = endpoint.split("/")[-1]
    agent_id = "Voice-Assistant-Agent"
    api_version = "2026-01-01-preview"
    
    # Get token for https://ai.azure.com/.default as required for agent service
    from azure.identity import AzureCliCredential
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
    credential = AzureCliCredential(tenant_id=tenant_id)
    token_obj = credential.get_token("https://ai.azure.com/.default")
    token = token_obj.token
    
    params_to_try = [
        {"project_id": project_name},
        {"project_name": project_name},
        {"project-name": project_name},
        {"agent-project-name": project_name},
        {"project": project_name}
    ]
    
    for params in params_to_try:
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"wss://{host}/voice-live/realtime?api-version={api_version}&agent_id={agent_id}&{param_str}"
        print(f"\n--- Testing with params: {params} ---")
        
        try:
            async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"}, open_timeout=5, ping_interval=None) as ws:
                print("Connected! Sending greeting response command...")
                session_update = {
                    "type": "session.update",
                    "session": {
                        "modalities": ["audio", "text"],
                        "voice": "alloy"
                    }
                }
                await ws.send(json.dumps(session_update))
                
                raw_msg = await ws.recv()
                event = json.loads(raw_msg)
                print(f"Response event type: {event.get('type')}")
                print(f"Content: {event}")
        except Exception as e:
            print(f"Failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())
