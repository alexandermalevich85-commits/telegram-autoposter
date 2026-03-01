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
IMAGE_SOURCE = _get("IMAGE_SOURCE", "generate").lower()    # generate | library

# API keys
CLAUDE_API_KEY = _get("CLAUDE_API_KEY")
GEMINI_API_KEY = _get("GEMINI_API_KEY")
OPENAI_API_KEY = _get("OPENAI_API_KEY")

# Face swap
FACE_SWAP_PROVIDER = _get("FACE_SWAP_PROVIDER", "").lower()  # replicate | gemini | openai | "" (disabled)
REPLICATE_API_KEY = _get("REPLICATE_API_KEY")

# Vertex AI (alternative to GEMINI_API_KEY)
GOOGLE_PROJECT_ID = _get("GOOGLE_PROJECT_ID")
GOOGLE_LOCATION = _get("GOOGLE_LOCATION", "us-central1")
GOOGLE_SERVICE_ACCOUNT_JSON = _get("GOOGLE_SERVICE_ACCOUNT_JSON")

# Telegram
TELEGRAM_BOT_TOKEN = _get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = _get("TELEGRAM_CHANNEL_ID")

# VKontakte
VK_ACCESS_TOKEN = _get("VK_ACCESS_TOKEN")
VK_GROUP_ID = _get("VK_GROUP_ID")

# Max messenger
MAX_BOT_TOKEN = _get("MAX_BOT_TOKEN")
MAX_CHAT_ID = _get("MAX_CHAT_ID")

# Pinterest
PINTEREST_ACCESS_TOKEN = _get("PINTEREST_ACCESS_TOKEN")
PINTEREST_BOARD_ID = _get("PINTEREST_BOARD_ID")

# Publish targets (comma-separated: telegram,vk,max,pinterest)
PUBLISH_TARGETS = _get("PUBLISH_TARGETS", "telegram").lower()

# Platform-specific footers (appended to post text at publish time)
TELEGRAM_FOOTER = _get("TELEGRAM_FOOTER")    # e.g. "👉 @my_bot"
VK_FOOTER = _get("VK_FOOTER")                # e.g. "👉 vk.com/my_group"
MAX_FOOTER = _get("MAX_FOOTER")              # e.g. "👉 Подробнее: ..."
PINTEREST_LINK = _get("PINTEREST_LINK")      # Destination URL for pin "Visit site" button

# GitHub (for syncing provider.cfg from Streamlit UI)
GITHUB_TOKEN = _get("GITHUB_TOKEN")


# ── Gemini client factory ────────────────────────────────────────────────────

_vertex_credentials_ready = False


def _setup_vertex_credentials():
    """Write service account JSON to a temp file and set GOOGLE_APPLICATION_CREDENTIALS.

    Idempotent — only runs once per process.
    """
    global _vertex_credentials_ready
    if _vertex_credentials_ready:
        return

    # If ADC is already configured (e.g., running on GCP or gcloud auth)
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        _vertex_credentials_ready = True
        return

    # Write service account JSON from env var to temp file
    if GOOGLE_SERVICE_ACCOUNT_JSON:
        import json
        import tempfile

        sa_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        fd, path = tempfile.mkstemp(suffix=".json", prefix="gcp_sa_")
        os.close(fd)
        with open(path, "w") as f:
            json.dump(sa_info, f)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path

    _vertex_credentials_ready = True


def get_gemini_client(api_key_override: str | None = None):
    """Create a google.genai.Client using Vertex AI or AI Studio credentials.

    Priority:
      1. api_key_override (explicit API key) → AI Studio
      2. GOOGLE_PROJECT_ID + service account → Vertex AI
      3. GEMINI_API_KEY → AI Studio
    """
    from google import genai

    # Explicit API key passed by caller → AI Studio
    if api_key_override:
        return genai.Client(api_key=api_key_override)

    # Vertex AI config present → Vertex AI
    if GOOGLE_PROJECT_ID:
        _setup_vertex_credentials()
        return genai.Client(
            vertexai=True,
            project=GOOGLE_PROJECT_ID,
            location=GOOGLE_LOCATION,
        )

    # Fallback → AI Studio with API key
    if GEMINI_API_KEY:
        return genai.Client(api_key=GEMINI_API_KEY)

    raise ValueError(
        "No Gemini credentials found. Set either GEMINI_API_KEY (AI Studio) "
        "or GOOGLE_PROJECT_ID + GOOGLE_SERVICE_ACCOUNT_JSON (Vertex AI)."
    )
