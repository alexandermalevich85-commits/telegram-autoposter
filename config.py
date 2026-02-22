import os
from dotenv import load_dotenv

load_dotenv()

# Provider selection
TEXT_PROVIDER = os.getenv("TEXT_PROVIDER", "claude").lower()    # claude | gemini | openai
IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "gemini").lower()  # gemini | openai

# API keys
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")
