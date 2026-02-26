"""Extract plain text from uploaded documents (txt, pdf, docx)."""

import io

MAX_TEXT_LENGTH = 30_000  # ~7500 tokens, safe for all LLM providers


def extract_text(uploaded_file) -> str:
    """Extract text from a Streamlit UploadedFile (txt, pdf, docx).

    Args:
        uploaded_file: Streamlit UploadedFile object with .name and .read().

    Returns:
        Extracted plain text, truncated to MAX_TEXT_LENGTH characters.
    """
    name = uploaded_file.name.lower()

    if name.endswith(".txt"):
        text = _extract_txt(uploaded_file)
    elif name.endswith(".pdf"):
        text = _extract_pdf(uploaded_file)
    elif name.endswith(".docx"):
        text = _extract_docx(uploaded_file)
    else:
        raise ValueError(f"Unsupported file format: {name}")

    # Truncate to safe limit
    if len(text) > MAX_TEXT_LENGTH:
        text = text[:MAX_TEXT_LENGTH] + "\n\n[... документ обрезан ...]"

    return text.strip()


def _extract_txt(uploaded_file) -> str:
    """Read plain text file."""
    raw = uploaded_file.read()
    # Try UTF-8 first, fall back to cp1251 (common for Russian docs)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1251", errors="replace")


def _extract_pdf(uploaded_file) -> str:
    """Extract text from PDF using pypdf."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(uploaded_file.read()))
    pages = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            pages.append(page_text)
    return "\n\n".join(pages)


def _extract_docx(uploaded_file) -> str:
    """Extract text from DOCX using python-docx."""
    from docx import Document

    doc = Document(io.BytesIO(uploaded_file.read()))
    paragraphs = []
    for para in doc.paragraphs:
        if para.text.strip():
            paragraphs.append(para.text)
    return "\n\n".join(paragraphs)
