"""Tests for markdown rendering helpers."""

from __future__ import annotations

from jutul_agent.transcript.markdown_html import (
    looks_like_markdown,
    render_markdown_html,
    strip_line_number_prefixes,
    strip_yaml_frontmatter,
)


def test_looks_like_markdown() -> None:
    assert looks_like_markdown("### Heading")
    assert looks_like_markdown("plain **bold** text")
    assert not looks_like_markdown("just one line")


def test_render_markdown_html() -> None:
    html = render_markdown_html("**bold**")
    assert "<strong>bold</strong>" in html


def test_strip_line_number_prefixes() -> None:
    text = "1\t---\n2\tname: wells\n3\tdescription: test\n"
    assert strip_line_number_prefixes(text).startswith("---\nname: wells")

    padded = "     1\t---\n     2\tname: wells\n     3\tdescription: test\n"
    assert strip_line_number_prefixes(padded).startswith("---\nname: wells")


def test_strip_yaml_frontmatter() -> None:
    text = "---\nname: wells\ndescription: test\n---\n\n# Title\n"
    assert strip_yaml_frontmatter(text).startswith("# Title")
