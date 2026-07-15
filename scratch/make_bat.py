import os

def make_bat():
    env_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env"))
    bat_file_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "sync_env.bat"))

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

    environments = ["production", "preview", "development"]
    with open(bat_file_path, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write("echo Starting Vercel Environment Variable Sync...\n")
        for key, val in env_vars.items():
            # Escape double quotes for batch file
            escaped_val = val.replace('"', '\\"')
            for env in environments:
                f.write(f'echo Syncing {key} to {env}...\n')
                f.write(f'call vercel env add "{key}" "{env}" --value "{escaped_val}" --yes --force > NUL 2>&1\n')
                f.write('ping -n 3 127.0.0.1 > NUL\n')
        f.write("echo Environment variables sync complete!\n")

    print(f"Successfully generated batch file at {bat_file_path}")

if __name__ == "__main__":
    make_bat()
