from config import TEXT_PROVIDER, CLAUDE_API_KEY, OPENAI_API_KEY, get_gemini_client

DEFAULT_SYSTEM_PROMPT = """\
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

DEFAULT_IMAGE_PROMPT_TEMPLATE = (
    "Beautiful aesthetic photo related to facial rejuvenation and {idea}, "
    "professional photography, soft lighting, skincare"
)

USER_MESSAGE = "Напиши пост на тему: {idea}"


def _parse_response(response_text: str, idea: str, image_prompt_template: str | None = None) -> tuple[str, str]:
    """Parse POST: and IMAGE_PROMPT: sections from model response."""
    if "POST:" in response_text and "IMAGE_PROMPT:" in response_text:
        parts = response_text.split("IMAGE_PROMPT:")
        post_text = parts[0].replace("POST:", "").strip()
        image_prompt = parts[1].strip()
    else:
        post_text = response_text.strip()
        template = image_prompt_template or DEFAULT_IMAGE_PROMPT_TEMPLATE
        image_prompt = template.format(idea=idea)
    return post_text, image_prompt


def _generate_claude(idea: str, system_prompt: str, image_prompt_template: str | None, api_key: str | None) -> tuple[str, str]:
    import anthropic
    key = api_key or CLAUDE_API_KEY
    client = anthropic.Anthropic(api_key=key)
    message = client.messages.create(
        model="claude-sonnet-4-5-20250929",
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": USER_MESSAGE.format(idea=idea)}],
    )
    return _parse_response(message.content[0].text, idea, image_prompt_template)


def _generate_gemini(idea: str, system_prompt: str, image_prompt_template: str | None, api_key: str | None) -> tuple[str, str]:
    client = get_gemini_client(api_key_override=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"{system_prompt}\n\n{USER_MESSAGE.format(idea=idea)}",
    )
    return _parse_response(response.text, idea, image_prompt_template)


def _generate_openai(idea: str, system_prompt: str, image_prompt_template: str | None, api_key: str | None) -> tuple[str, str]:
    import openai
    key = api_key or OPENAI_API_KEY
    client = openai.OpenAI(api_key=key)
    response = client.chat.completions.create(
        model="gpt-4o",
        max_tokens=1500,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": USER_MESSAGE.format(idea=idea)},
        ],
    )
    return _parse_response(response.choices[0].message.content, idea, image_prompt_template)


_PROVIDERS = {
    "claude": _generate_claude,
    "gemini": _generate_gemini,
    "openai": _generate_openai,
}


def generate_post(
    idea: str,
    provider: str | None = None,
    system_prompt: str | None = None,
    image_prompt_template: str | None = None,
    api_key: str | None = None,
    context_document: str | None = None,
) -> tuple[str, str]:
    """Generate a Telegram post text and image prompt from an idea.

    Args:
        idea: The topic/idea for the post.
        provider: Override TEXT_PROVIDER from config (claude/gemini/openai).
        system_prompt: Override the default system prompt.
        image_prompt_template: Override the fallback image prompt template.
            Use {idea} placeholder for the topic.
        api_key: Override the API key from config.
        context_document: Optional text from an attached document to use as
            additional context and information source for post generation.

    Returns:
        Tuple of (post_text, image_prompt).
    """
    prov = provider or TEXT_PROVIDER
    prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    # Append context document to system prompt if provided
    if context_document:
        prompt += (
            "\n\n--- КОНТЕКСТНЫЙ ДОКУМЕНТ ---\n"
            f"{context_document}\n"
            "--- КОНЕЦ ДОКУМЕНТА ---\n\n"
            "Используй информацию из документа выше как источник данных и контекст "
            "при написании поста. Опирайся на факты и стиль из документа."
        )

    provider_fn = _PROVIDERS.get(prov)
    if provider_fn is None:
        raise ValueError(
            f"Unknown TEXT_PROVIDER: '{prov}'. "
            f"Use one of: {', '.join(_PROVIDERS)}"
        )
    return provider_fn(idea, prompt, image_prompt_template, api_key)
