"""Central config. Reads env vars, provides sensible defaults for dev."""
import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("AGNES_DB", str(BASE_DIR / "db.sqlite"))

# API key the mobile app must send in X-API-Key header
API_KEY = os.getenv("AGNES_API_KEY", "devkey")

# Google Gemini LLM config. If no key set, the LLM layer returns
# deterministic mock responses so the system still runs end-to-end.
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
LLM_MODEL = os.getenv("AGNES_MODEL", "gemini-1.5-flash")
LLM_ENABLED = bool(GOOGLE_API_KEY)

# How aggressive to be when suggesting substitutes
# strict  -> only 1:1 canonical matches
# creative -> functional equivalents (different chemistry, same role)
DEFAULT_MODE = "strict"

# Email Settings
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "spherecastagnesai@gmail.com")
SMTP_PASS = os.getenv("SMTP_PASS", "") # Set this in .env!
