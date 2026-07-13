import os
import sys
import asyncio
import json
import urllib.parse
import websockets
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

from services.voice_realtime import get_azure_entra_token, REALTIME_TOOLS

load_dotenv()

async def main():
    print("=== TESTING CONNECTION WITH AGENT CONNECTION STRING ===")
    
    endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    host = endpoint.split("://")[-1].split("/")[0]
    
    subscription_id = "a1fb0563-d5ff-402a-a0b8-e3c871c973bf"
    resource_group = "Harish"
    project_name = "retail-ai-hub"
    agent_id = "6eda7330-7729-4bcf-aa06-e33b39299bd8"
    api_version = "2026-01-01-preview"
    
    print("Retrieving Entra ID Token (ai.azure.com)...")
    from azure.identity import AzureCliCredential
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
    credential = AzureCliCredential(tenant_id=tenant_id)
    token_obj = credential.get_token("https://ai.azure.com/.default")
    token = token_obj.token
    print("Token retrieved successfully.")
    
    # Try different connection string formats
    conn_strings = [
        f"eastus2.api.azureml.ms;{subscription_id};{resource_group};{project_name}",
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.CognitiveServices/accounts/retail-ai-hub-01/projects/{project_name}",
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/Microsoft.CognitiveServices/accounts/retail-ai-hub-01"
    ]
    
    for conn_str in conn_strings:
        encoded_conn_str = urllib.parse.quote(conn_str)
        url = f"wss://{host}/voice-live/realtime?api-version={api_version}&agent_id={agent_id}&agent-connection-string={encoded_conn_str}"
        print(f"\n--- Testing with connection string: {conn_str} ---")
        
        try:
            print("Connecting to WebSocket...")
            async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"}, open_timeout=5, ping_interval=None) as ws:
                print("Connected! Waiting for initial event from server...")
                
                print("Waiting for response...")
                raw_msg = await ws.recv()
                event = json.loads(raw_msg)
                print(f"Received event type: {event.get('type')}")
                print(f"Content: {event}")
                
        except Exception as e:
            print(f"Failed with exception type: {type(e)}")
            print(f"Failed with exception message: {e}")
            if hasattr(e, 'code'):
                print(f"Close code: {e.code}")
            if hasattr(e, 'reason'):
                print(f"Close reason: {e.reason}")

if __name__ == "__main__":
    asyncio.run(main())
