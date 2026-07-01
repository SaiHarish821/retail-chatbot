import os
import subprocess
from pathlib import Path

def main():
    env_path = Path("c:/Projects/retail-chatbot/.env")
    if not env_path.exists():
        print("No .env file found!")
        return

    # Parse .env file
    env_vars = {}
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                # Remove quotes if present
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                env_vars[key] = val

    print(f"Parsed {len(env_vars)} variables from .env")

    # Sync each variable to Vercel
    for key, val in env_vars.items():
        if not val:
            print(f"Skipping empty variable: {key}")
            continue
        print(f"Setting {key} on Vercel...")
        # Run vercel env add
        # We target all environments by default by omitting the environment argument,
        # or we can explicitly target production, preview, and development if needed.
        # But Vercel CLI allows omitting the env argument to set it for all.
        try:
            # Run command
            cmd = ["npx", "--yes", "vercel", "env", "add", key, "--value", val, "--yes", "--force"]
            # Let's hide the value from logs/stdout just in case
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            print(f"Successfully set {key}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to set {key}: {e.stderr.strip() or e.stdout.strip()}")

if __name__ == "__main__":
    main()
