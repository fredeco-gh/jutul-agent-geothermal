"""Renderings of a trace. Add a sibling module per output format."""

from jutul_agent.transcript.bundle import bundle_transcript
from jutul_agent.transcript.html import render_html
from jutul_agent.transcript.markdown import render_markdown
from jutul_agent.transcript.report import render_report

__all__ = ["bundle_transcript", "render_html", "render_markdown", "render_report"]
