"""Image library module — manage a pre-uploaded image collection.

Images are stored as individual JSON files in the image_library/ directory.
An index file (image_library.json) tracks metadata and the circular queue pointer.
"""

import base64
import io
import json
import os

from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_FILE = os.path.join(BASE_DIR, "image_library.json")
LIBRARY_DIR = os.path.join(BASE_DIR, "image_library")


def _ensure_library_dir():
    os.makedirs(LIBRARY_DIR, exist_ok=True)


def load_index() -> dict:
    if not os.path.exists(INDEX_FILE):
        return {"images": [], "next_index": 0}
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_index(data: dict) -> None:
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_image_b64(index: int) -> str | None:
    path = os.path.join(LIBRARY_DIR, f"{index}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("base64")


def add_image(image_bytes: bytes, filename: str) -> int:
    """Add an image to the library. Returns the assigned index."""
    _ensure_library_dir()

    img = Image.open(io.BytesIO(image_bytes))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")

    index_data = load_index()
    images = index_data.get("images", [])

    new_idx = max((img["index"] for img in images), default=0) + 1

    img_path = os.path.join(LIBRARY_DIR, f"{new_idx}.json")
    with open(img_path, "w", encoding="utf-8") as f:
        json.dump({"base64": b64, "filename": filename}, f, ensure_ascii=False)

    images.append({"index": new_idx, "filename": filename})
    index_data["images"] = images
    save_index(index_data)

    return new_idx


def remove_image(idx: int) -> bool:
    """Remove an image from the library by index."""
    index_data = load_index()
    images = index_data.get("images", [])

    new_images = [img for img in images if img["index"] != idx]
    if len(new_images) == len(images):
        return False

    img_path = os.path.join(LIBRARY_DIR, f"{idx}.json")
    if os.path.exists(img_path):
        os.remove(img_path)

    index_data["images"] = new_images
    if new_images:
        if index_data["next_index"] >= len(new_images):
            index_data["next_index"] = 0
    else:
        index_data["next_index"] = 0
    save_index(index_data)
    return True


def get_next_image() -> tuple[str | None, int | None]:
    """Get the next image from the circular queue.

    Returns (base64_string, image_index) or (None, None) if empty.
    Does NOT advance the pointer — call advance_pointer() after using.
    """
    index_data = load_index()
    images = index_data.get("images", [])
    if not images:
        return None, None

    pos = index_data.get("next_index", 0)
    if pos >= len(images):
        pos = 0

    img_entry = images[pos]
    b64 = load_image_b64(img_entry["index"])
    return b64, img_entry["index"]


def advance_pointer() -> None:
    """Advance next_index by 1, wrapping around if needed."""
    index_data = load_index()
    images = index_data.get("images", [])
    if not images:
        return

    pos = index_data.get("next_index", 0) + 1
    if pos >= len(images):
        pos = 0
    index_data["next_index"] = pos
    save_index(index_data)


def reset_pointer() -> None:
    index_data = load_index()
    index_data["next_index"] = 0
    save_index(index_data)


def count() -> int:
    return len(load_index().get("images", []))


def get_all_thumbnails() -> list[dict]:
    """Return list of {index, filename, base64} for all images."""
    index_data = load_index()
    result = []
    for img_entry in index_data.get("images", []):
        b64 = load_image_b64(img_entry["index"])
        if b64:
            result.append({
                "index": img_entry["index"],
                "filename": img_entry["filename"],
                "base64": b64,
            })
    return result
