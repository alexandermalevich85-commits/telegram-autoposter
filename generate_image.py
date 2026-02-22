import io
import os
import tempfile

import openai
import requests
from google import genai
from google.genai import types
from PIL import Image

from config import IMAGE_PROVIDER, GEMINI_API_KEY, OPENAI_API_KEY


def _save_to_temp(image: Image.Image) -> str:
    """Save a PIL Image to a temporary PNG file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".png", prefix="autoposter_")
    os.close(fd)
    image.save(path, "PNG")
    return path


def _generate_gemini(prompt: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-04-17",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["TEXT", "IMAGE"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            image = Image.open(io.BytesIO(part.inline_data.data))
            return _save_to_temp(image)

    raise RuntimeError("Gemini API did not return an image")


def _generate_openai(prompt: str) -> str:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.images.generate(
        model="dall-e-3",
        prompt=prompt,
        size="1024x1024",
        quality="standard",
        n=1,
    )

    image_url = response.data[0].url
    image_data = requests.get(image_url, timeout=30).content
    image = Image.open(io.BytesIO(image_data))
    return _save_to_temp(image)


_PROVIDERS = {
    "gemini": _generate_gemini,
    "openai": _generate_openai,
}


def generate_image(prompt: str) -> str:
    """Generate an image from a text prompt.

    Uses the provider specified by IMAGE_PROVIDER in .env.

    Returns:
        Path to the saved PNG file.
    """
    provider_fn = _PROVIDERS.get(IMAGE_PROVIDER)
    if provider_fn is None:
        raise ValueError(
            f"Unknown IMAGE_PROVIDER: '{IMAGE_PROVIDER}'. "
            f"Use one of: {', '.join(_PROVIDERS)}"
        )
    return provider_fn(prompt)
