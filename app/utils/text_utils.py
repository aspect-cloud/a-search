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
    supported_tags = [
        'b', 'strong', 'i', 'em', 'a', 'code', 'pre', 's', 'strike', 'del', 'u'
    ]

    def replace_unsupported_tags(match):
        tag_name = match.group(2).lower()
        if tag_name in supported_tags:
            return match.group(0)  # Keep the tag if it's supported
        else:
            return ''  # Remove the tag if it's not supported

    # Regex to find HTML tags: < (optional /) (tag name) (optional attributes) >
    # This regex is a basic one and might not handle all edge cases of malformed HTML perfectly.
    # It's designed to match typical HTML tag structures.
    cleaned_text = re.sub(r'(<[/]?[a-zA-Z]+[^>]*>)', replace_unsupported_tags, text, flags=re.IGNORECASE)

    # Additionally, remove any <p> tags that might have been left or introduced, as they are not explicitly supported
    # and were causing issues previously.
    cleaned_text = re.sub(r'<p[^>]*>', '', cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r'</p>', '', cleaned_text, flags=re.IGNORECASE)

    return cleaned_text


def strip_markdown_code_blocks(text: str) -> str:
    if text is None:
        return ""

    pattern = r"```(?:\w+\n)?(.*?)\n?```"

    stripped_text = re.sub(pattern, r'\1', text, flags=re.DOTALL)
    return stripped_text.strip()
