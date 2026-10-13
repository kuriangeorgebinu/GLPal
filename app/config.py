"""Settings, read from .env. Keys are never printed or sent to the browser."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Which AI to use: deepseek | openai | anthropic | mock.
# "auto" picks the first provider that has a key, and falls back to mock (works with no key).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").strip().lower()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip().rstrip("/")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()

DB_PATH = Path(os.getenv("GLPAL_DB", str(ROOT / "glpal.db")))
KNOWLEDGE_DIR = ROOT / "knowledge"
STATIC_DIR = ROOT / "static"
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))


def resolved_provider() -> str:
    if LLM_PROVIDER != "auto":
        return LLM_PROVIDER
    if DEEPSEEK_API_KEY:
        return "deepseek"
    if ANTHROPIC_API_KEY:
        return "anthropic"
    if OPENAI_API_KEY:
        return "openai"
    return "mock"
