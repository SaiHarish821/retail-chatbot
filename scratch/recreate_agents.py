import os
import sys
import json
import ast
from pathlib import Path
from dotenv import load_dotenv
from azure.identity import AzureCliCredential
from azure.ai.agents import AgentsClient
from azure.ai.agents.models import FunctionToolDefinition, FunctionDefinition

# Ensure we are in the workspace directory
WORKSPACE_DIR = Path("c:/Projects/retail-chatbot")
load_dotenv(WORKSPACE_DIR / ".env")

def main():
    project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
    deployment_name = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-5-mini").strip()

    print(f"Project Endpoint: {project_endpoint}")
    print(f"Tenant ID: {tenant_id}")
    print(f"Deployment Model Name: {deployment_name}")

    if not project_endpoint:
        print("ERROR: AZURE_AI_FOUNDRY_PROJECT_ENDPOINT is not set in .env")
        sys.exit(1)

    backup_path = WORKSPACE_DIR / "current_agents_backup.json"
    if not backup_path.exists():
        print(f"ERROR: Backup file not found at {backup_path}")
        sys.exit(1)

    with open(backup_path, "r", encoding="utf-8") as bf:
        agents_backup = json.load(bf)

    cred = AzureCliCredential(tenant_id=tenant_id)
    agents_client = AgentsClient(endpoint=project_endpoint, credential=cred)

    # Step 1: Clean up existing duplicate agents in the project
    print("\nScanning for existing agents to clean up...")
    try:
        existing_agents = agents_client.list_agents().data
        backup_agent_names = {a["name"] for a in agents_backup}
        for agent in existing_agents:
            if agent.name in backup_agent_names:
                print(f"  Deleting existing duplicate agent: {agent.name} (ID: {agent.id})")
                agents_client.delete_agent(agent.id)
    except Exception as e:
        print(f"Warning during cleanup: {e}. Proceeding to creation...")

    # Step 2: Create agents from backup
    print("\nRecreating agents from backup...")
    for agent_data in agents_backup:
        agent_name = agent_data["name"]
        print(f"Creating agent: {agent_name}...")

        instructions = agent_data.get("instructions", "")
        
        # Parse tools
        tools_list = []
        for t_str in agent_data.get("tools", []):
            try:
                t_dict = ast.literal_eval(t_str)
                func_info = t_dict["function"]
                func_def = FunctionDefinition(
                    name=func_info["name"],
                    description=func_info.get("description"),
                    parameters=func_info.get("parameters")
                )
                tool_def = FunctionToolDefinition(function=func_def)
                tools_list.append(tool_def)
            except Exception as ex:
                print(f"  WARNING: Failed to parse tool {t_str}: {ex}")

        try:
            created_agent = agents_client.create_agent(
                model=deployment_name,
                name=agent_name,
                instructions=instructions,
                tools=tools_list if tools_list else None
            )
            print(f"  Successfully created agent {agent_name} with ID: {created_agent.id}")
        except Exception as create_err:
            print(f"  ERROR: Failed to create agent {agent_name}: {create_err}")
            sys.exit(1)

    print("\nAGENT RECREATION COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
