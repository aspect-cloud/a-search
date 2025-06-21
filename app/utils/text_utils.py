import re

def clean_html_for_telegram(html_text: str) -> str:
    if not html_text:
        return ""
    return re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)


def strip_html_tags(text: str) -> str:
    if not text:
        return ""
    return re.sub(r'<[^>]+>', '', text)


def strip_markdown_code_blocks(text: str) -> str:
    if text is None:
        return ""

    pattern = r"```(?:\w+\n)?(.*?)\n?```"

    stripped_text = re.sub(pattern, r'\1', text, flags=re.DOTALL)
    return stripped_text.strip()
