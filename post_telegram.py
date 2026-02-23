import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID

# Telegram limits: photo caption ≤ 1024 chars, message text ≤ 4096 chars
_CAPTION_LIMIT = 1024


def send_post(
    photo_path: str,
    caption: str,
    bot_token: str | None = None,
    channel_id: str | None = None,
) -> dict:
    """Send a photo with caption to the Telegram channel.

    If the caption exceeds Telegram's 1024-char limit, the photo is sent
    without text first, then the full text follows as a separate message.

    Args:
        photo_path: Path to the image file.
        caption: HTML-formatted text for the post.
        bot_token: Override bot token from config.
        channel_id: Override channel ID from config.

    Returns:
        Telegram API response dict (from the text message if split,
        otherwise from the photo message).
    """
    token = bot_token or TELEGRAM_BOT_TOKEN
    chat_id = channel_id or TELEGRAM_CHANNEL_ID

    if len(caption) <= _CAPTION_LIMIT:
        # Caption fits — send photo + text together
        return _send_photo(token, chat_id, photo_path, caption)

    # Caption too long — send photo first, then text as separate message
    _send_photo(token, chat_id, photo_path, caption=None)
    return _send_message(token, chat_id, caption)


def _send_photo(token: str, chat_id: str, photo_path: str, caption: str | None) -> dict:
    """Send a photo, optionally with a caption."""
    api_url = f"https://api.telegram.org/bot{token}/sendPhoto"

    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "HTML"

    with open(photo_path, "rb") as photo_file:
        response = requests.post(
            api_url,
            data=data,
            files={"photo": photo_file},
            timeout=30,
        )

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result


def _send_message(token: str, chat_id: str, text: str) -> dict:
    """Send a plain text message with HTML formatting."""
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    response = requests.post(
        api_url,
        data={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        },
        timeout=30,
    )

    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result
