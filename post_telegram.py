import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID

API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"


def send_post(photo_path: str, caption: str) -> dict:
    """Send a photo with caption to the Telegram channel.

    Args:
        photo_path: Path to the image file.
        caption: HTML-formatted text for the post.

    Returns:
        Telegram API response dict.
    """
    with open(photo_path, "rb") as photo_file:
        response = requests.post(
            API_URL,
            data={
                "chat_id": TELEGRAM_CHANNEL_ID,
                "caption": caption,
                "parse_mode": "HTML",
            },
            files={
                "photo": photo_file,
            },
            timeout=30,
        )

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result
