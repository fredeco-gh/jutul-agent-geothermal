module JutulAgentFimbul

# Per-simulator warm-up package for Fimbul, which reuses JutulDarcy's solver plus an
# energy equation and ships no PrecompileTools workload of its own. Bakes the agent's
# simulate_reservoir + plot_cell_data paths; see JutulAgentJutulDarcy for the
# @recompile_invalidations rationale.

using Fimbul, JutulDarcy, Jutul
using PrecompileTools: @recompile_invalidations, @setup_workload, @compile_workload

@recompile_invalidations begin
    using GLMakie
end

# Smallest Fimbul run that compiles the geothermal (thermal-Darcy) solve path: the
# shipped analytical 1D case on a tiny mesh + few steps.
function _warm_solve()
    case, _sol, _x, _t = analytical_1d(num_cells = 20, num_steps = 8)
    simulate_reservoir(case, info_level = -1)
    return nothing
end

# Native 3D plotter (shared with JutulDarcy); needs a GL context, baked separately
# so a context-less precompile still bakes _warm_solve.
function _warm_plot()
    g = CartesianMesh((2, 2, 1), (1.0, 1.0, 1.0))
    dom = reservoir_domain(g, permeability = 1e-13, porosity = 0.2)
    fig, ax, plt = plot_cell_data(physical_representation(dom), dom[:porosity])
    GLMakie.save(joinpath(tempdir(), "jutul_agent_native_warm.png"), fig)
    return nothing
end

@setup_workload begin
    @compile_workload begin
        try
            _warm_solve()
        catch
        end
        try
            _warm_plot()
        catch
        end
    end
end

end # module
