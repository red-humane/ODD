"""
ODD Text Magic & Smart Transformer
==================================
Zero-AI, 100% offline, 0ms latency text and clipboard transformation engine.
Eliminates tedious manual work: case conversions, PDF line break cleaning,
JSON formatting, URL/Base64 encoding, data parsing, and UUID generation.
"""

import re
import json
import uuid
import time
import base64
import urllib.parse
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Callable, Any


# ---------------------------------------------------------------------------
# 1. CASE CONVERSION UTILITIES
# ---------------------------------------------------------------------------

def _split_into_words(text: str) -> List[str]:
    """Splits a string by spaces, punctuation, camelCase boundaries, and delimiters."""
    if not text:
        return []
    # Handle camelCase boundaries (e.g. "myVariableName" -> "my Variable Name")
    s1 = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', text)
    # Handle acronym boundaries (e.g. "XMLHTTPRequest" -> "XML HTTP Request")
    s2 = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1 \2', s1)
    # Replace non-alphanumeric chars with spaces (preserving standard unicode letters)
    words = re.split(r'[_\-\s\.\/\\\|\:\;\,]+', s2)
    return [w for w in words if w]


def to_title_case(text: str) -> str:
    """Converts text to Title Case (ignoring minor words if in a sentence, or capitalizing each word)."""
    words = text.split()
    if not words:
        return text
    return " ".join(w.capitalize() for w in words)


def to_camel_case(text: str) -> str:
    """Converts text to camelCase (e.g. 'hello_world_var' -> 'helloWorldVar')."""
    words = _split_into_words(text)
    if not words:
        return text
    first = words[0].lower()
    rest = [w.capitalize() for w in words[1:]]
    return first + "".join(rest)


def to_pascal_case(text: str) -> str:
    """Converts text to PascalCase (e.g. 'hello_world_var' -> 'HelloWorldVar')."""
    words = _split_into_words(text)
    if not words:
        return text
    return "".join(w.capitalize() for w in words)


def to_snake_case(text: str) -> str:
    """Converts text to snake_case (e.g. 'Hello World' -> 'hello_world')."""
    words = _split_into_words(text)
    if not words:
        return text
    return "_".join(w.lower() for w in words)


def to_constant_case(text: str) -> str:
    """Converts text to CONSTANT_CASE (e.g. 'api key' -> 'API_KEY')."""
    words = _split_into_words(text)
    if not words:
        return text
    return "_".join(w.upper() for w in words)


def to_kebab_case(text: str) -> str:
    """Converts text to kebab-case (e.g. 'Hello World' -> 'hello-world')."""
    words = _split_into_words(text)
    if not words:
        return text
    return "-".join(w.lower() for w in words)


def to_dot_case(text: str) -> str:
    """Converts text to dot.case (e.g. 'config max count' -> 'config.max.count')."""
    words = _split_into_words(text)
    if not words:
        return text
    return ".".join(w.lower() for w in words)


def to_sentence_case(text: str) -> str:
    """Capitalizes the first letter of each sentence."""
    if not text:
        return text
    sentences = re.split(r'([\.\?\!]\s+)', text)
    result = []
    for part in sentences:
        if part and not re.match(r'^[\.\?\!]\s+$', part):
            result.append(part[0].upper() + part[1:].lower())
        else:
            result.append(part)
    return "".join(result)


def to_alternating_case(text: str) -> str:
    """cOnVeRtS TeXt tO AlTeRnAtInG CaSe."""
    chars = []
    upper = False
    for c in text:
        if c.isalpha():
            chars.append(c.upper() if upper else c.lower())
            upper = not upper
        else:
            chars.append(c)
    return "".join(chars)


# ---------------------------------------------------------------------------
# 2. TEXT CLEANERS & FORMATTERS
# ---------------------------------------------------------------------------

def clean_line_breaks(text: str) -> str:
    """Joins lines broken by PDFs or OCR into a clean continuous paragraph."""
    paragraphs = text.split('\n\n')
    cleaned_paras = []
    for p in paragraphs:
        cleaned = re.sub(r'[\r\n]+', ' ', p)
        cleaned = re.sub(r'[ \t]+', ' ', cleaned).strip()
        if cleaned:
            cleaned_paras.append(cleaned)
    return '\n\n'.join(cleaned_paras)


def clean_extra_spaces(text: str) -> str:
    """Removes trailing whitespace, trims lines, and collapses multiple spaces into one."""
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        cleaned = re.sub(r'[ \t]+', ' ', line).strip()
        cleaned_lines.append(cleaned)
    return '\n'.join(cleaned_lines)


def strip_html_tags(text: str) -> str:
    """Strips HTML/XML tags and converts common entities to plain text."""
    s = re.sub(r'<\s*br\s*/?>', '\n', text, flags=re.IGNORECASE)
    s = re.sub(r'</\s*p\s*>', '\n\n', s, flags=re.IGNORECASE)
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"').replace('&#39;', "'")
    return s.strip()


def remove_duplicate_lines(text: str) -> str:
    """Removes duplicate lines while preserving the original order."""
    lines = text.splitlines()
    seen = set()
    unique_lines = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique_lines.append(line)
    return '\n'.join(unique_lines)


def sort_lines_asc(text: str) -> str:
    """Sorts all lines alphabetically (A -> Z)."""
    lines = [l for l in text.splitlines() if l.strip()]
    lines.sort(key=lambda s: s.lower())
    return '\n'.join(lines)


def sort_lines_desc(text: str) -> str:
    """Sorts all lines in reverse alphabetical order (Z -> A)."""
    lines = [l for l in text.splitlines() if l.strip()]
    lines.sort(key=lambda s: s.lower(), reverse=True)
    return '\n'.join(lines)


def remove_empty_lines(text: str) -> str:
    """Removes all blank or whitespace-only lines."""
    lines = [l for l in text.splitlines() if l.strip()]
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# 3. DATA, DEVELOPER & ENCODING UTILITIES
# ---------------------------------------------------------------------------

def prettify_json(text: str) -> str:
    """Formats and indents JSON data nicely with 2 spaces."""
    trimmed = text.strip()
    data = json.loads(trimmed)
    return json.dumps(data, indent=2, ensure_ascii=False)


def minify_json(text: str) -> str:
    """Minifies JSON to a single compact line."""
    trimmed = text.strip()
    data = json.loads(trimmed)
    return json.dumps(data, separators=(',', ':'), ensure_ascii=False)


def url_encode(text: str) -> str:
    """URL-encodes characters for query strings and paths."""
    return urllib.parse.quote(text, safe='')


def url_decode(text: str) -> str:
    """Decodes percent-encoded URL characters."""
    return urllib.parse.unquote(text)


def base64_encode(text: str) -> str:
    """Encodes UTF-8 text to Base64."""
    raw = text.encode('utf-8')
    return base64.b64encode(raw).decode('utf-8')


def base64_decode(text: str) -> str:
    """Decodes Base64 string to UTF-8 text."""
    cleaned = re.sub(r'\s+', '', text)
    missing_padding = len(cleaned) % 4
    if missing_padding:
        cleaned += '=' * (4 - missing_padding)
    raw = base64.b64decode(cleaned)
    return raw.decode('utf-8', errors='replace')


def extract_urls(text: str) -> str:
    """Extracts all web URLs found in the text, one per line."""
    url_pattern = r'https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*'
    urls = re.findall(url_pattern, text)
    if not urls:
        return "No URLs found in input"
    return '\n'.join(urls)


def extract_emails(text: str) -> str:
    """Extracts all email addresses found in the text, one per line."""
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    emails = re.findall(email_pattern, text)
    if not emails:
        return "No email addresses found in input"
    seen = set()
    unique = [e for e in emails if not (e.lower() in seen or seen.add(e.lower()))]
    return '\n'.join(unique)


def csv_to_markdown_table(text: str) -> str:
    """Converts comma-separated or tab-separated data into a clean Markdown table."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return text
    delimiter = '\t' if '\t' in lines[0] else ','
    
    rows = []
    for line in lines:
        cols = [c.strip().strip('"') for c in line.split(delimiter)]
        rows.append(cols)
    
    if not rows:
        return text
    
    max_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < max_cols:
            r.append('')
            
    header = rows[0]
    sep = ['---'] * max_cols
    body = rows[1:] if len(rows) > 1 else []
    
    md_lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |"
    ]
    for b in body:
        md_lines.append("| " + " | ".join(b) + " |")
    return '\n'.join(md_lines)


def to_sql_in_clause(text: str) -> str:
    """Converts a newline-separated or space-separated list of items into SQL IN ('val1', 'val2')."""
    lines = [l.strip() for l in re.split(r'[\r\n,]+', text) if l.strip()]
    if not lines:
        return "IN ()"
    quoted = [f"'{item.replace("'", "''")}'" for item in lines]
    return f"IN ({', '.join(quoted)})"


def slugify_text(text: str) -> str:
    """Converts text to an SEO-friendly URL slug (e.g. 'Hello World! 2026' -> 'hello-world-2026')."""
    s = text.lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_-]+', '-', s)
    return s.strip('-')


def generate_uuid(_text: str = "") -> str:
    """Generates a fresh UUID v4."""
    return str(uuid.uuid4())


def generate_unix_timestamp(_text: str = "") -> str:
    """Returns current Unix epoch timestamp in seconds."""
    return str(int(time.time()))


def generate_iso_timestamp(_text: str = "") -> str:
    """Returns current ISO 8601 UTC timestamp."""
    return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')


# ---------------------------------------------------------------------------
# 4. TRANSFORMATION REGISTRY & METADATA
# ---------------------------------------------------------------------------

class TextTransform:
    def __init__(
        self,
        id: str,
        title: str,
        category: str,
        icon: str,
        desc: str,
        func: Callable[[str], str],
        shortcut: str = ""
    ):
        self.id = id
        self.title = title
        self.category = category  # "Case", "Clean", "Data", "Encode", "Generate"
        self.icon = icon
        self.desc = desc
        self.func = func
        self.shortcut = shortcut


TRANSFORMS: List[TextTransform] = [
    # --- Category: Case ---
    TextTransform("title_case", "Title Case", "Case", "", "Capitalize Every Word", to_title_case, "T"),
    TextTransform("camel_case", "camelCase", "Case", "", "Lower first word, capitalize subsequent words", to_camel_case, "C"),
    TextTransform("snake_case", "snake_case", "Case", "", "Lower words separated with underscores", to_snake_case, "S"),
    TextTransform("kebab_case", "kebab-case", "Case", "", "Lower words separated with dashes", to_kebab_case, "K"),
    TextTransform("constant_case", "CONSTANT_CASE", "Case", "", "Uppercase words with underscores", to_constant_case),
    TextTransform("pascal_case", "PascalCase", "Case", "", "Capitalize all words without spaces", to_pascal_case),
    TextTransform("upper_case", "UPPERCASE", "Case", "", "Convert all characters to upper case", lambda t: t.upper()),
    TextTransform("lower_case", "lowercase", "Case", "", "Convert all characters to lower case", lambda t: t.lower()),
    TextTransform("sentence_case", "Sentence case", "Case", "", "Capitalize first letter of each sentence", to_sentence_case),
    TextTransform("dot_case", "dot.case", "Case", "", "Words separated with periods", to_dot_case),
    TextTransform("alternating_case", "aLtErNaTiNg", "Case", "", "Alternating upper and lower case", to_alternating_case),

    # --- Category: Clean ---
    TextTransform("clean_linebreaks", "Fix PDF Line Breaks", "Clean", "", "Unbreak lines from copied PDF / OCR text", clean_line_breaks),
    TextTransform("clean_extra_spaces", "Clean Extra Spaces", "Clean", "", "Collapse consecutive spaces & trim edges", clean_extra_spaces),
    TextTransform("strip_html", "Strip HTML Tags", "Clean", "", "Remove tags and convert HTML entities to text", strip_html_tags),
    TextTransform("remove_duplicates", "Deduplicate Lines", "Clean", "", "Remove duplicate lines keeping original order", remove_duplicate_lines),
    TextTransform("remove_empty", "Remove Empty Lines", "Clean", "", "Delete all blank lines", remove_empty_lines),
    TextTransform("sort_asc", "Sort Lines (A → Z)", "Clean", "", "Sort lines alphabetically", sort_lines_asc),
    TextTransform("sort_desc", "Sort Lines (Z → A)", "Clean", "", "Sort lines in descending order", sort_lines_desc),

    # --- Category: Data & Code ---
    TextTransform("json_prettify", "Format / Prettify JSON", "Data", "", "Format JSON with 2-space indentation", prettify_json, "J"),
    TextTransform("json_minify", "Minify JSON", "Data", "", "Compress JSON to single compact line", minify_json),
    TextTransform("csv_to_md", "CSV → Markdown Table", "Data", "", "Convert CSV/TSV data to Markdown table", csv_to_markdown_table),
    TextTransform("sql_in_clause", "SQL IN (...) List", "Data", "", "Format lines into SQL IN ('a', 'b', 'c')", to_sql_in_clause),
    TextTransform("extract_urls", "Extract All URLs", "Data", "", "Find and list all URLs in text", extract_urls),
    TextTransform("extract_emails", "Extract All Emails", "Data", "", "Find and list all email addresses in text", extract_emails),
    TextTransform("slugify", "Slugify (SEO URL)", "Data", "", "Convert string to clean URL slug", slugify_text),

    # --- Category: Encode ---
    TextTransform("url_encode", "URL Encode", "Encode", "", "Percent-encode URL characters", url_encode),
    TextTransform("url_decode", "URL Decode", "Encode", "", "Decode percent-encoded URL characters", url_decode),
    TextTransform("base64_encode", "Base64 Encode", "Encode", "", "Convert UTF-8 text into Base64", base64_encode),
    TextTransform("base64_decode", "Base64 Decode", "Encode", "", "Decode Base64 string to text", base64_decode),

    # --- Category: Generate ---
    TextTransform("gen_uuid", "Generate UUID v4", "Generate", "", "Generate a new random UUID v4", generate_uuid),
    TextTransform("gen_unix_ts", "Unix Epoch Timestamp", "Generate", "", "Current timestamp in seconds", generate_unix_timestamp),
    TextTransform("gen_iso_ts", "ISO 8601 Timestamp", "Generate", "", "Current timestamp in UTC ISO format", generate_iso_timestamp),
]

_TRANSFORMS_MAP: Dict[str, TextTransform] = {t.id: t for t in TRANSFORMS}


def get_transform(transform_id: str) -> Optional[TextTransform]:
    """Look up a transform by its identifier."""
    return _TRANSFORMS_MAP.get(transform_id)


def get_all_transforms(category: Optional[str] = None) -> List[TextTransform]:
    """Returns all registered transforms, optionally filtered by category."""
    if not category:
        return TRANSFORMS
    cat_low = category.lower().strip()
    return [t for t in TRANSFORMS if t.category.lower() == cat_low]


def apply_transform(text: str, transform_id: str) -> Tuple[bool, str, str]:
    """
    Applies the specified transformation on input text.
    Returns: (success: bool, output_text: str, message: str)
    """
    t = get_transform(transform_id)
    if not t:
        return False, text, f"Transform '{transform_id}' not found"
    try:
        res = t.func(text)
        return True, str(res), f"Transformed with {t.title}"
    except Exception as e:
        return False, text, f"Error formatting {t.title}: {str(e)}"
