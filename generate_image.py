import io
import os
import tempfile

import requests
from PIL import Image

from config import IMAGE_PROVIDER, GEMINI_API_KEY, OPENAI_API_KEY


def _save_to_temp(image: Image.Image) -> str:
    """Save a PIL Image to a temporary PNG file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".png", prefix="autoposter_")
    os.close(fd)
    image.save(path, "PNG")
    return path


def _generate_gemini(prompt: str, api_key: str | None) -> str:
    from google import genai
    from google.genai import types
    key = api_key or GEMINI_API_KEY
    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            image = Image.open(io.BytesIO(part.inline_data.data))
            return _save_to_temp(image)

    raise RuntimeError("Gemini API did not return an image")


def _generate_openai(prompt: str, api_key: str | None) -> str:
    import openai
    key = api_key or OPENAI_API_KEY
    client = openai.OpenAI(api_key=key)
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


def generate_image(
    prompt: str,
    provider: str | None = None,
    api_key: str | None = None,
) -> str:
    """Generate an image from a text prompt.

    Args:
        prompt: Text description for the image.
        provider: Override IMAGE_PROVIDER from config (gemini/openai).
        api_key: Override the API key from config.

    Returns:
        Path to the saved PNG file.
    """
    prov = provider or IMAGE_PROVIDER

    provider_fn = _PROVIDERS.get(prov)
    if provider_fn is None:
        raise ValueError(
            f"Unknown IMAGE_PROVIDER: '{prov}'. "
            f"Use one of: {', '.join(_PROVIDERS)}"
        )
    return provider_fn(prompt, api_key)
