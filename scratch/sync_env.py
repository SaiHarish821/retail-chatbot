import os
import subprocess
import sys
import time

def sync_env():
    env_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    if not os.path.exists(env_file_path):
        print(f"Error: .env file not found at {env_file_path}")
        sys.exit(1)

    env_vars = {}
    with open(env_file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip()
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                env_vars[key] = val

    print(f"Starting sync of {len(env_vars)} variables to Vercel (with DEVNULL redirection)...")
    
    environments = ["production", "preview", "development"]
    
    for i, (key, val) in enumerate(env_vars.items(), 1):
        print(f"[{i}/{len(env_vars)}] Syncing {key}...")
        sys.stdout.flush() # Force print output immediately
        for env in environments:
            escaped_val = val.replace('"', '\\"')
            cmd = f'vercel env add "{key}" "{env}" --value "{escaped_val}" --yes --force'
            
            subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True
            )
            time.sleep(1)

    print("All environment variables synced successfully!")

if __name__ == "__main__":
    sync_env()
