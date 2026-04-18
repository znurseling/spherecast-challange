"""Central config. Reads env vars, provides sensible defaults for dev."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("AGNES_DB", str(BASE_DIR / "db.sqlite"))

# API key the mobile app must send in X-API-Key header
API_KEY = os.getenv("AGNES_API_KEY", "devkey")

# Anthropic LLM config. If no key set, the LLM layer returns deterministic
# mock responses so the system still runs end-to-end for the demo.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("AGNES_MODEL", "claude-haiku-4-5-20251001")
LLM_ENABLED = bool(ANTHROPIC_API_KEY)

# How aggressive to be when suggesting substitutes
# strict  -> only 1:1 canonical matches
# creative -> functional equivalents (different chemistry, same role)
DEFAULT_MODE = "strict"
