import os
from dotenv import load_dotenv
from azure.identity import AzureCliCredential, DefaultAzureCredential
from azure.ai.projects import AIProjectClient

load_dotenv()

project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None

print(f"Endpoint: {project_endpoint}")
print(f"Tenant ID: {tenant_id}")

try:
    print("Initializing AIProjectClient with AzureCliCredential...")
    credential = AzureCliCredential(tenant_id=tenant_id)
    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential
    )
    
    print("Listing agents...")
    agents = list(client.agents.list())
    print(f"Success! Found {len(agents)} agents:")
    for a in agents:
        print(f" - {a.name} (ID: {a.id})")
except Exception as e:
    print(f"Error with AzureCliCredential: {e}")

try:
    print("\nInitializing AIProjectClient with DefaultAzureCredential...")
    credential = DefaultAzureCredential(tenant_id=tenant_id)
    client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential
    )
    
    print("Listing agents...")
    agents = list(client.agents.list())
    print(f"Success! Found {len(agents)} agents:")
    for a in agents:
        print(f" - {a.name} (ID: {a.id})")
except Exception as e:
    print(f"Error with DefaultAzureCredential: {e}")
