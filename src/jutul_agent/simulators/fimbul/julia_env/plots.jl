"""Fimbul headless plotting helpers for jutul-agent.

Fimbul cases reuse JutulDarcy result containers (``wd``, grid, cell fields).
The two helpers below mirror ``jutuldarcy/plots.jl`` so each env stays self-contained.
Each returns a Makie ``Figure``; never calls ``display``.
"""

using CairoMakie

function _well_names(wd)
    if wd isa AbstractDict
        return collect(keys(wd))
    end
    return Symbol[]
end

function _select_wells(wd, wells)
    names = _well_names(wd)
    if wells === :all
        return names
    end
    if wells isa Symbol
        return wells in names ? [wells] : names
    end
    return collect(wells)
end

function _grid_nxy(g)
    if hasproperty(g, :dims)
        d = g.dims
        return Int(d[1]), Int(d[2])
    end
    if hasproperty(g, :cartesian_dims)
        d = g.cartesian_dims
        return Int(d[1]), Int(d[2])
    end
    if hasproperty(g, :topology) && hasproperty(g.topology, :dims)
        d = g.topology.dims
        return Int(d[1]), Int(d[2])
    end
    try
        n = isqrt(length(g))
        return max(n, 1), max(n, 1)
    catch
        return 1, 1
    end
end

"""
    well_rates_figure(wd; wells=:all, kind=:rates, size=(900, 500))

Build a well-results figure from the ``wd`` dict returned by ``simulate_reservoir``.
"""
function well_rates_figure(wd; wells = :all, kind = :rates, size = (900, 500))
    selected = _select_wells(wd, wells)
    fig = Figure(size = size)
    if kind == :bhp
        ax = Axis(fig[1, 1], xlabel = "Step", ylabel = "BHP", title = "Bottom-hole pressure")
        for name in selected
            series = get(wd, name, nothing)
            series === nothing && continue
            bhp = get(series, :bhp, nothing)
            bhp === nothing && continue
            lines!(ax, 1:length(bhp), bhp; label = string(name))
        end
        axislegend(ax, position = :rb)
    else
        ax = Axis(fig[1, 1], xlabel = "Step", ylabel = "Rate", title = "Well rates")
        for name in selected
            series = get(wd, name, nothing)
            series === nothing && continue
            rate = get(series, :rate, nothing)
            grat = get(series, :grat, nothing)
            if rate !== nothing
                lines!(ax, 1:length(rate), rate; label = string(name, " total"))
            end
            if grat !== nothing
                lines!(ax, 1:length(grat), grat; label = string(name, " gas"))
            end
        end
        axislegend(ax, position = :rb)
    end
    return fig
end

"""
    cell_field_heatmap(g, field; colormap=:viridis, size=(800, 600))

Plot a per-cell scalar field on a structured grid.
"""
function cell_field_heatmap(g, field; colormap = :viridis, size = (800, 600))
    nx, ny = _grid_nxy(g)
    data = reshape(collect(field), nx, ny)
    fig = Figure(size = size)
    ax = Axis(fig[1, 1], aspect = DataAspect(), title = "Cell data")
    hm = heatmap!(ax, data; colormap = colormap)
    Colorbar(fig[1, 2], hm)
    return fig
end
