import os
import sys
import urllib.request
import urllib.error
from dotenv import load_dotenv
from azure.identity import AzureCliCredential, ClientSecretCredential

load_dotenv()

def get_azure_credential():
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip() or None
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip() or None
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "").strip() or None
    
    if client_id and client_secret and tenant_id:
        return ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
    else:
        return AzureCliCredential(tenant_id=tenant_id) if tenant_id else AzureCliCredential()

credential = get_azure_credential()
token = credential.get_token("https://cognitiveservices.azure.com/.default").token

# Try with cognitive services endpoint
cog_endpoint = os.getenv("COGNITIVE_SERVICES_ENDPOINT", "").strip()
print("COGNITIVE_SERVICES_ENDPOINT:", cog_endpoint)

# Parse voice name
voice_name_full = os.getenv("AZURE_VOICELIVE_VOICE", "en-US-Ava:DragonHDLatestNeural").strip()
base_voice = voice_name_full.split(":")[0]
if not base_voice.endswith("Neural"):
    tts_voice = f"{base_voice}Neural"
else:
    tts_voice = base_voice

print("Voice name full:", voice_name_full)
print("Mapped TTS Voice:", tts_voice)

def test_tts(endpoint, voice):
    ssml = (
        f"<speak version='1.0' xml:lang='en-US'>"
        f"<voice name='{voice}'>Hello, let me check that for you.</voice></speak>"
    )
    url = endpoint.rstrip("/") + "/tts/cognitiveservices/v1"
    print("Testing URL:", url)
    req = urllib.request.Request(url, data=ssml.encode("utf-8"), method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/ssml+xml")
    req.add_header("X-Microsoft-OutputFormat", "raw-24khz-16bit-mono-pcm")
    req.add_header("User-Agent", "test")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            print(f"Success! Synthesized {len(data)} bytes of PCM.")
            return True
    except urllib.error.HTTPError as he:
        print(f"HTTPError {he.code}: {he.reason}")
        print("Response:", he.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        print("Error:", e)
    return False

# Test 1: Mapped voice + Cognitive Services endpoint
print("\n--- Test 1 ---")
test_tts(cog_endpoint, tts_voice)

# Test 2: Original voice + Cognitive Services endpoint
print("\n--- Test 2 ---")
test_tts(cog_endpoint, voice_name_full)

# Test 3: Mapped voice + Project endpoint derived URL
project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", "").strip()
if project_endpoint:
    from urllib.parse import urlparse
    parsed = urlparse(project_endpoint)
    derived = f"{parsed.scheme}://{parsed.netloc}"
    print("\n--- Test 3 ---")
    test_tts(derived, voice_name_full)
