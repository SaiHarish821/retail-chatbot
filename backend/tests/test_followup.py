import sys
import os
import asyncio
from dotenv import load_dotenv

# Ensure backend directory is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))

from database import init_db, seed_db, load_db_customer_data
from agents import AgentRouter

load_dotenv()

async def run_tests():
    print("--- Initialising Database and Router ---")
    init_db()
    seed_db()
    customer_data = load_db_customer_data()
    router = AgentRouter(customer_data)

    print("\n--- Running Test Scenario 1: Ambiguous Confirmation on Multiple Options ---")
    history_1 = [
        {"role": "user", "content": "I want to place an order."},
        {"role": "assistant", "content": "Would you like delivery or Click & Collect?"}
    ]
    res_1 = await router.handle("Yes", history_1)
    print(f"Reply: {res_1['reply']}")
    print(f"Intent: {res_1['intent']}")
    print(f"Sources: {res_1['sources']}")
    
    # Assertions
    assert "context_resolver_clarification" in res_1["sources"], "Expected context_resolver_clarification in sources"
    assert "delivery" in res_1["reply"].lower() and "click" in res_1["reply"].lower(), "Expected clarification to mention options"
    print("Scenario 1 PASSED!")

    print("\n--- Running Test Scenario 2: Ambiguous Confirmation on Directions/Online ---")
    history_2 = [
        {"role": "user", "content": "Show me tea options."},
        {"role": "assistant", "content": "Here are the tea options: Sainsbury's Fairtrade Red Label Tea Bags (£2.10). Would you like directions to one of these stores or assistance with ordering online?"}
    ]
    res_2 = await router.handle("yeah", history_2)
    print(f"Reply: {res_2['reply']}")
    print(f"Intent: {res_2['intent']}")
    print(f"Sources: {res_2['sources']}")
    
    # Assertions
    assert "context_resolver_clarification" in res_2["sources"], "Expected context_resolver_clarification in sources"
    assert "directions" in res_2["reply"].lower() and "online" in res_2["reply"].lower(), "Expected clarification to mention directions/online"
    print("Scenario 2 PASSED!")

    print("\n--- Running Test Scenario 3: Intent Classification order check (Acknowledgement not General) ---")
    history_3 = [
        {"role": "user", "content": "How many stores are there?"},
        {"role": "assistant", "content": "There are 23 stores."}
    ]
    intent_3 = router._classify_intent("yes", history_3)
    print(f"Classified Intent: {intent_3}")
    assert intent_3 == "clarification_confirmation", f"Expected clarification_confirmation, got {intent_3}"
    print("Scenario 3 PASSED!")

    print("\n--- Running Test Scenario 4: Context Resolution fallback / single option resolution ---")
    history_4 = [
        {"role": "user", "content": "Is Salmon Fillets 400g in stock?"},
        {"role": "assistant", "content": "Yes, it is in stock at Camden. Would you like to check the price?"}
    ]
    resolution_4 = await router._resolve_context("sure", history_4)
    print(f"Resolution: {resolution_4}")
    assert resolution_4["type"] == "resolved_query", "Expected resolved_query type"
    assert "price" in resolution_4["query"].lower() and "salmon" in resolution_4["query"].lower(), "Expected query to contain salmon and price context"
    print("Scenario 4 PASSED!")

    print("\nAll automated verification checks PASSED successfully!")

if __name__ == "__main__":
    asyncio.run(run_tests())
