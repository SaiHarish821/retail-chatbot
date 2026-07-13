import os
import sys
from dotenv import load_dotenv
from azure.identity import AzureCliCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition

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
        
        agent_id = "Voice-Assistant-Agent-New"
        print(f"\nCreating brand new agent '{agent_id}'...")
        
        # Construct PromptAgentDefinition as a mapping
        definition = PromptAgentDefinition(
            instructions=(
                "You are a friendly Sainsbury's retail assistant. "
                "Keep responses conversational and naturally paced, under 30 words."
            )
        )
        definition["kind"] = "prompt"
        definition["model"] = "gpt-5-mini"
        
        new_version = project_client.agents.create_version(
            agent_name=agent_id,
            definition=definition,
            metadata={
                "microsoft.voice-live.enabled": "true"
            }
        )
        print("\nSUCCESS! New responses-compatible agent created.")
        print(f"Agent name: {new_version.name}")
        print(f"Version: {new_version.version}")
        print(f"ID: {new_version.id}")
        print(f"Metadata: {new_version.metadata}")
        
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
