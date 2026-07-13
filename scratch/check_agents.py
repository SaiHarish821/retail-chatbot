import os
import sys
from dotenv import load_dotenv
from azure.identity import AzureCliCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

def main():
    project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    tenant_id        = os.getenv("AZURE_TENANT_ID", "").strip() or None

    print(f"Project Endpoint: {project_endpoint}")
    print(f"Tenant ID: {tenant_id}")

    if not project_endpoint:
        print("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not configured in .env")
        return

    try:
        credential = AzureCliCredential(tenant_id=tenant_id)
        project_client = AIProjectClient(
            endpoint=project_endpoint,
            credential=credential,
        )
        print("Successfully created AIProjectClient.")
        
        print("\nListing agents:")
        agents = project_client.agents.list()
        for agent in agents:
            if agent.name == "Voice-Assistant-Agent":
                print("Voice-Assistant-Agent details:")
                print(agent)
            
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
