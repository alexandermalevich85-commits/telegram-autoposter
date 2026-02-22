import os
from dotenv import load_dotenv

load_dotenv()


def _get(key: str, default: str = "") -> str:
    """Get config value: st.secrets (Streamlit Cloud) → .env (local) → default."""
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


# Provider selection
TEXT_PROVIDER = _get("TEXT_PROVIDER", "claude").lower()    # claude | gemini | openai
IMAGE_PROVIDER = _get("IMAGE_PROVIDER", "gemini").lower()  # gemini | openai

# API keys
CLAUDE_API_KEY = _get("CLAUDE_API_KEY")
GEMINI_API_KEY = _get("GEMINI_API_KEY")
OPENAI_API_KEY = _get("OPENAI_API_KEY")

# Telegram
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = _get("TELEGRAM_CHANNEL_ID")
