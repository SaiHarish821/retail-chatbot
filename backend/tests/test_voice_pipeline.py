import os
import sys
import asyncio
import time
from dotenv import load_dotenv

# Set up paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
load_dotenv()

from database import init_db, seed_db, load_db_customer_data
from agents import AgentRouter
from services.acs_bot import sanitize_text_for_tts

async def run_voice_tests():
    print("=== INITIALISING AUTOMATED VOICE TESTS ===")
    init_db()
    seed_db()
    customer_data = load_db_customer_data()
    router = AgentRouter(customer_data)
    
    print("\n--- TEST 1: Heuristic Routing / Latency Verification ---")
    # Warm up call to authenticate and populate the LLM cache
    print("Warming up AgentRouter (getting Entra tokens and caches)...")
    await router.handle("hello", [], is_voice=True)
    
    start = time.time()
    # "where is my order" should route to order agent, is_voice=True
    res = await router.handle("where is my order?", [], is_voice=True)
    latency = time.time() - start
    
    print(f"Reply: '{res['reply']}'")
    print(f"Intent/Role: {res['intent']}")
    print(f"Sources: {res['sources']}")
    print(f"Measured Latency: {latency:.2f}s")
    
    assert latency < 10.0, f"Latency too high: {latency:.2f}s (should be sub-10.0s)"
    print("TEST 1 PASSED!")

    print("\n--- TEST 2: Voice Formatting Verification (Bullets/Markdown Removal) ---")
    raw_response = "Here is your order:\n* Item 1: Milk\n* Item 2: Eggs\nLet's check CUST-00123."
    sanitized = sanitize_text_for_tts(raw_response)
    print(f"Raw: {repr(raw_response)}")
    print(f"Sanitized: {repr(sanitized)}")
    assert "*" not in sanitized, "Markdown bullets were not stripped"
    assert "CUST" not in sanitized, "Customer ID was not stripped"
    print("TEST 2 PASSED!")

    print("\n--- TEST 3: Security Guardrails - Env Variables / Connection Strings ---")
    # If the bot tries to say something containing DB details, it should be intercepted
    compromised_reply = "Your order details are at DB_HOST=retail-chatbot-db.postgres.database.azure.com."
    from agents.validation import validate_and_sanitize_response
    secure_reply = validate_and_sanitize_response("where is my order", compromised_reply)
    print(f"Compromised: {repr(compromised_reply)}")
    print(f"Secure reply: {repr(secure_reply)}")
    assert "DB_HOST" not in secure_reply, "Guardrail failed to intercept DB_HOST disclosure"
    assert "postgres" not in secure_reply, "Guardrail failed to sanitize the text completely"
    assert "cannot disclose" in secure_reply, "Did not fallback to secure message"
    print("TEST 3 PASSED!")

    print("\n--- TEST 4: Security Guardrails - Third-Party Customer Info ---")
    # Try to leak another customer's email address
    compromised_email_reply = "The email linked is alice.brown@example.com."
    secure_email_reply = validate_and_sanitize_response("what is my email", compromised_email_reply)
    print(f"Compromised: {repr(compromised_email_reply)}")
    print(f"Secure email reply: {repr(secure_email_reply)}")
    assert "alice.brown" not in secure_email_reply, "Guardrail failed to intercept third-party email leakage"
    assert "unable to disclose" in secure_email_reply, "Did not fallback to account verification message"
    print("TEST 4 PASSED!")

    print("\n=== ALL VOICE AUTOMATED TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(run_voice_tests())
