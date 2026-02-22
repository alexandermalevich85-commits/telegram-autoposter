import anthropic
import openai
from google import genai

from config import TEXT_PROVIDER, CLAUDE_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY

SYSTEM_PROMPT = """\
Ты — эксперт по естественному омоложению лица. Ты ведёшь Telegram-канал и пишешь \
увлекательные, полезные посты для женщин 30-55 лет.

Правила:
- Пиши на русском языке
- Используй HTML-разметку для Telegram: <b>жирный</b>, <i>курсив</i>
- Длина поста: 500-1000 символов (не больше, это Telegram)
- Структура: цепляющий заголовок → полезный контент → призыв к действию
- Добавь 3-5 релевантных хэштегов в конце
- Не используй Markdown, только HTML-теги
- Разделяй абзацы пустой строкой (двойной \\n)
- Тон: дружелюбный, экспертный, без воды

Ответ должен быть в формате:
POST:
<текст поста с HTML-разметкой>

IMAGE_PROMPT:
<промпт на английском языке для генерации картинки к этому посту, \
описывающий красивое, эстетичное изображение связанное с темой поста, \
без текста на картинке, в стиле профессиональной фотографии>\
"""

USER_MESSAGE = "Напиши пост на тему: {idea}"


def _parse_response(response_text: str, idea: str) -> tuple[str, str]:
    """Parse POST: and IMAGE_PROMPT: sections from model response."""
    if "POST:" in response_text and "IMAGE_PROMPT:" in response_text:
        parts = response_text.split("IMAGE_PROMPT:")
        post_text = parts[0].replace("POST:", "").strip()
        image_prompt = parts[1].strip()
    else:
        post_text = response_text.strip()
        image_prompt = (
            f"Beautiful aesthetic photo related to facial rejuvenation and {idea}, "
            f"professional photography, soft lighting, skincare"
        )
    return post_text, image_prompt


def _generate_claude(idea: str) -> tuple[str, str]:
    client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1500,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": USER_MESSAGE.format(idea=idea)}],
    )
    return _parse_response(message.content[0].text, idea)


def _generate_gemini(idea: str) -> tuple[str, str]:
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-04-17",
        contents=f"{SYSTEM_PROMPT}\n\n{USER_MESSAGE.format(idea=idea)}",
    )
    return _parse_response(response.text, idea)


def _generate_openai(idea: str) -> tuple[str, str]:
    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1500,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_MESSAGE.format(idea=idea)},
        ],
    )
    return _parse_response(response.choices[0].message.content, idea)


_PROVIDERS = {
    "claude": _generate_claude,
    "gemini": _generate_gemini,
    "openai": _generate_openai,
}


def generate_post(idea: str) -> tuple[str, str]:
    """Generate a Telegram post text and image prompt from an idea.

    Uses the provider specified by TEXT_PROVIDER in .env.

    Returns:
        Tuple of (post_text, image_prompt).
    """
    provider_fn = _PROVIDERS.get(TEXT_PROVIDER)
    if provider_fn is None:
        raise ValueError(
            f"Unknown TEXT_PROVIDER: '{TEXT_PROVIDER}'. "
            f"Use one of: {', '.join(_PROVIDERS)}"
        )
    return provider_fn(idea)
