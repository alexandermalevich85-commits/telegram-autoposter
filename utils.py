"""Shared utility functions used across multiple modules."""

import base64
import io
import os
import re
import tempfile
import time
import logging

from PIL import Image

log = logging.getLogger("autoposter")


# ── HTML helpers ─────────────────────────────────────────────────────────────


def strip_html(text: str) -> str:
    """Convert HTML-formatted text to plain text.

    - Replaces <br> tags with newlines
    - Removes all other HTML tags
    - Decodes common HTML entities
    """
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'")
    return text.strip()


# ── Image encoding ───────────────────────────────────────────────────────────


def image_to_base64(image_path: str) -> str:
    """Read image, compress to JPEG quality 85, return base64 string."""
    img = Image.open(image_path)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def base64_to_tempfile(b64_string: str) -> str:
    """Decode base64 to a temporary JPEG file, return its path."""
    data = base64.b64decode(b64_string)
    fd, path = tempfile.mkstemp(suffix=".jpg", prefix="autoposter_")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(data)
    return path


def detect_content_type(file_path: str) -> str:
    """Detect MIME content type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")


# ── Retry helper ─────────────────────────────────────────────────────────────


def retry(fn, max_attempts: int = 3, delay: float = 2.0, backoff: float = 2.0):
    """Call fn() with exponential backoff retries.

    Args:
        fn: Callable to execute (no arguments).
        max_attempts: Maximum number of attempts.
        delay: Initial delay between retries in seconds.
        backoff: Multiplier for delay after each retry.

    Returns:
        Result of fn().

    Raises:
        Last exception if all attempts fail.
    """
    last_exc = None
    current_delay = delay
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_attempts:
                log.warning(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs...",
                    attempt, max_attempts, e, current_delay,
                )
                time.sleep(current_delay)
                current_delay *= backoff
            else:
                log.error("All %d attempts failed: %s", max_attempts, e)
    raise last_exc
