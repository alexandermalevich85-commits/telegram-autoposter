"""Face swap module — replace faces in generated images with the expert's face.

Three methods available:
  - replicate: Best quality, uses Replicate API face swap model (~$0.01/swap)
  - gemini: Free, passes reference face to Gemini as multimodal input
  - openai: Uses OpenAI gpt-image-1 with reference image editing
"""

import base64
import io
import os
import tempfile

import requests
from PIL import Image

from config import GEMINI_API_KEY, OPENAI_API_KEY, REPLICATE_API_KEY

EXPERT_FACE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "expert_face.json"
)


def load_expert_face_b64() -> str | None:
    """Load expert face base64 from expert_face.json. Returns None if not set."""
    import json

    if not os.path.exists(EXPERT_FACE_FILE):
        return None
    try:
        with open(EXPERT_FACE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("image_base64")
    except Exception:
        return None


def _b64_to_pil(b64_string: str) -> Image.Image:
    """Decode base64 string to PIL Image."""
    return Image.open(io.BytesIO(base64.b64decode(b64_string)))


def _pil_to_tempfile(img: Image.Image, suffix: str = ".png") -> str:
    """Save PIL Image to a temp file, return path."""
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="autoposter_")
    os.close(fd)
    img.save(path, "PNG" if suffix == ".png" else "JPEG")
    return path


def _pil_to_bytes(img: Image.Image, fmt: str = "PNG") -> bytes:
    """Convert PIL Image to bytes."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format=fmt)
    return buf.getvalue()


# ── Method 1: Replicate face swap ────────────────────────────────────────────


def _swap_replicate(
    source_image_path: str,
    expert_face_b64: str,
    api_key: str | None = None,
) -> str:
    """Use Replicate face swap model to replace face in source image."""
    import replicate

    key = api_key or REPLICATE_API_KEY
    if not key:
        raise ValueError("REPLICATE_API_KEY не задан")

    client = replicate.Client(api_token=key)

    # Prepare expert face as data URI
    expert_bytes = base64.b64decode(expert_face_b64)
    expert_uri = f"data:image/jpeg;base64,{base64.b64encode(expert_bytes).decode()}"

    # Prepare source image as data URI
    with open(source_image_path, "rb") as f:
        source_bytes = f.read()
    source_uri = f"data:image/png;base64,{base64.b64encode(source_bytes).decode()}"

    output = client.run(
        "xiankgx/face-swap:cff87316e31787df12002c9b4bff286f20cee315b38c4743bef89d8113e3d986",
        input={
            "target_image": source_uri,
            "swap_image": expert_uri,
        },
    )

    # output is a URL or FileOutput — download result
    if hasattr(output, "read"):
        result_bytes = output.read()
    else:
        result_url = str(output)
        result_bytes = requests.get(result_url, timeout=60).content

    result_img = Image.open(io.BytesIO(result_bytes))
    return _pil_to_tempfile(result_img)


# ── Method 2: Gemini with reference face ─────────────────────────────────────


def _swap_gemini(
    source_image_path: str,
    expert_face_b64: str,
    image_prompt: str = "",
    api_key: str | None = None,
) -> str:
    """Use Gemini multimodal to regenerate image with expert's face as reference."""
    from google import genai
    from google.genai import types

    key = api_key or GEMINI_API_KEY
    if not key:
        raise ValueError("GEMINI_API_KEY не задан")

    client = genai.Client(api_key=key)

    # Load expert face as PIL
    expert_img = _b64_to_pil(expert_face_b64)
    expert_bytes = _pil_to_bytes(expert_img, "JPEG")

    # Load source image
    with open(source_image_path, "rb") as f:
        source_bytes = f.read()

    prompt_text = (
        "Edit this image: replace the woman's face with the face from the reference photo. "
        "Keep the rest of the image exactly the same — same pose, background, lighting, and composition. "
        "Make the face blend naturally into the image."
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-04-17",
        contents=[
            prompt_text,
            types.Part.from_bytes(data=source_bytes, mime_type="image/png"),
            "Reference face photo:",
            types.Part.from_bytes(data=expert_bytes, mime_type="image/jpeg"),
        ],
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            result_img = Image.open(io.BytesIO(part.inline_data.data))
            return _pil_to_tempfile(result_img)

    raise RuntimeError("Gemini did not return an image with face swap")


# ── Method 3: OpenAI gpt-image-1 ────────────────────────────────────────────


def _swap_openai(
    source_image_path: str,
    expert_face_b64: str,
    api_key: str | None = None,
) -> str:
    """Use OpenAI gpt-image-1 to edit image with expert's face as reference."""
    import openai

    key = api_key or OPENAI_API_KEY
    if not key:
        raise ValueError("OPENAI_API_KEY не задан")

    client = openai.OpenAI(api_key=key)

    # Prepare images as file-like objects
    expert_bytes = base64.b64decode(expert_face_b64)

    with open(source_image_path, "rb") as source_file:
        source_bytes = source_file.read()

    response = client.images.edit(
        model="gpt-image-1",
        image=[
            io.BytesIO(source_bytes),
            io.BytesIO(expert_bytes),
        ],
        prompt=(
            "Replace the woman's face in the first image with the face from the second image. "
            "Keep everything else the same — pose, background, lighting, composition. "
            "Make the face blend naturally."
        ),
        size="1024x1024",
    )

    # gpt-image-1 returns base64 by default
    result_b64 = response.data[0].b64_json
    if result_b64:
        result_img = Image.open(io.BytesIO(base64.b64decode(result_b64)))
    else:
        result_url = response.data[0].url
        result_data = requests.get(result_url, timeout=30).content
        result_img = Image.open(io.BytesIO(result_data))

    return _pil_to_tempfile(result_img)


# ── Public API ───────────────────────────────────────────────────────────────


_METHODS = {
    "replicate": _swap_replicate,
    "gemini": _swap_gemini,
    "openai": _swap_openai,
}


def apply_face_swap(
    source_image_path: str,
    expert_face_b64: str | None = None,
    method: str = "replicate",
    image_prompt: str = "",
    api_key: str | None = None,
) -> str:
    """Apply face swap to a generated image using the expert's face.

    Args:
        source_image_path: Path to the generated image file.
        expert_face_b64: Base64 of expert's face photo. If None, loads from expert_face.json.
        method: Face swap method — replicate, gemini, or openai.
        image_prompt: Original image prompt (used by gemini method).
        api_key: Override the API key for the chosen method.

    Returns:
        Path to the new image with swapped face.
        If no expert face is available, returns the original path unchanged.
    """
    face_b64 = expert_face_b64 or load_expert_face_b64()
    if not face_b64:
        return source_image_path  # No expert face — return original

    swap_fn = _METHODS.get(method)
    if swap_fn is None:
        raise ValueError(
            f"Unknown face swap method: '{method}'. "
            f"Use one of: {', '.join(_METHODS)}"
        )

    if method == "gemini":
        return swap_fn(source_image_path, face_b64, image_prompt=image_prompt, api_key=api_key)
    return swap_fn(source_image_path, face_b64, api_key=api_key)
