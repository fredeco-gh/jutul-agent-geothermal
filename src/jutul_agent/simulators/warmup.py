"""The session-start GL-context warm-up.

Solve and plot paths are precompiled and cached at ``init`` (by the JutulAgent and
per-simulator JutulAgent<Sim> packages), so loading them at session start pays only
load latency. The one thing precompilation cannot bake is GLMakie's runtime GL
context, which is process-local. This module is the one simulator-agnostic snippet
that warms it, in the background, with a tiny offscreen save. ``run._start_warmup``
runs it after loading the warm packages.
"""

from __future__ import annotations

# Initialise this session's GLMakie GL context (the per-session cost precompilation
# cannot bake) with a tiny offscreen save. Best-effort: if GLMakie isn't usable here
# (no GL, no xvfb) the try/catch swallows it and plotting errors at first use.
GL_CONTEXT_WARMUP = """try
    using GLMakie  # already loaded by the warm packages; binds it into Main
    GLMakie.activate!(visible = false)
    let
        fig = Figure(size = (96, 96))
        ax = Axis3(fig[1, 1])
        surface!(ax, 1:4, 1:4, [Float64(i + j) for i in 1:4, j in 1:4])
        save(joinpath(tempdir(), "jutul_agent_gl_warmup.png"), fig)
    end
catch
end
"""
