import base64
import io
import os
import tempfile

import requests
from PIL import Image

from config import IMAGE_PROVIDER, OPENAI_API_KEY, get_gemini_client


def _save_to_temp(image: Image.Image) -> str:
    """Save a PIL Image to a temporary PNG file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".png", prefix="autoposter_")
    os.close(fd)
    image.save(path, "PNG")
    return path


def _generate_gemini(
    prompt: str,
    api_key: str | None,
    expert_face_b64: str | None = None,
    reference_image_b64: str | None = None,
) -> str:
    from google.genai import types

    client = get_gemini_client(api_key_override=api_key)

    if expert_face_b64 or reference_image_b64:
        text_prompt = prompt
        if expert_face_b64:
            text_prompt += (
                "\n\nСоздай изображение, где главный персонаж имеет лицо "
                "с приложенного референсного фото. Сохрани точное сходство лица."
            )
        if reference_image_b64:
            text_prompt += (
                "\n\nИспользуй приложенное фото как визуальный референс "
                "для стиля, композиции и атмосферы изображения."
            )
        contents = [text_prompt]
        if reference_image_b64:
            ref_bytes = base64.b64decode(reference_image_b64)
            contents.append(types.Part.from_bytes(data=ref_bytes, mime_type="image/jpeg"))
        if expert_face_b64:
            face_bytes = base64.b64decode(expert_face_b64)
            contents.append(types.Part.from_bytes(data=face_bytes, mime_type="image/jpeg"))
    else:
        contents = prompt

    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=contents,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            image = Image.open(io.BytesIO(part.inline_data.data))
            return _save_to_temp(image)

    raise RuntimeError("Gemini API did not return an image")


def _generate_openai(
    prompt: str,
    api_key: str | None,
    expert_face_b64: str | None = None,
    reference_image_b64: str | None = None,
) -> str:
    import openai

    key = api_key or OPENAI_API_KEY
    client = openai.OpenAI(api_key=key)

    if expert_face_b64 or reference_image_b64:
        # Use images.edit with reference images via gpt-image-1
        images_list = []
        full_prompt = prompt

        if expert_face_b64:
            face_bytes = base64.b64decode(expert_face_b64)
            face_file = io.BytesIO(face_bytes)
            face_file.name = "expert_face.jpg"
            images_list.append(face_file)
            full_prompt = (
                "IMPORTANT: The attached photo is a reference face. "
                "The person in the generated image MUST have exactly this face — "
                "same facial structure, eyes, nose, lips, skin tone, and overall appearance. "
                "Do NOT change or stylize the face. Preserve photographic facial likeness.\n\n"
                + full_prompt
            )

        if reference_image_b64:
            ref_bytes = base64.b64decode(reference_image_b64)
            ref_file = io.BytesIO(ref_bytes)
            ref_file.name = "reference.jpg"
            images_list.append(ref_file)
            full_prompt += (
                "\n\nUse the attached reference photo as visual guidance "
                "for style, composition, and atmosphere of the image."
            )

        response = client.images.edit(
            model="gpt-image-1",
            image=images_list if len(images_list) > 1 else images_list[0],
            prompt=full_prompt,
            size="1024x1024",
            quality="high",
        )

        img_b64 = response.data[0].b64_json
        image = Image.open(io.BytesIO(base64.b64decode(img_b64)))
    else:
        # Standard generation via dall-e-3
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
    expert_face_b64: str | None = None,
    reference_image_b64: str | None = None,
) -> str:
    """Generate an image from a text prompt.

    Args:
        prompt: Text description for the image.
        provider: Override IMAGE_PROVIDER from config (gemini/openai).
        api_key: Override the API key from config.
        expert_face_b64: Base64-encoded expert face photo for reference.
            If provided and provider is gemini, the image is generated
            with the expert's face in a single API call (no face swap needed).
        reference_image_b64: Base64-encoded reference photo for visual guidance
            (style, composition, atmosphere).

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
    return provider_fn(
        prompt, api_key,
        expert_face_b64=expert_face_b64,
        reference_image_b64=reference_image_b64,
    )
