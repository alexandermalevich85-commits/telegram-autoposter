import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID


def send_post(
    photo_path: str,
    caption: str,
    bot_token: str | None = None,
    channel_id: str | None = None,
) -> dict:
    """Send a photo with caption to the Telegram channel.

    Args:
        photo_path: Path to the image file.
        caption: HTML-formatted text for the post.
        bot_token: Override bot token from config.
        channel_id: Override channel ID from config.

    Returns:
        Telegram API response dict.
    """
    token = bot_token or TELEGRAM_BOT_TOKEN
    chat_id = channel_id or TELEGRAM_CHANNEL_ID
    api_url = f"https://api.telegram.org/bot{token}/sendPhoto"

    with open(photo_path, "rb") as photo_file:
        response = requests.post(
            api_url,
            data={
                "chat_id": chat_id,
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
