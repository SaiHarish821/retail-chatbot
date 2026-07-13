import sys
import importlib.metadata

print("Python version:", sys.version)
print("\nInstalled Azure & OpenAI Packages:")
for dist in importlib.metadata.distributions():
    name = dist.metadata["Name"]
    if "azure" in name.lower() or "openai" in name.lower():
        print(f"{name}: {dist.version}")
