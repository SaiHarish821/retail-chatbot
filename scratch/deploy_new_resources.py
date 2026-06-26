import os
import sys
import json
import subprocess
import ast
import tempfile
from pathlib import Path
from dotenv import load_dotenv

# Ensure we're in the right directory
WORKSPACE_DIR = Path("c:/Projects/retail-chatbot")
os.chdir(WORKSPACE_DIR)

# Load existing environment variables
load_dotenv(WORKSPACE_DIR / ".env")

RESOURCE_GROUP = "Harish"
LOCATION_EASTUS = "eastus"
LOCATION_EASTUS2 = "eastus2"

SPEECH_NAME = "retail-chatbot-speech-new"
ACS_NAME = "acs-retail-chatbot-new"
OPENAI_NAME = "retail-ai-poc-services"
HUB_NAME = "retail-ai-poc-new"
PROJECT_NAME = "retail-ai-poc"
DEPLOYMENT_NAME = "gpt-4o"

def run_command(cmd, shell=True, check=True):
    print(f"\nRunning command: {cmd}")
    res = subprocess.run(cmd, shell=shell, capture_output=True, text=True)
    if check and res.returncode != 0:
        print(f"ERROR: Command failed with code {res.returncode}")
        print(f"Stdout:\n{res.stdout}")
        print(f"Stderr:\n{res.stderr}")
        raise RuntimeError(f"Command failed: {cmd}")
    return res.stdout.strip()

def main():
    print("====================================================")
    # Step 1: Verify Subscription & Tenant
    print("Step 1: Verifying active subscription...")
    sub_info_str = run_command("az account show")
    sub_info = json.loads(sub_info_str)
    sub_id = sub_info["id"]
    tenant_id = sub_info["tenantId"]
    print(f"Active Subscription ID: {sub_id}")
    print(f"Active Tenant ID: {tenant_id}")

    # Register providers just in case
    print("Registering required resource providers...")
    run_command("az provider register --namespace Microsoft.CognitiveServices --wait")
    run_command("az provider register --namespace Microsoft.MachineLearningServices --wait")
    run_command("az provider register --namespace Microsoft.Communication --wait")

    # Step 2: Create Speech Resource
    print("\n====================================================")
    print("Step 2: Provisioning Speech Service...")
    run_command(
        f"az cognitiveservices account create --name {SPEECH_NAME} --resource-group {RESOURCE_GROUP} "
        f"--kind SpeechServices --sku S0 --location {LOCATION_EASTUS} --yes"
    )
    speech_key = run_command(
        f"az cognitiveservices account keys list --name {SPEECH_NAME} --resource-group {RESOURCE_GROUP} --query key1 -o tsv"
    )
    speech_endpoint = run_command(
        f"az cognitiveservices account show --name {SPEECH_NAME} --resource-group {RESOURCE_GROUP} --query properties.endpoint -o tsv"
    )
    print(f"Speech Key: {speech_key[:5]}...")
    print(f"Speech Endpoint: {speech_endpoint}")

    # Step 3: Create Azure Communication Services (ACS)
    print("\n====================================================")
    print("Step 3: Provisioning Azure Communication Services...")
    run_command(
        f"az communication create --name {ACS_NAME} --resource-group {RESOURCE_GROUP} "
        f"--data-location UnitedStates --location Global"
    )
    acs_conn = run_command(
        f"az communication list-key --name {ACS_NAME} --resource-group {RESOURCE_GROUP} --query primaryConnectionString -o tsv"
    )
    print(f"ACS Connection String: {acs_conn[:20]}...")

    # Step 4: Create Azure AI Services Resource
    print("\n====================================================")
    print("Step 4: Provisioning Azure AI Services resource with custom domain...")
    ai_services_exists = False
    try:
        show_res = run_command(f"az cognitiveservices account show --name {OPENAI_NAME} --resource-group {RESOURCE_GROUP}", check=False)
        if show_res and '"name":' in show_res:
            ai_services_exists = True
            print(f"AI Services resource {OPENAI_NAME} already exists. Skipping recreation.")
    except Exception:
        pass

    if not ai_services_exists:
        try:
            print("Deleting existing AI Services resource to allow custom domain recreation...")
            run_command(f"az cognitiveservices account delete --name {OPENAI_NAME} --resource-group {RESOURCE_GROUP}")
            print("Purging deleted resource from soft-delete status...")
            run_command(f"az cognitiveservices account purge --name {OPENAI_NAME} --resource-group {RESOURCE_GROUP} --location {LOCATION_EASTUS2}")
        except Exception as e:
            print(f"Delete/purge skipped or not needed: {e}")

        run_command(
            f"az cognitiveservices account create --name {OPENAI_NAME} --resource-group {RESOURCE_GROUP} "
            f"--kind AIServices --sku S0 --location {LOCATION_EASTUS2} --custom-domain {OPENAI_NAME} --yes"
        )
    openai_key = run_command(
        f"az cognitiveservices account keys list --name {OPENAI_NAME} --resource-group {RESOURCE_GROUP} --query key1 -o tsv"
    )
    openai_endpoint = run_command(
        f"az cognitiveservices account show --name {OPENAI_NAME} --resource-group {RESOURCE_GROUP} --query properties.endpoint -o tsv"
    )
    openai_resource_id = run_command(
        f"az cognitiveservices account show --name {OPENAI_NAME} --resource-group {RESOURCE_GROUP} --query id -o tsv"
    )
    print(f"OpenAI Endpoint: {openai_endpoint}")

    # Step 5: Deploy GPT-4o Model
    print("\n====================================================")
    print("Step 5: Deploying GPT-4o model...")
    deployment_exists = False
    try:
        dep_show = run_command(f"az cognitiveservices account deployment show --name {OPENAI_NAME} --resource-group {RESOURCE_GROUP} --deployment-name {DEPLOYMENT_NAME}", check=False)
        if dep_show and '"name":' in dep_show:
            deployment_exists = True
            print(f"Deployment {DEPLOYMENT_NAME} already exists. Skipping creation.")
    except Exception:
        pass

    if not deployment_exists:
        run_command(
            f"az cognitiveservices account deployment create --name {OPENAI_NAME} --resource-group {RESOURCE_GROUP} "
            f"--deployment-name {DEPLOYMENT_NAME} --model-name {DEPLOYMENT_NAME} --model-version \"2024-11-20\" "
            f"--model-format OpenAI --sku-name \"Standard\" --sku-capacity 10"
        )
        print("GPT-4o model deployed successfully.")

    # Step 6: Create AI Foundry Hub
    print("\n====================================================")
    print("Step 6: Creating Azure AI Foundry Hub...")
    hub_exists = False
    try:
        hub_show = run_command(f"az ml workspace show --name {HUB_NAME} --resource-group {RESOURCE_GROUP}", check=False)
        if hub_show and '"name":' in hub_show:
            hub_exists = True
            print(f"Hub {HUB_NAME} already exists. Skipping creation.")
    except Exception:
        pass

    if not hub_exists:
        run_command(
            f"az ml workspace create --name {HUB_NAME} --resource-group {RESOURCE_GROUP} "
            f"--location {LOCATION_EASTUS2} --kind hub"
        )
    hub_id = run_command(
        f"az ml workspace show --name {HUB_NAME} --resource-group {RESOURCE_GROUP} --query id -o tsv"
    )
    print(f"Hub created. Hub Resource ID: {hub_id}")

    # Step 7: Create AI Foundry Project
    print("\n====================================================")
    print("Step 7: Creating Azure AI Foundry Project...")
    project_exists = False
    try:
        project_show = run_command(f"az ml workspace show --name {PROJECT_NAME} --resource-group {RESOURCE_GROUP}", check=False)
        if project_show and '"name":' in project_show:
            project_exists = True
            print(f"Project {PROJECT_NAME} already exists. Skipping creation.")
    except Exception:
        pass

    if not project_exists:
        run_command(
            f"az ml workspace create --name {PROJECT_NAME} --resource-group {RESOURCE_GROUP} "
            f"--location {LOCATION_EASTUS2} --kind project --hub-id {hub_id}"
        )
    project_show_str = run_command(
        f"az ml workspace show --name {PROJECT_NAME} --resource-group {RESOURCE_GROUP}"
    )
    project_show = json.loads(project_show_str)
    print("Project created. Show metadata properties:")
    print(json.dumps(project_show, indent=2)[:500])

    project_endpoint = run_command(
        f"az resource show --ids /subscriptions/{sub_id}/resourceGroups/{RESOURCE_GROUP}/providers/Microsoft.MachineLearningServices/workspaces/{PROJECT_NAME} --query properties.agentsEndpointUri -o tsv"
    )
    print(f"Target Project Endpoint: {project_endpoint}")

    # Step 8: Link Azure OpenAI Service connection to Project
    print("\n====================================================")
    print("Step 8: Linking Azure OpenAI Connection to AI Project...")
    connection_yaml_content = f"""
$schema: https://azuremlschemas.azureedge.net/latest/azureOpenAIConnection.schema.json
name: {OPENAI_NAME}
type: azure_open_ai
target: {openai_endpoint}
azure_endpoint: {openai_endpoint}
open_ai_resource_id: {openai_resource_id}
api_key: {openai_key}
is_shared: true
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(connection_yaml_content)
        connection_yaml_path = f.name
    
    try:
        print("Connecting to Hub...")
        run_command(
            f"az ml connection create --file {connection_yaml_path} --resource-group {RESOURCE_GROUP} --workspace-name {HUB_NAME}"
        )
        print("Azure OpenAI resource successfully connected to Hub.")
    except Exception as e:
        print(f"Hub connection failed: {e}")

    try:
        print("Connecting to Project...")
        run_command(
            f"az ml connection create --file {connection_yaml_path} --resource-group {RESOURCE_GROUP} --workspace-name {PROJECT_NAME}"
        )
        print("Azure OpenAI resource successfully connected to Project.")
    except Exception as e:
        print(f"Project connection failed: {e}")
    finally:
        if os.path.exists(connection_yaml_path):
            os.remove(connection_yaml_path)

    # Step 9: Recreate Agents from Backup
    print("\n====================================================")
    print("Step 9: Recreating Agents from backup...")
    
    backup_path = WORKSPACE_DIR / "current_agents_backup.json"
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found at {backup_path}")
    
    with open(backup_path, "r") as bf:
        agents_backup = json.load(bf)
    
    from azure.identity import AzureCliCredential
    from azure.ai.agents import AgentsClient
    from azure.ai.agents.models import FunctionToolDefinition, FunctionDefinition

    print("Initializing AgentsClient with endpoint:", project_endpoint)
    cred = AzureCliCredential(tenant_id=tenant_id)
    agents_client = AgentsClient(endpoint=project_endpoint, credential=cred)

    # Recreate each agent
    for agent_data in agents_backup:
        agent_name = agent_data["name"]
        
        print(f"Creating agent: {agent_name}...")
        
        instructions = agent_data.get("instructions", "")
        model = agent_data.get("model", "gpt-4o")
        
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
        
        created_agent = agents_client.create_agent(
            model=model,
            name=agent_name,
            instructions=instructions,
            tools=tools_list if tools_list else None
        )
        print(f"  Agent {agent_name} successfully created with ID: {created_agent.id}")

    # Step 10: Update .env File
    print("\n====================================================")
    print("Step 10: Updating .env file...")
    
    env_path = WORKSPACE_DIR / ".env"
    with open(env_path, "r") as ef:
        env_lines = ef.readlines()

    openai_endpoint_v1 = openai_endpoint.rstrip("/")
    if not openai_endpoint_v1.endswith("/openai/v1"):
        openai_endpoint_v1 = f"{openai_endpoint_v1}/openai/v1"

    updates = {
        "AZURE_AI_FOUNDRY_API_KEY": openai_key,
        "AZURE_TENANT_ID": tenant_id,
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT": project_endpoint,
        "AZURE_OPENAI_ENDPOINT": openai_endpoint_v1,
        "AZURE_SPEECH_KEY": speech_key,
        "AZURE_SPEECH_REGION": LOCATION_EASTUS,
        "ACS_CONNECTION_STRING": acs_conn,
        "COGNITIVE_SERVICES_ENDPOINT": f"https://{OPENAI_NAME}.cognitiveservices.azure.com/"
    }

    # Replace existing lines or append new ones
    updated_lines = []
    seen_keys = set()
    for line in env_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, val = stripped.split("=", 1)
            key = key.strip()
            if key in updates:
                updated_lines.append(f"{key}={updates[key]}\n")
                seen_keys.add(key)
                continue
        updated_lines.append(line)

    # Append any keys that weren't in the original .env
    for key, val in updates.items():
        if key not in seen_keys:
            updated_lines.append(f"{key}={val}\n")

    with open(env_path, "w") as ef:
        ef.writelines(updated_lines)

    print(".env file successfully updated with new resource configuration.")
    print("====================================================")
    print("MIGRATION COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    main()
