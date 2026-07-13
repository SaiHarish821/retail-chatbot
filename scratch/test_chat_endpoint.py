import json
import httpx

def test_endpoint():
    url = "http://127.0.0.1:8000/chat"
    payload = {
        "message": "Where is my order?",
        "conversation_history": [],
        "stream": True
    }
    
    print(f"Sending POST request to {url}...")
    try:
        with httpx.stream("POST", url, json=payload, timeout=20.0) as r:
            print(f"Status Code: {r.status_code}")
            if r.status_code != 200:
                print("Response text:", r.read().decode("utf-8"))
                return
            
            print("Response chunks:")
            for chunk in r.iter_lines():
                if chunk:
                    print(chunk)
    except Exception as e:
        print(f"HTTP Request failed: {e}")

if __name__ == "__main__":
    test_endpoint()
