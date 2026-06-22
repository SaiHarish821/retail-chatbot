import sys
from pathlib import Path

# Add root and backend directories to python path for clean relative imports on Vercel
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))
sys.path.append(str(root_dir / "backend"))

from backend.main import app
