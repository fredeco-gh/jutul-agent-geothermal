"""AgentREPL.jl backend — the only ``JuliaSession`` implementation today.

This sub-package owns everything AgentREPL-specific: the MCP-over-stdio
client (``backend.py``) and the captured-stdout text cleanup
(``text.py``). Add a new backend by adding a sibling sub-package whose
``__init__`` re-exports a ``JuliaSession``-compatible class.
"""

from jutul_agent.julia.backends.agentrepl.backend import AgentREPLBackend, AgentREPLConfig
from jutul_agent.julia.backends.agentrepl.text import (
    render_terminal_output,
    strip_ansi,
    strip_julia_repl_echo,
)

__all__ = [
    "AgentREPLBackend",
    "AgentREPLConfig",
    "render_terminal_output",
    "strip_ansi",
    "strip_julia_repl_echo",
]
