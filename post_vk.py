"""Publish a photo + text post to a VKontakte community wall.

Supports both community (group) tokens and user tokens.

Wall upload flow (preferred):
1. photos.getWallUploadServer → upload URL
2. Upload photo → server, photo, hash
3. photos.saveWallPhoto → attachment ID
4. wall.post with attachment → post_id

Messages upload flow (fallback for community tokens):
1. photos.getMessagesUploadServer → upload URL
2. Upload photo → server, photo, hash
3. photos.saveMessagesPhoto → attachment ID (with access_key)
4. wall.post with attachment → post_id
"""

import io
import os
import logging
import tempfile
import requests

from PIL import Image as _PILImage

from config import VK_ACCESS_TOKEN, VK_GROUP_ID, VK_FOOTER
from utils import strip_html

_API_VERSION = "5.199"
_API_BASE = "https://api.vk.com/method"

log = logging.getLogger(__name__)


def _vk_post(method: str, params: dict, timeout: int = 15) -> dict:
    """Make a VK API call using POST (keeps token out of URL/logs)."""
    resp = requests.post(
        f"{_API_BASE}/{method}",
        data={**params, "v": _API_VERSION},
        timeout=timeout,
    ).json()
    if "error" in resp:
        raise RuntimeError(f"VK {method}: {resp['error']}")
    return resp


def _upload_file_to_server(upload_url: str, photo_path: str) -> dict:
    """Upload an image file to a VK upload server.

    Converts the image to JPEG via a temp file (more reliable than BytesIO
    on Streamlit Cloud).  The multipart field name ``photo`` matches the
    official VK API documentation and vk_api library.
    """
    # Convert to JPEG temp file for format consistency and reliability
    img = _PILImage.open(photo_path)
    fd, tmp_jpg = tempfile.mkstemp(suffix=".jpg", prefix="vk_upload_")
    os.close(fd)
    try:
        img.convert("RGB").save(tmp_jpg, format="JPEG", quality=95)
        jpeg_size = os.path.getsize(tmp_jpg)
        print(f"[VK] JPEG temp file: {tmp_jpg} ({jpeg_size} bytes)")

        with open(tmp_jpg, "rb") as f:
            upload_resp = requests.post(
                upload_url,
                files={"photo": ("photo.jpg", f, "image/jpeg")},
                timeout=60,
            ).json()
    finally:
        try:
            os.remove(tmp_jpg)
        except OSError:
            pass

    print(f"[VK] Upload response: {upload_resp}")

    if not upload_resp.get("photo") or upload_resp["photo"] == "[]":
        raise RuntimeError(f"VK photo upload returned empty: {upload_resp}")

    return upload_resp


def _upload_photo_wall(token: str, gid: str, photo_path: str) -> str:
    """Upload photo via Wall Upload Server (user token or community token with photos scope)."""
    print("[VK] Trying photos.getWallUploadServer...")
    resp = _vk_post("photos.getWallUploadServer", {
        "group_id": gid, "access_token": token,
    })
    upload_url = resp["response"]["upload_url"]
    print(f"[VK] Got wall upload URL (album_id={resp['response'].get('album_id')})")

    upload_resp = _upload_file_to_server(upload_url, photo_path)

    save_resp = _vk_post("photos.saveWallPhoto", {
        "group_id": gid,
        "photo": upload_resp["photo"],
        "server": upload_resp["server"],
        "hash": upload_resp["hash"],
        "access_token": token,
    })

    info = save_resp["response"][0]
    # Wall photos typically don't need access_key
    attachment = f"photo{info['owner_id']}_{info['id']}"
    if info.get("access_key"):
        attachment += f"_{info['access_key']}"
    print(f"[VK] Wall photo saved: {attachment} (owner={info['owner_id']}, id={info['id']})")
    return attachment


def _upload_photo_messages(token: str, gid: str, photo_path: str) -> str:
    """Upload photo via Messages Upload Server (community token fallback).

    Photos saved via saveMessagesPhoto belong to the bot/community messages
    album, NOT the wall album. To attach them to a wall.post, VK requires
    the ``access_key`` that is returned alongside the photo metadata.
    """
    print("[VK] Trying photos.getMessagesUploadServer...")
    resp = _vk_post("photos.getMessagesUploadServer", {
        "group_id": gid, "access_token": token,
    })
    upload_url = resp["response"]["upload_url"]
    print("[VK] Got messages upload URL")

    upload_resp = _upload_file_to_server(upload_url, photo_path)

    save_resp = _vk_post("photos.saveMessagesPhoto", {
        "photo": upload_resp["photo"],
        "server": upload_resp["server"],
        "hash": upload_resp["hash"],
        "access_token": token,
    })

    info = save_resp["response"][0]
    attachment = f"photo{info['owner_id']}_{info['id']}"
    # access_key is REQUIRED for message-album photos used in wall posts
    if info.get("access_key"):
        attachment += f"_{info['access_key']}"
        print(f"[VK] Messages photo saved: {attachment} (has access_key)")
    else:
        print(f"[VK] WARNING: Messages photo has NO access_key: {attachment}")
        log.warning("Messages photo has NO access_key — wall post may appear without image!")
    return attachment


def send_post(
    photo_path: str,
    caption: str,
    access_token: str | None = None,
    group_id: str | None = None,
    footer_text: str | None = None,
) -> dict:
    """Send a photo with text to a VK community wall.

    Args:
        photo_path: Path to the image file.
        caption: HTML-formatted text (will be stripped to plain text).
        access_token: VK access token (community or user token with wall,photos scope).
        group_id: VK community ID (without minus sign).

    Returns:
        {"ok": True, "result": {"message_id": "wall-GID_PID"}}
    """
    token = access_token or VK_ACCESS_TOKEN
    gid = group_id or VK_GROUP_ID

    if not token:
        raise RuntimeError("VK_ACCESS_TOKEN не задан")
    if not gid:
        raise RuntimeError("VK_GROUP_ID не задан")

    # Strip minus sign if provided
    gid = gid.lstrip("-")

    plain_text = strip_html(caption)

    # Append platform-specific footer (e.g., VK bot/group link)
    footer = footer_text if footer_text is not None else VK_FOOTER
    if footer:
        plain_text = plain_text + "\n\n" + footer

    print(f"[VK] Publishing to group {gid}, image: {photo_path}")
    print(f"[VK] Image exists: {os.path.exists(photo_path)}, "
          f"size: {os.path.getsize(photo_path) if os.path.exists(photo_path) else 0} bytes")

    # Strategy: try Wall upload first (works with both user tokens and
    # community tokens that have 'photos' scope), then Messages upload
    # as a fallback (community tokens with 'messages' scope).
    attachment = None
    errors = []

    for method_name, method_fn in [
        ("Wall", _upload_photo_wall),
        ("Messages", _upload_photo_messages),
    ]:
        if attachment is not None:
            break
        try:
            attachment = method_fn(token, gid, photo_path)
            print(f"[VK] ✅ Photo uploaded via {method_name} method: {attachment}")
        except Exception as e:
            errors.append(f"{method_name}: {e}")
            print(f"[VK] ❌ {method_name} upload failed: {e}")

    if attachment is None:
        raise RuntimeError(f"VK photo upload failed: {'; '.join(errors)}")

    # Create wall post
    print(f"[VK] Posting to wall with attachment: {attachment}")
    post_resp = _vk_post("wall.post", {
        "owner_id": f"-{gid}",
        "from_group": 1,
        "message": plain_text,
        "attachments": attachment,
        "access_token": token,
    })

    post_id = post_resp["response"]["post_id"]
    print(f"[VK] ✅ Post published: wall-{gid}_{post_id}")

    return {
        "ok": True,
        "result": {"message_id": f"wall-{gid}_{post_id}"},
    }
