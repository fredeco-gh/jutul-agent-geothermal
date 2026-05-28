"""Filter noisy assistant prose that duplicates tool cards in the TUI.

Cases the agent reliably gets wrong (worth suppressing):

* Returning the raw ``write_todos`` payload or a ``"Updated todo list …"``
  line in the prose channel — the dedicated card already shows it.
* Echoing a recent tool result back as prose, in full or near-full.
* Dumping a skill's markdown verbatim after reading it (frontmatter or a
  recognisable skill header + section signature). The skill has already
  been mounted into the system prompt; copying it into the chat adds
  hundreds of lines of noise.
"""

from __future__ import annotations

import re
from collections import deque

_TODO_UPDATE = re.compile(r"^Updated todo list to \[\{", re.IGNORECASE | re.DOTALL)
_NUMBERED_LINE = re.compile(r"^\s*\d+\t")
# Skill files start with a YAML frontmatter block whose first field is
# ``name:`` — that's specific enough to never appear in regular prose.
_SKILL_FRONTMATTER = re.compile(r"^---\s*\nname:\s*\S+", re.MULTILINE)
# MEMORY.md always opens with this top-level heading.
_MEMORY_INDEX_HEADING = re.compile(r"^#\s+Memory index\b", re.MULTILINE)
_SECTION_HEADER = re.compile(r"^##\s+\S", re.MULTILINE)
_TOP_LEVEL_HEADING = re.compile(r"^#\s+\S", re.MULTILINE)
_MAX_PROSE_CHARS = 4000
_TRUNCATED_PROSE_CHARS = 1200
_DOC_DUMP_MIN_CHARS = 400
_DOC_DUMP_MIN_SECTIONS = 3


def filter_assistant_text(
    text: str,
    *,
    recent_tool_outputs: deque[str] | None = None,
) -> str | None:
    """Return cleaned assistant text, or ``None`` when the block should be omitted."""

    stripped = text.strip()
    if not stripped:
        return None

    if _TODO_UPDATE.match(stripped):
        return None
    if _looks_like_raw_todo_list(stripped):
        return None
    if _looks_like_skill_dump(stripped):
        return None
    if recent_tool_outputs and _mostly_duplicates_tool_output(stripped, recent_tool_outputs):
        return None
    if len(stripped) > _MAX_PROSE_CHARS:
        return stripped[:_TRUNCATED_PROSE_CHARS].rstrip() + "\n\n_… [assistant message truncated]_"
    return stripped


def remember_tool_output(
    outputs: deque[str],
    content: str,
    *,
    limit: int = 8,
) -> None:
    """Track recent tool results so duplicate prose can be suppressed."""

    normalized = _normalize_for_compare(content)
    if not normalized or len(normalized) < 40:
        return
    outputs.append(normalized)
    while len(outputs) > limit:
        outputs.popleft()


def _looks_like_raw_todo_list(text: str) -> bool:
    if not text.startswith("[{") or "'content'" not in text:
        return False
    return "'status'" in text and ("'pending'" in text or "'completed'" in text)


def _looks_like_skill_dump(text: str) -> bool:
    """True when the text appears to be a SKILL.md body or MEMORY.md dump.

    Three patterns we treat as "this is a document, not a conversational
    reply":

    1. The YAML frontmatter every skill file starts with — unique enough
       to short-circuit even short matches.
    2. The ``# Memory index`` heading that opens MEMORY.md.
    3. Document-like structure: top-level ``# Title``, three or more
       ``## Section`` headers, and at least ~400 characters. A normal
       chat reply rarely has three section headers.
    """

    if _SKILL_FRONTMATTER.search(text):
        return True
    if _MEMORY_INDEX_HEADING.search(text):
        return True
    if len(text) < _DOC_DUMP_MIN_CHARS:
        return False
    if not _TOP_LEVEL_HEADING.search(text):
        return False
    return len(_SECTION_HEADER.findall(text)) >= _DOC_DUMP_MIN_SECTIONS


def _mostly_duplicates_tool_output(text: str, outputs: deque[str]) -> bool:
    normalized = _normalize_for_compare(text)
    if not normalized:
        return True
    for tool_out in outputs:
        if normalized == tool_out:
            return True
        if len(normalized) >= 80 and normalized in tool_out:
            return True
        if len(tool_out) >= 80 and tool_out in normalized:
            return True
        if _overlap_ratio(normalized, tool_out) >= 0.85:
            return True
    return False


def _overlap_ratio(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if shorter in longer:
        return len(shorter) / len(longer)
    left_lines = {line.strip() for line in left.splitlines() if line.strip()}
    right_lines = {line.strip() for line in right.splitlines() if line.strip()}
    if not left_lines or not right_lines:
        return 0.0
    shared = left_lines & right_lines
    return len(shared) / max(len(left_lines), len(right_lines))


def _normalize_for_compare(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = _NUMBERED_LINE.sub("", line).strip()
        if stripped:
            lines.append(stripped)
    return "\n".join(lines)
