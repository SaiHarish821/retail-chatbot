import os
import asyncio
from dotenv import load_dotenv
from azure.identity import AzureCliCredential
from azure.ai.projects import AIProjectClient
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

load_dotenv()

project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
deployment = os.getenv("AZURE_AI_FOUNDRY_DEPLOYMENT_NAME", "gpt-5.1")

async def test():
    print("Initializing clients...")
    credential = AzureCliCredential(tenant_id=tenant_id)
    project_client = AIProjectClient(
        endpoint=project_endpoint,
        credential=credential
    )
    openai_client = project_client.get_openai_client()
    
    print("Testing direct completions call...")
    try:
        res = openai_client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello! Say hi."}
            ],
            max_completion_tokens=10,
            temperature=0.0,
        )
        print(f"Direct Completions Reply: {res.choices[0].message.content}")
    except Exception as e:
        print(f"Direct completions failed: {e}")

    print("\nTesting LangChain ChatOpenAI call...")
    try:
        print("Getting Entra token...")
        token = credential.get_token("https://ai.azure.com/.default").token
        print(f"Token acquired successfully (length={len(token)})")
        
        llm = ChatOpenAI(
            openai_api_base=str(openai_client.base_url),
            openai_api_key=token,
            model=deployment,
            temperature=0.0,
        )
        print("Invoking LangChain...")
        messages = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="Hello! Say hi.")
        ]
        res = await asyncio.get_event_loop().run_in_executor(
            None, lambda: llm.invoke(messages)
        )
        print(f"LangChain Reply: {res.content}")
    except Exception as e:
        print(f"LangChain call failed: {e}")

if __name__ == "__main__":
    asyncio.run(test())
