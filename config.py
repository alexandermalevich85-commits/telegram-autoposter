import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get(key: str, default: str = "") -> str:
    """Get config value from environment variables.

    On Streamlit Cloud the secrets are bridged into os.environ by app.py
    before this module is imported, so os.getenv() works everywhere:
      - Local dev: .env → load_dotenv() → os.getenv()
      - Streamlit Cloud: st.secrets → os.environ (bridged in app.py) → os.getenv()
      - GitHub Actions: env vars set directly → os.getenv()
    """
    return os.getenv(key, default)


# Provider selection
TEXT_PROVIDER = _get("TEXT_PROVIDER", "claude").lower()    # claude | gemini | openai
IMAGE_PROVIDER = _get("IMAGE_PROVIDER", "gemini").lower()  # gemini | openai

# API keys
CLAUDE_API_KEY = _get("CLAUDE_API_KEY")
GEMINI_API_KEY = _get("GEMINI_API_KEY")
OPENAI_API_KEY = _get("OPENAI_API_KEY")

# Face swap
FACE_SWAP_PROVIDER = _get("FACE_SWAP_PROVIDER", "").lower()  # replicate | gemini | openai | "" (disabled)
REPLICATE_API_KEY = _get("REPLICATE_API_KEY")

# Telegram
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = _get("TELEGRAM_CHANNEL_ID")

# GitHub (for syncing provider.cfg from Streamlit UI)
GITHUB_TOKEN = _get("GITHUB_TOKEN")
