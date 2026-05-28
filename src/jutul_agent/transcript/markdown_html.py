"""Convert markdown prose to HTML for transcript renderers."""

from __future__ import annotations

import re
from functools import lru_cache

from markdown_it import MarkdownIt

_MD_MARKERS = re.compile(
    r"(^|\n)(#{1,6}\s|\*\*[^*]+\*\*|```|^\s*[-*+]\s|^\s*\d+\.\s|\|.+\|)",
    re.MULTILINE,
)
_YAML_FRONTMATTER = re.compile(r"^---\s*\n.*?\n---\s*\n", re.DOTALL)


@lru_cache(maxsize=1)
def _markdown_renderer() -> MarkdownIt:
    return MarkdownIt("gfm-like")


def looks_like_markdown(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if "```" in stripped or "**" in stripped:
        return True
    if _MD_MARKERS.search(stripped):
        return True
    return stripped.startswith("# ") and "\n" in stripped


_NUMBERED_LINE = re.compile(r"^\s*\d+\t")


def strip_line_number_prefixes(text: str) -> str:
    """Remove ``cat -n`` style prefixes from ``read_file`` tool output."""
    lines = text.splitlines()
    if len(lines) < 2:
        return text
    sample = lines[: min(len(lines), 24)]
    numbered = sum(1 for ln in sample if _NUMBERED_LINE.match(ln))
    if numbered < max(3, len(sample) // 2):
        return text
    return "\n".join(_NUMBERED_LINE.sub("", ln, count=1) for ln in lines)


def strip_yaml_frontmatter(text: str) -> str:
    """Drop YAML frontmatter blocks from skill files and similar markdown."""
    return _YAML_FRONTMATTER.sub("", text, count=1)


def render_markdown_html(text: str) -> str:
    """Render markdown to an HTML fragment (no wrapper element)."""
    return _markdown_renderer().render(text.strip())
