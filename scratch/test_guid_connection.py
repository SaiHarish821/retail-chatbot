import os
import sys
import asyncio
import json
import websockets
from dotenv import load_dotenv

load_dotenv()

async def test_guid(api_version, param_name, use_guid):
    endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    host = endpoint.split("://")[-1].split("/")[0]
    project_name = endpoint.split("/")[-1]
    
    agent_id = "6eda7330-7729-4bcf-aa06-e33b39299bd8" if use_guid else "Voice-Assistant-Agent"
    
    # Get token for https://ai.azure.com/.default
    from azure.identity import AzureCliCredential
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
    credential = AzureCliCredential(tenant_id=tenant_id)
    token_obj = credential.get_token("https://ai.azure.com/.default")
    token = token_obj.token
    
    url = f"wss://{host}/voice-live/realtime?api-version={api_version}&agent_id={agent_id}&{param_name}={project_name}"
    print(f"\nTesting URL: {url}")
    
    try:
        async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"}, open_timeout=5, ping_interval=None) as ws:
            print("Connected! Sending session update...")
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

async def main():
    print("=== TESTING CONNECTION WITH AGENT GUID ===")
    
    # Test 1: api-version=2026-04-10 with GUID and project_id
    print("\n--- Test 1: 2026-04-10 with GUID and project_id ---")
    await test_guid("2026-04-10", "project_id", True)
    
    # Test 2: api-version=2026-01-01-preview with GUID and agent-project-name
    print("\n--- Test 2: 2026-01-01-preview with GUID and agent-project-name ---")
    await test_guid("2026-01-01-preview", "agent-project-name", True)

if __name__ == "__main__":
    asyncio.run(main())
