import re

def clean_html_for_telegram(html_text: str) -> str:
    if not html_text:
        return ""
    return re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)


def strip_html_tags(text: str) -> str:
    if not text:
        return ""

    # List of HTML tags supported by Telegram Bot API
    # Source: https://core.telegram.org/api/entities and https://telegram-bot-sdk.readme.io/reference/sendmessage
    # Strip leading/trailing whitespace first to ensure tags are at the beginning/end if they exist
    text = text.strip()

    # List of HTML tags supported by Telegram Bot API
    supported_tags = [
        'b', 'i', 'code', 's', 'u', 'pre', 'a'
    ]

    def replace_unsupported_tags(match):
        tag_name = match.group(2).lower()
        attributes = match.group(3) if match.group(3) else ''

        if tag_name in supported_tags:
            return match.group(0)  # Keep the tag if it's supported
        else:
            return ''  # Remove the tag if it's not supported

    # Regex to find HTML tags: < (optional /) (tag name) (optional attributes) >
    # group(0) is the entire match, group(1) is the optional '/', group(2) is the tag name, group(3) is attributes
    cleaned_text = re.sub(r'<(/)?([a-zA-Z]+)([^>]*)>', replace_unsupported_tags, text, flags=re.IGNORECASE)

    return cleaned_text


def strip_markdown_code_blocks(text: str) -> str:
    if text is None:
        return ""

    pattern = r"```(?:\w+\n)?(.*?)\n?```"

    stripped_text = re.sub(pattern, r'\1', text, flags=re.DOTALL)
    return stripped_text.strip()

def normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    # Replace multiple newlines with at most two newlines
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Replace multiple spaces with a single space
    text = re.sub(r' {2,}', ' ', text)
    # Remove leading/trailing whitespace from each line
    text = '\n'.join([line.strip() for line in text.split('\n')])
    return text.strip()
