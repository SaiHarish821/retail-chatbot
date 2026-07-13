import time
import httpx

url = "http://127.0.0.1:8000/chat"
payload = {
    "message": "where is my order?",
    "conversation_history": []
}

print("Sending request to /chat...")
start = time.time()
try:
    response = httpx.post(url, json=payload, timeout=60.0)
    elapsed = time.time() - start
    print(f"Status Code: {response.status_code}")
    print(f"Elapsed Time: {elapsed:.3f}s")
    if response.status_code == 200:
        data = response.json()
        print(f"Reply: {data.get('reply')}")
        print(f"Intent: {data.get('intent')}")
        print(f"Sources: {data.get('sources')}")
        print(f"Suggestions: {data.get('suggestions')}")
    else:
        print(f"Error: {response.text}")
except Exception as e:
    print(f"Request failed: {e}")
