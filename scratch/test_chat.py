import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

WORKSPACE_DIR = Path("c:/Projects/retail-chatbot")
sys.path.insert(0, str(WORKSPACE_DIR / "backend"))
load_dotenv(WORKSPACE_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

async def test():
    from agents import AgentRouter
    from database import init_db, seed_db, load_db_customer_data
    
    # Init DB
    init_db()
    seed_db()
    
    print("Initializing AgentRouter...")
    try:
        customer_data = load_db_customer_data()
        router = AgentRouter(customer_data=customer_data)
        print("AgentRouter initialized successfully.")
    except Exception as e:
        print(f"Error during initialization: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\nSending test message 'Where is my order?'...")
    try:
        res = await router.handle(message="Where is my order?", history=[])
        print("Response received successfully. Saving to file...")
        res_file = WORKSPACE_DIR / "scratch" / "test_chat_response.txt"
        with open(res_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(res, indent=2))
        print(f"Response written to: {res_file}")
    except Exception as e:
        print(f"Error during message handle: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
