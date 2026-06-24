"""Quick traceback test - run this inside backend folder"""
import sys, os, traceback
from dotenv import load_dotenv

# Load env
load_dotenv('.env')  # in workspace root
load_dotenv('backend/.env')

sys.path.insert(0, os.path.abspath('backend'))

async def run():
    from backend.database import load_db_customer_data
    from backend.agents import AgentRouter
    
    data = load_db_customer_data()
    router = AgentRouter(customer_data=data)
    
    try:
        result = await router.handle("where is my order", [], is_voice=True)
        print("SUCCESS:", result['reply'][:200])
    except Exception as e:
        traceback.print_exc()
        print("ERROR:", e)

if __name__ == '__main__':
    import asyncio
    asyncio.run(run())
