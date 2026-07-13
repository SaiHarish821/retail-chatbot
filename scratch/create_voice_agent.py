import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from azure.identity import AzureCliCredential
from azure.ai.agents import AgentsClient

WORKSPACE_DIR = Path("c:/Projects/retail-chatbot")
load_dotenv(WORKSPACE_DIR / ".env")

def main():
    project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
    deployment_name = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-5-mini").strip()
    agent_name = os.getenv("AZURE_AGENT_VOICE_NAME", "Voice-Assistant-Agent-New").strip()

    print(f"Project Endpoint: {project_endpoint}")
    print(f"Tenant ID: {tenant_id}")
    print(f"Deployment Model Name: {deployment_name}")
    print(f"Voice Agent Name: {agent_name}")

    if not project_endpoint:
        print("ERROR: AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set in .env")
        sys.exit(1)

    cred = AzureCliCredential(tenant_id=tenant_id)
    agents_client = AgentsClient(endpoint=project_endpoint, credential=cred)

    # Clean up existing one if it exists
    print("\nScanning for existing voice assistant agent to clean up...")
    try:
        existing_agents = agents_client.list_agents().data
        for agent in existing_agents:
            if agent.name == agent_name:
                print(f"  Deleting existing voice agent: {agent.name} (ID: {agent.id})")
                agents_client.delete_agent(agent.id)
    except Exception as e:
        print(f"Warning during cleanup: {e}")

    # Create the agent
    try:
        created_agent = agents_client.create_agent(
            model=deployment_name,
            name=agent_name,
            instructions=(
                "You are a friendly Sainsbury's retail customer support assistant. "
                "You only answer retail-related questions (orders, deliveries, refunds, returns, products, promotions, store info, account queries, and retail policies). "
                "Politely decline all unrelated requests (such as jokes, general knowledge, coding, math, stories, roleplay, etc.). "
                "If asked an unrelated question, respond with a short, professional message stating you are only designed for retail support and invite a retail question. "
                "Keep responses conversational, naturally paced, and under 30 words."
            ),
            metadata={
                "microsoft.voice-live.enabled": "true"
            }
        )
        print(f"\nSUCCESS! Voice-enabled agent created.")
        print(f"Agent name: {created_agent.name}")
        print(f"ID: {created_agent.id}")
        print(f"Metadata: {created_agent.metadata}")
    except Exception as create_err:
        print(f"ERROR: Failed to create voice agent: {create_err}")
        sys.exit(1)

if __name__ == "__main__":
    main()
