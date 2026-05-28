"""Headless Makie figure capture for jutul-agent's ``julia_plot`` tool.

The Python tool ``include``s this file once per session (after ``using
CairoMakie``) and then calls ``JutulAgentPlots.plot_and_save`` with the
user's expression wrapped in a ``begin … end`` block.
"""

module JutulAgentPlots

using CairoMakie

export plot_and_save, is_makie_figure, save_figure

is_makie_figure(x) = x isa Figure

function _ensure_parent_dir(path::AbstractString)
    parent_dir = dirname(path)
    if !isempty(parent_dir) && !isdir(parent_dir)
        mkpath(parent_dir)
    end
end

function _save_kwargs(size, dpi)
    kwargs = Pair{Symbol, Any}[]
    if size !== nothing && size isa Tuple && length(size) == 2
        push!(kwargs, :size => (Int(size[1]), Int(size[2])))
    end
    if dpi !== nothing
        push!(kwargs, :dpi => Int(dpi))
    end
    return kwargs
end

"""
    save_figure(fig; path, format=:png, size=nothing, dpi=nothing)

Save a Makie ``Figure`` to *path* using CairoMakie. *format* is ``:png`` or ``:svg``.
*size* and *dpi* are passed through to ``CairoMakie.save``.
"""
function save_figure(
    fig::Figure;
    path::AbstractString,
    format::Symbol = :png,
    size = nothing,
    dpi = nothing,
)
    _ensure_parent_dir(path)
    kwargs = _save_kwargs(size, dpi)
    if format in (:png, :svg)
        CairoMakie.save(path, fig; kwargs...)
    else
        error("unsupported plot format: $format (use :png or :svg)")
    end
    return path
end

"""
    plot_and_save(fig; path, format, size, dpi)

Verify *fig* is a Makie ``Figure`` and save it. Errors carry the user-visible
"must evaluate to a Makie Figure" message the Python tool surfaces.
"""
function plot_and_save(fig; path, format, size, dpi)
    if !is_makie_figure(fig)
        error("julia_plot: code must evaluate to a Makie Figure; got " *
              string(typeof(fig)))
    end
    return save_figure(fig; path = path, format = format, size = size, dpi = dpi)
end

end # module
