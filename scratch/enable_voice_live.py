import os
import sys
from dotenv import load_dotenv
from azure.identity import AzureCliCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import AgentDefinition

load_dotenv()

def main():
    project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    tenant_id        = os.getenv("AZURE_TENANT_ID", "").strip() or None

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
        
        agent_id = "Voice-Assistant-Agent"
        print(f"\nFetching agent '{agent_id}' details...")
        agent = project_client.agents.get(agent_name=agent_id)
        latest_version = agent.versions.latest
        
        print(f"Latest version details: {latest_version}")
        
        # Reuse and modify the existing definition object
        raw_def = latest_version.definition
        
        # Update the model to gpt-4o for voice performance
        raw_def.model = "gpt-4o"
        
        print("\nCreating new agent version with Voice Live enabled...")
        
        new_version = project_client.agents.create_version(
            agent_name=agent_id,
            definition=raw_def,
            metadata={
                "microsoft.voice-live.enabled": "true"
            }
        )
        
        print("\nSUCCESS! New agent version created with Voice Live enabled.")
        print(f"New Version: {new_version.version}")
        print(f"New Metadata: {new_version.metadata}")
        
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
